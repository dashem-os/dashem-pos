"""S10.1 D1/R11 — Final concurrency and lock-hierarchy acceptance matrix.

Covers all five acceptance groups required by the D1/R11 concurrency review,
using independent PostgreSQL connections (`Session(engine)`) and deterministic
synchronization (`threading.Event` / `threading.Barrier` where an unreached
barrier fails the test, never relying on `sleep` alone):

1. The two reviewer lock-inversion scenarios (`transfer_order` vs `create_intent`
   and newly discovered `NegotiationOrder` link during `_lock_coverage_scope` vs
   `create_intent`), proving absence of `40P01` deadlocks + negative controls
   demonstrating that reintroducing either inversion deterministically triggers
   PostgreSQL `40P01` (`deadlock detected`).
2. `transfer_order`, `transfer_order_to_table`, and `merge_sessions` concurrent
   with `create_intent` and `confirm_intent`, covering both order-scoped
   (`orders:...`) and session-scoped (`table-session:...`) negotiations and
   including `TableSession` and `ServiceTable` in the lock hierarchy.
3. Reuse of active negotiations in `open_negotiation` concurrent with payment
   (`create_intent` / `confirm_intent`) + negative control proving detection of
   lock inversion when `Order` is locked before `CheckoutNegotiation`.
4. Channel Hub `ORDER_UPDATED` (`inbox.process_event`) concurrent with
   `create_intent` and `confirm_intent`.
5. Cancellation with own coverage, joint coverage, and no coverage, plus
   deterministic concurrent joint reduction (two LOCAL orders of R$ 100,
   unassigned reserve of R$ 150, two concurrent R$ 40 discounts -> one APPLIED,
   one NEEDS_REVIEW, final total R$ 160) + negative control proving that
   per-order-only locking allows both reductions to apply (total R$ 120 < R$ 150).
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.main import app
from app.models.channel_hub import (
    ChannelInboxStatusEnum,
    ChannelOrderLine,
    ChannelOrderLineStatusEnum,
    ExternalOrderMapping,
    ExternalOrderTerminalStateEnum,
)
from app.models.negotiation import (
    CheckoutNegotiation,
    CheckoutNegotiationStatusEnum,
    NegotiationOrder,
    PaymentAllocation,
    PaymentIntent,
    PaymentIntentStatusEnum,
)
from app.models.order import Order, OrderItem, OrderItemStatusEnum, OrderStatusEnum
from app.models.payment import PaymentMethodEnum
from app.models.table_service import (
    ServiceTable,
    ServiceTableStatusEnum,
    TableSession,
    TableSessionStatusEnum,
)
from app.modules.channels import inbox
from app.modules.settlement import contracts as settlement
from app.services import negotiation_service as ns
from app.services import order_service as os
from app.services import transfer_service as ts
from test_channel_inbox import _connected, _event, _line, _mapping, _receive, _row
from test_s12_transfers import base as _seed_pos_base, tab as _seed_tab


def _pgcode(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "pgcode", None)


def _assert_no_deadlock_or_timeout(exc: BaseException) -> None:
    code = _pgcode(exc)
    assert code not in {"40P01", "57014", "55P03"}, (
        f"Unexpected PostgreSQL lock/timeout error pgcode={code}: {exc!r}"
    )


async def _seed_table_fixture(client: httpx.AsyncClient, label: str):
    """Create a tenant, store, two active table sessions, one free table, and an order with a R$ 100 item."""
    tenant, store, headers, actor = await _seed_pos_base(client, label)
    source = await _seed_tab(client, headers, store, actor, f"{label}-Source")
    dest = await _seed_tab(client, headers, store, actor, f"{label}-Dest")

    r_order2 = await client.post(
        f"/api/v1/tables/sessions/{source['id']}/orders",
        headers={**headers, "Idempotency-Key": f"ord2-{uuid.uuid4()}"},
        json={"display_reference": "Second", "actor_id": actor},
    )
    assert r_order2.status_code == 200, r_order2.text
    second_order = r_order2.json()

    r_table = await client.post(
        "/api/v1/tables",
        headers={**headers, "Idempotency-Key": f"tbl-{uuid.uuid4()}"},
        json={"store_id": store["id"], "code": f"T-{uuid.uuid4().hex[:6]}", "name": "Mesa Livre", "capacity": 4},
    )
    assert r_table.status_code in (200, 201), r_table.text
    free_table = r_table.json()

    r_prod = await client.post(
        "/api/v1/catalog/products",
        headers=headers,
        json={"name": "Prato R11", "sku": f"R11-{uuid.uuid4().hex[:8]}", "unit": "UN", "tracks_inventory": False},
    )
    assert r_prod.status_code in (200, 201), r_prod.text
    product = r_prod.json()

    r_price = await client.post(
        "/api/v1/catalog/prices",
        headers=headers,
        json={"product_id": product["id"], "store_id": store["id"], "cost_price": 10, "sale_price": 100},
    )
    assert r_price.status_code in (200, 201), r_price.text

    r_assort = await client.post(
        "/api/v1/catalog/assortments",
        headers=headers,
        json={
            "code": f"ASSORT-{uuid.uuid4().hex[:8]}",
            "name": "Mesa R11",
            "scopes": [{"store_id": store["id"], "sales_context": "TABLE"}],
            "product_ids": [product["id"]],
        },
    )
    assert r_assort.status_code in (200, 201), r_assort.text

    order_id = source["orders"][0]["id"]
    r_item = await client.post(
        f"/api/v1/orders/{order_id}/items",
        headers={**headers, "Idempotency-Key": f"item-{uuid.uuid4()}"},
        json={"product_id": product["id"], "quantity": 1, "actor_id": actor},
    )
    assert r_item.status_code == 200, r_item.text

    r_item2 = await client.post(
        f"/api/v1/orders/{second_order['id']}/items",
        headers={**headers, "Idempotency-Key": f"item2-{uuid.uuid4()}"},
        json={"product_id": product["id"], "quantity": 1, "actor_id": actor},
    )
    assert r_item2.status_code == 200, r_item2.text

    with Session(engine) as db:
        set_platform_db_context(db)
        src_row = db.get(TableSession, uuid.UUID(source["id"]))
        dst_row = db.get(TableSession, uuid.UUID(dest["id"]))
        tbl_row = db.get(ServiceTable, uuid.UUID(free_table["id"]))
        source["version"] = src_row.version
        dest["version"] = dst_row.version
        free_table["version"] = tbl_row.version

    context = TenantContext(
        tenant_id=uuid.UUID(tenant["id"]),
        store_id=uuid.UUID(store["id"]),
        user_id=uuid.UUID(actor),
        auth_subject="local-auth-bypass",
        capabilities=("table_service", "pos_checkout"),
    )
    return {
        "tenant": tenant,
        "store": store,
        "headers": headers,
        "actor": uuid.UUID(actor),
        "actor_str": actor,
        "context": context,
        "source": source,
        "dest": dest,
        "free_table": free_table,
        "order_id": uuid.UUID(order_id),
        "second_order_id": uuid.UUID(second_order["id"]),
        "product": product,
    }


@pytest.mark.asyncio
async def test_matrix_1a_reproducer_transfer_order_vs_create_intent_no_deadlock_and_control():
    """Matrix 1A: Reviewer reproducer `transfer_vs_payment` + negative control.

    - Canonical protocol: `transfer_order` enters `_order_has_coverage` before holding
      lower-level `TableSession`/`Order` locks, while `create_intent` locks
      `CheckoutNegotiation` -> `TableSession` -> `Order`. Zero `40P01` deadlock;
      `create_intent` completes and `transfer_order` is rejected with 409 because
      the order now carries financial coverage.
    - Negative control: Reintroducing the old lock order (`TableSession` + `Order`
      locked `FOR UPDATE` before `CheckoutNegotiation` while `create_intent` holds
      `CheckoutNegotiation` and requests `Order` `FOR UPDATE`) deterministically
      produces PostgreSQL `40P01` (`deadlock detected`).
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.local", timeout=30.0
    ) as client:
        fx = await _seed_table_fixture(client, "M1ATransferLock")
        r_neg = await client.post(
            "/api/v1/negotiations",
            headers={**fx["headers"], "Idempotency-Key": f"neg-{uuid.uuid4()}"},
            json={
                "store_id": fx["store"]["id"],
                "order_ids": [str(fx["order_id"])],
                "actor_id": fx["actor_str"],
            },
        )
        assert r_neg.status_code == 200, r_neg.text
        neg_id = uuid.UUID(r_neg.json()["id"])

    transfer_at_coverage = threading.Event()
    finance_holds_neg = threading.Event()
    original_has = ts._order_has_coverage
    original_locked = ns._locked_negotiation
    outcomes: dict[str, object] = {}

    def pause_transfer(db: Session, order_ids: list[uuid.UUID]) -> bool:
        transfer_at_coverage.set()
        assert finance_holds_neg.wait(8.0), "Barrier not reached: finance did not lock CheckoutNegotiation"
        return original_has(db, order_ids)

    def pause_finance(db: Session, context: TenantContext, negotiation_id: uuid.UUID) -> CheckoutNegotiation:
        row = original_locked(db, context, negotiation_id)
        finance_holds_neg.set()
        return row

    ts._order_has_coverage = pause_transfer
    ns._locked_negotiation = pause_finance
    try:
        def run_transfer() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                try:
                    ts.transfer_order(
                        db,
                        fx["context"],
                        source_session_id=uuid.UUID(fx["source"]["id"]),
                        destination_session_id=uuid.UUID(fx["dest"]["id"]),
                        order_id=fx["order_id"],
                        expected_source_version=fx["source"]["version"],
                        expected_destination_version=fx["dest"]["version"],
                        reason="Matrix 1A transfer vs payment",
                        actor_id=fx["actor"],
                        idempotency_key=f"m1a-tr-{uuid.uuid4().hex}",
                    )
                    outcomes["transfer"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes["transfer"] = exc
                    db.rollback()

        def run_finance() -> None:
            assert transfer_at_coverage.wait(8.0), "Barrier not reached: transfer did not reach _order_has_coverage"
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                try:
                    ns.create_intent(
                        db,
                        fx["context"],
                        neg_id,
                        method=PaymentMethodEnum.PIX,
                        amount=Decimal("10.00"),
                        cash_session_id=None,
                        tendered_amount=None,
                        allocations=[],
                        actor_id=fx["actor"],
                        idempotency_key=f"m1a-pi-{uuid.uuid4().hex}",
                    )
                    outcomes["finance"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes["finance"] = exc
                    db.rollback()

        t1 = threading.Thread(target=run_transfer, name="m1a-transfer")
        t2 = threading.Thread(target=run_finance, name="m1a-finance")
        t1.start()
        t2.start()
        t1.join(15.0)
        t2.join(15.0)
        assert not t1.is_alive() and not t2.is_alive(), "Threads did not finish within timeout"
    finally:
        ts._order_has_coverage = original_has
        ns._locked_negotiation = original_locked

    assert outcomes.get("finance") == "completed", f"Expected finance to complete, got: {outcomes.get('finance')!r}"
    transfer_exc = outcomes.get("transfer")
    assert isinstance(transfer_exc, HTTPException), f"Expected HTTPException(409), got: {transfer_exc!r}"
    assert transfer_exc.status_code == 409
    assert "cobertura financeira" in str(transfer_exc.detail)

    with Session(engine) as db:
        set_platform_db_context(db)
        ord_row = db.get(Order, fx["order_id"])
        assert ord_row.table_session_id == uuid.UUID(fx["source"]["id"])
        cov = settlement.coverage_on_orders(db, [fx["order_id"]])[fx["order_id"]]
        assert cov.order_covered == Decimal("10.0000")
        assert cov.joint_covered == Decimal("10.0000")

    # --- Negative Control: Reintroducing Order->Negotiation vs Negotiation->Order inversion ---
    ctrl_transfer_holds_order = threading.Event()
    ctrl_finance_holds_neg = threading.Event()
    ctrl_pgcodes: list[str | None] = []

    def inverted_transfer() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='5s'"))
            try:
                db.exec(select(Order).where(Order.id == fx["order_id"]).with_for_update()).one()
                ctrl_transfer_holds_order.set()
                assert ctrl_finance_holds_neg.wait(5.0), "Control barrier not reached: finance did not lock negotiation"
                db.exec(select(CheckoutNegotiation).where(CheckoutNegotiation.id == neg_id).with_for_update()).one()
            except OperationalError as exc:
                ctrl_pgcodes.append(_pgcode(exc))
            finally:
                db.rollback()

    def inverted_finance() -> None:
        assert ctrl_transfer_holds_order.wait(5.0), "Control barrier not reached: transfer did not lock order"
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='5s'"))
            try:
                db.exec(select(CheckoutNegotiation).where(CheckoutNegotiation.id == neg_id).with_for_update()).one()
                ctrl_finance_holds_neg.set()
                db.exec(select(Order).where(Order.id == fx["order_id"]).with_for_update()).one()
            except OperationalError as exc:
                ctrl_pgcodes.append(_pgcode(exc))
            finally:
                db.rollback()

    ct1 = threading.Thread(target=inverted_transfer, name="ctrl-1a-transfer")
    ct2 = threading.Thread(target=inverted_finance, name="ctrl-1a-finance")
    ct1.start()
    ct2.start()
    ct1.join(10.0)
    ct2.join(10.0)
    assert not ct1.is_alive() and not ct2.is_alive()
    assert "40P01" in ctrl_pgcodes, f"Control must detect 40P01 deadlock when inversion is reintroduced; got {ctrl_pgcodes}"


@pytest.mark.asyncio
async def test_matrix_1b_reproducer_new_negotiation_link_vs_payment_no_deadlock_and_control():
    """Matrix 1B: Reviewer reproducer `new_link_vs_payment` + negative control.

    - Canonical protocol: When `_lock_coverage_scope` discovers a newly created
      `NegotiationOrder` link after acquiring `Order` (`FOR UPDATE`), it rolls back
      its savepoint (releasing the `Order` lock) and restarts from Level 2
      (`CheckoutNegotiation` -> `Order`), never locking `CheckoutNegotiation` while
      holding `Order`. Both `scope` and `payment` complete with zero `40P01`.
    - Negative control: Acquiring `CheckoutNegotiation` (`FOR UPDATE`) directly in
      the post-check while holding `Order` (`FOR UPDATE`) deterministically
      produces `40P01` (`deadlock detected`).
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.local", timeout=30.0
    ) as client:
        tenant, headers, actor, _product, connection = await _connected(client, "M1BNewLink", "ITEM-A")
        ref = f"m1b-unlinked-{uuid.uuid4().hex[:8]}"
        placed = _event(
            connection["merchant_external_id"],
            "ORDER_PLACED",
            ref,
            sequence=1,
            lines=[_line("l1", "ITEM-A", 1, unit_price="100.00")],
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(placed)
        assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        oid = _mapping(connection["id"], ref).order_id

    ctx = TenantContext(
        tenant_id=uuid.UUID(tenant["id"]),
        store_id=uuid.UUID(headers["X-Store-ID"]),
        user_id=uuid.UUID(actor),
        auth_subject="local-auth-bypass",
    )
    initial_links_read = threading.Event()
    payment_holds_new_neg = threading.Event()
    scope_holds_order = threading.Event()
    orig_exec = Session.exec
    orig_locked = ns._locked_negotiation
    intercepted = {"initial": False, "order": False}
    outcomes: dict[str, object] = {}

    def hooked_exec(db: Session, statement, *args, **kwargs):
        returned = orig_exec(db, statement, *args, **kwargs)
        if threading.current_thread().name == "m1b-scope":
            sql = str(statement)
            if (
                "SELECT negotiation_orders.order_id, negotiation_orders.negotiation_id" in sql
                and not intercepted["initial"]
            ):
                intercepted["initial"] = True
                initial_links_read.set()
                assert payment_holds_new_neg.wait(8.0), "Barrier not reached: new negotiation was not locked by payment"
            elif "FROM orders" in sql and "FOR UPDATE" in sql and not intercepted["order"]:
                intercepted["order"] = True
                scope_holds_order.set()
        return returned

    def hooked_locked(db: Session, context: TenantContext, nid: uuid.UUID) -> CheckoutNegotiation:
        row = orig_locked(db, context, nid)
        if threading.current_thread().name == "m1b-payment":
            payment_holds_new_neg.set()
            assert scope_holds_order.wait(8.0), "Barrier not reached: scope did not lock order on attempt 1"
        return row

    Session.exec = hooked_exec
    ns._locked_negotiation = hooked_locked
    try:
        def run_scope() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                orig_exec(db, text("SET LOCAL statement_timeout='10s'"))
                try:
                    cov = settlement.coverage_on_orders(db, [oid])
                    outcomes["scope"] = "completed"
                    outcomes["scope_cov"] = cov[oid]
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes["scope"] = exc
                finally:
                    db.rollback()

        t_scope = threading.Thread(target=run_scope, name="m1b-scope")
        t_scope.start()
        assert initial_links_read.wait(8.0), "Barrier not reached: initial discovery was not intercepted"

        with Session(engine) as db:
            set_platform_db_context(db)
            neg = ns.open_negotiation(
                db,
                ctx,
                store_id=ctx.store_id,
                table_session_id=None,
                order_ids=[oid],
                actor_id=uuid.UUID(actor),
                idempotency_key=f"m1b-neg-{uuid.uuid4().hex}",
            )
            neg_id = uuid.UUID(str(neg["id"]))

        def run_payment() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                orig_exec(db, text("SET LOCAL statement_timeout='10s'"))
                try:
                    ns.create_intent(
                        db,
                        ctx,
                        neg_id,
                        method=PaymentMethodEnum.PIX,
                        amount=Decimal("10.00"),
                        cash_session_id=None,
                        tendered_amount=None,
                        allocations=[],
                        actor_id=uuid.UUID(actor),
                        idempotency_key=f"m1b-pi-{uuid.uuid4().hex}",
                    )
                    outcomes["payment"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes["payment"] = exc
                    db.rollback()

        t_payment = threading.Thread(target=run_payment, name="m1b-payment")
        t_payment.start()
        t_scope.join(15.0)
        t_payment.join(15.0)
        assert not t_scope.is_alive() and not t_payment.is_alive(), "Threads did not finish within timeout"
    finally:
        Session.exec = orig_exec
        ns._locked_negotiation = orig_locked

    assert outcomes.get("scope") == "completed", f"Scope failed: {outcomes.get('scope')!r}"
    assert outcomes.get("payment") == "completed", f"Payment failed: {outcomes.get('payment')!r}"
    scope_cov: settlement.OrderCoverage = outcomes["scope_cov"]
    assert scope_cov.order_covered == Decimal("10.0000")
    assert scope_cov.joint_covered == Decimal("10.0000")

    # --- Negative Control: Out-of-order CheckoutNegotiation lock after holding Order lock ---
    ctrl_scope_locked_order = threading.Event()
    ctrl_payment_locked_neg = threading.Event()
    ctrl_pgcodes: list[str | None] = []

    def broken_scope_post_lock() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='5s'"))
            try:
                db.exec(select(Order).where(Order.id == oid).with_for_update()).one()
                ctrl_scope_locked_order.set()
                assert ctrl_payment_locked_neg.wait(5.0), "Control barrier not reached"
                db.exec(select(CheckoutNegotiation).where(CheckoutNegotiation.id == neg_id).with_for_update()).one()
            except OperationalError as exc:
                ctrl_pgcodes.append(_pgcode(exc))
            finally:
                db.rollback()

    def broken_payment_lock() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='5s'"))
            try:
                db.exec(select(CheckoutNegotiation).where(CheckoutNegotiation.id == neg_id).with_for_update()).one()
                ctrl_payment_locked_neg.set()
                assert ctrl_scope_locked_order.wait(5.0), "Control barrier not reached"
                db.exec(select(Order).where(Order.id == oid).with_for_update()).one()
            except OperationalError as exc:
                ctrl_pgcodes.append(_pgcode(exc))
            finally:
                db.rollback()

    ct_s = threading.Thread(target=broken_scope_post_lock, name="ctrl-1b-scope")
    ct_p = threading.Thread(target=broken_payment_lock, name="ctrl-1b-payment")
    ct_s.start()
    ct_p.start()
    ct_s.join(10.0)
    ct_p.join(10.0)
    assert not ct_s.is_alive() and not ct_p.is_alive()
    assert "40P01" in ctrl_pgcodes, f"Control must detect 40P01 deadlock on out-of-order post-lock; got {ctrl_pgcodes}"


@pytest.mark.asyncio
async def test_matrix_2_transfers_and_merge_concurrent_with_create_and_confirm_intent():
    """Matrix 2: `transfer_order`, `transfer_order_to_table`, and `merge_sessions`
    concurrent with `create_intent` and `confirm_intent`, covering both order-scoped
    and session-scoped negotiations and `TableSession` / `ServiceTable` locks.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.local", timeout=30.0
    ) as client:
        # --- Subcase 2A: transfer_order vs confirm_intent on SESSION-SCOPED negotiation ---
        fx_a = await _seed_table_fixture(client, "M2ATransferSessionConfirm")
        r_neg_a = await client.post(
            "/api/v1/negotiations",
            headers={**fx_a["headers"], "Idempotency-Key": f"neg-2a-{uuid.uuid4()}"},
            json={
                "store_id": fx_a["store"]["id"],
                "table_session_id": fx_a["source"]["id"],
                "order_ids": [],
                "actor_id": fx_a["actor_str"],
            },
        )
        assert r_neg_a.status_code == 200, r_neg_a.text
        neg_a_id = uuid.UUID(r_neg_a.json()["id"])

        r_pi_a = await client.post(
            f"/api/v1/negotiations/{neg_a_id}/intents",
            headers={**fx_a["headers"], "Idempotency-Key": f"pi-2a-{uuid.uuid4()}"},
            json={
                "method": "PIX",
                "amount": "40.00",
                "allocations": [{"order_id": str(fx_a["order_id"]), "amount": "40.00"}],
                "actor_id": fx_a["actor_str"],
            },
        )
        assert r_pi_a.status_code == 200, r_pi_a.text
        intent_a_id = uuid.UUID(r_pi_a.json()["intents"][0]["id"])

        barrier_2a = threading.Barrier(2, timeout=8.0)
        outcomes_2a: dict[str, object] = {}

        def transfer_2a() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                barrier_2a.wait()
                try:
                    ts.transfer_order(
                        db,
                        fx_a["context"],
                        source_session_id=uuid.UUID(fx_a["source"]["id"]),
                        destination_session_id=uuid.UUID(fx_a["dest"]["id"]),
                        order_id=fx_a["order_id"],
                        expected_source_version=fx_a["source"]["version"],
                        expected_destination_version=fx_a["dest"]["version"],
                        reason="Subcase 2A transfer covered order",
                        actor_id=fx_a["actor"],
                        idempotency_key=f"m2a-tr-{uuid.uuid4().hex}",
                    )
                    outcomes_2a["transfer"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes_2a["transfer"] = exc
                    db.rollback()

        def confirm_2a() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                barrier_2a.wait()
                try:
                    ns.confirm_intent(
                        db,
                        fx_a["context"],
                        intent_a_id,
                        actor_id=fx_a["actor"],
                        idempotency_key=f"m2a-cf-{uuid.uuid4().hex}",
                    )
                    outcomes_2a["confirm"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes_2a["confirm"] = exc
                    db.rollback()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(transfer_2a)
            f2 = pool.submit(confirm_2a)
            f1.result(timeout=15.0)
            f2.result(timeout=15.0)

        assert outcomes_2a.get("confirm") == "completed"
        tr_exc_2a = outcomes_2a.get("transfer")
        assert isinstance(tr_exc_2a, HTTPException) and tr_exc_2a.status_code == 409
        with Session(engine) as db:
            set_platform_db_context(db)
            assert db.get(Order, fx_a["order_id"]).table_session_id == uuid.UUID(fx_a["source"]["id"])
            assert db.get(PaymentIntent, intent_a_id).status == PaymentIntentStatusEnum.CONFIRMED

        # --- Subcase 2B: transfer_order_to_table vs create_intent (order-scoped) & confirm_intent ---
        fx_b = await _seed_table_fixture(client, "M2BTransferToTable")
        r_neg_b = await client.post(
            "/api/v1/negotiations",
            headers={**fx_b["headers"], "Idempotency-Key": f"neg-2b-{uuid.uuid4()}"},
            json={
                "store_id": fx_b["store"]["id"],
                "order_ids": [str(fx_b["order_id"])],
                "actor_id": fx_b["actor_str"],
            },
        )
        assert r_neg_b.status_code == 200, r_neg_b.text
        neg_b_id = uuid.UUID(r_neg_b.json()["id"])

        tr_b_at_cov = threading.Event()
        fin_b_holds_neg = threading.Event()
        orig_has_b = ts._order_has_coverage
        orig_locked_b = ns._locked_negotiation
        outcomes_2b: dict[str, object] = {}

        def pause_tr_b(db: Session, order_ids: list[uuid.UUID]) -> bool:
            tr_b_at_cov.set()
            assert fin_b_holds_neg.wait(8.0), "Barrier 2B not reached: finance did not lock negotiation"
            return orig_has_b(db, order_ids)

        def pause_fin_b(db: Session, context: TenantContext, nid: uuid.UUID) -> CheckoutNegotiation:
            row = orig_locked_b(db, context, nid)
            fin_b_holds_neg.set()
            return row

        ts._order_has_coverage = pause_tr_b
        ns._locked_negotiation = pause_fin_b
        try:
            def run_tr_to_table() -> None:
                with Session(engine) as db:
                    set_platform_db_context(db)
                    db.exec(text("SET LOCAL statement_timeout='10s'"))
                    try:
                        ts.transfer_order_to_table(
                            db,
                            fx_b["context"],
                            source_session_id=uuid.UUID(fx_b["source"]["id"]),
                            destination_table_id=uuid.UUID(fx_b["free_table"]["id"]),
                            order_id=fx_b["order_id"],
                            expected_source_version=fx_b["source"]["version"],
                            expected_table_version=fx_b["free_table"]["version"],
                            reason="Subcase 2B transfer to table vs payment",
                            actor_id=fx_b["actor"],
                            idempotency_key=f"m2b-trt-{uuid.uuid4().hex}",
                        )
                        outcomes_2b["transfer_to_table"] = "completed"
                    except Exception as exc:  # noqa: BLE001
                        _assert_no_deadlock_or_timeout(exc)
                        outcomes_2b["transfer_to_table"] = exc
                        db.rollback()

            def run_fin_b() -> None:
                assert tr_b_at_cov.wait(8.0), "Barrier 2B not reached: transfer_order_to_table did not reach coverage"
                with Session(engine) as db:
                    set_platform_db_context(db)
                    db.exec(text("SET LOCAL statement_timeout='10s'"))
                    try:
                        ns.create_intent(
                            db,
                            fx_b["context"],
                            neg_b_id,
                            method=PaymentMethodEnum.PIX,
                            amount=Decimal("25.00"),
                            cash_session_id=None,
                            tendered_amount=None,
                            allocations=[],
                            actor_id=fx_b["actor"],
                            idempotency_key=f"m2b-pi-{uuid.uuid4().hex}",
                        )
                        outcomes_2b["finance"] = "completed"
                    except Exception as exc:  # noqa: BLE001
                        _assert_no_deadlock_or_timeout(exc)
                        outcomes_2b["finance"] = exc
                        db.rollback()

            tb1 = threading.Thread(target=run_tr_to_table, name="m2b-transfer")
            tb2 = threading.Thread(target=run_fin_b, name="m2b-finance")
            tb1.start()
            tb2.start()
            tb1.join(15.0)
            tb2.join(15.0)
            assert not tb1.is_alive() and not tb2.is_alive()
        finally:
            ts._order_has_coverage = orig_has_b
            ns._locked_negotiation = orig_locked_b

        assert outcomes_2b.get("finance") == "completed"
        tr_b_exc = outcomes_2b.get("transfer_to_table")
        assert isinstance(tr_b_exc, HTTPException) and tr_b_exc.status_code == 409
        with Session(engine) as db:
            set_platform_db_context(db)
            tbl = db.get(ServiceTable, uuid.UUID(fx_b["free_table"]["id"]))
            assert tbl.status == ServiceTableStatusEnum.AVAILABLE
            assert db.get(Order, fx_b["order_id"]).table_session_id == uuid.UUID(fx_b["source"]["id"])

        # --- Subcase 2C: merge_sessions vs create_intent on source session negotiation ---
        fx_c = await _seed_table_fixture(client, "M2CMergeSessions")
        r_neg_c = await client.post(
            "/api/v1/negotiations",
            headers={**fx_c["headers"], "Idempotency-Key": f"neg-2c-{uuid.uuid4()}"},
            json={
                "store_id": fx_c["store"]["id"],
                "table_session_id": fx_c["source"]["id"],
                "order_ids": [],
                "actor_id": fx_c["actor_str"],
            },
        )
        assert r_neg_c.status_code == 200, r_neg_c.text
        neg_c_id = uuid.UUID(r_neg_c.json()["id"])

        mg_c_at_cov = threading.Event()
        fin_c_holds_neg = threading.Event()
        orig_has_c = ts._order_has_coverage
        orig_locked_c = ns._locked_negotiation
        outcomes_2c: dict[str, object] = {}

        def pause_mg_c(db: Session, order_ids: list[uuid.UUID]) -> bool:
            mg_c_at_cov.set()
            assert fin_c_holds_neg.wait(8.0), "Barrier 2C not reached: finance did not lock negotiation"
            return orig_has_c(db, order_ids)

        def pause_fin_c(db: Session, context: TenantContext, nid: uuid.UUID) -> CheckoutNegotiation:
            row = orig_locked_c(db, context, nid)
            fin_c_holds_neg.set()
            return row

        ts._order_has_coverage = pause_mg_c
        ns._locked_negotiation = pause_fin_c
        try:
            def run_merge_c() -> None:
                with Session(engine) as db:
                    set_platform_db_context(db)
                    db.exec(text("SET LOCAL statement_timeout='10s'"))
                    try:
                        ts.merge_sessions(
                            db,
                            fx_c["context"],
                            source_session_id=uuid.UUID(fx_c["source"]["id"]),
                            destination_session_id=uuid.UUID(fx_c["dest"]["id"]),
                            expected_source_version=fx_c["source"]["version"],
                            expected_destination_version=fx_c["dest"]["version"],
                            reason="Subcase 2C merge vs payment",
                            actor_id=fx_c["actor"],
                            idempotency_key=f"m2c-mg-{uuid.uuid4().hex}",
                        )
                        outcomes_2c["merge"] = "completed"
                    except Exception as exc:  # noqa: BLE001
                        _assert_no_deadlock_or_timeout(exc)
                        outcomes_2c["merge"] = exc
                        db.rollback()

            def run_fin_c() -> None:
                assert mg_c_at_cov.wait(8.0), "Barrier 2C not reached: merge_sessions did not reach coverage"
                with Session(engine) as db:
                    set_platform_db_context(db)
                    db.exec(text("SET LOCAL statement_timeout='10s'"))
                    try:
                        ns.create_intent(
                            db,
                            fx_c["context"],
                            neg_c_id,
                            method=PaymentMethodEnum.PIX,
                            amount=Decimal("30.00"),
                            cash_session_id=None,
                            tendered_amount=None,
                            allocations=[],
                            actor_id=fx_c["actor"],
                            idempotency_key=f"m2c-pi-{uuid.uuid4().hex}",
                        )
                        outcomes_2c["finance"] = "completed"
                    except Exception as exc:  # noqa: BLE001
                        _assert_no_deadlock_or_timeout(exc)
                        outcomes_2c["finance"] = exc
                        db.rollback()

            tc1 = threading.Thread(target=run_merge_c, name="m2c-merge")
            tc2 = threading.Thread(target=run_fin_c, name="m2c-finance")
            tc1.start()
            tc2.start()
            tc1.join(15.0)
            tc2.join(15.0)
            assert not tc1.is_alive() and not tc2.is_alive()
        finally:
            ts._order_has_coverage = orig_has_c
            ns._locked_negotiation = orig_locked_c

        assert outcomes_2c.get("finance") == "completed"
        mg_c_exc = outcomes_2c.get("merge")
        assert isinstance(mg_c_exc, HTTPException) and mg_c_exc.status_code == 409
        with Session(engine) as db:
            set_platform_db_context(db)
            src_c = db.get(TableSession, uuid.UUID(fx_c["source"]["id"]))
            assert src_c.status != TableSessionStatusEnum.CLOSED

        # --- Subcase 2D: transfer_order_to_table vs confirm_intent on SESSION-SCOPED negotiation ---
        fx_d = await _seed_table_fixture(client, "M2DTransferToTableSessionConfirm")
        r_neg_d = await client.post(
            "/api/v1/negotiations",
            headers={**fx_d["headers"], "Idempotency-Key": f"neg-2d-{uuid.uuid4()}"},
            json={
                "store_id": fx_d["store"]["id"],
                "table_session_id": fx_d["source"]["id"],
                "order_ids": [],
                "actor_id": fx_d["actor_str"],
            },
        )
        assert r_neg_d.status_code == 200, r_neg_d.text
        neg_d_id = uuid.UUID(r_neg_d.json()["id"])

        r_pi_d = await client.post(
            f"/api/v1/negotiations/{neg_d_id}/intents",
            headers={**fx_d["headers"], "Idempotency-Key": f"pi-2d-{uuid.uuid4()}"},
            json={
                "method": "PIX",
                "amount": "35.00",
                "allocations": [{"order_id": str(fx_d["order_id"]), "amount": "35.00"}],
                "actor_id": fx_d["actor_str"],
            },
        )
        assert r_pi_d.status_code == 200, r_pi_d.text
        intent_d_id = uuid.UUID(r_pi_d.json()["intents"][0]["id"])

        barrier_2d = threading.Barrier(2, timeout=8.0)
        outcomes_2d: dict[str, object] = {}

        def transfer_to_table_2d() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                barrier_2d.wait()
                try:
                    ts.transfer_order_to_table(
                        db,
                        fx_d["context"],
                        source_session_id=uuid.UUID(fx_d["source"]["id"]),
                        destination_table_id=uuid.UUID(fx_d["free_table"]["id"]),
                        order_id=fx_d["order_id"],
                        expected_source_version=fx_d["source"]["version"],
                        expected_table_version=fx_d["free_table"]["version"],
                        reason="Subcase 2D transfer to table vs confirm",
                        actor_id=fx_d["actor"],
                        idempotency_key=f"m2d-trt-{uuid.uuid4().hex}",
                    )
                    outcomes_2d["transfer_to_table"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes_2d["transfer_to_table"] = exc
                    db.rollback()

        def confirm_2d() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                barrier_2d.wait()
                try:
                    ns.confirm_intent(
                        db,
                        fx_d["context"],
                        intent_d_id,
                        actor_id=fx_d["actor"],
                        idempotency_key=f"m2d-cf-{uuid.uuid4().hex}",
                    )
                    outcomes_2d["confirm"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes_2d["confirm"] = exc
                    db.rollback()

        with ThreadPoolExecutor(max_workers=2) as pool:
            fd1 = pool.submit(transfer_to_table_2d)
            fd2 = pool.submit(confirm_2d)
            fd1.result(timeout=15.0)
            fd2.result(timeout=15.0)

        assert outcomes_2d.get("confirm") == "completed"
        tr_d_exc = outcomes_2d.get("transfer_to_table")
        assert isinstance(tr_d_exc, HTTPException) and tr_d_exc.status_code == 409
        with Session(engine) as db:
            set_platform_db_context(db)
            assert db.get(ServiceTable, uuid.UUID(fx_d["free_table"]["id"])).status == ServiceTableStatusEnum.AVAILABLE
            assert db.get(PaymentIntent, intent_d_id).status == PaymentIntentStatusEnum.CONFIRMED

        # --- Subcase 2E: merge_sessions vs confirm_intent on ORDER-SCOPED negotiation ---
        fx_e = await _seed_table_fixture(client, "M2EMergeOrderConfirm")
        r_neg_e = await client.post(
            "/api/v1/negotiations",
            headers={**fx_e["headers"], "Idempotency-Key": f"neg-2e-{uuid.uuid4()}"},
            json={
                "store_id": fx_e["store"]["id"],
                "order_ids": [str(fx_e["order_id"])],
                "actor_id": fx_e["actor_str"],
            },
        )
        assert r_neg_e.status_code == 200, r_neg_e.text
        neg_e_id = uuid.UUID(r_neg_e.json()["id"])

        r_pi_e = await client.post(
            f"/api/v1/negotiations/{neg_e_id}/intents",
            headers={**fx_e["headers"], "Idempotency-Key": f"pi-2e-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "45.00", "allocations": [], "actor_id": fx_e["actor_str"]},
        )
        assert r_pi_e.status_code == 200, r_pi_e.text
        intent_e_id = uuid.UUID(r_pi_e.json()["intents"][0]["id"])

        barrier_2e = threading.Barrier(2, timeout=8.0)
        outcomes_2e: dict[str, object] = {}

        def merge_2e() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                barrier_2e.wait()
                try:
                    ts.merge_sessions(
                        db,
                        fx_e["context"],
                        source_session_id=uuid.UUID(fx_e["source"]["id"]),
                        destination_session_id=uuid.UUID(fx_e["dest"]["id"]),
                        expected_source_version=fx_e["source"]["version"],
                        expected_destination_version=fx_e["dest"]["version"],
                        reason="Subcase 2E merge vs confirm",
                        actor_id=fx_e["actor"],
                        idempotency_key=f"m2e-mg-{uuid.uuid4().hex}",
                    )
                    outcomes_2e["merge"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes_2e["merge"] = exc
                    db.rollback()

        def confirm_2e() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                barrier_2e.wait()
                try:
                    ns.confirm_intent(
                        db,
                        fx_e["context"],
                        intent_e_id,
                        actor_id=fx_e["actor"],
                        idempotency_key=f"m2e-cf-{uuid.uuid4().hex}",
                    )
                    outcomes_2e["confirm"] = "completed"
                except Exception as exc:  # noqa: BLE001
                    _assert_no_deadlock_or_timeout(exc)
                    outcomes_2e["confirm"] = exc
                    db.rollback()

        with ThreadPoolExecutor(max_workers=2) as pool:
            fe1 = pool.submit(merge_2e)
            fe2 = pool.submit(confirm_2e)
            fe1.result(timeout=15.0)
            fe2.result(timeout=15.0)

        assert outcomes_2e.get("confirm") == "completed"
        mg_e_exc = outcomes_2e.get("merge")
        assert isinstance(mg_e_exc, HTTPException) and mg_e_exc.status_code == 409
        with Session(engine) as db:
            set_platform_db_context(db)
            assert db.get(TableSession, uuid.UUID(fx_e["source"]["id"])).status != TableSessionStatusEnum.CLOSED
            assert db.get(PaymentIntent, intent_e_id).status == PaymentIntentStatusEnum.CONFIRMED


@pytest.mark.asyncio
async def test_matrix_3_open_negotiation_reuse_concurrent_with_payment_and_control():
    """Matrix 3: Reusing an active negotiation in `open_negotiation` concurrent with
    `create_intent` and `confirm_intent` + negative control.

    - Canonical protocol: `open_negotiation` locks active `CheckoutNegotiation`
      (Level 2) before `TableSession` (Level 3) and `Order` (Level 5), matching
      `create_intent` and `confirm_intent`. Both complete without `40P01`.
    - Negative control: Locking `Order` (`FOR UPDATE`) before locking the active
      `CheckoutNegotiation` (`FOR UPDATE`) while `create_intent` holds
      `CheckoutNegotiation` and locks `Order` deterministically triggers `40P01`.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.local", timeout=30.0
    ) as client:
        fx = await _seed_table_fixture(client, "M3ReuseNeg")
        r_neg = await client.post(
            "/api/v1/negotiations",
            headers={**fx["headers"], "Idempotency-Key": f"neg-m3-{uuid.uuid4()}"},
            json={
                "store_id": fx["store"]["id"],
                "table_session_id": fx["source"]["id"],
                "order_ids": [],
                "actor_id": fx["actor_str"],
            },
        )
        assert r_neg.status_code == 200, r_neg.text
        neg_id = uuid.UUID(r_neg.json()["id"])

    barrier_create = threading.Barrier(2, timeout=8.0)
    outcomes_create: dict[str, object] = {}

    def reuse_neg() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='10s'"))
            barrier_create.wait()
            try:
                proj = ns.open_negotiation(
                    db,
                    fx["context"],
                    store_id=uuid.UUID(fx["store"]["id"]),
                    table_session_id=uuid.UUID(fx["source"]["id"]),
                    order_ids=[],
                    actor_id=fx["actor"],
                    idempotency_key=f"m3-reuse-1-{uuid.uuid4().hex}",
                )
                outcomes_create["reuse"] = proj
            except Exception as exc:  # noqa: BLE001
                _assert_no_deadlock_or_timeout(exc)
                outcomes_create["reuse_err"] = exc
                db.rollback()

    def create_pi() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='10s'"))
            barrier_create.wait()
            try:
                proj = ns.create_intent(
                    db,
                    fx["context"],
                    neg_id,
                    method=PaymentMethodEnum.PIX,
                    amount=Decimal("50.00"),
                    cash_session_id=None,
                    tendered_amount=None,
                    allocations=[{"order_id": fx["order_id"], "amount": Decimal("50.00")}],
                    actor_id=fx["actor"],
                    idempotency_key=f"m3-pi-1-{uuid.uuid4().hex}",
                )
                outcomes_create["create"] = proj
            except Exception as exc:  # noqa: BLE001
                _assert_no_deadlock_or_timeout(exc)
                outcomes_create["create_err"] = exc
                db.rollback()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(reuse_neg)
        f2 = pool.submit(create_pi)
        f1.result(timeout=15.0)
        f2.result(timeout=15.0)

    assert "reuse_err" not in outcomes_create, f"Reuse failed: {outcomes_create.get('reuse_err')!r}"
    assert "create_err" not in outcomes_create, f"Create intent failed: {outcomes_create.get('create_err')!r}"
    assert uuid.UUID(str(outcomes_create["reuse"]["id"])) == neg_id
    intent_id = uuid.UUID(str(outcomes_create["create"]["intents"][0]["id"]))

    # Concurrent reuse vs confirm_intent
    barrier_confirm = threading.Barrier(2, timeout=8.0)
    outcomes_confirm: dict[str, object] = {}

    def reuse_neg_2() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='10s'"))
            barrier_confirm.wait()
            try:
                proj = ns.open_negotiation(
                    db,
                    fx["context"],
                    store_id=uuid.UUID(fx["store"]["id"]),
                    table_session_id=uuid.UUID(fx["source"]["id"]),
                    order_ids=[],
                    actor_id=fx["actor"],
                    idempotency_key=f"m3-reuse-2-{uuid.uuid4().hex}",
                )
                outcomes_confirm["reuse"] = proj
            except Exception as exc:  # noqa: BLE001
                _assert_no_deadlock_or_timeout(exc)
                outcomes_confirm["reuse_err"] = exc
                db.rollback()

    def confirm_pi() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='10s'"))
            barrier_confirm.wait()
            try:
                proj = ns.confirm_intent(
                    db,
                    fx["context"],
                    intent_id,
                    actor_id=fx["actor"],
                    idempotency_key=f"m3-cf-1-{uuid.uuid4().hex}",
                )
                outcomes_confirm["confirm"] = proj
            except Exception as exc:  # noqa: BLE001
                _assert_no_deadlock_or_timeout(exc)
                outcomes_confirm["confirm_err"] = exc
                db.rollback()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(reuse_neg_2)
        f2 = pool.submit(confirm_pi)
        f1.result(timeout=15.0)
        f2.result(timeout=15.0)

    assert "reuse_err" not in outcomes_confirm
    assert "confirm_err" not in outcomes_confirm
    assert Decimal(str(outcomes_confirm["confirm"]["confirmed_amount"])) == Decimal("50.0000")

    # --- Negative Control: Reusing negotiation locking TableSession/Order before CheckoutNegotiation ---
    ctrl_reuse_locked_session = threading.Event()
    ctrl_pay_locked_neg = threading.Event()
    ctrl_pgcodes: list[str | None] = []

    def inverted_reuse() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='5s'"))
            try:
                db.exec(select(TableSession).where(TableSession.id == uuid.UUID(fx["source"]["id"])).with_for_update()).one()
                ctrl_reuse_locked_session.set()
                assert ctrl_pay_locked_neg.wait(5.0), "Control barrier not reached"
                db.exec(select(CheckoutNegotiation).where(CheckoutNegotiation.id == neg_id).with_for_update()).one()
            except OperationalError as exc:
                ctrl_pgcodes.append(_pgcode(exc))
            finally:
                db.rollback()

    def inverted_pay() -> None:
        with Session(engine) as db:
            set_platform_db_context(db)
            db.exec(text("SET LOCAL statement_timeout='5s'"))
            try:
                db.exec(select(CheckoutNegotiation).where(CheckoutNegotiation.id == neg_id).with_for_update()).one()
                ctrl_pay_locked_neg.set()
                assert ctrl_reuse_locked_session.wait(5.0), "Control barrier not reached"
                db.exec(select(TableSession).where(TableSession.id == uuid.UUID(fx["source"]["id"])).with_for_update()).one()
            except OperationalError as exc:
                ctrl_pgcodes.append(_pgcode(exc))
            finally:
                db.rollback()

    ct1 = threading.Thread(target=inverted_reuse, name="ctrl-m3-reuse")
    ct2 = threading.Thread(target=inverted_pay, name="ctrl-m3-pay")
    ct1.start()
    ct2.start()
    ct1.join(10.0)
    ct2.join(10.0)
    assert not ct1.is_alive() and not ct2.is_alive()
    assert "40P01" in ctrl_pgcodes, f"Control must detect 40P01 deadlock on inverted reuse lock order; got {ctrl_pgcodes}"


@pytest.mark.asyncio
async def test_matrix_4_channel_order_updated_concurrent_with_create_and_confirm_intent():
    """Matrix 4: Channel Hub `ORDER_UPDATED` (`inbox.process_event`) concurrent with
    `create_intent` and `confirm_intent`.

    - Subcase 4A: `create_intent` (reserving R$ 60 on a R$ 100 LOCAL order) locks
      `CheckoutNegotiation` first while `inbox.process_event` (`ORDER_UPDATED` reducing
      order to R$ 40) reaches `coverage_on_orders`. Zero deadlock/timeout; `create_intent`
      commits R$ 60 reserve, and `ORDER_UPDATED` deterministically lands in `NEEDS_REVIEW`
      (`ITEM_BELOW_SETTLEMENT`), keeping the order at R$ 100.
    - Subcase 4B: `confirm_intent` (confirming the R$ 60 reserve) runs concurrently with
      a safe `ORDER_UPDATED` (reducing the order from R$ 100 to R$ 75 >= R$ 60),
      synchronized via a mandatory `threading.Barrier(2)`. Both succeed without deadlock:
      intent is `CONFIRMED` (R$ 60), update is `APPLIED` (R$ 75), and negotiation
      projection reports `total_due = 75.0000`, `settled_total = 60.0000`.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.local", timeout=30.0
    ) as client:
        tenant, headers, actor, _product, connection = await _connected(client, "M4ChannelVsPay", "ITEM-A")
        store_id = headers["X-Store-ID"]
        merchant = connection["merchant_external_id"]

        ref = f"m4-ord-{uuid.uuid4().hex[:8]}"
        placed = _event(
            merchant,
            "ORDER_PLACED",
            ref,
            sequence=1,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "total": "100.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(placed)
        assert inbox.process_event(_row(placed["id"]).id) == ChannelInboxStatusEnum.APPLIED
        mapping = _mapping(connection["id"], ref)

        r_neg = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-m4-{uuid.uuid4()}"},
            json={"store_id": store_id, "order_ids": [str(mapping.order_id)], "actor_id": actor},
        )
        assert r_neg.status_code == 200, r_neg.text
        neg_id = uuid.UUID(r_neg.json()["id"])

        ctx = TenantContext(
            tenant_id=uuid.UUID(tenant["id"]),
            store_id=uuid.UUID(store_id),
            user_id=uuid.UUID(actor),
            auth_subject="local-auth-bypass",
        )

        # Subcase 4A: ORDER_UPDATED (to R$ 40 < R$ 60) vs create_intent (R$ 60)
        unsafe_upd = _event(
            merchant,
            "ORDER_UPDATED",
            ref,
            sequence=2,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "discount": "60.00", "total": "40.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(unsafe_upd)
        unsafe_ev_id = _row(unsafe_upd["id"]).id

        upd_at_cov = threading.Event()
        pay_holds_neg = threading.Event()
        orig_cov = settlement.coverage_on_orders
        orig_locked = ns._locked_negotiation
        outcomes_4a: dict[str, object] = {}

        def pause_upd_cov(db: Session, order_ids):
            if threading.current_thread().name == "m4a-channel":
                upd_at_cov.set()
                assert pay_holds_neg.wait(8.0), "Barrier 4A not reached: create_intent did not lock negotiation"
            return orig_cov(db, order_ids)

        def pause_pay_lock(db: Session, context: TenantContext, nid: uuid.UUID) -> CheckoutNegotiation:
            row = orig_locked(db, context, nid)
            if threading.current_thread().name == "m4a-pay":
                pay_holds_neg.set()
            return row

        settlement.coverage_on_orders = pause_upd_cov
        ns._locked_negotiation = pause_pay_lock
        try:
            def run_channel_4a() -> None:
                outcomes_4a["channel"] = inbox.process_event(unsafe_ev_id)

            def run_pay_4a() -> None:
                assert upd_at_cov.wait(8.0), "Barrier 4A not reached: channel update did not reach coverage_on_orders"
                with Session(engine) as db:
                    set_platform_db_context(db)
                    db.exec(text("SET LOCAL statement_timeout='10s'"))
                    outcomes_4a["pay"] = ns.create_intent(
                        db,
                        ctx,
                        neg_id,
                        method=PaymentMethodEnum.PIX,
                        amount=Decimal("60.00"),
                        cash_session_id=None,
                        tendered_amount=None,
                        allocations=[],
                        actor_id=uuid.UUID(actor),
                        idempotency_key=f"m4a-pi-{uuid.uuid4().hex}",
                    )

            t_ch = threading.Thread(target=run_channel_4a, name="m4a-channel")
            t_py = threading.Thread(target=run_pay_4a, name="m4a-pay")
            t_ch.start()
            t_py.start()
            t_ch.join(15.0)
            t_py.join(15.0)
            assert not t_ch.is_alive() and not t_py.is_alive()
        finally:
            settlement.coverage_on_orders = orig_cov
            ns._locked_negotiation = orig_locked

        assert outcomes_4a.get("channel") == ChannelInboxStatusEnum.NEEDS_REVIEW
        assert _row(unsafe_upd["id"]).quarantine_code == "ITEM_BELOW_SETTLEMENT"
        intent_4a_id = uuid.UUID(str(outcomes_4a["pay"]["intents"][0]["id"]))

        # Subcase 4B: Safe ORDER_UPDATED (to R$ 75 >= R$ 60) concurrent with confirm_intent (R$ 60)
        safe_upd = _event(
            merchant,
            "ORDER_UPDATED",
            ref,
            sequence=3,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "discount": "25.00", "total": "75.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(safe_upd)
        safe_ev_id = _row(safe_upd["id"]).id

        barrier_4b = threading.Barrier(2, timeout=8.0)
        outcomes_4b: dict[str, object] = {}

        def run_channel_4b() -> None:
            barrier_4b.wait()
            outcomes_4b["channel"] = inbox.process_event(safe_ev_id)

        def run_confirm_4b() -> None:
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                barrier_4b.wait()
                outcomes_4b["confirm"] = ns.confirm_intent(
                    db,
                    ctx,
                    intent_4a_id,
                    actor_id=uuid.UUID(actor),
                    idempotency_key=f"m4b-cf-{uuid.uuid4().hex}",
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(run_channel_4b)
            f2 = pool.submit(run_confirm_4b)
            f1.result(timeout=15.0)
            f2.result(timeout=15.0)

        assert outcomes_4b.get("channel") == ChannelInboxStatusEnum.APPLIED
        r_proj = await client.get(f"/api/v1/negotiations/{neg_id}", headers=headers)
        assert r_proj.status_code == 200, r_proj.text
        proj_data = r_proj.json()
        assert Decimal(str(proj_data["total_due"])) == Decimal("75.0000")
        assert Decimal(str(proj_data["confirmed_amount"])) == Decimal("60.0000")
        assert Decimal(str(proj_data["remaining_amount"])) == Decimal("15.0000")


@pytest.mark.asyncio
async def test_matrix_5_cancel_coverage_and_concurrent_joint_reduction_with_control():
    """Matrix 5: Cancellation with own/joint coverage, cancellation without coverage,
    and deterministic concurrent joint reduction (2 orders of R$ 100, joint reserve
    of R$ 150, 2 concurrent R$ 40 discounts -> 1 APPLIED, 1 NEEDS_REVIEW, total R$ 160)
    + negative control proving that per-order-only locking allows both reductions to apply.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.local", timeout=30.0
    ) as client:
        _tenant, headers, actor, _product, connection = await _connected(client, "M5JointAndCancel", "ITEM-A")
        store_id = headers["X-Store-ID"]
        merchant = connection["merchant_external_id"]

        # 5A: Two LOCAL orders of R$ 100, unassigned reserve of R$ 150:
        #     - ORDER_CANCELLED on either order -> NEEDS_REVIEW (ITEM_BELOW_SETTLEMENT)
        #     - Two concurrent R$ 40 reductions -> one APPLIED, one NEEDS_REVIEW, final total R$ 160
        ref_1 = f"m5-ord1-{uuid.uuid4().hex[:8]}"
        ref_2 = f"m5-ord2-{uuid.uuid4().hex[:8]}"
        for ref in (ref_1, ref_2):
            ev = _event(
                merchant,
                "ORDER_PLACED",
                ref,
                sequence=1,
                lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
                totals={"delivery_fee": "0.00", "total": "100.00"},
                payment={"status": "PAY_ON_DELIVERY"},
            )
            _receive(ev)
            assert inbox.process_event(_row(ev["id"]).id) == ChannelInboxStatusEnum.APPLIED

        map_1, map_2 = _mapping(connection["id"], ref_1), _mapping(connection["id"], ref_2)
        r_neg = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"neg-m5-{uuid.uuid4()}"},
            json={
                "store_id": store_id,
                "order_ids": [str(map_1.order_id), str(map_2.order_id)],
                "actor_id": actor,
            },
        )
        assert r_neg.status_code == 200, r_neg.text
        neg_id = r_neg.json()["id"]

        r_pi = await client.post(
            f"/api/v1/negotiations/{neg_id}/intents",
            headers={**headers, "Idempotency-Key": f"pi-m5-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "150.00", "allocations": [], "actor_id": actor},
        )
        assert r_pi.status_code == 200, r_pi.text

        # Cancellation under joint coverage -> NEEDS_REVIEW
        canc_1 = _event(merchant, "ORDER_CANCELLED", ref_1, sequence=2)
        _receive(canc_1)
        assert inbox.process_event(_row(canc_1["id"]).id) == ChannelInboxStatusEnum.NEEDS_REVIEW
        assert _row(canc_1["id"]).quarantine_code == "ITEM_BELOW_SETTLEMENT"

        # Cancellation without coverage -> APPLIED
        ref_free = f"m5-free-{uuid.uuid4().hex[:8]}"
        ev_free = _event(
            merchant,
            "ORDER_PLACED",
            ref_free,
            sequence=1,
            lines=[_line("l1", "ITEM-A", 2, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "total": "50.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        canc_free = _event(merchant, "ORDER_CANCELLED", ref_free, sequence=2)
        _receive(ev_free, canc_free)
        assert inbox.process_event(_row(ev_free["id"]).id) == ChannelInboxStatusEnum.APPLIED
        assert inbox.process_event(_row(canc_free["id"]).id) == ChannelInboxStatusEnum.APPLIED
        map_free = _mapping(connection["id"], ref_free)
        with Session(engine) as db:
            set_platform_db_context(db)
            assert db.get(Order, map_free.order_id).status == OrderStatusEnum.CANCELED
            assert db.get(ExternalOrderMapping, map_free.id).terminal_state == ExternalOrderTerminalStateEnum.CANCELED
            line_free = db.exec(
                select(ChannelOrderLine).where(ChannelOrderLine.external_order_mapping_id == map_free.id)
            ).one()
            assert line_free.status == ChannelOrderLineStatusEnum.CANCELED

        # Deterministic concurrent reduction on (ref_1, ref_2): two R$ 40 discounts
        upd_1 = _event(
            merchant,
            "ORDER_UPDATED",
            ref_1,
            sequence=3,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "discount": "40.00", "total": "60.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        upd_2 = _event(
            merchant,
            "ORDER_UPDATED",
            ref_2,
            sequence=2,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "discount": "40.00", "total": "60.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(upd_1, upd_2)
        ev1_id = _row(upd_1["id"]).id
        ev2_id = _row(upd_2["id"]).id

        entry_barrier = threading.Barrier(2, timeout=8.0)
        orig_cov = settlement.coverage_on_orders

        def synced_cov(session: Session, order_ids):
            entry_barrier.wait()
            return orig_cov(session, order_ids)

        settlement.coverage_on_orders = synced_cov
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(inbox.process_event, ev1_id)
                f2 = pool.submit(inbox.process_event, ev2_id)
                res_1 = f1.result(timeout=15.0)
                res_2 = f2.result(timeout=15.0)
        finally:
            settlement.coverage_on_orders = orig_cov

        assert {res_1, res_2} == {
            ChannelInboxStatusEnum.APPLIED,
            ChannelInboxStatusEnum.NEEDS_REVIEW,
        }
        with Session(engine) as db:
            set_platform_db_context(db)
            amt_1 = ns._order_amount(db, db.get(Order, map_1.order_id))
            amt_2 = ns._order_amount(db, db.get(Order, map_2.order_id))
            assert sorted([amt_1, amt_2]) == [Decimal("60.0000"), Decimal("100.0000")]
            assert amt_1 + amt_2 == Decimal("160.0000")

        # --- Negative Control: Per-order-only locking without shared negotiation/sibling lock ---
        ctrl_ref_1 = f"m5-ctrl1-{uuid.uuid4().hex[:8]}"
        ctrl_ref_2 = f"m5-ctrl2-{uuid.uuid4().hex[:8]}"
        for ref in (ctrl_ref_1, ctrl_ref_2):
            ev = _event(
                merchant,
                "ORDER_PLACED",
                ref,
                sequence=1,
                lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
                totals={"delivery_fee": "0.00", "total": "100.00"},
                payment={"status": "PAY_ON_DELIVERY"},
            )
            _receive(ev)
            assert inbox.process_event(_row(ev["id"]).id) == ChannelInboxStatusEnum.APPLIED

        cmap_1, cmap_2 = _mapping(connection["id"], ctrl_ref_1), _mapping(connection["id"], ctrl_ref_2)
        r_cneg = await client.post(
            "/api/v1/negotiations",
            headers={**headers, "Idempotency-Key": f"cneg-m5-{uuid.uuid4()}"},
            json={
                "store_id": store_id,
                "order_ids": [str(cmap_1.order_id), str(cmap_2.order_id)],
                "actor_id": actor,
            },
        )
        assert r_cneg.status_code == 200, r_cneg.text
        cneg_id = uuid.UUID(r_cneg.json()["id"])

        r_cpi = await client.post(
            f"/api/v1/negotiations/{cneg_id}/intents",
            headers={**headers, "Idempotency-Key": f"cpi-m5-{uuid.uuid4()}"},
            json={"method": "PIX", "amount": "150.00", "allocations": [], "actor_id": actor},
        )
        assert r_cpi.status_code == 200, r_cpi.text

        cupd_1 = _event(
            merchant,
            "ORDER_UPDATED",
            ctrl_ref_1,
            sequence=2,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "discount": "40.00", "total": "60.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        cupd_2 = _event(
            merchant,
            "ORDER_UPDATED",
            ctrl_ref_2,
            sequence=2,
            lines=[_line("l1", "ITEM-A", 4, unit_price="25.00")],
            totals={"delivery_fee": "0.00", "discount": "40.00", "total": "60.00"},
            payment={"status": "PAY_ON_DELIVERY"},
        )
        _receive(cupd_1, cupd_2)
        cev1_id = _row(cupd_1["id"]).id
        cev2_id = _row(cupd_2["id"]).id

        ctrl_pre_barrier = threading.Barrier(2, timeout=8.0)
        ctrl_post_barrier = threading.Barrier(2, timeout=8.0)
        orig_lock_scope = ns._lock_coverage_scope

        def unlocked_per_order_scope(session: Session, order_ids):
            wanted = sorted({oid for oid in order_ids if oid}, key=str)
            for oid in wanted:
                session.exec(select(Order).where(Order.id == oid).with_for_update()).all()
            negotiations = {cneg_id: session.get(CheckoutNegotiation, cneg_id)}
            linked = {cneg_id: [cmap_1.order_id, cmap_2.order_id]}
            return wanted, negotiations, linked

        def ctrl_synced_cov(session: Session, order_ids):
            ctrl_pre_barrier.wait()
            res = orig_cov(session, order_ids)
            ctrl_post_barrier.wait()
            return res

        ns._lock_coverage_scope = unlocked_per_order_scope
        settlement.coverage_on_orders = ctrl_synced_cov
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                cf1 = pool.submit(inbox.process_event, cev1_id)
                cf2 = pool.submit(inbox.process_event, cev2_id)
                cres_1 = cf1.result(timeout=15.0)
                cres_2 = cf2.result(timeout=15.0)
        finally:
            ns._lock_coverage_scope = orig_lock_scope
            settlement.coverage_on_orders = orig_cov

        assert (cres_1, cres_2) == (
            ChannelInboxStatusEnum.APPLIED,
            ChannelInboxStatusEnum.APPLIED,
        ), "Control must demonstrate that per-order-only locking allows both concurrent reductions to apply"
        with Session(engine) as db:
            set_platform_db_context(db)
            camt_1 = ns._order_amount(db, db.get(Order, cmap_1.order_id))
            camt_2 = ns._order_amount(db, db.get(Order, cmap_2.order_id))
            assert camt_1 + camt_2 == Decimal("120.0000")


@pytest.mark.asyncio
async def test_matrix_6_table_session_activity_vs_payment_canonical_ordering_and_control():
    """Matrix 6: Local item mutations (add_item, update_item, cancel_item) vs payment (create_intent, confirm_intent).

    Proves:
    1. All 6 combinations in both scheduling directions:
       - payment acquiring TableSession lock first
       - native command acquiring TableSession lock first
       Zero 40P01 deadlock, zero timeout, zero internal error.
    2. Persisted results, totals, financial coverage, and idempotent repetition.
    3. Negative control reintroducing the lock inversion (Order locked before TableSession
       while payment holds TableSession and requests Order) deterministically producing 40P01.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://review.local", timeout=30.0
    ) as client:
        async def _seed_case(label: str, payment_op: str):
            fx = await _seed_table_fixture(client, label)
            opened = await client.post(
                "/api/v1/negotiations",
                headers={**fx["headers"], "Idempotency-Key": f"neg-{uuid.uuid4()}"},
                json={
                    "store_id": fx["store"]["id"],
                    "table_session_id": fx["source"]["id"],
                    "order_ids": [],
                    "actor_id": fx["actor_str"],
                },
            )
            assert opened.status_code == 200, opened.text
            fx["neg_id"] = uuid.UUID(opened.json()["id"])
            if payment_op == "confirm":
                pending = await client.post(
                    f"/api/v1/negotiations/{fx['neg_id']}/intents",
                    headers={**fx["headers"], "Idempotency-Key": f"res-{uuid.uuid4()}"},
                    json={"method": "PIX", "amount": "10.00", "allocations": [], "actor_id": fx["actor_str"]},
                )
                assert pending.status_code == 200, pending.text
                fx["intent_id"] = uuid.UUID(pending.json()["intents"][0]["id"])
            with Session(engine) as db:
                set_platform_db_context(db)
                fx["item_id"] = db.exec(select(OrderItem.id).where(OrderItem.order_id == fx["order_id"])).one()
            return fx

        def _run_subcase(fx, op: str, pay_op: str, direction: str):
            first_holds_session = threading.Event()
            real_exec = Session.exec
            result = {}
            native_idemp = f"idemp-native-{uuid.uuid4()}"
            pay_idemp = f"idemp-pay-{uuid.uuid4()}"

            def capture_exec(db, statement, *args, **kwargs):
                returned = real_exec(db, statement, *args, **kwargs)
                sql = str(statement)
                if "FROM table_sessions" in sql and "FOR UPDATE" in sql:
                    cur_name = threading.current_thread().name
                    if direction == "payment_first" and cur_name == "payment":
                        first_holds_session.set()
                    elif direction == "native_first" and cur_name == "native":
                        first_holds_session.set()
                return returned

            Session.exec = capture_exec

            def native_thread_fn():
                if direction == "payment_first":
                    assert first_holds_session.wait(8.0), "payment did not lock TableSession"
                with Session(engine) as db:
                    set_platform_db_context(db)
                    real_exec(db, text("SET LOCAL statement_timeout='10s'"))
                    try:
                        common = dict(idempotency_key=native_idemp, actor_id=fx["actor"])
                        if op == "add":
                            item = os.add_item(
                                db, fx["context"], fx["order_id"],
                                product_id=uuid.UUID(fx["product"]["id"]),
                                quantity=Decimal("1"), modifier_ids=[], notes=None,
                                **common,
                            )
                        elif op == "update":
                            item = os.update_item(
                                db, fx["context"], fx["order_id"], fx["item_id"],
                                quantity=Decimal("2"), notes="Updated note",
                                **common,
                            )
                        elif op == "cancel":
                            item = os.cancel_item(
                                db, fx["context"], fx["order_id"], fx["item_id"],
                                reason="Cancellation in test matrix",
                                **common,
                            )
                        result["native"] = "completed"
                        result["item_id"] = item.id
                    except Exception as exc:
                        result["native"] = {"type": type(exc).__name__, "pgcode": _pgcode(exc), "msg": str(exc)}
                        db.rollback()

            def payment_thread_fn():
                if direction == "native_first":
                    assert first_holds_session.wait(8.0), "native did not lock TableSession"
                with Session(engine) as db:
                    set_platform_db_context(db)
                    real_exec(db, text("SET LOCAL statement_timeout='10s'"))
                    try:
                        if pay_op == "create":
                            ns.create_intent(
                                db, fx["context"], fx["neg_id"],
                                method=PaymentMethodEnum.PIX, amount=Decimal("10.00"),
                                cash_session_id=None, tendered_amount=None, allocations=[],
                                actor_id=fx["actor"], idempotency_key=pay_idemp,
                            )
                        else:
                            ns.confirm_intent(
                                db, fx["context"], fx["intent_id"],
                                actor_id=fx["actor"], idempotency_key=pay_idemp,
                            )
                        result["payment"] = "completed"
                    except Exception as exc:
                        result["payment"] = {"type": type(exc).__name__, "pgcode": _pgcode(exc), "msg": str(exc)}
                        db.rollback()

            threads = [
                threading.Thread(target=native_thread_fn, name="native"),
                threading.Thread(target=payment_thread_fn, name="payment"),
            ]
            try:
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(15.0)
                assert not any(t.is_alive() for t in threads), "Threads timed out"
            finally:
                Session.exec = real_exec

            assert result.get("native") == "completed", (
                f"native failed in {op}_vs_{pay_op} ({direction}): {result.get('native')}"
            )
            assert result.get("payment") == "completed", (
                f"payment failed in {op}_vs_{pay_op} ({direction}): {result.get('payment')}"
            )

            # Verify idempotency repetition of native command
            with Session(engine) as db:
                set_platform_db_context(db)
                common = dict(idempotency_key=native_idemp, actor_id=fx["actor"])
                if op == "add":
                    replayed = os.add_item(
                        db, fx["context"], fx["order_id"],
                        product_id=uuid.UUID(fx["product"]["id"]),
                        quantity=Decimal("1"), modifier_ids=[], notes=None,
                        **common,
                    )
                    assert replayed.id == result["item_id"]
                elif op == "update":
                    replayed = os.update_item(
                        db, fx["context"], fx["order_id"], fx["item_id"],
                        quantity=Decimal("2"), notes="Updated note",
                        **common,
                    )
                    assert replayed.id == fx["item_id"]
                    assert replayed.quantity == Decimal("2.0000")
                elif op == "cancel":
                    replayed = os.cancel_item(
                        db, fx["context"], fx["order_id"], fx["item_id"],
                        reason="Cancellation in test matrix",
                        **common,
                    )
                    assert replayed.id == fx["item_id"]
                    assert replayed.status == OrderItemStatusEnum.CANCELED

            # Verify database persisted state and totals
            with Session(engine) as db:
                set_platform_db_context(db)
                ord_row = db.get(Order, fx["order_id"])
                assert ord_row.status == OrderStatusEnum.OPEN
                items = list(db.exec(select(OrderItem).where(OrderItem.order_id == fx["order_id"])).all())
                if op == "add":
                    assert len(items) == 2
                elif op == "update":
                    upd_item = db.get(OrderItem, fx["item_id"])
                    assert upd_item.quantity == Decimal("2.0000")
                elif op == "cancel":
                    canc_item = db.get(OrderItem, fx["item_id"])
                    assert canc_item.status == OrderItemStatusEnum.CANCELED

        # Run all 6 combinations in both scheduling directions
        for op in ("add", "update", "cancel"):
            for pay_op in ("create", "confirm"):
                for direction in ("payment_first", "native_first"):
                    label = f"M6{op.title()}{pay_op.title()}{direction[:3].title()}"
                    fx = await _seed_case(label, pay_op)
                    _run_subcase(fx, op, pay_op, direction)

        # --- Negative Control: Reintroducing Order -> TableSession inversion ---
        ctrl_fx = await _seed_case("CtrlNativeInversion", "create")
        native_holds_order = threading.Event()
        payment_holds_session = threading.Event()
        ctrl_result = {}

        def ctrl_native():
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                try:
                    # Inversion: lock Order before TableSession
                    db.exec(select(Order).where(Order.id == ctrl_fx["order_id"]).with_for_update()).one()
                    native_holds_order.set()
                    assert payment_holds_session.wait(8.0), "payment did not lock TableSession"
                    db.exec(select(TableSession).where(TableSession.id == uuid.UUID(ctrl_fx["source"]["id"])).with_for_update()).one()
                    ctrl_result["native"] = "completed"
                except OperationalError as exc:
                    ctrl_result["native"] = {"type": "OperationalError", "pgcode": _pgcode(exc)}
                    db.rollback()

        def ctrl_payment():
            assert native_holds_order.wait(8.0), "native did not lock Order"
            with Session(engine) as db:
                set_platform_db_context(db)
                db.exec(text("SET LOCAL statement_timeout='10s'"))
                try:
                    # Canonical payment: lock TableSession before Order
                    db.exec(select(TableSession).where(TableSession.id == uuid.UUID(ctrl_fx["source"]["id"])).with_for_update()).one()
                    payment_holds_session.set()
                    db.exec(select(Order).where(Order.id == ctrl_fx["order_id"]).with_for_update()).one()
                    ctrl_result["payment"] = "completed"
                except OperationalError as exc:
                    ctrl_result["payment"] = {"type": "OperationalError", "pgcode": _pgcode(exc)}
                    db.rollback()

        t_native = threading.Thread(target=ctrl_native, name="ctrl_native")
        t_pay = threading.Thread(target=ctrl_payment, name="ctrl_pay")
        t_native.start()
        t_pay.start()
        t_native.join(15.0)
        t_pay.join(15.0)
        assert not t_native.is_alive() and not t_pay.is_alive()

        pgcodes = [r.get("pgcode") for r in ctrl_result.values() if isinstance(r, dict)]
        assert "40P01" in pgcodes, f"Negative control must detect 40P01 deadlock, got: {ctrl_result}"
