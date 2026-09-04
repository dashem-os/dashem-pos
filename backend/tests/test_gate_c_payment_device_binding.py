"""Gate C — a card execution reaches exactly one persisted route, or none.

ADR-022 says the browser never chooses a provider, a bridge or a pinpad. It
hands over the id of a `PaymentDeviceBinding` and the server rebuilds the whole
chain in the same transaction: tenant, unit, register, POS device, active
provider configuration, execution mode, and — for TEF — the bridge terminal
paired to that same register and provider. For a PIN shift, the device of the
operational session must be exactly the device of the binding.

The implementation was already there, in `_resolve_execution_binding`. What the
confrontation audit of 4/9/2026 found missing was the proof, and it was partly
wrong about that: `test_s9_payment_providers.py` already covers acceptance
criteria 1 (a legacy payload choosing provider and terminal is refused), 4 (an
offline bridge does not block cash, PIX or another intent) and 5 (SmartPOS is
refused explicitly, with no false authorisation).

What was genuinely unproven is the crossing matrix — criteria 2, 3 and 7 — and
that is what this module holds. Every case below is a route that exists and is
legitimate somewhere, pointed at a place it does not belong.
"""

import os
import uuid

import httpx
import pytest

from test_s8_checkout_negotiation import _context, _intent
from test_s9_payment_providers import _payment_binding


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _provider_and_terminal(client, headers, actor, store_id, register_id, code):
    """An active provider configuration with a paired, online bridge terminal."""
    configuration = (await client.post(
        "/api/v1/providers/configurations",
        headers={**headers, "Idempotency-Key": f"config-{uuid.uuid4()}"},
        json={
            "store_id": store_id, "provider_code": "SITEF",
            "credentials_ref": f"secret://tenant/{code}", "actor_id": actor,
        },
    )).json()
    paired = (await client.post(
        "/api/v1/providers/bridge/terminals",
        headers={**headers, "Idempotency-Key": f"pair-{uuid.uuid4()}"},
        json={
            "store_id": store_id, "register_id": register_id,
            "provider_configuration_id": configuration["id"],
            "terminal_code": f"PINPAD-{code}", "actor_id": actor,
        },
    )).json()
    return configuration, paired["terminal"], paired["pairing_code"]


async def _online(client, tenant_id, store_id, terminal, pairing_code):
    response = await client.post(
        f"/api/v1/providers/bridge/terminals/{terminal['id']}/heartbeat",
        json={
            "tenant_id": tenant_id, "store_id": store_id, "pairing_code": pairing_code,
            "bridge_version": "1.0.0", "protocol_version": "1.0",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ONLINE"


async def _card_intent(client, headers, store_id, table_session_id, actor, cash_session):
    """A negotiation with cash already confirmed and a card amount outstanding."""
    negotiation = (await client.post(
        "/api/v1/negotiations",
        headers={**headers, "Idempotency-Key": f"neg-{uuid.uuid4()}"},
        json={"store_id": store_id, "table_session_id": table_session_id, "actor_id": actor},
    )).json()
    _, cash_intent = await _intent(
        client, headers, negotiation["id"], actor, "CASH", 10, uuid.uuid4(), cash_session["id"],
    )
    confirmed = await client.post(
        f"/api/v1/negotiations/intents/{cash_intent['id']}/confirm",
        headers={**headers, "Idempotency-Key": f"cash-{uuid.uuid4()}"},
        json={"actor_id": actor},
    )
    assert confirmed.status_code == 200, confirmed.text
    _, card_intent = await _intent(
        client, headers, negotiation["id"], actor, "CREDIT_CARD", 54.9, uuid.uuid4(),
    )
    return negotiation, card_intent


async def _execute(client, headers, intent_id, binding_id, actor):
    return await client.post(
        "/api/v1/providers/transactions",
        headers={**headers, "Idempotency-Key": f"exec-{uuid.uuid4()}"},
        json={
            "payment_intent_id": intent_id,
            "payment_device_binding_id": binding_id,
            "actor_id": actor,
        },
    )


@pytest.mark.asyncio
async def test_gate_c_refuses_every_binding_that_is_not_this_units_own():
    """Criteria 2 and 7: a real binding, offered where it does not belong."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, _table, table_session, _order, cash = await _context(client, "GateC")
        configuration, terminal, pairing = await _provider_and_terminal(
            client, headers, actor, store["id"], cash["register_id"], "A",
        )
        await _online(client, tenant["id"], store["id"], terminal, pairing)
        binding, _device = await _payment_binding(
            client, headers, actor, store["id"], cash["register_id"],
            configuration["id"], terminal["id"], f"GC-A-{uuid.uuid4().hex[:6]}",
        )
        _negotiation, card_intent = await _card_intent(
            client, headers, store["id"], table_session["id"], actor, cash,
        )

        # A second tenant, complete and legitimate on its own terms.
        other_tenant, other_store, other_headers, other_actor, _t2, _s2, _o2, other_cash = await _context(client, "GateCB")
        other_config, other_terminal, other_pairing = await _provider_and_terminal(
            client, other_headers, other_actor, other_store["id"], other_cash["register_id"], "B",
        )
        await _online(client, other_tenant["id"], other_store["id"], other_terminal, other_pairing)
        other_binding, _other_device = await _payment_binding(
            client, other_headers, other_actor, other_store["id"], other_cash["register_id"],
            other_config["id"], other_terminal["id"], f"GC-B-{uuid.uuid4().hex[:6]}",
        )

        # The neighbour's binding, presented with our own headers. The id is
        # real; it just belongs to somebody else's condominium.
        crossed = await _execute(client, headers, card_intent["id"], other_binding["id"], actor)
        assert crossed.status_code == 409, crossed.text
        assert "vínculo de pagamento ativo" in crossed.json()["detail"]

        # The mirror image, and it has to be built properly to mean anything.
        # Reusing our intent under the neighbour's headers is refused at the
        # intent — correct, and a different rule. To isolate the binding, the
        # neighbour needs a card intent of their own; then everything matches
        # except the route.
        _other_negotiation, other_card_intent = await _card_intent(
            client, other_headers, other_store["id"], _s2["id"], other_actor, other_cash,
        )
        reversed_cross = await _execute(
            client, other_headers, other_card_intent["id"], binding["id"], other_actor,
        )
        assert reversed_cross.status_code == 409, reversed_cross.text
        assert "vínculo de pagamento ativo" in reversed_cross.json()["detail"]

        # The honest route still works, so the refusals above are isolation and
        # not a broken chain.
        allowed = await _execute(client, headers, card_intent["id"], binding["id"], actor)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["transaction"]["status"] in ("PROCESSING", "CONFIRMED")


@pytest.mark.asyncio
async def test_gate_c_refuses_a_binding_whose_chain_stopped_being_true():
    """Criterion 2: the chain is rebuilt per execution, not trusted from before.

    A binding is not a permanent permission. Pausing it, or revoking the POS it
    names, has to stop the next execution even though the row still exists and
    still points at things that exist.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        tenant, store, headers, actor, _table, table_session, _order, cash = await _context(client, "GateCChain")
        configuration, terminal, pairing = await _provider_and_terminal(
            client, headers, actor, store["id"], cash["register_id"], "C",
        )
        await _online(client, tenant["id"], store["id"], terminal, pairing)
        binding, device = await _payment_binding(
            client, headers, actor, store["id"], cash["register_id"],
            configuration["id"], terminal["id"], f"GC-C-{uuid.uuid4().hex[:6]}",
        )
        _negotiation, card_intent = await _card_intent(
            client, headers, store["id"], table_session["id"], actor, cash,
        )

        paused = await client.patch(
            f"/api/v1/providers/device-bindings/{binding['id']}",
            headers={**headers, "Idempotency-Key": f"pause-{uuid.uuid4()}"},
            json={"status": "PAUSED", "reason": "Gate C: pausa antes da execução", "actor_id": actor},
        )
        assert paused.status_code == 200, paused.text

        refused = await _execute(client, headers, card_intent["id"], binding["id"], actor)
        assert refused.status_code == 409, refused.text
        assert "vínculo de pagamento ativo" in refused.json()["detail"]

        resumed = await client.patch(
            f"/api/v1/providers/device-bindings/{binding['id']}",
            headers={**headers, "Idempotency-Key": f"resume-{uuid.uuid4()}"},
            json={"status": "ACTIVE", "reason": "Gate C: reativação", "actor_id": actor},
        )
        assert resumed.status_code == 200, resumed.text

        # With the binding active again, the POS it names is revoked. The row is
        # untouched and still points at a device that exists.
        revoked = await client.patch(
            f"/api/v1/devices/{device['id']}",
            headers=headers,
            json={"status": "REVOKED", "reason": "Gate C: POS retirado de operação", "actor_id": actor},
        )
        assert revoked.status_code == 200, revoked.text

        orphaned = await _execute(client, headers, card_intent["id"], binding["id"], actor)
        assert orphaned.status_code == 409, orphaned.text
        assert "perdeu seu POS ou provider ativo" in orphaned.json()["detail"]


def test_gate_c_a_pin_shift_executes_only_through_its_own_pos():
    """Criterion 3, which the HTTP suite structurally cannot reach.

    The rule fires on `context.auth_provider == "operational"` or an operational
    role. The HTTP tests run against the container with AUTH_MODE=disabled, so
    every request arrives as the local bypass principal: the branch is never
    entered and a green HTTP suite would prove nothing about it. This exercises
    the resolver directly, with a context built the way the middleware builds one
    from a real operational JWT.

    Two POS terminals on the same register, each with its own binding. A shift
    held on the first must not execute through the second — the row is valid,
    the provider is active, the bridge is online, and it is still the wrong
    device for this person's shift.
    """
    import uuid as _uuid
    from datetime import datetime, timedelta

    from fastapi import HTTPException
    from sqlmodel import Session
    import pytest as _pytest

    from app.core.context import TenantContext
    from app.core.database import engine
    from app.core.tenancy import set_platform_db_context, set_tenant_db_context
    from app.models.device import (
        OperationalDevice, OperationalDeviceStatusEnum, OperationalDeviceTypeEnum,
    )
    from app.models.identity import (
        Employee, Membership, MembershipStatusEnum, OperationalCredential,
        OperationalSession, OperationalSessionStatusEnum,
        Register, RoleEnum, Store, Tenant, TenantStatusEnum, User,
    )
    from app.models.provider import (
        BridgeTerminalStatusEnum, PaymentDeviceBinding, PaymentDeviceBindingStatusEnum,
        PaymentDeviceExecutionModeEnum, PaymentProviderConfiguration,
        ProviderConfigurationStatusEnum, TefBridgeTerminal,
    )
    from app.services import provider_service

    suffix = _uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"GateC PIN {suffix}", slug=f"gatec-pin-{suffix}", status=TenantStatusEnum.ACTIVE)
        operator = User(full_name="Operadora do turno")
        session.add(tenant); session.add(operator); session.flush()
        store = Store(tenant_id=tenant.id, name="Matriz", code=f"GCP-{suffix}")
        session.add(store); session.flush()
        register = Register(tenant_id=tenant.id, store_id=store.id, name="Caixa", code=f"CXP-{suffix}")
        session.add(register); session.flush()
        membership = Membership(
            user_id=operator.id, tenant_id=tenant.id, store_id=store.id,
            role=RoleEnum.CASHIER, status=MembershipStatusEnum.ACTIVE,
        )
        configuration = PaymentProviderConfiguration(
            tenant_id=tenant.id, store_id=store.id, provider_code=f"SITEF{suffix[:3]}",
            status=ProviderConfigurationStatusEnum.ACTIVE, credentials_ref="secret://gatec/pin",
            configured_by=operator.id,
        )
        session.add(membership); session.add(configuration); session.flush()
        employee = Employee(
            tenant_id=tenant.id, home_store_id=store.id,
            employee_number=f"OP-{suffix[:5]}", full_name="Operadora do turno",
            user_id=operator.id,
        )
        session.add(employee); session.flush()
        credential = OperationalCredential(
            tenant_id=tenant.id, store_id=store.id, user_id=operator.id,
            membership_id=membership.id, employee_id=employee.id,
            employee_code=f"GC{suffix[:5].upper()}",
        )
        session.add(credential); session.flush()

        # One bridge terminal per register — uq_tef_bridge_register makes that a
        # domain invariant, and it is the right one: the pinpad belongs to the
        # till, not to a screen. Two POS devices share it, each with its own
        # binding, which is exactly the shape that makes criterion 3 matter.
        terminal = TefBridgeTerminal(
            tenant_id=tenant.id, store_id=store.id, register_id=register.id,
            provider_configuration_id=configuration.id, terminal_code=f"PIN-{suffix}",
            pairing_secret_hash="0" * 64, status=BridgeTerminalStatusEnum.ONLINE,
            paired_by=operator.id,
        )
        session.add(terminal); session.flush()

        devices, bindings = [], []
        for index in (1, 2):
            device = OperationalDevice(
                tenant_id=tenant.id, store_id=store.id, code=f"POS{index}-{suffix}",
                name=f"POS {index}", device_type=OperationalDeviceTypeEnum.POS,
                register_id=register.id, status=OperationalDeviceStatusEnum.ACTIVE,
            )
            session.add(device); session.flush()
            binding = PaymentDeviceBinding(
                tenant_id=tenant.id, store_id=store.id, register_id=register.id,
                operational_device_id=device.id, provider_configuration_id=configuration.id,
                tef_bridge_terminal_id=terminal.id,
                execution_mode=PaymentDeviceExecutionModeEnum.TEF_BRIDGE,
                status=PaymentDeviceBindingStatusEnum.ACTIVE, configured_by=operator.id,
                external_device_reference=f"REF-{index}-{suffix}",
            )
            session.add(binding); session.flush()
            devices.append(device); bindings.append(binding)

        shift = OperationalSession(
            tenant_id=tenant.id, store_id=store.id, register_id=register.id,
            device_id=devices[0].id, user_id=operator.id, membership_id=membership.id,
            credential_id=credential.id, terminal_authorization_version=1, credential_version=1,
            expires_at=datetime.utcnow() + timedelta(hours=8),
            status=OperationalSessionStatusEnum.ACTIVE,
        )
        session.add(shift); session.flush()
        ids = (
            tenant.id, store.id, register.id, operator.id, shift.id,
            devices[0].id, bindings[0].id, bindings[1].id,
        )
        session.commit()

    tenant_id, store_id, register_id, operator_id, shift_id, own_device, own_binding, other_binding = ids

    def _shift_context(device_id):
        return TenantContext(
            tenant_id=tenant_id, store_id=store_id, user_id=operator_id,
            role=RoleEnum.CASHIER, auth_subject="authenticated-operator",
            auth_provider="operational", operational_session_id=shift_id,
            register_id=register_id, device_id=device_id,
        )

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, operator_id)

        # The shift's own route resolves: same tenant, unit, register, device.
        binding, configuration, device, terminal = provider_service._resolve_execution_binding(
            session, _shift_context(own_device),
            payment_device_binding_id=own_binding, store_id=store_id,
        )
        assert binding.id == own_binding
        assert device.id == own_device
        assert terminal is not None and terminal.status == BridgeTerminalStatusEnum.ONLINE

        # The neighbouring POS on the same register. Everything about the
        # binding is valid; it simply is not the device this person is on.
        with _pytest.raises(HTTPException) as refused:
            provider_service._resolve_execution_binding(
                session, _shift_context(own_device),
                payment_device_binding_id=other_binding, store_id=store_id,
            )
        assert refused.value.status_code == 403
        assert "não pertence ao POS e caixa vinculados" in refused.value.detail

        # And a claimed device that does not match the persisted shift is
        # refused too, so spoofing the header buys nothing.
        with _pytest.raises(HTTPException) as spoofed:
            provider_service._resolve_execution_binding(
                session, _shift_context(_uuid.uuid4()),
                payment_device_binding_id=own_binding, store_id=store_id,
            )
        assert spoofed.value.status_code == 403
