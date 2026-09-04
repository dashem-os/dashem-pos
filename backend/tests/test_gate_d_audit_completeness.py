"""Gate D — the three criteria the existing suite did not reach.

`test_gate_d_payment_audit.py` already proves most of ADR-023: the four stages
are distinct and ordered, the immutability triggers reject UPDATE and DELETE on
all three trails, a sibling unit sees none of the events, and productivity is
persisted, rebuildable and published with its formulas.

Three things were not covered, and this module holds them:

  * criterion 2 is a six-part scope check — tenant, unit, register, device,
    session and binding — and the existing test varies four of them. A binding
    from the sibling register and a mismatched register were unproven, which
    matters because those are the two elements a caller could plausibly get
    wrong without malice;
  * criterion 3 says a service callback must not assume the person's identity.
    The bridge reports a result under its own principal while the operator and
    shift of origin survive on the event — human authorship and service
    authorship are adjacent, never merged;
  * criterion 4 says a repeated result is not recorded twice, while a genuinely
    different outcome still is. UNKNOWN becoming CONFIRMED is a real transition
    and must append; CONFIRMED reported twice must not.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.device import OperationalDevice, OperationalDeviceTypeEnum
from app.models.identity import (
    Employee, Membership, MembershipStatusEnum, OperationalCredential,
    OperationalSession, Register, RoleEnum, Store, Tenant, TenantStatusEnum, User,
)
from app.models.negotiation import CheckoutNegotiation, PaymentIntent
from app.models.payment import PaymentMethodEnum
from app.models.provider import (
    PaymentDeviceBinding, PaymentDeviceExecutionModeEnum, PaymentExecutionEvent,
    PaymentExecutionStageEnum, PaymentProviderConfiguration,
    ProviderConfigurationStatusEnum, ProviderTransaction, ProviderTransactionStatusEnum,
)
from app.services import payment_audit_service


def _fixture():
    """One audited shift, plus a sibling register with a binding of its own."""
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"GateD C {suffix}", slug=f"gate-d-c-{suffix}", status=TenantStatusEnum.ACTIVE)
        operator = User(full_name="Operadora auditada")
        session.add(tenant); session.add(operator); session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"GDC-{suffix}")
        session.add(store); session.flush()
        register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa 1", code=f"GDC1-{suffix}")
        sibling_register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa 2", code=f"GDC2-{suffix}")
        membership = Membership(
            user_id=operator.id, tenant_id=tenant.id, store_id=store.id,
            role=RoleEnum.OPERATOR, status=MembershipStatusEnum.ACTIVE,
        )
        employee = Employee(
            tenant_id=tenant.id, user_id=operator.id, home_store_id=store.id,
            employee_number=f"GDC-{suffix}", full_name=operator.full_name,
        )
        session.add(register); session.add(sibling_register)
        session.add(membership); session.add(employee); session.flush()
        credential = OperationalCredential(
            tenant_id=tenant.id, store_id=store.id, user_id=operator.id,
            membership_id=membership.id, employee_id=employee.id,
            employee_code=f"GDC{suffix}", pin_salt="salt", pin_hash="hash",
        )
        configuration = PaymentProviderConfiguration(
            tenant_id=tenant.id, store_id=store.id, provider_code=f"GATE-D-C-{suffix}",
            status=ProviderConfigurationStatusEnum.ACTIVE, configured_by=operator.id,
        )
        session.add(credential); session.add(configuration); session.flush()

        devices, bindings = [], []
        for index, reg in enumerate((register, sibling_register), start=1):
            device = OperationalDevice(
                tenant_id=tenant.id, store_id=store.id, code=f"GDCPOS{index}-{suffix}",
                name=f"POS {index}", device_type=OperationalDeviceTypeEnum.POS, register_id=reg.id,
            )
            session.add(device); session.flush()
            binding = PaymentDeviceBinding(
                tenant_id=tenant.id, store_id=store.id, register_id=reg.id,
                operational_device_id=device.id, provider_configuration_id=configuration.id,
                execution_mode=PaymentDeviceExecutionModeEnum.SMARTPOS,
                external_device_reference=f"GDC-{index}-{suffix}", configured_by=operator.id,
            )
            session.add(binding); session.flush()
            devices.append(device); bindings.append(binding)

        authority = OperationalSession(
            tenant_id=tenant.id, store_id=store.id, register_id=register.id,
            device_id=devices[0].id, user_id=operator.id, membership_id=membership.id,
            credential_id=credential.id, terminal_authorization_version=devices[0].authorization_version,
            credential_version=credential.session_version,
            expires_at=datetime.utcnow() + timedelta(hours=8),
        )
        negotiation = CheckoutNegotiation(
            tenant_id=tenant.id, store_id=store.id, scope_key=f"GATE-D-C:{suffix}",
            subtotal=Decimal("100.00"), total_due=Decimal("100.00"), source_version=1,
            opened_by=operator.id, open_idempotency_key=f"gdc-neg-{suffix}", open_request_hash="n" * 64,
        )
        session.add(authority); session.add(negotiation); session.flush()
        intent = PaymentIntent(
            tenant_id=tenant.id, store_id=store.id, negotiation_id=negotiation.id,
            method=PaymentMethodEnum.CREDIT_CARD, amount=Decimal("100.00"),
            provider="GATE_D_C", idempotency_key=f"gdc-intent-{suffix}", request_hash="i" * 64,
            created_by=operator.id,
        )
        session.add(intent); session.flush()
        transaction = ProviderTransaction(
            tenant_id=tenant.id, store_id=store.id, payment_intent_id=intent.id,
            provider_configuration_id=configuration.id, payment_device_binding_id=bindings[0].id,
            provider_code=configuration.provider_code, adapter_version="1.0.0",
            correlation_id=f"gdc-corr-{suffix}", idempotency_key=f"gdc-tx-{suffix}",
            request_hash="t" * 64, created_by=operator.id,
        )
        session.add(transaction); session.flush()
        ids = {
            "tenant": tenant.id, "store": store.id, "register": register.id,
            "sibling_register": sibling_register.id, "operator": operator.id,
            "authority": authority.id, "device": devices[0].id, "sibling_device": devices[1].id,
            "binding": bindings[0].id, "sibling_binding": bindings[1].id,
            "intent": intent.id, "transaction": transaction.id,
        }
        session.commit()
    return ids


def _context(ids):
    return TenantContext(
        tenant_id=ids["tenant"], store_id=ids["store"], user_id=ids["operator"],
        role=RoleEnum.OPERATOR, auth_subject="authenticated-operator",
        auth_provider="operational", operational_session_id=ids["authority"],
        register_id=ids["register"], device_id=ids["device"],
    )


def _load(session, ids):
    return (
        session.get(ProviderTransaction, ids["transaction"]),
        session.get(PaymentIntent, ids["intent"]),
        session.get(PaymentDeviceBinding, ids["binding"]),
        session.get(OperationalDevice, ids["device"]),
    )


def test_gate_d_refuses_a_binding_or_register_from_the_neighbouring_till():
    """Criterion 2, on the two elements the existing suite left unvaried."""
    ids = _fixture()
    with Session(engine) as session:
        set_tenant_db_context(session, ids["tenant"], ids["store"], ids["operator"])
        transaction, intent, binding, device = _load(session, ids)
        sibling_binding = session.get(PaymentDeviceBinding, ids["sibling_binding"])
        sibling_device = session.get(OperationalDevice, ids["sibling_device"])

        # A binding that belongs to the till next door. The transaction names
        # our binding, so the mismatch is caught before any event is written.
        with pytest.raises(HTTPException) as wrong_binding:
            payment_audit_service.record_request_and_approval(
                session, _context(ids), transaction=transaction, intent=intent,
                binding=sibling_binding, device=sibling_device, actor_id=ids["operator"],
            )
        assert wrong_binding.value.status_code == 403
        assert "Escopo de auditoria" in wrong_binding.value.detail

        # The register claimed in the context does not match the binding's.
        with pytest.raises(HTTPException) as wrong_register:
            payment_audit_service.record_request_and_approval(
                session, _context(ids).model_copy(update={"register_id": ids["sibling_register"]}),
                transaction=transaction, intent=intent, binding=binding,
                device=device, actor_id=ids["operator"],
            )
        assert wrong_register.value.status_code == 403

        # Nothing was written by either refusal.
        assert session.exec(select(PaymentExecutionEvent).where(
            PaymentExecutionEvent.provider_transaction_id == ids["transaction"],
        )).all() == []


def test_gate_d_keeps_service_authorship_beside_human_authorship():
    """Criterion 3: the bridge reports, the operator keeps the shift."""
    ids = _fixture()
    bridge_principal = uuid.uuid4()
    with Session(engine) as session:
        set_tenant_db_context(session, ids["tenant"], ids["store"], ids["operator"])
        transaction, intent, binding, device = _load(session, ids)
        payment_audit_service.record_request_and_approval(
            session, _context(ids), transaction=transaction, intent=intent,
            binding=binding, device=device, actor_id=ids["operator"],
        )
        # The callback arrives with the bridge as principal, exactly as
        # report_bridge_result builds it: no operational session, a service
        # subject, and the terminal as user.
        service_context = TenantContext(
            tenant_id=ids["tenant"], store_id=ids["store"], user_id=bridge_principal,
            auth_subject=f"service:tef-bridge:{bridge_principal}",
        )
        payment_audit_service.record_execution_result(
            session, service_context, transaction=transaction, intent=intent,
            actor_id=bridge_principal, outcome=ProviderTransactionStatusEnum.CONFIRMED,
        )
        session.commit()

    with Session(engine) as session:
        set_tenant_db_context(session, ids["tenant"], ids["store"], ids["operator"])
        events = list(session.exec(select(PaymentExecutionEvent).where(
            PaymentExecutionEvent.provider_transaction_id == ids["transaction"],
        ).order_by(PaymentExecutionEvent.sequence)).all())
        result = next(e for e in events if e.stage == PaymentExecutionStageEnum.RESULT_RECORDED)

        # The bridge is the author of this event...
        assert result.event_actor_id == bridge_principal
        # ...and the person whose shift produced the sale is still on it.
        assert result.operational_actor_id == ids["operator"]
        assert result.operational_session_id == ids["authority"]
        assert result.operational_device_id == ids["device"]
        assert result.event_actor_id != result.operational_actor_id


def test_gate_d_records_a_changed_outcome_and_ignores_a_repeated_one():
    """Criterion 4: idempotent on sameness, honest about a real transition."""
    ids = _fixture()
    with Session(engine) as session:
        set_tenant_db_context(session, ids["tenant"], ids["store"], ids["operator"])
        transaction, intent, binding, device = _load(session, ids)
        payment_audit_service.record_request_and_approval(
            session, _context(ids), transaction=transaction, intent=intent,
            binding=binding, device=device, actor_id=ids["operator"],
        )
        context = _context(ids)

        def outcomes():
            return [
                event.outcome for event in session.exec(select(PaymentExecutionEvent).where(
                    PaymentExecutionEvent.provider_transaction_id == ids["transaction"],
                    PaymentExecutionEvent.stage == PaymentExecutionStageEnum.RESULT_RECORDED,
                ).order_by(PaymentExecutionEvent.sequence)).all()
            ]

        # A timeout reported as UNKNOWN, then the same timeout reported again.
        for _ in range(2):
            payment_audit_service.record_execution_result(
                session, context, transaction=transaction, intent=intent,
                actor_id=ids["operator"], outcome=ProviderTransactionStatusEnum.UNKNOWN,
            )
        assert outcomes() == ["UNKNOWN"], "um resultado idêntico não pode virar dois fatos"

        # Reconciliation finds the charge went through. That is a different
        # outcome and has to become a new fact, never a rewrite of the old one.
        payment_audit_service.record_execution_result(
            session, context, transaction=transaction, intent=intent,
            actor_id=ids["operator"], outcome=ProviderTransactionStatusEnum.CONFIRMED,
        )
        assert outcomes() == ["UNKNOWN", "CONFIRMED"]

        # And the confirmation repeated does not double either.
        payment_audit_service.record_execution_result(
            session, context, transaction=transaction, intent=intent,
            actor_id=ids["operator"], outcome=ProviderTransactionStatusEnum.CONFIRMED,
        )
        assert outcomes() == ["UNKNOWN", "CONFIRMED"]

        # EXECUTED is written once no matter how many results arrive.
        executed = session.exec(select(PaymentExecutionEvent).where(
            PaymentExecutionEvent.provider_transaction_id == ids["transaction"],
            PaymentExecutionEvent.stage == PaymentExecutionStageEnum.EXECUTED,
        )).all()
        assert len(executed) == 1
