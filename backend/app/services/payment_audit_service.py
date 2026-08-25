import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, delete, select

from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.models.identity import OperationalSession, OperationalSessionStatusEnum, User
from app.models.negotiation import PaymentIntent
from app.models.provider import (
    OperationalProductivityProjection,
    PaymentDeviceBinding,
    PaymentDeviceBindingStatusEnum,
    PaymentExecutionEvent,
    PaymentExecutionStageEnum,
    ProviderTransaction,
    ProviderTransactionStatusEnum,
)
from app.models.device import OperationalDevice, OperationalDeviceStatusEnum, OperationalDeviceTypeEnum
from app.services import reliability_service


PRODUCTIVITY_FORMULAS = {
    "approval_rate": "approved_count / requested_count",
    "execution_rate": "executed_count / approved_count",
    "confirmation_rate": "confirmed_count / executed_count",
    "confirmed_amount": "SUM(amount) dos eventos RESULT_RECORDED com outcome = CONFIRMED",
}
TERMINAL_FAILURES = {
    ProviderTransactionStatusEnum.FAILED.value,
    ProviderTransactionStatusEnum.CANCELED.value,
}


def _lock_projection(session: Session, tenant_id: uuid.UUID, store_id: uuid.UUID) -> None:
    """Serialize live updates with a full rebuild for the same tenant/store."""
    session.exec(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:projection_key, 0))"),
        params={"projection_key": f"payment-productivity:{tenant_id}:{store_id}"},
    )


def _validated_scope(
    session: Session,
    context: TenantContext,
    transaction: ProviderTransaction,
    intent: PaymentIntent,
    binding: PaymentDeviceBinding,
    device: OperationalDevice,
    actor_id: uuid.UUID,
) -> dict:
    if (
        transaction.tenant_id != context.tenant_id
        or intent.tenant_id != context.tenant_id
        or binding.tenant_id != context.tenant_id
        or device.tenant_id != context.tenant_id
        or transaction.store_id != intent.store_id
        or intent.store_id != binding.store_id
        or binding.store_id != device.store_id
        or (context.store_id and context.store_id != intent.store_id)
        or transaction.payment_intent_id != intent.id
        or transaction.payment_device_binding_id != binding.id
        or transaction.provider_configuration_id != binding.provider_configuration_id
        or binding.operational_device_id != device.id
        or binding.register_id != device.register_id
        or binding.status != PaymentDeviceBindingStatusEnum.ACTIVE
        or device.status != OperationalDeviceStatusEnum.ACTIVE
        or device.device_type != OperationalDeviceTypeEnum.POS
    ):
        raise HTTPException(status_code=403, detail="Escopo de auditoria do pagamento não é íntegro.")

    operational_session_id = context.operational_session_id
    operational_actor_id = actor_id
    if operational_session_id:
        authority = session.get(OperationalSession, operational_session_id)
        if (
            not authority
            or authority.status != OperationalSessionStatusEnum.ACTIVE
            or authority.tenant_id != context.tenant_id
            or authority.store_id != intent.store_id
            or authority.device_id != device.id
            or authority.register_id != binding.register_id
            or authority.user_id != context.user_id
            or authority.expires_at <= datetime.utcnow()
            or context.device_id != device.id
            or context.register_id != binding.register_id
        ):
            raise HTTPException(status_code=403, detail="Sessão operacional não pertence ao escopo auditado.")
        operational_actor_id = authority.user_id

    return {
        "tenant_id": context.tenant_id,
        "store_id": intent.store_id,
        "register_id": binding.register_id,
        "operational_device_id": device.id,
        "operational_session_id": operational_session_id,
        "operational_actor_id": operational_actor_id,
    }


def _source_scope(session: Session, context: TenantContext, transaction: ProviderTransaction) -> PaymentExecutionEvent:
    source = session.exec(scope_tenant_query(select(PaymentExecutionEvent).where(
        PaymentExecutionEvent.provider_transaction_id == transaction.id,
    ), PaymentExecutionEvent, context).order_by(PaymentExecutionEvent.sequence)).first()
    if not source:
        raise HTTPException(status_code=409, detail="Transação sem cadeia de autoridade auditável.")
    if (
        source.tenant_id != transaction.tenant_id
        or source.store_id != transaction.store_id
        or source.payment_intent_id != transaction.payment_intent_id
        or source.payment_device_binding_id != transaction.payment_device_binding_id
        or (context.store_id and context.store_id != source.store_id)
    ):
        raise HTTPException(status_code=403, detail="Escopo original da transação não corresponde ao callback.")
    if context.auth_provider == "operational" and (
        source.operational_session_id != context.operational_session_id
        or source.operational_device_id != context.device_id
        or source.register_id != context.register_id
        or source.operational_actor_id != context.user_id
    ):
        raise HTTPException(status_code=403, detail="A sessão não pode concluir uma transação de outro turno ou dispositivo.")
    return source


def _apply_projection(session: Session, event: PaymentExecutionEvent) -> None:
    if not event.operational_session_id or not event.operational_actor_id:
        return
    _lock_projection(session, event.tenant_id, event.store_id)
    projection = session.exec(select(OperationalProductivityProjection).where(
        OperationalProductivityProjection.tenant_id == event.tenant_id,
        OperationalProductivityProjection.operational_session_id == event.operational_session_id,
    ).with_for_update()).first()
    if not projection:
        projection = OperationalProductivityProjection(
            tenant_id=event.tenant_id,
            store_id=event.store_id,
            register_id=event.register_id,
            operational_device_id=event.operational_device_id,
            operational_session_id=event.operational_session_id,
            operator_id=event.operational_actor_id,
            first_event_at=event.occurred_at,
            last_event_at=event.occurred_at,
        )
        session.add(projection)
    elif (
        projection.store_id != event.store_id
        or projection.register_id != event.register_id
        or projection.operational_device_id != event.operational_device_id
        or projection.operator_id != event.operational_actor_id
    ):
        raise HTTPException(status_code=409, detail="A projeção do turno divergiu do evento imutável.")

    if event.stage == PaymentExecutionStageEnum.REQUESTED:
        projection.requested_count += 1
        projection.requested_amount += Decimal(event.amount)
    elif event.stage == PaymentExecutionStageEnum.APPROVED:
        projection.approved_count += 1
    elif event.stage == PaymentExecutionStageEnum.EXECUTED:
        projection.executed_count += 1
    elif event.stage == PaymentExecutionStageEnum.RESULT_RECORDED:
        if event.outcome == ProviderTransactionStatusEnum.CONFIRMED.value:
            projection.confirmed_count += 1
            projection.confirmed_amount += Decimal(event.amount)
        elif event.outcome in TERMINAL_FAILURES:
            projection.failed_count += 1
    projection.last_event_at = max(projection.last_event_at, event.occurred_at)
    projection.updated_at = datetime.utcnow()


def _append(
    session: Session,
    transaction: ProviderTransaction,
    *,
    source: dict,
    event_actor_id: uuid.UUID,
    stage: PaymentExecutionStageEnum,
    amount: Decimal,
    outcome: Optional[str] = None,
    payload: Optional[dict] = None,
) -> PaymentExecutionEvent:
    existing = list(session.exec(select(PaymentExecutionEvent).where(
        PaymentExecutionEvent.tenant_id == transaction.tenant_id,
        PaymentExecutionEvent.provider_transaction_id == transaction.id,
    ).order_by(PaymentExecutionEvent.sequence)).all())
    if stage == PaymentExecutionStageEnum.EXECUTED:
        previous = next((row for row in existing if row.stage == stage), None)
        if previous:
            return previous
    if stage == PaymentExecutionStageEnum.RESULT_RECORDED:
        previous = next((row for row in reversed(existing) if row.stage == stage), None)
        if previous and previous.outcome == outcome:
            return previous
    event = PaymentExecutionEvent(
        **source,
        event_actor_id=event_actor_id,
        payment_intent_id=transaction.payment_intent_id,
        payment_device_binding_id=transaction.payment_device_binding_id,
        provider_transaction_id=transaction.id,
        stage=stage,
        sequence=(existing[-1].sequence + 1) if existing else 1,
        amount=Decimal(amount),
        outcome=outcome,
        request_hash=transaction.request_hash,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    _apply_projection(session, event)
    return event


def record_request_and_approval(
    session: Session,
    context: TenantContext,
    *,
    transaction: ProviderTransaction,
    intent: PaymentIntent,
    binding: PaymentDeviceBinding,
    device: OperationalDevice,
    actor_id: uuid.UUID,
) -> None:
    actor = resolve_actor(context, actor_id)
    source = _validated_scope(session, context, transaction, intent, binding, device, actor)
    _append(
        session, transaction, source=source, event_actor_id=actor,
        stage=PaymentExecutionStageEnum.REQUESTED, amount=Decimal(intent.amount),
        payload={"provider_code": transaction.provider_code},
    )
    _append(
        session, transaction, source=source, event_actor_id=actor,
        stage=PaymentExecutionStageEnum.APPROVED, amount=Decimal(intent.amount),
        payload={"authority": "operational_session" if context.operational_session_id else "management_identity"},
    )


def record_execution_result(
    session: Session,
    context: TenantContext,
    *,
    transaction: ProviderTransaction,
    intent: PaymentIntent,
    actor_id: uuid.UUID,
    outcome: ProviderTransactionStatusEnum,
    payload: Optional[dict] = None,
) -> None:
    source_event = _source_scope(session, context, transaction)
    source = {
        "tenant_id": source_event.tenant_id,
        "store_id": source_event.store_id,
        "register_id": source_event.register_id,
        "operational_device_id": source_event.operational_device_id,
        "operational_session_id": source_event.operational_session_id,
        "operational_actor_id": source_event.operational_actor_id,
    }
    _append(
        session, transaction, source=source, event_actor_id=actor_id,
        stage=PaymentExecutionStageEnum.EXECUTED, amount=Decimal(intent.amount),
        payload={"provider_code": transaction.provider_code},
    )
    _append(
        session, transaction, source=source, event_actor_id=actor_id,
        stage=PaymentExecutionStageEnum.RESULT_RECORDED, amount=Decimal(intent.amount),
        outcome=outcome.value, payload=payload,
    )


def rebuild_productivity(
    session: Session, context: TenantContext, *, store_id: uuid.UUID, actor_id: uuid.UUID,
) -> dict:
    actor = resolve_actor(context, actor_id)
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Unidade fora do contexto autorizado.")
    _lock_projection(session, context.tenant_id, store_id)
    events = list(session.exec(scope_tenant_query(select(PaymentExecutionEvent).where(
        PaymentExecutionEvent.store_id == store_id,
    ), PaymentExecutionEvent, context).order_by(
        PaymentExecutionEvent.occurred_at, PaymentExecutionEvent.sequence,
    )).all())
    session.exec(delete(OperationalProductivityProjection).where(
        OperationalProductivityProjection.tenant_id == context.tenant_id,
        OperationalProductivityProjection.store_id == store_id,
    ))
    session.flush()
    for event in events:
        _apply_projection(session, event)
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id, actor_id=actor,
        action="payment.productivity.rebuilt", target=f"PAYMENT-PRODUCTIVITY-{store_id}",
        audit_payload={"source_events": len(events)}, aggregate_type="payment_productivity",
        aggregate_id=str(store_id), event_type="payment.productivity.rebuilt",
        outbox_payload={"store_id": str(store_id), "source_events": len(events)},
    )
    session.commit()
    return {"store_id": store_id, "source_events": len(events), "status": "READY"}


def productivity_summary(
    session: Session, context: TenantContext, *, store_id: uuid.UUID, days: int = 30,
) -> dict:
    if days < 1 or days > 366:
        raise HTTPException(status_code=422, detail="Período deve possuir entre 1 e 366 dias.")
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Unidade fora do contexto autorizado.")
    lower = datetime.utcnow() - timedelta(days=days)
    rows = list(session.exec(scope_tenant_query(select(OperationalProductivityProjection).where(
        OperationalProductivityProjection.store_id == store_id,
        OperationalProductivityProjection.last_event_at >= lower,
    ), OperationalProductivityProjection, context).order_by(
        OperationalProductivityProjection.last_event_at.desc(),
    )).all())
    grouped: dict[uuid.UUID, dict] = defaultdict(lambda: {
        "requested_count": 0, "approved_count": 0, "executed_count": 0,
        "confirmed_count": 0, "failed_count": 0,
        "requested_amount": Decimal("0"), "confirmed_amount": Decimal("0"),
        "shift_count": 0, "last_event_at": None,
    })
    for row in rows:
        item = grouped[row.operator_id]
        for key in ("requested_count", "approved_count", "executed_count", "confirmed_count", "failed_count"):
            item[key] += getattr(row, key)
        item["requested_amount"] += Decimal(row.requested_amount)
        item["confirmed_amount"] += Decimal(row.confirmed_amount)
        item["shift_count"] += 1
        item["last_event_at"] = max(filter(None, [item["last_event_at"], row.last_event_at]))
    operators = {user.id: user for user in session.exec(select(User).where(User.id.in_(list(grouped) or [uuid.uuid4()]))).all()}
    items = []
    for operator_id, item in grouped.items():
        requested = item["requested_count"]
        approved = item["approved_count"]
        executed = item["executed_count"]
        items.append({
            "operator_id": operator_id,
            "operator_name": operators.get(operator_id).full_name if operators.get(operator_id) else "Operador indisponível",
            **{key: value for key, value in item.items() if key not in {"requested_amount", "confirmed_amount"}},
            "requested_amount": float(item["requested_amount"]),
            "confirmed_amount": float(item["confirmed_amount"]),
            "approval_rate": approved / requested if requested else 0,
            "execution_rate": executed / approved if approved else 0,
            "confirmation_rate": item["confirmed_count"] / executed if executed else 0,
        })
    watermark = max((row.last_event_at for row in rows), default=None)
    return {
        "generated_at": datetime.utcnow(), "source_watermark": watermark,
        "projection_version": 1, "days": days, "items": items,
        "formulas": PRODUCTIVITY_FORMULAS,
    }
