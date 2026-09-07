#!/usr/bin/env python
"""Quem perde a jornada de mesa **por causa desta mudança**.

Até agora, um tenant sem contrato versionado atravessava a regra: a jornada de
mesa passava mesmo sem FOOD_SERVICE declarado. Isso deixou de valer, e a mudança
é correta — mas ela não pode chegar ao ambiente publicado sem alguém olhar quem
está do outro lado.

**A pergunta certa é comparativa.** A versão anterior deste roteiro contava como
impacto todo tenant que hoje não tem a jornada, e isso mistura duas coisas
diferentes: quem perdeu agora, e quem já estava bloqueado antes. Um tenant com
contrato sem FOOD_SERVICE, por exemplo, já era recusado pela regra antiga —
listá-lo como perda atribuiria a esta mudança um bloqueio que ela não causou, e
inflaria o número que sustenta a decisão de liberar.

Então a elegibilidade é calculada **duas vezes sobre os mesmos dados**, pelo mesmo
caminho de runtime, trocando exclusivamente a função da regra:

* `elegivel_antes` — a regra anterior, em que ausência de contrato liberava;
* `elegivel_depois` — a regra atual, em que o legado responde pelo perfil.

Impacto é `antes=True e depois=False`, e nada mais.

**O escopo é o tenant, não a unidade.** A elegibilidade é resolvida sem
`store_id`, então override de capability por loja não entra na conta. Um tenant
que mantém a jornada aqui pode tê-la desligada em alguma unidade por override, e
este levantamento não veria — para decidir por unidade seria preciso repetir a
avaliação loja a loja.

**E ele mede acesso, não publicação.** A mudança também passou a recusar publicar
e reativar sortimento TABLE em tenant sem FOOD_SERVICE, inclusive contratado.
Esse comportamento mudou e não aparece em nenhuma linha deste relatório: um
tenant contratado sem FOOD nunca teve a jornada — logo não é impacto de acesso —
mas passou a ser recusado ao publicar.

**Este roteiro só lê.** Ele não declara atividade, não altera perfil e não toca em
capability. A regularização acontece pelos fluxos que já existem, cada um com o
seu ator autenticado e a sua trilha:

* **tenant com contrato** — editor de contrato do Owner console, incluindo
  FOOD_SERVICE em `activity_keys`. É o único caminho que muda o que vale, porque
  o contrato vence a atribuição de perfil;
* **tenant legado** — aplicação de profile de capability no Control
  (`POST /control/tenants/{id}/capability-profiles/{revision_id}`), que valida a
  revisão, encerra a atribuição anterior e responde por um ator autenticado.

Uso:

    python scripts/food_rule_impact.py                    # relatório
    python scripts/food_rule_impact.py --csv impacto.csv  # exportação completa
"""

import argparse
import csv
from contextlib import contextmanager

from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import Tenant
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.modules.capabilities import service as capability_service
from app.services.contract_entitlement_service import resolve_contract_entitlements


TABLE = "table_service"
FOOD = "FOOD_SERVICE"

IMPACTO = "impacto"
BLOQUEIO_PREEXISTENTE = "bloqueio_preexistente"
MANTEM = "mantem"


def previous_rule(session, tenant_id, capability_key: str) -> bool:
    """A regra como era antes: sem contrato, a jornada passava.

    Reproduzida aqui em vez de mantida na aplicação — o produto não deve carregar
    a semântica antiga só para o relatório conseguir comparar.
    """
    if capability_key != TABLE:
        return True
    snapshot = resolve_contract_entitlements(session, tenant_id)
    return snapshot is None or FOOD in snapshot.activity_keys


@contextmanager
def _rule(function):
    """Trocar exclusivamente a função da regra, mantendo o resto do caminho.

    A comparação precisa diferir em uma coisa só. Reescrever a elegibilidade em
    SQL daria uma segunda verdade; substituir a função e reusar
    `effective_capabilities` mantém overrides de loja, snapshot de contrato e
    dependências exatamente como o runtime os aplica.
    """
    original = capability_service.capability_allowed_by_activity
    capability_service.capability_allowed_by_activity = function
    try:
        yield
    finally:
        capability_service.capability_allowed_by_activity = original


def classify(elegivel_antes: bool, elegivel_depois: bool) -> str:
    """Impacto é só o que esta mudança tirou.

    `antes=False` significa que o tenant já era recusado — por contrato sem
    FOOD_SERVICE, por capability ausente, por override de loja. A mudança não
    causou aquilo, e contá-la ali seria atribuir a ela um bloqueio alheio.
    """
    if elegivel_depois:
        return MANTEM
    return IMPACTO if elegivel_antes else BLOQUEIO_PREEXISTENTE


def _candidates(session: Session) -> list[Tenant]:
    """Tenants que tinham a capability de mesa, por linha ou por contrato."""
    with_row = set(session.exec(
        select(TenantCapability.tenant_id).where(
            TenantCapability.key == TABLE,
            TenantCapability.enabled.is_(True),
            TenantCapability.status.in_({
                EntitlementStatusEnum.CONFIGURED, EntitlementStatusEnum.ACTIVE,
            }),
        )
    ).all())
    result = []
    for tenant in session.exec(select(Tenant).order_by(Tenant.name)).all():
        snapshot = resolve_contract_entitlements(session, tenant.id)
        if (snapshot is not None and TABLE in snapshot.capability_keys) or tenant.id in with_row:
            result.append(tenant)
    return result


def evaluate(session: Session, tenant: Tenant) -> dict:
    """A elegibilidade nas duas regras, pelo mesmo caminho da aplicação."""
    set_tenant_db_context(session, tenant.id, None, None)
    with _rule(previous_rule):
        antes = TABLE in capability_service.effective_capabilities(session, tenant.id)
    set_tenant_db_context(session, tenant.id, None, None)
    depois = TABLE in capability_service.effective_capabilities(session, tenant.id)
    snapshot = resolve_contract_entitlements(session, tenant.id)
    return {
        "tenant_id": str(tenant.id),
        "slug": tenant.slug,
        "nome": tenant.name,
        "origem": "contrato" if snapshot is not None else "legado",
        "atividades_declaradas": "|".join(
            capability_service.tenant_activity_keys(session, tenant.id)
        ),
        "elegivel_antes": antes,
        "elegivel_depois": depois,
        "classificacao": classify(antes, depois),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", metavar="ARQUIVO",
                        help="exportar o levantamento completo, sem corte")
    args = parser.parse_args()

    with Session(engine) as session:
        set_platform_db_context(session)
        candidatos = _candidates(session)
        linhas = []
        for tenant in candidatos:
            linhas.append(evaluate(session, tenant))
            set_platform_db_context(session)

    impacto = [linha for linha in linhas if linha["classificacao"] == IMPACTO]
    preexistente = [linha for linha in linhas if linha["classificacao"] == BLOQUEIO_PREEXISTENTE]
    por_contrato = [linha for linha in impacto if linha["origem"] == "contrato"]
    legados = [linha for linha in impacto if linha["origem"] == "legado"]

    print(f"Tenants com a capability de mesa: {len(linhas)}")
    print(f"IMPACTO desta mudança (antes=True, depois=False): {len(impacto)}")
    print(f"  legados (sem contrato) ........ {len(legados)}  → aplicação de profile no Control")
    print(f"  com contrato versionado ....... {len(por_contrato)}  → editor de contrato do Owner")
    print()
    print(f"Bloqueio preexistente, não causado por esta mudança: {len(preexistente)}")
    print("  já eram recusados pela regra anterior — contrato sem FOOD_SERVICE, ou")
    print("  capability ausente no snapshot. Continuam como estavam.")
    print()

    if args.csv:
        campos = ["tenant_id", "slug", "nome", "origem", "atividades_declaradas",
                  "elegivel_antes", "elegivel_depois", "classificacao"]
        with open(args.csv, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=campos)
            writer.writeheader()
            writer.writerows(linhas)
        print(f"Levantamento completo exportado em {args.csv} ({len(linhas)} linhas).")
    elif impacto:
        print("Use --csv para o levantamento completo. Amostra do impacto:")
        for linha in impacto[:20]:
            print(f"  {linha['tenant_id']}  {linha['origem']:8}  "
                  f"{linha['atividades_declaradas'] or '(nenhuma)':28}  {linha['nome']}")
        if len(impacto) > 20:
            print(f"  ... e mais {len(impacto) - 20}; a tela é amostra, o CSV é o dado.")

    print()
    print("Escopo e limites deste levantamento:")
    print("  · é por TENANT, não por unidade. A elegibilidade é resolvida sem")
    print("    store_id, então override de capability por loja não entra na conta;")
    print("  · mede ACESSO à jornada. A mesma mudança também recusa publicar e")
    print("    reativar sortimento TABLE sem FOOD_SERVICE, inclusive em tenant")
    print("    contratado — comportamento que mudou e que nenhuma linha aqui mede;")
    print("  · diz quem perde acesso, não quem *deveria* perder. Um tenant sem")
    print("    atendimento registrado pode ser implantação recente, e não capability")
    print("    indevida — a ausência de uso não prova nada sobre a intenção;")
    print("  · regularizar ou remover acesso é decisão comercial, tomada tenant a")
    print("    tenant, pelos fluxos autenticados, e não por este roteiro;")
    print("  · para tenant com contrato, mexer no perfil legado não muda nada: o")
    print("    contrato tem precedência, e a correção é no contrato.")
    return 0 if not impacto else 2


if __name__ == "__main__":
    raise SystemExit(main())
