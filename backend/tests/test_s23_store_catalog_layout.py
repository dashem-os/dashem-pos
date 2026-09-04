"""S23 — the unit's window, the person's band, and the reorder that must be atomic.

The three claims worth proving here are not "the endpoint answers 200".

The first is that permuting positions works at all. A non-deferred unique on
position is checked during the statement, so a swap violates it halfway through
even inside one transaction — which is why dragging was impossible before. The
swap test below is the whole reason the constraint is DEFERRABLE.

The second is that a genuine collision surfaces as a conflict and not as a
crash. Deferring moves the check to COMMIT, so an uncaught IntegrityError there
reaches the operator as a 500. Two managers reordering the same window must get
one winner and one 409.

The third is that personalising never moves the unit's window. That is the point
of the separate band: positions stay put for training, shift change and support,
no matter who has shortcuts.
"""

import os
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.permissions import route_requirement
from app.core.tenancy import set_platform_db_context
from app.models.catalog import QuickAccessProduct, StoreCatalogLayout
from app.models.identity import Membership, MembershipStatusEnum, RoleEnum, User
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.services import catalog_service

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _product(client, headers, suffix, name):
    return (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": name, "sku": f"VIT-{suffix}", "unit": "UN", "tracks_inventory": False,
    })).json()


@pytest.mark.asyncio
async def test_s23_store_window_is_ordered_atomically_and_never_moved_by_a_personal_band():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        suffix = uuid.uuid4().hex[:8]
        tenant = (await client.post("/api/v1/identity/tenants", json={
            "name": f"Vitrine {suffix}", "slug": f"vitrine-{suffix}",
        })).json()
        store = (await client.post("/api/v1/identity/stores", json={
            "tenant_id": tenant["id"], "name": "Matriz", "code": f"VIT-{suffix}",
        })).json()
        with Session(engine) as db:
            set_platform_db_context(db)
            db.add(TenantCapability(
                tenant_id=uuid.UUID(tenant["id"]), key="counter_order",
                enabled=True, status=EntitlementStatusEnum.ACTIVE,
            ))
            db.commit()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        products = [await _product(client, headers, f"{suffix}-{i}", f"Item {i}") for i in range(4)]
        ids = [p["id"] for p in products]

        # An empty window reports version 0, which is what a first reorder sends.
        empty = (await client.get("/api/v1/catalog/layout", headers=headers)).json()
        assert empty["version"] == 0 and empty["product_ids"] == []

        first = await client.put("/api/v1/catalog/layout", headers=headers, json={
            "product_ids": ids[:3], "expected_version": 0,
        })
        assert first.status_code == 200, first.text
        assert first.json()["product_ids"] == ids[:3]
        assert first.json()["version"] == 1

        # THE SWAP. Positions 1 and 3 exchange places. With a non-deferred unique
        # this is the write that cannot happen.
        swapped = [ids[2], ids[1], ids[0]]
        second = await client.put("/api/v1/catalog/layout", headers=headers, json={
            "product_ids": swapped, "expected_version": 1,
        })
        assert second.status_code == 200, second.text
        assert second.json()["product_ids"] == swapped
        assert second.json()["version"] == 2

        # A stale version loses, and is told what it was working from — never a
        # silent overwrite, and never a 500.
        stale = await client.put("/api/v1/catalog/layout", headers=headers, json={
            "product_ids": ids[:2], "expected_version": 1,
        })
        assert stale.status_code == 409, stale.text
        assert (await client.get("/api/v1/catalog/layout", headers=headers)).json()["product_ids"] == swapped

        # The same product twice would renumber the window under the manager.
        duplicated = await client.put("/api/v1/catalog/layout", headers=headers, json={
            "product_ids": [ids[0], ids[0]], "expected_version": 2,
        })
        assert duplicated.status_code == 400, duplicated.text

        # An archived product is not a button: it is refused on the way in, and
        # it also stops being rendered if it is archived after the fact.
        await client.patch(f"/api/v1/catalog/products/{ids[3]}", headers=headers, json={"is_active": False})
        archived = await client.put("/api/v1/catalog/layout", headers=headers, json={
            "product_ids": [ids[0], ids[3]], "expected_version": 2,
        })
        assert archived.status_code == 409, archived.text

        await client.put("/api/v1/catalog/layout", headers=headers, json={
            "product_ids": [ids[0], ids[1], ids[2]], "expected_version": 2,
        })
        await client.patch(f"/api/v1/catalog/products/{ids[1]}", headers=headers, json={"is_active": False})
        rendered = (await client.get("/api/v1/catalog/layout", headers=headers)).json()
        assert ids[1] not in rendered["product_ids"], "produto arquivado continua na vitrine"
        assert rendered["product_ids"] == [ids[0], ids[2]]

        # A different sales context is a different window, not the same one.
        takeaway = await client.put("/api/v1/catalog/layout", headers=headers, json={
            "product_ids": [ids[2]], "expected_version": 0, "sales_context": "TAKEAWAY",
        })
        assert takeaway.status_code == 200, takeaway.text
        counter = (await client.get("/api/v1/catalog/layout", headers=headers)).json()
        assert counter["product_ids"] == [ids[0], ids[2]], "a vitrine do balcão mudou junto com a de retirada"

        with Session(engine) as db:
            set_platform_db_context(db)
            layouts = db.exec(select(StoreCatalogLayout).where(
                StoreCatalogLayout.tenant_id == uuid.UUID(tenant["id"])
            )).all()
            assert {row.sales_context for row in layouts} == {"COUNTER", "TAKEAWAY"}
            assert {row.business_activity for row in layouts} == {"ALL"}


def test_s23_arranging_buttons_never_requires_power_over_the_catalogue():
    """A cashier ordering their own shortcuts is not administering products.

    Before S23 the quick access route demanded `catalog.update`, so the only way
    to let an operator keep their buttons was to hand them the catalogue.
    """
    assert route_requirement("PUT", "/api/v1/catalog/layout").permission == "catalog.layout.manage"
    assert route_requirement("GET", "/api/v1/catalog/layout").permission == "catalog.read"

    for path in ("/api/v1/catalog/quick-access", f"/api/v1/catalog/quick-access/{uuid.uuid4()}"):
        for method in ("PUT", "DELETE"):
            requirement = route_requirement(method, path)
            assert requirement.permission == "catalog.layout.personalize", f"{method} {path}"

    # The catalogue itself did not become cheaper to change.
    assert route_requirement("POST", "/api/v1/catalog/products").permission == "catalog.update"


@pytest.mark.asyncio
async def test_s23_personal_band_is_private_scoped_and_does_not_displace_the_window():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        suffix = uuid.uuid4().hex[:8]
        tenant = (await client.post("/api/v1/identity/tenants", json={
            "name": f"Faixa {suffix}", "slug": f"faixa-{suffix}",
        })).json()
        store = (await client.post("/api/v1/identity/stores", json={
            "tenant_id": tenant["id"], "name": "Matriz", "code": f"FX-{suffix}",
        })).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
        products = [await _product(client, headers, f"{suffix}-{i}", f"Atalho {i}") for i in range(3)]
        ids = [p["id"] for p in products]

        await client.put("/api/v1/catalog/layout", headers=headers, json={
            "product_ids": ids, "expected_version": 0,
        })
        window_before = (await client.get("/api/v1/catalog/layout", headers=headers)).json()["product_ids"]

    # The personal band needs a membership, and the local auth bypass never
    # resolves one — it short-circuits before the membership query. Exercising
    # it at the service boundary is not a shortcut: it is the only place where a
    # real membership exists in this mode.
    with Session(engine) as db:
        set_platform_db_context(db)
        user = User(email=f"vitrine-{suffix}@dashem.test", full_name="Caixa da Vitrine")
        db.add(user)
        db.flush()
        membership = Membership(
            user_id=user.id, tenant_id=uuid.UUID(tenant["id"]),
            role=RoleEnum.CASHIER, status=MembershipStatusEnum.ACTIVE,
        )
        db.add(membership)
        db.commit()
        db.refresh(membership)
        membership_id, user_id = membership.id, membership.user_id

    with Session(engine) as db:
        set_platform_db_context(db)
        context = TenantContext(
            tenant_id=uuid.UUID(tenant["id"]), store_id=uuid.UUID(store["id"]),
            user_id=user_id, membership_id=membership_id, auth_subject="local-auth-bypass",
        )
        personal = catalog_service.reorder_quick_access(
            db, context, [uuid.UUID(ids[2]), uuid.UUID(ids[0])],
        )
        assert [str(row.product_id) for row in personal] == [ids[2], ids[0]]
        assert [row.position for row in personal] == [1, 2]

        # The personal band permutes atomically, on the same deferred constraint.
        reordered = catalog_service.reorder_quick_access(
            db, context, [uuid.UUID(ids[0]), uuid.UUID(ids[2])],
        )
        assert [str(row.product_id) for row in reordered] == [ids[0], ids[2]]

        rows = db.exec(select(QuickAccessProduct).where(
            QuickAccessProduct.tenant_id == uuid.UUID(tenant["id"])
        )).all()
        assert {row.sales_context for row in rows} == {"COUNTER"}
        assert {row.business_activity for row in rows} == {"ALL"}
        assert sorted(row.position for row in rows) == [1, 2]

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        # The whole point of a separate band: personalising moved nothing.
        window_after = (await client.get("/api/v1/catalog/layout", headers=headers)).json()["product_ids"]
        assert window_after == window_before, "a faixa pessoal deslocou a vitrine da unidade"
