import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.device import OperationalDevice, OperationalDeviceTypeEnum
from app.models.identity import (
    Employee,
    Membership,
    MembershipStatusEnum,
    OperationalCredential,
    OperationalSession,
    RoleEnum,
    Store,
    Tenant,
    TenantStatusEnum,
    User,
)
from app.models.negotiation import CheckoutNegotiation, PaymentIntent
from app.models.payment import PaymentMethodEnum, Register
from app.models.provider import (
    OperationalProductivityProjection,
    PaymentDeviceBinding,
    PaymentDeviceExecutionModeEnum,
    PaymentExecutionEvent,
    PaymentExecutionStageEnum,
    PaymentProviderConfiguration,
    ProviderConfigurationStatusEnum,
    ProviderTransaction,
    ProviderTransactionEvent,
    ProviderTransactionStatusEnum,
)
from app.models.reliability import AuditEvent
from app.services import payment_audit_service


def _context(
    tenant_id: uuid.UUID, store_id: uuid.UUID, user_id: uuid.UUID,
    register_id: uuid.UUID, device_id: uuid.UUID, authority_id: uuid.UUID,
) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id, store_id=store_id, user_id=user_id,
        role=RoleEnum.OPERATOR, auth_provider="operational",
        register_id=register_id, device_id=device_id,
        operational_session_id=authority_id,
    )


def test_gate_d_persists_immutable_scope_and_rebuildable_productivity():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"Gate D {suffix}", slug=f"gate-d-{suffix}", status=TenantStatusEnum.ACTIVE)
        other_tenant = Tenant(name=f"Gate D Other {suffix}", slug=f"gate-d-other-{suffix}", status=TenantStatusEnum.ACTIVE)
        operator = User(full_name="Operadora auditada")
        session.add(tenant); session.add(other_tenant); session.add(operator); session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"GD-{suffix}")
        sibling_store = Store(tenant_id=tenant.id, name="Filial", code=f"GDF-{suffix}")
        session.add(store); session.add(sibling_store); session.flush()
        register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa", code=f"GDCX-{suffix}")
        membership = Membership(
            user_id=operator.id, tenant_id=tenant.id, store_id=store.id,
            role=RoleEnum.OPERATOR, status=MembershipStatusEnum.ACTIVE,
        )
        employee = Employee(
            tenant_id=tenant.id, user_id=operator.id, home_store_id=store.id,
            employee_number=f"GD-{suffix}", full_name=operator.full_name,
        )
        session.add(register); session.add(membership); session.add(employee); session.flush()
        credential = OperationalCredential(
            tenant_id=tenant.id, store_id=store.id, user_id=operator.id,
            membership_id=membership.id, employee_id=employee.id,
            employee_code=f"GD{suffix}", pin_salt="salt", pin_hash="hash",
        )
        device = OperationalDevice(
            tenant_id=tenant.id, store_id=store.id, code=f"GDPOS-{suffix}", name="POS auditado",
            device_type=OperationalDeviceTypeEnum.POS, register_id=register.id,
        )
        configuration = PaymentProviderConfiguration(
            tenant_id=tenant.id, store_id=store.id, provider_code=f"GATE-D-{suffix}",
            status=ProviderConfigurationStatusEnum.ACTIVE, configured_by=operator.id,
        )
        session.add(credential); session.add(device); session.add(configuration); session.flush()
        authority = OperationalSession(
            tenant_id=tenant.id, store_id=store.id, register_id=register.id,
            device_id=device.id, user_id=operator.id, membership_id=membership.id,
            credential_id=credential.id, terminal_authorization_version=device.authorization_version,
            credential_version=credential.session_version, expires_at=datetime.utcnow() + timedelta(hours=8),
        )
        binding = PaymentDeviceBinding(
            tenant_id=tenant.id, store_id=store.id, register_id=register.id,
            operational_device_id=device.id, provider_configuration_id=configuration.id,
            execution_mode=PaymentDeviceExecutionModeEnum.SMARTPOS,
            external_device_reference=f"GD-SMART-{suffix}", configured_by=operator.id,
        )
        negotiation = CheckoutNegotiation(
            tenant_id=tenant.id, store_id=store.id, scope_key=f"GATE-D:{suffix}",
            subtotal=Decimal("100.00"), total_due=Decimal("100.00"), source_version=1,
            opened_by=operator.id, open_idempotency_key=f"gd-neg-{suffix}", open_request_hash="n" * 64,
        )
        session.add(authority); session.add(binding); session.add(negotiation); session.flush()
        intent = PaymentIntent(
            tenant_id=tenant.id, store_id=store.id, negotiation_id=negotiation.id,
            method=PaymentMethodEnum.CREDIT_CARD, amount=Decimal("100.00"),
            provider="GATE_D", idempotency_key=f"gd-intent-{suffix}", request_hash="i" * 64,
            created_by=operator.id,
        )
        session.add(intent); session.flush()
        transaction = ProviderTransaction(
            tenant_id=tenant.id, store_id=store.id, payment_intent_id=intent.id,
            payment_device_binding_id=binding.id, provider_configuration_id=configuration.id,
            provider_code=configuration.provider_code, adapter_version="1.0.0",
            correlation_id=f"gd-corr-{suffix}", idempotency_key=f"gd-tx-{suffix}",
            request_hash="t" * 64, created_by=operator.id,
        )
        legacy_event = ProviderTransactionEvent(
            tenant_id=tenant.id, provider_transaction_id=transaction.id,
            event_type="payment.provider.started", actor_id=operator.id, payload={},
        )
        audit = AuditEvent(
            actor_id=operator.id, tenant_id=tenant.id, store_id=store.id,
            action="gate.d.fixture", target=f"GATE-D-{suffix}", payload="{}",
        )
        session.add(transaction); session.add(legacy_event); session.add(audit); session.commit()
        ids = {
            "tenant": tenant.id, "other_tenant": other_tenant.id, "store": store.id,
            "sibling_store": sibling_store.id, "operator": operator.id, "register": register.id,
            "device": device.id, "authority": authority.id, "binding": binding.id,
            "intent": intent.id, "transaction": transaction.id,
            "legacy_event": legacy_event.id, "audit": audit.id,
        }

    context = _context(
        ids["tenant"], ids["store"], ids["operator"],
        ids["register"], ids["device"], ids["authority"],
    )
    with Session(engine) as session:
        set_tenant_db_context(session, ids["tenant"], ids["store"], ids["operator"])
        transaction = session.get(ProviderTransaction, ids["transaction"])
        intent = session.get(PaymentIntent, ids["intent"])
        binding = session.get(PaymentDeviceBinding, ids["binding"])
        device = session.get(OperationalDevice, ids["device"])
        payment_audit_service.record_request_and_approval(
            session, context, transaction=transaction, intent=intent,
            binding=binding, device=device, actor_id=ids["operator"],
        )
        transaction.status = ProviderTransactionStatusEnum.CONFIRMED
        payment_audit_service.record_execution_result(
            session, context, transaction=transaction, intent=intent,
            actor_id=ids["operator"], outcome=ProviderTransactionStatusEnum.CONFIRMED,
        )
        session.commit()
        events = list(session.exec(select(PaymentExecutionEvent).where(
            PaymentExecutionEvent.provider_transaction_id == ids["transaction"],
        ).order_by(PaymentExecutionEvent.sequence)).all())
        assert [event.stage for event in events] == [
            PaymentExecutionStageEnum.REQUESTED,
            PaymentExecutionStageEnum.APPROVED,
            PaymentExecutionStageEnum.EXECUTED,
            PaymentExecutionStageEnum.RESULT_RECORDED,
        ]
        assert all(event.tenant_id == ids["tenant"] for event in events)
        assert all(event.store_id == ids["store"] for event in events)
        assert all(event.register_id == ids["register"] for event in events)
        assert all(event.operational_device_id == ids["device"] for event in events)
        assert all(event.operational_session_id == ids["authority"] for event in events)
        projection = session.exec(select(OperationalProductivityProjection).where(
            OperationalProductivityProjection.operational_session_id == ids["authority"],
        )).one()
        assert (projection.requested_count, projection.approved_count, projection.executed_count) == (1, 1, 1)
        assert projection.confirmed_count == 1
        assert projection.confirmed_amount == Decimal("100.0000")

        projection.confirmed_count = 99
        session.add(projection); session.commit()
        payment_audit_service.rebuild_productivity(
            session, context, store_id=ids["store"], actor_id=ids["operator"],
        )
        rebuilt = session.exec(select(OperationalProductivityProjection).where(
            OperationalProductivityProjection.operational_session_id == ids["authority"],
        )).one()
        assert rebuilt.confirmed_count == 1
        summary = payment_audit_service.productivity_summary(
            session, context, store_id=ids["store"], days=30,
        )
        assert summary["items"][0]["confirmation_rate"] == 1
        assert summary["items"][0]["confirmed_amount"] == 100

        invalid_contexts = [
            context.model_copy(update={"tenant_id": ids["other_tenant"]}),
            context.model_copy(update={"store_id": ids["sibling_store"]}),
            context.model_copy(update={"device_id": uuid.uuid4()}),
            context.model_copy(update={"operational_session_id": uuid.uuid4()}),
        ]
        for invalid in invalid_contexts:
            with pytest.raises(HTTPException) as rejected:
                payment_audit_service.record_request_and_approval(
                    session, invalid, transaction=transaction, intent=intent,
                    binding=binding, device=device, actor_id=ids["operator"],
                )
            assert rejected.value.status_code == 403

    with Session(engine) as session:
        set_tenant_db_context(session, ids["tenant"], ids["sibling_store"], ids["operator"])
        assert session.exec(select(PaymentExecutionEvent).where(
            PaymentExecutionEvent.provider_transaction_id == ids["transaction"],
        )).first() is None

    immutable_rows = (
        ("payment_execution_events", "provider_transaction_id", ids["transaction"]),
        ("provider_transaction_events", "id", ids["legacy_event"]),
        ("audit_events", "id", ids["audit"]),
    )
    with Session(engine) as session:
        set_platform_db_context(session)
        trigger_count = session.exec(text("""
            SELECT count(*) FROM pg_trigger
            WHERE NOT tgisinternal
              AND tgname IN (
                'payment_execution_events_immutable',
                'provider_transaction_events_immutable',
                'audit_events_immutable'
              )
        """)).one()
        assert trigger_count[0] == 3
    for table, column, row_id in immutable_rows:
        with Session(engine) as session:
            set_platform_db_context(session)
            with pytest.raises(DBAPIError):
                session.exec(
                    text(f"UPDATE {table} SET tenant_id = tenant_id WHERE {column} = :row_id"),
                    params={"row_id": row_id},
                )
                session.commit()
            session.rollback()
        with Session(engine) as session:
            set_platform_db_context(session)
            with pytest.raises(DBAPIError):
                session.exec(text(f"DELETE FROM {table} WHERE {column} = :row_id"), params={"row_id": row_id})
                session.commit()
            session.rollback()
