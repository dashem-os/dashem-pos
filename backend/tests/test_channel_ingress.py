"""S10.1, step 2: the channel's door, through the real API.

Proposal `docs/product/proposta-s10-1-channel-hub.md` (revision 3), §3.3 and
§3.7. The channel here is the reference connector, and every answer it gives is
simulated. What is real: HTTP, the signature over the bytes that arrived, the
server-side resolution of whose event it is, the database, RLS and the retention
deadline each event is born with.

Covered: R15, R16, R17, P2, P5, P7, P20 and the duplicate and divergent paths of
R4 and R5. Since step 3 the server processes events right after the response;
these events carry no order, so they end in quarantine — on the reception clock.
"""

import json
import os
import re
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.channel_hub import ChannelInboxEvent, ChannelRetentionBasisEnum
from app.models.reliability import AuditEvent
from app.modules.channels.adapters import reference
from app.modules.channels.contracts import ChannelDataPermission
from test_s10_channel_hub import _base, _settled

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")
INGRESS = "/api/v1/channels/ingress/CONTRACT_TEST"
APP = Path(__file__).resolve().parents[1] / "app"


def _event(merchant: str, **extra) -> dict:
    return {
        "id": f"evt-{uuid.uuid4()}", "merchant_id": merchant, "type": "ORDER_PLACED",
        "order_id": f"pedido-{uuid.uuid4()}",
        "customer": {"name": "Cliente Ingresso", "phone": "11988887777"},
        **extra,
    }


def _signed(*events) -> tuple[bytes, dict]:
    body = json.dumps({"events": list(events)}).encode("utf-8")
    return body, {"Content-Type": "application/json", reference.SIGNATURE_HEADER: reference.sign(body)}


def _rows(provider_event_id: str) -> list[ChannelInboxEvent]:
    with Session(engine) as db:
        set_platform_db_context(db)
        return list(db.exec(select(ChannelInboxEvent).where(
            ChannelInboxEvent.provider_event_id == provider_event_id,
        )).all())


@pytest.mark.asyncio
async def test_evento_assinado_entra_na_conexao_do_merchant_ja_com_prazo():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, store, _headers, _actor, _product, connection = await _base(client, "Ingresso")
        event = _event(
            connection["merchant_external_id"],
            # Nada disto escolhe tenant ou prazo: é conteúdo do canal, e só.
            tenant_id=str(uuid.uuid4()), retention_until="2099-01-01T00:00:00",
            retention_basis="ESTADO_TERMINAL",
        )
        body, headers = _signed(event)
        response = await client.post(INGRESS, content=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"events": [{"provider_event_id": event["id"], "outcome": "RECEIVED"}]}

    row = _settled(event["id"])
    assert (str(row.tenant_id), str(row.store_id), str(row.merchant_connection_id)) == (
        tenant["id"], store["id"], connection["id"],
    )
    # Sem seção de pedido, o evento não vira pedido: quarentena com código, e o
    # prazo contado da recepção não se mexe (D6).
    assert row.status.value == "QUARANTINED" and row.quarantine_code == "PAYLOAD_ORDER_MISSING"
    assert row.raw_payload == event
    assert row.external_order_id == event["order_id"]
    assert row.acknowledged_at == row.received_at
    assert row.retention_basis == ChannelRetentionBasisEnum.RECEPCAO
    assert row.retention_until == row.received_at + timedelta(days=30)
    assert row.legal_hold_until is None and row.legal_hold_reason is None


@pytest.mark.asyncio
async def test_o_mesmo_evento_repetido_nao_cria_nada_e_o_divergente_fica_so_registrado():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        *_, connection = await _base(client, "Repeticao")
        event = _event(connection["merchant_external_id"])
        body, headers = _signed(event)
        assert (await client.post(INGRESS, content=body, headers=headers)).json()["events"][0]["outcome"] == "RECEIVED"
        again = await client.post(INGRESS, content=body, headers=headers)
        assert again.json()["events"][0]["outcome"] == "DUPLICATE"

        altered = {**event, "customer": {"name": "Outro Nome", "phone": "11911112222"}}
        body, headers = _signed(altered)
        divergent = await client.post(INGRESS, content=body, headers=headers)
        assert divergent.status_code == 200
        assert divergent.json()["events"][0]["outcome"] == "DIVERGENT"

    row = _settled(event["id"])
    assert row.raw_payload == event, "o conteúdo guardado não é trocado pelo divergente"
    with Session(engine) as db:
        set_platform_db_context(db)
        audit = db.exec(select(AuditEvent).where(
            AuditEvent.action == "channel.ingress.divergent_event",
            AuditEvent.target == f"CHANNEL-INBOX-{row.id}",
        )).all()
    assert len(audit) == 1
    # Trilha imutável: identificadores e hashes, nunca o conteúdo (H17).
    for personal in ("Cliente Ingresso", "Outro Nome", "11988887777", "11911112222"):
        assert personal not in audit[0].payload


@pytest.mark.asyncio
async def test_a_assinatura_vale_sobre_os_bytes_que_chegaram():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        *_, connection = await _base(client, "Bytes")
        event = _event(connection["merchant_external_id"])
        body, headers = _signed(event)
        same_json = json.dumps(json.loads(body), indent=2, sort_keys=True).encode("utf-8")
        reserialized = await client.post(INGRESS, content=same_json, headers=headers)
        assert reserialized.status_code == 401
        assert reserialized.json()["detail"] == {"code": "SIGNATURE_INVALID"}
        unsigned = await client.post(INGRESS, content=body, headers={"Content-Type": "application/json"})
        assert unsigned.status_code == 401
        assert unsigned.json()["detail"] == {"code": "SIGNATURE_MISSING"}
    assert _rows(event["id"]) == []


@pytest.mark.asyncio
async def test_merchant_sem_conexao_conectada_e_recusado_sem_gravar_nada():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, store, headers, actor, *_ = await _base(client, "SemConexao")
        pending = await client.post("/api/v1/channels/connections", headers={
            **headers, "Idempotency-Key": f"conn-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "provider_code": "CONTRACT_TEST",
                 "merchant_external_id": f"pendente-{uuid.uuid4().hex[:8]}", "channel_name": "Não validado",
                 "actor_id": actor})
        assert pending.status_code == 200 and pending.json()["connection"]["status"] == "NOT_CONNECTED"
        unknown = _event(f"desconhecido-{uuid.uuid4().hex[:8]}")
        not_validated = _event(pending.json()["connection"]["merchant_external_id"])
        body, signed_headers = _signed(unknown, not_validated)
        response = await client.post(INGRESS, content=body, headers=signed_headers)
        assert response.status_code == 200
        assert [item["outcome"] for item in response.json()["events"]] == [
            "MERCHANT_NOT_CONNECTED", "MERCHANT_NOT_CONNECTED",
        ]
    assert _rows(unknown["id"]) == [] and _rows(not_validated["id"]) == []


@pytest.mark.asyncio
async def test_cada_evento_vai_para_o_tenant_do_seu_merchant_e_ninguem_ve_o_do_outro():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant_a, _store_a, headers_a, _actor_a, _p, connection_a = await _base(client, "TenantA")
        tenant_b, store_b, headers_b, actor_b, _p, connection_b = await _base(client, "TenantB")
        event_a = _event(connection_a["merchant_external_id"])
        event_b = _event(connection_b["merchant_external_id"])
        body, headers = _signed(event_a, event_b)
        response = await client.post(INGRESS, content=body, headers=headers)
        assert [item["outcome"] for item in response.json()["events"]] == ["RECEIVED", "RECEIVED"]

        inbox_b = {item["provider_event_id"] for item in (await client.get("/api/v1/channels/inbox", headers=headers_b)).json()}
        assert event_b["id"] in inbox_b and event_a["id"] not in inbox_b

        # O merchant de A não se conecta no tenant B: a entrega ficaria ambígua.
        taken = await client.post("/api/v1/channels/connections", headers={
            **headers_b, "Idempotency-Key": f"conn-{uuid.uuid4()}",
        }, json={"store_id": store_b["id"], "provider_code": "CONTRACT_TEST",
                 "merchant_external_id": connection_a["merchant_external_id"], "channel_name": "Tomado",
                 "actor_id": actor_b})
        assert taken.status_code == 200, taken.text
        refused = await client.post(f"/api/v1/channels/connections/{taken.json()['connection']['id']}/validate", headers={
            **headers_b, "Idempotency-Key": f"validate-{uuid.uuid4()}",
        }, json={"actor_id": actor_b})
        assert refused.status_code == 200, refused.text
        assert refused.json()["status"] == "NOT_CONNECTED"
        assert refused.json()["last_error_code"] == "MERCHANT_CONNECTED_ELSEWHERE"

        later = _event(connection_a["merchant_external_id"])
        body, headers = _signed(later)
        assert (await client.post(INGRESS, content=body, headers=headers)).json()["events"][0]["outcome"] == "RECEIVED"

    assert str(_rows(event_a["id"])[0].tenant_id) == tenant_a["id"]
    assert str(_rows(event_b["id"])[0].tenant_id) == tenant_b["id"]
    assert str(_rows(later["id"])[0].tenant_id) == tenant_a["id"]


@pytest.mark.asyncio
async def test_provedor_que_a_plataforma_nao_fala_nao_tem_porta_e_corpo_invalido_e_codigo():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        body, headers = _signed(_event("qualquer"))
        missing = await client.post("/api/v1/channels/ingress/IFOOD", content=body, headers=headers)
        assert missing.status_code == 404
        assert missing.json()["detail"] == {"code": "PROVIDER_NOT_AVAILABLE"}
        broken = b'{"eventos": ["Cliente Ingresso 11988887777"]}'
        rejected = await client.post(INGRESS, content=broken, headers={
            "Content-Type": "application/json", reference.SIGNATURE_HEADER: reference.sign(broken),
        })
        assert rejected.status_code == 400
        assert rejected.json()["detail"] == {"code": "EVENTS_MISSING"}
        assert "11988887777" not in rejected.text


@pytest.mark.asyncio
async def test_legal_hold_so_existe_completo():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        *_, connection = await _base(client, "Hold")
        event = _event(connection["merchant_external_id"])
        body, headers = _signed(event)
        assert (await client.post(INGRESS, content=body, headers=headers)).status_code == 200
    row = _settled(event["id"])

    with Session(engine) as db:
        set_platform_db_context(db)
        stored = db.get(ChannelInboxEvent, row.id)
        stored.legal_hold_until = stored.received_at + timedelta(days=365)
        db.add(stored)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    with Session(engine) as db:
        set_platform_db_context(db)
        stored = db.get(ChannelInboxEvent, row.id)
        stored.legal_hold_until = stored.received_at + timedelta(days=365)
        stored.legal_hold_reason = "Disputa de cobrança do pedido"
        stored.legal_hold_reference = "INCIDENTE-TESTE-1"
        stored.legal_hold_by = uuid.uuid4()
        stored.legal_hold_review_at = stored.received_at + timedelta(days=30)
        db.add(stored)
        db.flush()
        db.rollback()


def _granted_d7(session: Session) -> set[str]:
    keys = tuple(permission.value for permission in ChannelDataPermission)
    rows = session.exec(text(
        "SELECT 'perfil:' || permission_key FROM role_profile_permissions WHERE permission_key = ANY(:keys) "
        "UNION ALL SELECT 'pessoa:' || permission_key FROM permission_grants WHERE permission_key = ANY(:keys)"
    ).bindparams(keys=list(keys))).all()
    return {row[0] for row in rows}


def test_as_permissoes_da_d7_existem_e_ninguem_as_recebe_antes_de_definidas_e_testadas():
    keys = {permission.value for permission in ChannelDataPermission}
    with Session(engine) as db:
        set_platform_db_context(db)
        catalog = {row[0] for row in db.exec(text(
            "SELECT key FROM permissions WHERE key = ANY(:keys)"
        ).bindparams(keys=list(keys))).all()}
        assert catalog == keys
        assert _granted_d7(db) == set(), "permissão da D7 concedida antes de a concessão ser definida e testada"

        # Controle: a medida tem de enxergar uma concessão plantada.
        profile_id = db.exec(text("SELECT id FROM role_profiles WHERE is_system LIMIT 1")).first()[0]
        db.exec(text(
            "INSERT INTO role_profile_permissions (id, role_profile_id, permission_key) "
            "VALUES (gen_random_uuid(), :profile, 'channel.retention.purge')"
        ).bindparams(profile=profile_id))
        assert _granted_d7(db) == {"perfil:channel.retention.purge"}
        db.rollback()

    # E nenhuma rota as exige ou as oferece: fora do contrato, o código não as nomeia.
    naming = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "contracts.py" and path.parent.name == "channels":
            continue
        source = path.read_text(encoding="utf-8-sig")
        if re.search(r"ChannelDataPermission|channel\.(order_contact|legal_hold|retention)\.", source):
            naming.append(path.relative_to(APP).as_posix())
    assert naming == []
