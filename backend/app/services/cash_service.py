import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional
from sqlmodel import Session, select
from fastapi import HTTPException, status
from app.core.context import TenantContext, scope_tenant_query
from app.models.payment import (
    Register, CashSession, CashMovement, Payment, CashSessionStatusEnum, CashMovementTypeEnum, PaymentMethodEnum, PaymentStatusEnum
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

def open_cash_session(
    session: Session,
    context: TenantContext,
    store_id: uuid.UUID,
    register_id: uuid.UUID,
    operator_id: uuid.UUID,
    opening_balance: Decimal
) -> CashSession:
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
        CashSession.status == CashSessionStatusEnum.OPEN
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
    query = select(CashSession).where(CashSession.id == session_id).with_for_update()
    query = scope_tenant_query(query, CashSession, context)
    cash_session = session.exec(query).first()
    if not cash_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cash session not found for this tenant.")

    if cash_session.status != CashSessionStatusEnum.OPEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cash session is not OPEN.")

    closing_dec = Decimal(str(closing_balance))

    # Calculate expected balance based on actual cash ledger entries
    movs_query = select(CashMovement).where(CashMovement.cash_session_id == session_id)
    movs = session.exec(movs_query).all()

    expected = Decimal("0.00")
    for m in movs:
        if m.movement_type in (CashMovementTypeEnum.OPENING, CashMovementTypeEnum.SALE_PAYMENT, CashMovementTypeEnum.REINFORCEMENT):
            expected += m.amount
        elif m.movement_type == CashMovementTypeEnum.BLEED:
            expected -= m.amount

    variance = closing_dec - expected

    cash_session.status = CashSessionStatusEnum.CLOSED
    cash_session.expected_balance = expected
    cash_session.closing_balance = closing_dec
    cash_session.variance = variance
    cash_session.closed_at = datetime.utcnow()
    session.add(cash_session)

    # Audit & Outbox (Without creating a duplicate CashMovement that inflates balance!)
    reliability_service.write_audit_and_outbox(
        session=session,
        tenant_id=context.tenant_id,
        store_id=cash_session.store_id,
        actor_id=operator_id,
        action="cash_session.close",
        target=f"SESSION-{cash_session.id}",
        audit_payload={
            "session_id": str(cash_session.id),
            "closing_balance": str(closing_dec),
            "expected_balance": str(expected),
            "variance": str(variance)
        },
        aggregate_type="cash_session",
        aggregate_id=str(cash_session.id),
        event_type="cash_session.closed",
        outbox_payload={
            "tenant_id": str(context.tenant_id),
            "store_id": str(cash_session.store_id),
            "session_id": str(cash_session.id),
            "variance": str(variance)
        }
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
    notes: Optional[str] = None
) -> CashMovement:
    query = select(CashSession).where(CashSession.id == session_id)
    query = scope_tenant_query(query, CashSession, context)
    cash_session = session.exec(query).first()
    if not cash_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cash session not found for this tenant.")

    if cash_session.status != CashSessionStatusEnum.OPEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot add movement to CLOSED cash session.")

    amt_dec = Decimal(str(amount))
    movement = CashMovement(
        tenant_id=context.tenant_id,
        store_id=cash_session.store_id,
        cash_session_id=session_id,
        actor_id=actor_id,
        movement_type=movement_type,
        amount=amt_dec,
        notes=notes
    )
    session.add(movement)
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

