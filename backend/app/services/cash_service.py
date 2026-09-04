import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional
from sqlmodel import Session, select
from fastapi import HTTPException, status
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.identity import Register
from app.models.payment import (
    CashSession, CashMovement, Payment, CashSessionStatusEnum, CashMovementTypeEnum, PaymentMethodEnum, PaymentStatusEnum
)
from app.services import reliability_service

def create_register(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    name: str,
    code: str
) -> Register:
    existing_query = select(Register).where(
        Register.store_id == store_id,
        Register.code == code
    )
    existing_query = scope_tenant_query(existing_query, Register, context)
    if session.exec(existing_query).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Register with code '{code}' already exists for this store."
        )

    register = Register(
        tenant_id=context.tenant_id,
        store_id=store_id,
        name=name,
        code=code
    )
    session.add(register)
    session.commit()
    session.refresh(register)
    return register


def update_register(
    session: Session,
    context: TenantContext,
    register_id: uuid.UUID,
    *,
    name: Optional[str],
    is_active: Optional[bool],
    actor_id: Optional[uuid.UUID],
    reason: str,
) -> Register:
    register = session.exec(scope_tenant_query(select(Register).where(
        Register.id == register_id,
    ), Register, context).with_for_update()).first()
    if not register:
        raise HTTPException(status_code=404, detail="Terminal não encontrado.")
    if is_active is False and session.exec(scope_tenant_query(select(CashSession).where(
        CashSession.register_id == register.id,
        CashSession.status.in_([CashSessionStatusEnum.OPEN, CashSessionStatusEnum.CLOSING]),
    ), CashSession, context)).first():
        raise HTTPException(status_code=409, detail="Feche o caixa antes de pausar o terminal.")
    actor = resolve_actor(context, actor_id)
    if name is not None:
        register.name = name.strip()
    if is_active is not None:
        register.is_active = is_active
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=register.store_id, actor_id=actor,
        action="register.updated", target=f"REGISTER-{register.id}",
        audit_payload={"name": register.name, "is_active": register.is_active, "reason": reason},
        aggregate_type="register", aggregate_id=str(register.id), event_type="register.updated",
        outbox_payload={"register_id": str(register.id), "is_active": register.is_active},
    )
    session.add(register); session.commit(); session.refresh(register)
    return register

def require_named_shift_authority(context: TenantContext, action: str) -> None:
    """A shift is a financial fact and must answer to a named person.

    Who may open or close one is decided by the permission matrix — `cash.open`
    and `cash.close`, already enforced per route — and the authorship is decided
    by `resolve_actor`, which only ever accepts the authenticated principal. This
    guard adds the one thing neither of those covers: that a principal exists at
    all, so a shift can never be attributed to nobody.

    It deliberately does *not* ask which kind of session is holding it. Requiring
    an operational session here meant a merchant working alone had to invent a
    second identity of herself, ask an imaginary supervisor for a PIN, and type
    it into her own browser to sell her own goods. The matrix always granted
    `cash.open` to OWNER, TENANT_OWNER, ADMIN and MANAGER; the earlier version of
    this guard contradicted it.

    Where the shift is held on a *shared* counter terminal, the code and PIN are
    still what identifies the person — not because of a rule written here, but
    because that surface only ever offers the operational gate.
    """
    # The disabled-auth subject is the explicit development and test boundary the
    # codebase already uses for authority checks.
    if context.auth_subject == "local-auth-bypass":
        return
    if not context.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{action} exige uma identidade autenticada.",
        )


def open_cash_session(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    register_id: uuid.UUID,
    operator_id: uuid.UUID,
    opening_balance: Decimal
) -> CashSession:
    require_named_shift_authority(context, "Abrir o caixa")
    operator_id = resolve_actor(context, operator_id)
    # Pessimistic Lock on Register to prevent concurrent OPEN sessions
    reg_query = select(Register).where(
        Register.id == register_id,
        Register.tenant_id == context.tenant_id,
        Register.store_id == store_id
    ).with_for_update()
    register = session.exec(reg_query).first()
    if not register or not register.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Register '{register_id}' is invalid or inactive."
        )

    # Check for existing OPEN session on this register
    open_query = select(CashSession).where(
        CashSession.register_id == register_id,
        CashSession.status.in_([CashSessionStatusEnum.OPEN, CashSessionStatusEnum.CLOSING])
    )
    open_query = scope_tenant_query(open_query, CashSession, context)
    if session.exec(open_query).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Register '{register.name}' already has an OPEN cash session."
        )

    opening_dec = Decimal(str(opening_balance))
    cash_session = CashSession(
        tenant_id=context.tenant_id,
        store_id=store_id,
        register_id=register_id,
        operator_id=operator_id,
        status=CashSessionStatusEnum.OPEN,
        opening_balance=opening_dec
    )
    session.add(cash_session)
    session.flush()

    # Opening Cash Movement
    movement = CashMovement(
        tenant_id=context.tenant_id,
        store_id=store_id,
        cash_session_id=cash_session.id,
        actor_id=operator_id,
        movement_type=CashMovementTypeEnum.OPENING,
        amount=opening_dec,
        notes="Abertura de Caixa"
    )
    session.add(movement)

    # Audit & Outbox
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=store_id,
        actor_id=operator_id,
        action="cash_session.open",
        target=f"SESSION-{cash_session.id}",
        audit_payload={"session_id": str(cash_session.id), "opening_balance": str(opening_dec)},
        aggregate_type="cash_session",
        aggregate_id=str(cash_session.id),
        event_type="cash_session.opened",
        outbox_payload={"tenant_id": str(context.tenant_id), "store_id": str(store_id), "session_id": str(cash_session.id)}
    )

    session.commit()
    session.refresh(cash_session)
    return cash_session

def close_cash_session(
    session: Session,
    context: TenantContext,
    session_id: uuid.UUID,
    closing_balance: Decimal,
    operator_id: uuid.UUID
) -> CashSession:
    cash_session = begin_cash_close(
        session, context, session_id=session_id, operator_id=operator_id,
        expected_version=None, blind_count=False,
    )
    return finalize_cash_close(
        session, context, session_id=session_id, operator_id=operator_id,
        closing_balance=closing_balance, expected_version=cash_session.version,
        divergence_reason="Fechamento legado confirmado pelo operador",
    )


def _expected_cash_balance(session: Session, session_id: uuid.UUID) -> Decimal:
    movements = session.exec(select(CashMovement).where(CashMovement.cash_session_id == session_id)).all()
    positive = {
        CashMovementTypeEnum.OPENING, CashMovementTypeEnum.SALE_PAYMENT,
        CashMovementTypeEnum.RECEIVABLE_PAYMENT, CashMovementTypeEnum.REINFORCEMENT,
    }
    negative = {CashMovementTypeEnum.BLEED, CashMovementTypeEnum.REFUND}
    expected = Decimal("0.00")
    for movement in movements:
        if movement.movement_type in positive:
            expected += movement.amount
        elif movement.movement_type in negative:
            expected -= movement.amount
    return expected


def begin_cash_close(
    session: Session, context: TenantContext, session_id: uuid.UUID, *,
    operator_id: uuid.UUID, expected_version: Optional[int], blind_count: bool,
) -> CashSession:
    require_named_shift_authority(context, "Fechar o caixa")
    operator_id = resolve_actor(context, operator_id)
    query = select(CashSession).where(CashSession.id == session_id).with_for_update()
    query = scope_tenant_query(query, CashSession, context)
    cash_session = session.exec(query).first()
    if not cash_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cash session not found for this tenant.")

    if cash_session.status != CashSessionStatusEnum.OPEN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Sessão de caixa não está OPEN.")
    if expected_version is not None and cash_session.version != expected_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Versão de caixa desatualizada.")
    cash_session.status = CashSessionStatusEnum.CLOSING
    cash_session.blind_count = blind_count
    cash_session.closing_started_at = datetime.utcnow()
    cash_session.closing_started_by = operator_id
    cash_session.version += 1
    session.add(cash_session)
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=cash_session.store_id,
        actor_id=operator_id,
        action="cash_session.close_started",
        target=f"SESSION-{cash_session.id}",
        audit_payload={"session_id": str(cash_session.id), "version": cash_session.version, "blind_count": blind_count},
        aggregate_type="cash_session",
        aggregate_id=str(cash_session.id),
        event_type="cash_session.closing",
        outbox_payload={"session_id": str(cash_session.id), "version": cash_session.version}
    )
    session.flush()
    return cash_session


def finalize_cash_close(
    session: Session, context: TenantContext, session_id: uuid.UUID, *,
    operator_id: uuid.UUID, closing_balance: Decimal, expected_version: int,
    divergence_reason: Optional[str],
) -> CashSession:
    operator_id = resolve_actor(context, operator_id)
    cash_session = session.exec(scope_tenant_query(select(CashSession).where(
        CashSession.id == session_id,
    ), CashSession, context).with_for_update()).first()
    if not cash_session:
        raise HTTPException(status_code=404, detail="Sessão de caixa não encontrada.")
    if cash_session.status != CashSessionStatusEnum.CLOSING:
        raise HTTPException(status_code=409, detail="Sessão de caixa não está em conferência.")
    if cash_session.version != expected_version:
        raise HTTPException(status_code=409, detail="Versão de fechamento desatualizada.")
    expected = _expected_cash_balance(session, session_id)
    counted = Decimal(str(closing_balance))
    variance = counted - expected
    if variance != 0 and not (divergence_reason or "").strip():
        raise HTTPException(status_code=422, detail="Motivo é obrigatório quando há divergência de caixa.")
    cash_session.status = CashSessionStatusEnum.CLOSED
    cash_session.expected_balance = expected
    cash_session.closing_balance = counted
    cash_session.variance = variance
    cash_session.divergence_reason = (divergence_reason or "").strip() or None
    cash_session.closed_at = datetime.utcnow()
    cash_session.version += 1
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=cash_session.store_id,
        actor_id=operator_id, action="cash_session.close", target=f"SESSION-{cash_session.id}",
        audit_payload={"session_id": str(cash_session.id), "closing_balance": str(counted),
                       "expected_balance": str(expected), "variance": str(variance),
                       "reason": cash_session.divergence_reason, "version": cash_session.version},
        aggregate_type="cash_session", aggregate_id=str(cash_session.id), event_type="cash_session.closed",
        outbox_payload={"session_id": str(cash_session.id), "variance": str(variance), "version": cash_session.version},
    )

    session.commit()
    session.refresh(cash_session)
    return cash_session

def add_cash_movement(
    session: Session,
    context: TenantContext,
    session_id: uuid.UUID,
    actor_id: uuid.UUID,
    movement_type: CashMovementTypeEnum,
    amount: Decimal,
    notes: Optional[str] = None,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> CashMovement:
    actor_id = resolve_actor(context, actor_id)
    if idempotency_key:
        existing = session.exec(scope_tenant_query(select(CashMovement).where(
            CashMovement.idempotency_key == idempotency_key,
        ), CashMovement, context)).first()
        if existing:
            return existing
    query = select(CashSession).where(CashSession.id == session_id).with_for_update()
    query = scope_tenant_query(query, CashSession, context)
    cash_session = session.exec(query).first()
    if not cash_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cash session not found for this tenant.")

    if cash_session.status != CashSessionStatusEnum.OPEN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Movimentos exigem caixa OPEN.")

    amt_dec = Decimal(str(amount))
    movement = CashMovement(
        tenant_id=context.tenant_id,
        store_id=cash_session.store_id,
        cash_session_id=session_id,
        actor_id=actor_id,
        movement_type=movement_type,
        amount=amt_dec,
        notes=notes, source_type=source_type, source_id=source_id,
        idempotency_key=idempotency_key,
    )
    session.add(movement)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=cash_session.store_id,
        actor_id=actor_id, action="cash_movement.created", target=f"CASH-MOVEMENT-{movement.id}",
        audit_payload={"movement_type": movement_type.value, "amount": str(amt_dec),
                       "source_type": source_type, "source_id": source_id},
        aggregate_type="cash_session", aggregate_id=str(cash_session.id),
        event_type="cash.movement.created", outbox_payload={"cash_movement_id": str(movement.id)},
    )
    session.commit()
    session.refresh(movement)
    return movement

def list_registers(
    session: Session,
    context: TenantContext,
    store_id: Optional[uuid.UUID] = None
) -> List[Register]:
    query = select(Register).where(Register.tenant_id == context.tenant_id)
    if store_id:
        query = query.where(Register.store_id == store_id)
    return session.exec(query).all()

def list_cash_sessions(
    session: Session,
    context: TenantContext,
    store_id: Optional[uuid.UUID] = None,
    status_filter: Optional[CashSessionStatusEnum] = None
) -> List[CashSession]:
    query = select(CashSession).where(CashSession.tenant_id == context.tenant_id)
    if store_id:
        query = query.where(CashSession.store_id == store_id)
    if status_filter:
        query = query.where(CashSession.status == status_filter)
    return session.exec(query.order_by(CashSession.opened_at.desc())).all()

def get_active_cash_session(
    session: Session,
    context: TenantContext,
    store_id: Optional[uuid.UUID] = None,
    register_id: Optional[uuid.UUID] = None
) -> Optional[CashSession]:
    query = select(CashSession).where(
        CashSession.tenant_id == context.tenant_id,
        CashSession.status == CashSessionStatusEnum.OPEN
    )
    if store_id:
        query = query.where(CashSession.store_id == store_id)
    if register_id:
        query = query.where(CashSession.register_id == register_id)
    return session.exec(query.order_by(CashSession.opened_at.desc())).first()

def list_cash_movements(
    session: Session,
    context: TenantContext,
    session_id: uuid.UUID
) -> List[CashMovement]:
    query = select(CashMovement).where(
        CashMovement.tenant_id == context.tenant_id,
        CashMovement.cash_session_id == session_id
    )
    return session.exec(query.order_by(CashMovement.created_at.asc())).all()
