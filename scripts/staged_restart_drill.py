#!/usr/bin/env python
"""S25.1 - reinicio encenado: o dinheiro atravessa a queda do processo.

A matriz de aceite do S25.1 registra que o estado sobrevive a outra sessao e a
outro processo, provado em teste, e que um `docker restart` no meio de uma
cobranca **nao** havia sido encenado. Aqui ele e encenado, contra a pilha real:
API, worker e Postgres em conteineres separados, derrubados de verdade.

  A. Cobranca em voo, sem resposta. Reinicia API e worker com a cobranca
     registrada e ainda sem desfecho. Na volta a reserva continua de pe, o
     cancelamento e recusado com EXTERNAL_CHARGE_IN_FLIGHT, e so a resposta
     encerra a parcela.

     Nenhum dinheiro real se move e nenhum pinpad e acionado: o roteiro posta
     ele mesmo, com o segredo de pareamento, a resposta que um bridge daria.
     O que fica provado e o ciclo do servidor, nao uma cobranca de verdade.

  B. Resposta gravada e nao aplicada. O resultado terminal e persistido e o
     processo morre entre os dois commits. Depois do reinicio ninguem abre a
     conta: a varredura do worker reaplica a resposta sozinha.

Uso: python scripts/staged_restart_drill.py
"""

import os
import subprocess
import time
import uuid

import httpx

BASE_URL = os.getenv("DRILL_BASE_URL", "http://localhost:8002")
API_CONTAINER = os.getenv("DRILL_API_CONTAINER", "dashem-pos-backend")
WORKER_CONTAINER = os.getenv("DRILL_WORKER_CONTAINER", "dashem-pos-worker")
DB_CONTAINER = os.getenv("DRILL_DB_CONTAINER", "dashem-pos-db")
MENU = (("Hamburguer", 35), ("Coca-Cola", 10), ("Whisky", 40), ("Pizza", 60))

log = []


def say(line=""):
    print(line, flush=True)
    log.append(line)


def sql(query):
    """psql com acesso de plataforma. RLS e forcado, entao o drill se declara."""
    statement = "SET app.platform_access = 'true'; " + query
    done = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "dashem_pos", "-d", "dashem_pos",
         "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", statement],
        capture_output=True, text=True,
    )
    if done.returncode != 0:
        raise SystemExit("psql falhou: " + done.stderr.strip())
    # psql ecoa o "SET" da declaracao de acesso; o valor pedido e a ultima linha.
    lines = [line for line in done.stdout.strip().splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def restart(*containers):
    started = time.monotonic()
    done = subprocess.run(["docker", "restart", *containers], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit("docker restart falhou: " + done.stderr.strip())
    for _ in range(90):
        try:
            if httpx.get(BASE_URL + "/health", timeout=2).status_code == 200:
                return round(time.monotonic() - started, 1)
        except Exception:
            pass
        time.sleep(1)
    raise SystemExit("API nao voltou depois do reinicio")


def uptime(container):
    return subprocess.run(
        ["docker", "inspect", container, "--format", "{{.State.StartedAt}}"],
        capture_output=True, text=True,
    ).stdout.strip()


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FALHOU"
    say("  [" + mark + "] " + label + ((" - " + detail) if detail else ""))
    if not condition:
        raise SystemExit("Drill interrompido em: " + label)


def by_name(projection):
    return {row["product_name"]: row for row in projection["item_settlements"]}


OPEN = ("PENDING", "PROCESSING")


def pending(projection):
    return [row for row in projection["intents"] if row["status"] == "PENDING"][-1]


def bootstrap(client, prefix):
    """Um tenant, uma mesa servida e um cardapio publicado - o caminho real."""
    suffix = uuid.uuid4().hex[:8]
    actor = str(uuid.uuid4())
    tenant = client.post("/api/v1/identity/tenants", json={
        "name": prefix + " " + suffix, "slug": prefix.lower() + "-" + suffix,
    }).json()
    store = client.post("/api/v1/identity/stores", json={
        "tenant_id": tenant["id"], "name": "Matriz", "code": prefix[:3].upper() + "-" + suffix,
    }).json()
    for key in ("counter_order", "table_service"):
        sql(
            "INSERT INTO tenant_capabilities (id, tenant_id, key, enabled, configuration, "
            "created_at, updated_at, status, contract_limits) VALUES (gen_random_uuid(), '"
            + tenant["id"] + "', '" + key + "', true, '{}', now(), now(), 'ACTIVE', '{}')"
        )
    headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
    table = client.post("/api/v1/tables", headers={**headers, "Idempotency-Key": "table-" + suffix}, json={
        "store_id": store["id"], "code": "M-01", "name": "Mesa 01", "capacity": 6, "actor_id": actor,
    }).json()
    table_session = client.post("/api/v1/tables/sessions", headers={
        **headers, "Idempotency-Key": "session-" + suffix,
    }, json={"store_id": store["id"], "service_table_id": table["id"], "actor_id": actor}).json()
    order_id = table_session["orders"][0]["id"]
    assortment = client.post("/api/v1/catalog/assortments", headers=headers, json={
        "code": "ASSORT-DRILL-" + suffix, "name": "Cardapio",
        "scopes": [{"store_id": store["id"], "sales_context": "TABLE"}], "product_ids": [],
    }).json()
    for index, (name, price) in enumerate(MENU, start=1):
        product = client.post("/api/v1/catalog/products", headers=headers, json={
            "name": name, "sku": "DRILL-" + suffix + "-" + str(index), "unit": "UN",
            "tracks_inventory": False,
        }).json()
        client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": product["id"], "store_id": store["id"], "cost_price": 1, "sale_price": price,
        })
        client.post("/api/v1/catalog/assortments/" + assortment["id"] + "/products", headers=headers, json={
            "expected_version": index, "product_ids": [product["id"]],
        })
        launched = client.post("/api/v1/orders/" + order_id + "/items", headers={
            **headers, "Idempotency-Key": "item-" + suffix + "-" + str(index),
        }, json={"product_id": product["id"], "quantity": 1, "actor_id": actor})
        assert launched.status_code == 200, launched.text
    return tenant, store, headers, actor, table_session, suffix


def tef_chain(client, headers, tenant, store, actor, suffix):
    """Provider, bridge pareado e vinculo de POS - a cadeia de producao."""
    register = client.post("/api/v1/cash/registers", headers=headers, json={
        "store_id": store["id"], "name": "Caixa Drill", "code": "CX-" + suffix[:6],
    }).json()
    configuration = client.post("/api/v1/providers/configurations", headers={
        **headers, "Idempotency-Key": "config-" + str(uuid.uuid4()),
    }, json={"store_id": store["id"], "provider_code": "SITEF",
             "credentials_ref": "secret://tenant/sitef", "actor_id": actor}).json()
    paired = client.post("/api/v1/providers/bridge/terminals", headers={
        **headers, "Idempotency-Key": "pair-" + str(uuid.uuid4()),
    }, json={"store_id": store["id"], "register_id": register["id"],
             "provider_configuration_id": configuration["id"],
             "terminal_code": "PINPAD-" + suffix[:6], "actor_id": actor}).json()
    terminal, pairing_code = paired["terminal"], paired["pairing_code"]
    beat = client.post("/api/v1/providers/bridge/terminals/" + terminal["id"] + "/heartbeat", json={
        "tenant_id": tenant["id"], "store_id": store["id"], "pairing_code": pairing_code,
        "bridge_version": "1.0.0", "protocol_version": "1.0",
    })
    assert beat.status_code == 200 and beat.json()["status"] == "ONLINE", beat.text
    device = client.post("/api/v1/devices", headers=headers, json={
        "store_id": store["id"], "code": "POS-" + suffix[:6], "name": "POS de pagamento",
        "device_type": "POS", "register_id": register["id"], "actor_id": actor,
    }).json()
    binding = client.post("/api/v1/providers/device-bindings", headers={
        **headers, "Idempotency-Key": "binding-" + str(uuid.uuid4()),
    }, json={"store_id": store["id"], "register_id": register["id"],
             "operational_device_id": device["id"],
             "provider_configuration_id": configuration["id"],
             "execution_mode": "TEF_BRIDGE", "tef_bridge_terminal_id": terminal["id"],
             "actor_id": actor}).json()
    return terminal, pairing_code, binding


def charge(client, headers, negotiation_id, actor, binding_id, amount, item_id):
    """Uma parcela declarando a rota, e a cobranca registrada como em voo.

    Nada e entregue a pinpad nenhum: o transporte de comandos ao bridge nao
    existe (frente A). `BridgeQueuedAdapter.start` devolve PROCESSING, que e o
    contrato de producao, e o servidor passa a ter uma cobranca cujo desfecho
    so pode vir de fora.
    """
    created = client.post("/api/v1/negotiations/" + negotiation_id + "/intents", headers={
        **headers, "Idempotency-Key": "intent-" + str(uuid.uuid4()),
    }, json={"method": "CREDIT_CARD", "amount": amount, "actor_id": actor,
             "payer_label": "Astra", "payment_device_binding_id": binding_id,
             "allocations": [{"amount": amount, "order_item_id": item_id}]})
    assert created.status_code == 200, created.text
    intent = pending(created.json())
    executed = client.post("/api/v1/providers/transactions", headers={
        **headers, "Idempotency-Key": "exec-" + str(uuid.uuid4()),
        "X-Correlation-ID": "drill-" + uuid.uuid4().hex[:12],
    }, json={"payment_intent_id": intent["id"], "payment_device_binding_id": binding_id,
             "actor_id": actor})
    assert executed.status_code == 200, executed.text
    return intent, executed.json()


def scenario_a(client):
    say("## Cenario A - reinicio com a cobranca em voo")
    tenant, store, headers, actor, table_session, suffix = bootstrap(client, "DrillA")
    negotiation = client.post("/api/v1/negotiations", headers={
        **headers, "Idempotency-Key": "neg-" + str(uuid.uuid4()),
    }, json={"store_id": store["id"], "table_session_id": table_session["id"],
             "actor_id": actor}).json()
    terminal, pairing_code, binding = tef_chain(client, headers, tenant, store, actor, suffix)
    whisky = by_name(negotiation)["Whisky"]["order_item_id"]

    intent, execution = charge(client, headers, negotiation["id"], actor, binding["id"], 40, whisky)
    transaction_id = execution["transaction"]["id"]
    check("cobranca registrada em voo, sem presumir aprovacao",
          execution["transaction"]["status"] == "PROCESSING",
          "transacao " + transaction_id[:8] + " em PROCESSING")

    before = client.get("/api/v1/negotiations/" + negotiation["id"], headers=headers).json()
    held = by_name(before)["Whisky"]
    check("linha reservada antes da queda",
          float(held["reserved_amount"]) == 40 and float(held["available_amount"]) == 0)

    api_before, worker_before = uptime(API_CONTAINER), uptime(WORKER_CONTAINER)
    say("  ... docker restart com a cobranca em voo, sem resposta")
    elapsed = restart(API_CONTAINER, WORKER_CONTAINER)
    check("conteineres realmente reiniciaram",
          uptime(API_CONTAINER) != api_before and uptime(WORKER_CONTAINER) != worker_before,
          "API de volta em " + str(elapsed) + "s")

    after = client.get("/api/v1/negotiations/" + negotiation["id"], headers=headers).json()
    survivor = next(row for row in after["intents"] if row["id"] == intent["id"])
    still = by_name(after)["Whisky"]
    check("a parcela atravessou a queda ainda aberta",
          survivor["status"] in OPEN and survivor["awaiting_provider"] is True,
          "parcela em " + survivor["status"])
    check("a reserva atravessou a queda intacta",
          float(still["reserved_amount"]) == 40 and float(still["available_amount"]) == 0)
    check("cobranca enviada nao carrega prazo de expiracao",
          survivor["reserve_expires_at"] is None)

    refused = client.post("/api/v1/negotiations/intents/" + intent["id"] + "/cancel", headers={
        **headers, "Idempotency-Key": "cancel-" + str(uuid.uuid4()),
    }, json={"reason": "Operador achou que o reinicio tinha perdido a cobranca",
             "actor_id": actor})
    detail = refused.json().get("detail", {})
    code = detail.get("code") if isinstance(detail, dict) else str(detail)
    check("depois do reinicio, ninguem libera cartao em voo pela mao",
          refused.status_code == 409 and code == "EXTERNAL_CHARGE_IN_FLIGHT",
          "HTTP " + str(refused.status_code) + " " + str(code))

    # A resposta que um bridge daria, postada pelo proprio roteiro com o segredo
    # de pareamento. E o caminho de producao do callback, e nao uma cobranca.
    answered = client.post(
        "/api/v1/providers/bridge/terminals/" + terminal["id"]
        + "/transactions/" + transaction_id + "/result",
        json={"tenant_id": tenant["id"], "store_id": store["id"], "pairing_code": pairing_code,
              "status": "CONFIRMED", "nsu": "NSU77341", "authorization_code": "A1B2C3",
              "acquirer": "DRILL", "card_brand": "VISA"})
    check("a transacao continua viva para receber a resposta",
          answered.status_code == 200, "HTTP " + str(answered.status_code))

    settled = client.get("/api/v1/negotiations/" + negotiation["id"], headers=headers).json()
    closed = next(row for row in settled["intents"] if row["id"] == intent["id"])
    paid = by_name(settled)["Whisky"]
    check("a resposta fecha a parcela que sobreviveu", closed["status"] == "CONFIRMED")
    check("o item fica quitado, e so ele",
          float(paid["settled_amount"]) == 40 and paid["is_paid"] is True
          and float(by_name(settled)["Pizza"]["available_amount"]) == 60)
    say()


def scenario_b(client):
    say("## Cenario B - queda entre os dois commits, sem ninguem para consultar")
    tenant, store, headers, actor, table_session, suffix = bootstrap(client, "DrillB")
    negotiation = client.post("/api/v1/negotiations", headers={
        **headers, "Idempotency-Key": "neg-" + str(uuid.uuid4()),
    }, json={"store_id": store["id"], "table_session_id": table_session["id"],
             "actor_id": actor}).json()
    terminal, pairing_code, binding = tef_chain(client, headers, tenant, store, actor, suffix)
    pizza = by_name(negotiation)["Pizza"]["order_item_id"]
    intent, execution = charge(client, headers, negotiation["id"], actor, binding["id"], 60, pizza)
    transaction_id = execution["transaction"]["id"]

    # A resposta chega e e persistida; o processo morre antes de tocar a
    # parcela. E exatamente a janela que `_apply_result` abre de proposito.
    sql("UPDATE provider_transactions SET status = 'CONFIRMED', nsu = 'NSU90210', "
        "authorization_code = 'D4E5F6', acquirer = 'DRILL', card_brand = 'MASTER', "
        "updated_at = now() WHERE id = '" + transaction_id + "'")
    stranded = sql("SELECT t.status || '|' || i.status FROM provider_transactions t "
                   "JOIN payment_intents i ON i.id = t.payment_intent_id "
                   "WHERE t.id = '" + transaction_id + "'")
    check("cobranca aprovada ao lado de parcela aberta",
          stranded.split("|")[0] == "CONFIRMED" and stranded.split("|")[1] in OPEN,
          "linhas discordando: " + stranded)

    api_before, worker_before = uptime(API_CONTAINER), uptime(WORKER_CONTAINER)
    say("  ... docker restart com as duas linhas discordando")
    elapsed = restart(API_CONTAINER, WORKER_CONTAINER)
    check("conteineres realmente reiniciaram",
          uptime(API_CONTAINER) != api_before and uptime(WORKER_CONTAINER) != worker_before,
          "API de volta em " + str(elapsed) + "s")

    say("  ... ninguem abre a conta; esperando a varredura do worker (ate 180s)")
    recovered, waited = None, time.monotonic()
    while time.monotonic() - waited < 180:
        state = sql("SELECT status FROM payment_intents WHERE id = '" + intent["id"] + "'")
        if state == "CONFIRMED":
            recovered = round(time.monotonic() - waited, 1)
            break
        time.sleep(5)
    check("a varredura reaplica a resposta sem ninguem perguntar",
          recovered is not None,
          "parcela conciliada " + str(recovered) + "s depois do reinicio")

    final = client.get("/api/v1/negotiations/" + negotiation["id"], headers=headers).json()
    row = by_name(final)["Pizza"]
    check("o item aparece quitado para quem abrir a conta depois",
          float(row["settled_amount"]) == 60 and row["is_paid"] is True)
    asked = sql("SELECT count(*) FROM provider_transactions WHERE payment_intent_id = '"
                + intent["id"] + "'")
    check("nada foi perguntado de novo ao provider", asked == "1",
          asked + " transacao para a parcela")
    say()


def main():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    say("# S25.1 - drill de reinicio encenado")
    say("Alvo: " + BASE_URL + " · conteineres " + API_CONTAINER + ", " + WORKER_CONTAINER)
    say("Commit: " + head + " · " + time.strftime("%d/%m/%Y %H:%M:%S"))
    say()
    with httpx.Client(base_url=BASE_URL, timeout=60) as client:
        scenario_a(client)
        scenario_b(client)
    say("## Resultado")
    say("Os dois cenarios passaram contra a pilha real, com reinicio de verdade no meio.")
    out = os.getenv("DRILL_LOG")
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write("\n".join(log) + "\n")


if __name__ == "__main__":
    main()
