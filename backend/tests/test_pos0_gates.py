import uuid
import os
import pytest
import httpx

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")

@pytest.mark.asyncio
async def test_gate_1_and_2_health_and_ports():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        res = await client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["service"] == "Dashem POS"

@pytest.mark.asyncio
async def test_gate_4_and_5_membership_invariants():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Create Tenant 1
        t1_slug = f"tenant-{uuid.uuid4().hex[:6]}"
        t1_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant One", "slug": t1_slug})
        assert t1_res.status_code == 200
        t1 = t1_res.json()

        # Create Store 1 in Tenant 1
        s1_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t1["id"], "name": "Loja 1", "code": "L1"})
        assert s1_res.status_code == 200
        s1 = s1_res.json()

        # Create Tenant 2 and Store 2
        t2_slug = f"tenant-{uuid.uuid4().hex[:6]}"
        t2_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Two", "slug": t2_slug})
        t2 = t2_res.json()

        s2_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t2["id"], "name": "Loja 2", "code": "L2"})
        s2 = s2_res.json()

        # Create User
        u_email = f"user-{uuid.uuid4().hex[:6]}@example.com"
        u_res = await client.post("/api/v1/identity/users", json={"email": u_email, "full_name": "Usuário de Teste", "password": "pass"})
        assert u_res.status_code == 200
        u = u_res.json()

        # Valid Membership: User + Tenant 1 + Store 1
        m_valid = await client.post("/api/v1/identity/memberships", json={
            "user_id": u["id"],
            "tenant_id": t1["id"],
            "store_id": s1["id"],
            "role": "OWNER"
        })
        assert m_valid.status_code == 200

        # INVARIANT VIOLATION: Store 2 (belongs to Tenant 2) assigned to Tenant 1 membership
        m_invalid = await client.post("/api/v1/identity/memberships", json={
            "user_id": u["id"],
            "tenant_id": t1["id"],
            "store_id": s2["id"],  # Wrong tenant!
            "role": "MANAGER"
        })
        assert m_invalid.status_code == 400
        assert "does not belong to Tenant" in m_invalid.json()["detail"]

        # DUPLICATE CONSTRAINT VIOLATION: Duplicate (User, Tenant 1, Store 1)
        m_dup = await client.post("/api/v1/identity/memberships", json={
            "user_id": u["id"],
            "tenant_id": t1["id"],
            "store_id": s1["id"],
            "role": "MANAGER"
        })
        assert m_dup.status_code == 409
        assert "already exists" in m_dup.json()["detail"]

@pytest.mark.asyncio
async def test_gate_6_7_8_atomic_outbox_idempotency_correlation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant_id = str(uuid.uuid4())
        store_id = str(uuid.uuid4())
        actor_id = str(uuid.uuid4())
        idempotency_key = f"key-{uuid.uuid4().hex[:6]}"
        correlation_id = f"corr-{uuid.uuid4().hex[:6]}"

        request_data_A = {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "actor_id": actor_id,
            "action_name": "inventory.adjust",
            "payload_data": "Adjust +10 units"
        }

        # 1. First execution with Idempotency-Key & Correlation ID
        headers = {
            "Idempotency-Key": idempotency_key,
            "X-Correlation-ID": correlation_id
        }
        res1 = await client.post("/api/v1/identity/test-atomic-mutation", json=request_data_A, headers=headers)
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["status"] == "success"
        assert res1.headers["x-correlation-id"] == correlation_id

        # 2. Duplicate execution with SAME key & SAME payload -> Cached 200 Response
        res2 = await client.post("/api/v1/identity/test-atomic-mutation", json=request_data_A, headers=headers)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["audit_id"] == data1["audit_id"]

        # 3. Duplicate execution with SAME key & DIFFERENT payload -> 409 Conflict
        request_data_B = dict(request_data_A)
        request_data_B["payload_data"] = "Adjust +50 units (DIFFERENT)"
        
        res3 = await client.post("/api/v1/identity/test-atomic-mutation", json=request_data_B, headers=headers)
        assert res3.status_code == 409
        err_detail = res3.json()["detail"]
        assert err_detail["code"] == "IDEMPOTENCY_KEY_REUSED"

@pytest.mark.asyncio
async def test_concurrent_idempotency_race_condition():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        import asyncio
        tenant_id = str(uuid.uuid4())
        store_id = str(uuid.uuid4())
        actor_id = str(uuid.uuid4())
        idempotency_key = f"concurrent-key-{uuid.uuid4().hex[:6]}"

        request_data = {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "actor_id": actor_id,
            "action_name": "sale.checkout",
            "payload_data": "Simultaneous Checkout Test"
        }

        headers = {
            "Idempotency-Key": idempotency_key,
            "X-Correlation-ID": f"corr-conc-{uuid.uuid4().hex[:4]}"
        }

        # Send 5 simultaneous requests at the exact same time
        tasks = [
            client.post("/api/v1/identity/test-atomic-mutation", json=request_data, headers=headers)
            for _ in range(5)
        ]
        responses = await asyncio.gather(*tasks)

        # All 5 responses must return 200 OK with identical audit_id / outbox_id
        for res in responses:
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"

        audit_ids = {res.json()["audit_id"] for res in responses}
        assert len(audit_ids) == 1, "Concurrent requests returned divergent audit records!"
