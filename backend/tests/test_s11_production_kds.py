import os
import uuid

import httpx
import pytest
from sqlmodel import Session

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.channel import SalesChannel, SalesChannelTypeEnum

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")

async def _base(client: httpx.AsyncClient, label: str):
    suffix=uuid.uuid4().hex[:8]; actor=str(uuid.uuid4())
    tenant=(await client.post("/api/v1/identity/tenants",json={"name":label,"slug":f"{label.lower()}-{suffix}"})).json()
    store=(await client.post("/api/v1/identity/stores",json={"tenant_id":tenant["id"],"name":"Matriz","code":f"P-{suffix}"})).json()
    with Session(engine) as db:
        set_platform_db_context(db)
        from app.models.platform import TenantCapability, EntitlementStatusEnum
        db.add(TenantCapability(tenant_id=uuid.UUID(tenant["id"]), key="counter_order", enabled=True, status=EntitlementStatusEnum.ACTIVE))
        db.add(TenantCapability(tenant_id=uuid.UUID(tenant["id"]), key="table_service", enabled=True, status=EntitlementStatusEnum.ACTIVE))
        db.add(TenantCapability(tenant_id=uuid.UUID(tenant["id"]), key="delivery_orders", enabled=True, status=EntitlementStatusEnum.ACTIVE))
        db.commit()
    headers={"X-Tenant-ID":tenant["id"],"X-Store-ID":store["id"]}
    product=(await client.post("/api/v1/catalog/products",headers=headers,json={
        "name":"Hambúrguer","sku":f"HB-{suffix}","unit":"UN","tracks_inventory":False,
        "requires_fulfillment":True,"production_destination":"COZINHA"})).json()
    await client.post("/api/v1/catalog/prices",headers=headers,json={"product_id":product["id"],"store_id":store["id"],"cost_price":7,"sale_price":25})
    await client.post("/api/v1/catalog/assortments", headers=headers, json={
        "code": f"ASSORT-KDS-{uuid.uuid4().hex[:8]}",
        "name": "Sortimento KDS",
        "scopes": [
            {"store_id": store["id"], "sales_context": "COUNTER"},
            {"store_id": store["id"], "sales_context": "TAKEAWAY"},
            {"store_id": store["id"], "sales_context": "TABLE"},
            {"store_id": store["id"], "sales_context": "DELIVERY"},
        ],
        "product_ids": [product["id"]],
    })
    kitchen=(await client.post("/api/v1/production/points",headers={**headers,"Idempotency-Key":f"point-{uuid.uuid4()}"},json={
        "store_id":store["id"],"code":"COZINHA","name":"Cozinha","point_type":"KITCHEN","actor_id":actor})).json()
    bar=(await client.post("/api/v1/production/points",headers={**headers,"Idempotency-Key":f"point-{uuid.uuid4()}"},json={
        "store_id":store["id"],"code":"BAR","name":"Bar","point_type":"BAR","actor_id":actor})).json()
    rule=await client.post("/api/v1/production/rules",headers={**headers,"Idempotency-Key":f"rule-{uuid.uuid4()}"},json={
        "production_point_id":kitchen["id"],"product_id":product["id"],"priority":20,"actor_id":actor})
    assert rule.status_code == 200, rule.text
    return tenant,store,headers,actor,product,kitchen,bar

async def _order(client, headers, actor, store, product, fulfillment="COUNTER", origin="POS", channel_id=None, modifiers=None):
    opened=await client.post("/api/v1/orders",headers={**headers,"Idempotency-Key":f"order-{uuid.uuid4()}"},json={
        "store_id":store["id"],"origin":origin,"fulfillment":fulfillment,"channel_id":channel_id,"actor_id":actor})
    assert opened.status_code == 200, opened.text
    item=await client.post(f"/api/v1/orders/{opened.json()['id']}/items",headers={**headers,"Idempotency-Key":f"item-{uuid.uuid4()}"},json={
        "product_id":product["id"],"quantity":1,"modifier_ids":modifiers or [],"actor_id":actor})
    assert item.status_code == 200, item.text
    return opened.json(),item.json()

@pytest.mark.asyncio
async def test_s11_routes_all_origins_modifier_override_and_concurrent_kds_without_touching_price():
  async with httpx.AsyncClient(base_url=BASE_URL) as client:
    tenant,store,headers,actor,product,kitchen,bar=await _base(client,"Production")
    group=(await client.post("/api/v1/catalog/modifier-groups",headers=headers,json={"name":"Preparo","minimum_choices":0,"maximum_choices":1,"is_required":False})).json()
    modifier=(await client.post("/api/v1/catalog/modifiers",headers=headers,json={"group_id":group["id"],"name":"No bar","price_delta":2})).json()
    await client.post(f"/api/v1/catalog/products/{product['id']}/modifier-groups",headers=headers,json={"group_id":group["id"],"position":1})
    override=await client.post("/api/v1/production/rules",headers={**headers,"Idempotency-Key":f"rule-{uuid.uuid4()}"},json={
        "production_point_id":bar["id"],"modifier_id":modifier["id"],"priority":10,"actor_id":actor})
    assert override.status_code == 200
    with Session(engine) as db:
        set_platform_db_context(db)
        channel=SalesChannel(tenant_id=uuid.UUID(tenant["id"]),store_id=uuid.UUID(store["id"]),code=f"EXT-{uuid.uuid4().hex[:6]}",name="Externo",channel_type=SalesChannelTypeEnum.MARKETPLACE,is_active=True)
        db.add(channel); db.commit(); db.refresh(channel); channel_id=str(channel.id)
    counter,counter_item=await _order(client,headers,actor,store,product)
    table,_=await _order(client,headers,actor,store,product,"DINE_IN")
    external,_=await _order(client,headers,actor,store,product,"DELIVERY","SALES_CHANNEL",channel_id)
    modified,modified_item=await _order(client,headers,actor,store,product,modifiers=[modifier["id"]])
    for order in (counter,table,external):
        key=f"dispatch-{uuid.uuid4()}"; response=await client.post(f"/api/v1/production/orders/{order['id']}/dispatch",headers={**headers,"Idempotency-Key":key},json={"actor_id":actor})
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1 and response.json()[0]["point"]["id"] == kitchen["id"]
        retry=await client.post(f"/api/v1/production/orders/{order['id']}/dispatch",headers={**headers,"Idempotency-Key":key},json={"actor_id":actor})
        assert retry.json()[0]["ticket"]["id"] == response.json()[0]["ticket"]["id"]
    routed=await client.post(f"/api/v1/production/orders/{modified['id']}/dispatch",headers={**headers,"Idempotency-Key":f"dispatch-{uuid.uuid4()}"},json={"actor_id":actor})
    assert len(routed.json()) == 1 and routed.json()[0]["point"]["id"] == bar["id"]
    ticket=routed.json()[0]["ticket"]
    transition_key=f"transition-{uuid.uuid4()}"
    accepted=await client.post(f"/api/v1/production/tickets/{ticket['id']}/transition",headers={**headers,"Idempotency-Key":transition_key},json={"target":"ACCEPTED","expected_version":1,"actor_id":actor,"device_id":"kds-a"})
    assert accepted.status_code == 200 and accepted.json()["ticket"]["version"] == 2
    retry=await client.post(f"/api/v1/production/tickets/{ticket['id']}/transition",headers={**headers,"Idempotency-Key":transition_key},json={"target":"ACCEPTED","expected_version":1,"actor_id":actor,"device_id":"kds-a"})
    assert retry.status_code == 200
    stale=await client.post(f"/api/v1/production/tickets/{ticket['id']}/transition",headers={**headers,"Idempotency-Key":f"transition-{uuid.uuid4()}"},json={"target":"PREPARING","expected_version":1,"actor_id":actor,"device_id":"kds-b"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "PRODUCTION_VERSION_CONFLICT"
    fresh=await client.post(f"/api/v1/production/tickets/{ticket['id']}/transition",headers={**headers,"Idempotency-Key":f"transition-{uuid.uuid4()}"},json={"target":"PREPARING","expected_version":2,"actor_id":actor,"device_id":"kds-b"})
    assert fresh.status_code == 200
    unchanged=(await client.get(f"/api/v1/orders/{modified['id']}",headers=headers)).json()
    persisted=next(item for item in unchanged["items"] if item["id"]==modified_item["id"])
    assert float(persisted["unit_price"]) == float(modified_item["unit_price"]) == 27
    other_tenant,other_store,other_headers,*_=await _base(client,"OtherProduction")
    visible=await client.get("/api/v1/production/tickets",headers=other_headers)
    assert all(row["ticket"]["id"] != ticket["id"] for row in visible.json())
