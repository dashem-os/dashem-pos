import os
import uuid
from datetime import datetime, timedelta

import httpx
import pytest


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _context(client: httpx.AsyncClient, prefix: str):
    suffix = uuid.uuid4().hex[:8]
    tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"{prefix} {suffix}", "slug": f"{prefix.lower()}-{suffix}"})).json()
    store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"{prefix[:3].upper()}-{suffix}"})).json()
    return tenant, store, {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}


@pytest.mark.asyncio
async def test_s13_1_backoffice_separates_configuration_reservation_and_attendant_state():
    actor = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        _tenant, store, headers = await _context(client, "Backoffice")
        area_response = await client.post("/api/v1/tables/areas", headers=headers, json={
            "store_id": store["id"], "code": "SALAO", "name": "Salão principal",
            "kind": "INTERNAL", "sort_order": 10, "actor_id": actor,
        })
        assert area_response.status_code == 201, area_response.text
        area = area_response.json()
        table_response = await client.post("/api/v1/tables", headers={**headers, "Idempotency-Key": f"table-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "code": "M-01", "name": "Mesa 01", "capacity": 4,
            "area_id": area["id"], "sort_order": 1, "actor_id": actor,
        })
        assert table_response.status_code == 200, table_response.text
        table = table_response.json()
        assert table["area"] == "Salão principal"
        assert table["area_id"] == area["id"]

        reservation_response = await client.post(f"/api/v1/tables/{table['id']}/reservations", headers={
            **headers, "Idempotency-Key": f"reservation-{uuid.uuid4()}",
        }, json={
            "customer_name": "Marcelo Cliente", "customer_phone": "21999999999", "party_size": 3,
            "reserved_for": (datetime.utcnow() + timedelta(minutes=10)).isoformat(),
            "duration_minutes": 90, "notes": "Janela", "actor_id": actor,
        })
        assert reservation_response.status_code == 201, reservation_response.text
        reservation = reservation_response.json()
        assert reservation["duration_minutes"] == 90
        projection = (await client.get("/api/v1/tables", headers=headers)).json()[0]
        assert projection["status"] == "RESERVED"
        assert projection["active_reservation"]["id"] == reservation["id"]

        denied = await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": f"open-denied-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "service_table_id": table["id"], "actor_id": actor,
        })
        assert denied.status_code == 409
        opened = await client.post("/api/v1/tables/sessions", headers={**headers, "Idempotency-Key": f"open-confirmed-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "service_table_id": table["id"], "reservation_id": reservation["id"], "actor_id": actor,
        })
        assert opened.status_code == 200, opened.text
        assert opened.json()["service_table"]["status"] == "OCCUPIED"
        listed_reservation = next(item for item in (await client.get("/api/v1/tables/reservations", headers=headers)).json() if item["id"] == reservation["id"])
        assert listed_reservation["status"] == "SEATED"

        closed = await client.post(f"/api/v1/tables/sessions/{opened.json()['id']}/close", headers={
            **headers, "Idempotency-Key": f"close-{uuid.uuid4()}",
        }, json={"expected_version": opened.json()["version"], "reason": "Atendimento de teste vazio", "actor_id": actor})
        assert closed.status_code == 200, closed.text
        available = (await client.get("/api/v1/tables", headers=headers)).json()[0]
        reopened = await client.post("/api/v1/tables/sessions", headers={
            **headers, "Idempotency-Key": f"open-again-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "service_table_id": table["id"], "actor_id": actor})
        assert reopened.status_code == 200, reopened.text

        future_start = datetime.utcnow() + timedelta(hours=4)
        future = await client.post(f"/api/v1/tables/{table['id']}/reservations", headers={
            **headers, "Idempotency-Key": f"future-reservation-{uuid.uuid4()}",
        }, json={
            "customer_name": "Reserva futura", "party_size": 2,
            "reserved_for": future_start.isoformat(), "duration_minutes": 120, "actor_id": actor,
        })
        assert future.status_code == 201, future.text
        occupied = (await client.get("/api/v1/tables", headers=headers)).json()[0]
        assert occupied["status"] == "OCCUPIED"
        assert occupied["active_reservation"]["id"] == future.json()["id"]

        overlap = await client.post(f"/api/v1/tables/{table['id']}/reservations", headers={
            **headers, "Idempotency-Key": f"overlap-reservation-{uuid.uuid4()}",
        }, json={
            "customer_name": "Conflito", "party_size": 2,
            "reserved_for": (future_start + timedelta(minutes=30)).isoformat(),
            "duration_minutes": 60, "actor_id": actor,
        })
        assert overlap.status_code == 409

        blocked = await client.post(f"/api/v1/tables/{table['id']}/state", headers=headers, json={
            "expected_version": occupied["version"], "target": "BLOCKED", "reason": "Cadeira danificada", "actor_id": actor,
        })
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["status"] == "OCCUPIED"
        assert blocked.json()["blocking_reason"] == "Cadeira danificada"

        released = await client.post(f"/api/v1/tables/sessions/{reopened.json()['id']}/close", headers={
            **headers, "Idempotency-Key": f"close-pending-block-{uuid.uuid4()}",
        }, json={"expected_version": reopened.json()["version"], "reason": "Encerrar para manutenção", "actor_id": actor})
        assert released.status_code == 200, released.text
        final_table = (await client.get("/api/v1/tables", headers=headers)).json()[0]
        assert final_table["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_s13_1_registers_pos_kds_and_printer_devices_with_lifecycle():
    actor = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        _tenant, store, headers = await _context(client, "Devices")
        pos_response = await client.post("/api/v1/devices", headers=headers, json={
            "store_id": store["id"], "code": "POS-01", "name": "Terminal balcão", "device_type": "POS",
            "actor_id": actor,
        })
        assert pos_response.status_code == 201, pos_response.text
        assert pos_response.json()["register_id"] is not None

        kds_response = await client.post("/api/v1/devices", headers=headers, json={
            "store_id": store["id"], "code": "KDS-01", "name": "Tela cozinha", "device_type": "KDS",
            "point_type": "KITCHEN", "actor_id": actor,
        })
        assert kds_response.status_code == 201, kds_response.text
        kds = kds_response.json()
        assert kds["production_point_id"] is not None
        printer_response = await client.post("/api/v1/devices", headers=headers, json={
            "store_id": store["id"], "code": "IMP-01", "name": "Impressora cozinha", "device_type": "PRINTER",
            "configuration_ref": "bridge://cozinha/impressora-01", "actor_id": actor,
        })
        assert printer_response.status_code == 201, printer_response.text
        assert printer_response.json()["production_point_id"] is not None
        paused = await client.patch(f"/api/v1/devices/{kds['id']}", headers=headers, json={
            "status": "PAUSED", "reason": "Manutenção preventiva", "actor_id": actor,
        })
        assert paused.status_code == 200
        assert (await client.post(f"/api/v1/devices/{kds['id']}/heartbeat", headers=headers)).status_code == 403
        active = await client.patch(f"/api/v1/devices/{kds['id']}", headers=headers, json={
            "status": "ACTIVE", "reason": "Manutenção concluída", "actor_id": actor,
        })
        assert active.status_code == 200
        heartbeat = await client.post(f"/api/v1/devices/{kds['id']}/heartbeat", headers=headers)
        assert heartbeat.status_code == 200
        assert heartbeat.json()["last_seen_at"] is not None
        assert len((await client.get("/api/v1/devices", headers=headers)).json()) == 3
