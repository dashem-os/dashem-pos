import os
import uuid
from datetime import datetime

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.bi import BiDailyFact, BiFactScopeEnum, BiProjectionState
from test_s14_receivables import _context
from test_s15_receivable_collection import _issue


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


@pytest.mark.asyncio
async def test_s17_projection_is_rebuildable_scoped_and_drills_to_persisted_sources():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant_a, store_a, headers_a, actor_a, customer_a, product_a = await _context(client, "BI-A")
        policy = await client.put(f"/api/v1/receivables/customers/{customer_a['id']}/policy", headers=headers_a, json={
            "credit_limit": 500, "terms_days": 30, "status": "ACTIVE", "actor_id": actor_a,
        })
        assert policy.status_code == 200
        receivable = await _issue(client, store_a, headers_a, actor_a, customer_a, product_a)
        today = datetime.utcnow().date().isoformat()
        refresh = await client.post("/api/v1/management/bi/refresh", headers=headers_a, json={
            "actor_id": actor_a, "start_date": today, "end_date": today,
        })
        assert refresh.status_code == 200, refresh.text
        first_version = refresh.json()["version"]
        overview = await client.get("/api/v1/management/overview?days=7", headers=headers_a)
        assert overview.status_code == 200, overview.text
        body = overview.json()
        assert body["revenue_today"] == 60
        assert body["sales_today"] == 1
        assert body["receivables_issued_30d"] == 60
        assert body["projection_lag_seconds"] >= 0
        assert "net_revenue" in body["formulas"]
        drilldown = await client.get(f"/api/v1/management/bi/drilldown?metric=net_revenue&competence_date={today}", headers=headers_a)
        assert drilldown.status_code == 200, drilldown.text
        assert drilldown.json()["total"] == 1
        assert drilldown.json()["items"][0]["source_id"] == receivable["sale_id"]

        rebuilt = await client.post("/api/v1/management/bi/refresh", headers=headers_a, json={
            "actor_id": actor_a, "start_date": today, "end_date": today,
        })
        assert rebuilt.status_code == 200
        assert rebuilt.json()["version"] == first_version + 1
        after_rebuild = await client.get("/api/v1/management/overview?days=7", headers=headers_a)
        assert after_rebuild.json()["revenue_today"] == 60

        tenant_b, store_b, headers_b, actor_b, *_ = await _context(client, "BI-B")
        refresh_b = await client.post("/api/v1/management/bi/refresh", headers=headers_b, json={
            "actor_id": actor_b, "start_date": today, "end_date": today,
        })
        assert refresh_b.status_code == 200, refresh_b.text
        overview_b = await client.get("/api/v1/management/overview?days=7", headers=headers_b)
        assert overview_b.status_code == 200
        assert overview_b.json()["revenue_today"] == 0
        assert overview_b.json()["sales_today"] == 0

    with Session(engine) as db:
        set_platform_db_context(db)
        a_facts = db.exec(select(BiDailyFact).where(BiDailyFact.tenant_id == uuid.UUID(tenant_a["id"]))).all()
        b_facts = db.exec(select(BiDailyFact).where(BiDailyFact.tenant_id == uuid.UUID(tenant_b["id"]))).all()
        assert len([item for item in a_facts if item.scope == BiFactScopeEnum.SALES]) == 1
        assert len([item for item in b_facts if item.scope == BiFactScopeEnum.SALES]) == 0
        assert len(db.exec(select(BiProjectionState).where(BiProjectionState.store_id == uuid.UUID(store_a["id"]))).all()) == 1
