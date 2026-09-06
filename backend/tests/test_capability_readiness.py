"""ADR-031 — a declaração de prontidão tem que se sustentar sozinha.

Um campo que diz "pronta" e não aponta para nada é a mesma dívida que o
`frozenset` que ele substituiu. Estes testes são o que impede a declaração de
envelhecer em silêncio: evidência que sumiu do repositório, versão avaliada que
ficou para trás, `PARTIAL` que não diz o que falta.

O caso que motivou tudo isto está afirmado nominalmente: `tef` não é vendável
enquanto o transporte de comandos ao bridge não existir.
"""

from pathlib import Path

import pytest

from app.modules.capabilities.eligibility import EligibilityReason, eligibility
from app.modules.capabilities.readiness import (
    CAPABILITY_READINESS, CapabilityReadiness, HomologationState, ImplementationState,
    sellable_capabilities,
)
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, IMPLEMENTED_CAPABILITIES


REPOSITORY = Path(__file__).resolve().parents[2]


def test_every_registered_capability_declares_its_readiness():
    """Nenhuma capability entra no catálogo sem dizer em que pé está."""
    missing = sorted(set(CAPABILITY_REGISTRY) - set(CAPABILITY_READINESS))
    assert missing == [], f"Capabilities sem prontidão declarada: {missing}"
    extra = sorted(set(CAPABILITY_READINESS) - set(CAPABILITY_REGISTRY))
    assert extra == [], f"Prontidão declarada para capability inexistente: {extra}"


def test_declared_evidence_exists_in_the_repository():
    """`{"passed": true}` não é prova, e caminho quebrado é a mesma dívida."""
    broken = [
        (item.key, path)
        for item in CAPABILITY_READINESS.values()
        for path in item.evidence
        if not (REPOSITORY / path).exists()
    ]
    assert broken == [], f"Evidência declarada que não existe: {broken}"


def test_readiness_is_bound_to_the_version_it_evaluated():
    """Mudar a versão do contrato invalida a prontidão até alguém reavaliar."""
    stale = [
        (key, item.evaluated_version, CAPABILITY_REGISTRY[key].version)
        for key, item in CAPABILITY_READINESS.items()
        if CAPABILITY_REGISTRY[key].version != item.evaluated_version
    ]
    assert stale == [], f"Prontidão avaliada em outra versão do contrato: {stale}"


def test_partial_readiness_has_to_say_what_is_missing():
    with pytest.raises(ValueError, match="precisa dizer o que falta"):
        CapabilityReadiness(
            key="x", evaluated_version="1.0.0",
            implementation=ImplementationState.PARTIAL, evidence=("backend/tests",),
        )


def test_a_claim_without_evidence_is_refused():
    with pytest.raises(ValueError, match="precisa apontar evidência"):
        CapabilityReadiness(
            key="x", evaluated_version="1.0.0", implementation=ImplementationState.COMPLETE,
        )


def test_only_complete_implementations_may_be_sold():
    """O gate comercial é o eixo de implementação, e nada mais."""
    assert sellable_capabilities() == IMPLEMENTED_CAPABILITIES
    for key in IMPLEMENTED_CAPABILITIES:
        assert CAPABILITY_READINESS[key].implementation is ImplementationState.COMPLETE


def test_tef_is_not_sellable_while_the_bridge_cannot_receive_a_command():
    """O achado de 06/09/2026, afirmado pelo nome para não voltar em silêncio.

    Configuração, pareamento e callback existem e são exercidos por teste. O que
    não existe é o caminho pelo qual o comando chega ao bridge — sem ele nenhuma
    cobrança sai daqui, nem com adquirente contratado.
    """
    tef = CAPABILITY_READINESS["tef"]
    assert tef.implementation is ImplementationState.PARTIAL
    assert "transporte de comandos" in tef.missing
    assert "tef" not in IMPLEMENTED_CAPABILITIES


def test_homologation_is_declared_per_integration_never_per_capability():
    """Homologar com um adquirente não diz nada sobre outro."""
    tef = CAPABILITY_READINESS["tef"]
    assert [item.integration for item in tef.homologations] == ["SITEF"]
    assert tef.homologation_state is HomologationState.PENDING
    # Quem não depende de terceiro não fica pendente para sempre por omissão.
    assert CAPABILITY_READINESS["catalog"].homologation_state is HomologationState.NOT_APPLICABLE


def test_development_debt_is_never_reported_as_a_commercial_choice():
    """Mandar o Owner editar um plano não resolve o que não foi construído."""
    # Mesmo com plano e atividade cobrindo, o que está incompleto continua
    # incompleto — e a razão devolvida diz isso, em vez de "fora do plano".
    assert eligibility(
        "tef", plan_capability_keys=["tef"], activity_capability_keys=["tef"],
    ).reason is EligibilityReason.IN_DEVELOPMENT
    # E o inverso: o que está pronto e fora do catálogo é decisão comercial,
    # que o Owner resolve marcando uma caixa.
    assert eligibility(
        "table_service", plan_capability_keys=[], activity_capability_keys=["table_service"],
    ).reason is EligibilityReason.NOT_IN_PLAN
    assert eligibility(
        "table_service", plan_capability_keys=["table_service"], activity_capability_keys=[],
    ).reason is EligibilityReason.NOT_OFFERED_BY_ACTIVITIES
    assert eligibility(
        "table_service", plan_capability_keys=["table_service"],
        activity_capability_keys=["table_service"],
    ).reachable


def test_nfce_is_incomplete_because_the_only_gateway_fabricates_the_document():
    """O eixo de homologação não cobre um emissor que inventa a chave.

    O ciclo do documento existe, mas `fiscal_gateway` é um singleton global
    apontando para `FakeFiscalGateway`, que gera a chave de acesso com `uuid4` e
    devolve uma URL de DANFE inexistente. Isso é implementação incompleta, não
    atestado pendente: nenhuma certificação da SEFAZ conserta isso.
    """
    from app.providers.fiscal_provider import FakeFiscalGateway, fiscal_gateway

    assert isinstance(fiscal_gateway, FakeFiscalGateway)
    nfce = CAPABILITY_READINESS["fiscal_nfce"]
    assert nfce.implementation is ImplementationState.PARTIAL
    assert "gateway fiscal real" in nfce.missing
    assert "fiscal_nfce" not in IMPLEMENTED_CAPABILITIES
    # E a homologação continua sendo uma pergunta separada, ainda pendente.
    assert nfce.homologation_state is HomologationState.PENDING


def test_a_capability_standing_on_something_incomplete_is_not_deliverable(monkeypatch):
    """Elegibilidade é do que a capability precisa, não só dela mesma."""
    from app.modules.capabilities import eligibility as eligibility_module
    from app.modules.capabilities.readiness import CapabilityReadiness

    # `high_speed_checkout` depende de `barcode_scanning` e `payments`. Se o que
    # está embaixo não estiver pronto, ela também não está — por mais completo
    # que esteja o código dela.
    broken = dict(CAPABILITY_READINESS)
    broken["barcode_scanning"] = CapabilityReadiness(
        key="barcode_scanning", evaluated_version="1.0.0",
        implementation=ImplementationState.PARTIAL,
        evidence=("backend/tests/test_pos3_gates.py",), missing="leitor real",
    )
    monkeypatch.setattr(eligibility_module, "CAPABILITY_READINESS", broken)

    blocked = eligibility_module.eligibility(
        "high_speed_checkout",
        plan_capability_keys=["high_speed_checkout"],
        activity_capability_keys=["high_speed_checkout"],
    )
    assert blocked.reason is EligibilityReason.IN_DEVELOPMENT
    assert blocked.blocked_by == "barcode_scanning"
    assert not blocked.reachable


def test_eligibility_map_answers_a_whole_catalogue_in_one_composition():
    """Existe para que nenhum consumidor refaça a conta por conta própria."""
    from app.modules.capabilities.eligibility import eligibility_map

    resolved = eligibility_map(
        ["table_service", "tef", "fiscal_nfce", "combos"],
        plan_capability_keys=["table_service", "tef", "fiscal_nfce"],
        activity_capability_keys=["table_service", "tef", "combos"],
    )
    assert resolved["table_service"].reason is EligibilityReason.REACHABLE
    # Incompletas continuam incompletas mesmo cobertas por plano e atividade.
    assert resolved["tef"].reason is EligibilityReason.IN_DEVELOPMENT
    assert resolved["fiscal_nfce"].reason is EligibilityReason.IN_DEVELOPMENT
    # E o que está pronto e fora do plano é decisão comercial, não dívida.
    assert resolved["combos"].reason is EligibilityReason.NOT_IN_PLAN


def test_homologation_travels_with_the_integration_it_attests():
    """Resumir a lista perderia a única informação que importa: qual deles."""
    tef = CAPABILITY_READINESS["tef"]
    nfce = CAPABILITY_READINESS["fiscal_nfce"]
    assert [item.integration for item in tef.homologations] == ["SITEF"]
    assert [item.integration for item in nfce.homologations] == ["SEFAZ"]
    assert tef.homologations[0].state is HomologationState.PENDING
