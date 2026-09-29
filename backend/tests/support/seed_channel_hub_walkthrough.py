"""Um food service com um canal conectado, para a travessia autenticada do S10.1.

Parte da semeadura de food service (`seed_food_service_walkthrough.py`), que já
entrega gestora com e-mail, perfil de atividade e `delivery_orders`, e
acrescenta só o que o canal precisa:

* o cardápio passa a alcançar **delivery**, e os dois itens vão para a cozinha;
* a segunda pessoa, a gerente limitada, tem `channel.manage`, `channel.configure`
  e `channel.catalog.manage` **negados** na concessão do vínculo: ela vê a tela e
  não mexe. É o mesmo mecanismo com que um lojista tira uma permissão de alguém;
* pelas rotas do produto, com o token da gestora: a conexão do conector de
  referência, validada; o código do canal do chope vinculado ao produto; e a
  cozinha como ponto de produção.

O código do bolinho **não** é vinculado aqui: vinculá-lo é jornada, e jornada se
percorre na tela.

O conector de referência só existe em teste e desenvolvimento. A chave com que
ele assina o ingresso é derivada de `SECRET_KEY`, e vai para a fixture porque o
roteiro faz o papel do canal. Ela vale só para este ambiente local.

Uso, da pasta `backend/`, com o ambiente da API de `AUTH_MODE=test`:
    python tests/support/seed_channel_hub_walkthrough.py --api http://127.0.0.1:8004 --output <fixture.json>
"""

import argparse
import hashlib
import hmac
import json
import sys
import uuid
from pathlib import Path

import httpx
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.core.tenancy import set_platform_db_context  # noqa: E402
from app.models.assortment import Assortment, AssortmentScope, SalesContextEnum  # noqa: E402
from app.models.catalog import Product  # noqa: E402
from app.models.identity import Membership, PermissionGrant, PermissionGrantEffectEnum, User  # noqa: E402
from seed_food_service_walkthrough import semear  # noqa: E402

NEGADAS_A_LEITORA = ("channel.manage", "channel.configure", "channel.catalog.manage")
COZINHA = "COZINHA"


def _chave_do_ingresso() -> str:
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), b"channel-reference-ingress", hashlib.sha256).hexdigest()


def semear_canal(api: str, saida: Path) -> dict:
    semear(saida)
    fixture = json.loads(saida.read_text(encoding="utf-8"))
    tenant_id, store_id = uuid.UUID(fixture["tenant_id"]), uuid.UUID(fixture["store_id"])
    skus = list(fixture["produtos"])
    chope_sku, bolinho_sku = skus[0], skus[1]

    with Session(engine) as session:
        set_platform_db_context(session)
        cardapio = session.exec(select(Assortment).where(Assortment.tenant_id == tenant_id)).one()
        session.add(AssortmentScope(tenant_id=tenant_id, assortment_id=cardapio.id,
                                    store_id=store_id, sales_context=SalesContextEnum.DELIVERY))
        for sku in skus:
            produto = session.get(Product, uuid.UUID(fixture["produtos"][sku]))
            produto.requires_fulfillment = True
            produto.production_destination = COZINHA
            session.add(produto)
        leitora = session.exec(select(Membership).join(User, User.id == Membership.user_id).where(
            User.email == fixture["limited_email"])).one()
        for chave in NEGADAS_A_LEITORA:
            session.add(PermissionGrant(
                tenant_id=tenant_id, membership_id=leitora.id, permission_key=chave,
                effect=PermissionGrantEffectEnum.DENY,
                reason="Homologação S10.1: ver os canais não é poder mexer neles",
                granted_by=uuid.UUID(fixture["gestora_id"]),
            ))
        session.commit()

    cabecalhos = {"Authorization": f"Bearer {fixture['manager_token']}",
                  "X-Tenant-ID": str(tenant_id), "X-Store-ID": str(store_id)}
    merchant = f"loja-canal-{uuid.uuid4().hex[:6]}"
    with httpx.Client(base_url=api, timeout=30, headers=cabecalhos) as api_client:
        def post(caminho, corpo, chave=True):
            extra = {"Idempotency-Key": f"hom-canal-{uuid.uuid4()}"} if chave else {}
            resposta = api_client.post(caminho, json=corpo, headers=extra)
            if resposta.status_code >= 300:
                raise SystemExit(f"{caminho} respondeu {resposta.status_code}: {resposta.text[:300]}")
            return resposta.json()

        conexao = post("/api/v1/channels/connections", {
            "store_id": str(store_id), "provider_code": "CONTRACT_TEST",
            "merchant_external_id": merchant, "channel_name": "Canal de homologação",
        })["connection"]
        validada = post(f"/api/v1/channels/connections/{conexao['id']}/validate", {})
        if validada["status"] != "CONNECTED":
            raise SystemExit(f"a conexão não validou: {validada['status']} {validada.get('last_error_code')}")
        post("/api/v1/channel-catalog/mappings", {
            "connection_id": conexao["id"], "entity_type": "PRODUCT",
            "internal_id": fixture["produtos"][chope_sku], "external_id": "CHOPE-500",
        })
        post("/api/v1/production/points", {
            "store_id": str(store_id), "code": COZINHA, "name": "Cozinha", "point_type": "KITCHEN",
        })

    fixture.update({
        "channel": {
            "connection_id": conexao["id"], "merchant_external_id": merchant,
            "mapped_code": "CHOPE-500", "unmapped_code": "BOLINHO-12",
            "unmapped_product_name": "Porção de Bolinho de Bacalhau",
            "ingress_key_hex": _chave_do_ingresso(),
            "denied_to_limited": list(NEGADAS_A_LEITORA),
        },
    })
    saida.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"canal semeado: {fixture['tenant_name']} · merchant {merchant}")
    return fixture


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8004")
    parser.add_argument("--output", required=True, type=Path)
    argumentos = parser.parse_args()
    semear_canal(argumentos.api, argumentos.output)
