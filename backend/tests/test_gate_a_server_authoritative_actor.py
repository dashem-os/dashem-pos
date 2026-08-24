import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.context import LOCAL_BYPASS_ACTOR_ID, TenantContext, resolve_actor
from app.services import (
    bi_service,
    cash_service,
    channel_catalog_service,
    channel_hub_service,
    device_service,
    fiscal_service,
    inventory_service,
    negotiation_service,
    order_service,
    payment_service,
    production_service,
    provider_service,
    receivable_service,
    reconciliation_service,
    sale_service,
    table_service,
    transfer_service,
)


def _authenticated() -> tuple[TenantContext, uuid.UUID, uuid.UUID]:
    actor_id = uuid.uuid4()
    attacker_id = uuid.uuid4()
    return TenantContext(tenant_id=uuid.uuid4(), user_id=actor_id), actor_id, attacker_id


def test_gate_a_actor_is_always_derived_from_authenticated_context():
    context, actor_id, attacker_id = _authenticated()

    assert resolve_actor(context) == actor_id
    assert resolve_actor(context, actor_id) == actor_id
    with pytest.raises(HTTPException) as rejected:
        resolve_actor(context, attacker_id)
    assert rejected.value.status_code == 403


def test_gate_a_anonymous_context_cannot_author_mutations():
    with pytest.raises(HTTPException) as rejected:
        resolve_actor(TenantContext(tenant_id=uuid.uuid4()), uuid.uuid4())
    assert rejected.value.status_code == 401


def test_gate_a_local_bypass_is_explicit_stable_and_never_zero():
    context = TenantContext(tenant_id=uuid.uuid4(), auth_subject="local-auth-bypass")
    claimed = uuid.uuid4()

    assert resolve_actor(context, claimed) == claimed
    assert resolve_actor(context) == LOCAL_BYPASS_ACTOR_ID
    assert LOCAL_BYPASS_ACTOR_ID.int != 0


def test_gate_a_server_issued_service_identity_is_authoritative():
    service_actor_id = uuid.uuid4()
    context = TenantContext(
        tenant_id=uuid.uuid4(),
        user_id=service_actor_id,
        auth_subject=f"service:tef-bridge:{service_actor_id}",
    )

    assert resolve_actor(context, service_actor_id) == service_actor_id
    with pytest.raises(HTTPException) as rejected:
        resolve_actor(context, uuid.uuid4())
    assert rejected.value.status_code == 403


@pytest.mark.parametrize(
    "resolver",
    [
        channel_catalog_service.actor,
        channel_hub_service._actor,
        device_service._actor,
        negotiation_service._actor,
        order_service._actor,
        production_service._actor,
        provider_service._actor,
        receivable_service._actor,
        table_service._actor,
        transfer_service._actor,
    ],
)
def test_gate_a_domain_resolvers_reject_spoofed_actor(resolver):
    context, _actor_id, attacker_id = _authenticated()
    with pytest.raises(HTTPException) as rejected:
        resolver(context, attacker_id)
    assert rejected.value.status_code == 403


@pytest.mark.parametrize(
    "mutation",
    [
        lambda context, attacker: payment_service.refund_payment(
            None, context, uuid.uuid4(), actor_id=attacker, amount=Decimal("1.00"),
            reason="test", idempotency_key="gate-a-refund", cash_session_id=None,
            provider_reference=None,
        ),
        lambda context, attacker: payment_service.confirm_payment(
            None, context, uuid.uuid4(), actor_id=attacker,
        ),
        lambda context, attacker: fiscal_service.issue_fiscal_document(
            None, context, uuid.uuid4(), attacker,
        ),
        lambda context, attacker: fiscal_service.retry_fiscal_document(
            None, context, uuid.uuid4(), actor_id=attacker,
        ),
        lambda context, attacker: fiscal_service.cancel_fiscal_document(
            None, context, uuid.uuid4(), attacker, "test",
        ),
        lambda context, attacker: inventory_service.adjust_stock(
            None, context, uuid.uuid4(), uuid.uuid4(), attacker, None, Decimal("1.00"),
        ),
        lambda context, attacker: reconciliation_service.reconcile_sale(
            None, context, uuid.uuid4(), actor_id=attacker,
            provider_reported_total=None, provider=None, provider_reference=None, notes=None,
        ),
        lambda context, attacker: sale_service.create_sale(
            None, context, uuid.uuid4(), actor_id=attacker,
        ),
        lambda context, attacker: sale_service.cancel_sale(
            None, context, uuid.uuid4(), actor_id=attacker,
        ),
        lambda context, attacker: sale_service.checkout_sale(
            None, context, uuid.uuid4(), attacker,
        ),
        lambda context, attacker: bi_service.refresh_daily_projection(
            None, context, store_id=uuid.uuid4(), actor_id=attacker,
        ),
        lambda context, attacker: cash_service.open_cash_session(
            None, context, uuid.uuid4(), uuid.uuid4(), attacker, Decimal("0.00"),
        ),
    ],
)
def test_gate_a_direct_mutation_entrypoints_reject_spoofing_before_database_access(mutation):
    context, _actor_id, attacker_id = _authenticated()
    with pytest.raises(HTTPException) as rejected:
        mutation(context, attacker_id)
    assert rejected.value.status_code == 403
