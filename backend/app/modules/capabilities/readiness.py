"""ADR-031 — prontidão por capability, em eixos que não se resumem a um booleano.

`IMPLEMENTED_CAPABILITIES` era um `frozenset`: uma pergunta só, respondida à mão.
Em 06/09/2026 a `tef` mostrou o que isso não comporta — ela estava na lista, e
três coisas diferentes eram falsas ao mesmo tempo: nenhum plano a vendia, o
transporte de comandos ao bridge não existia, e nenhum adquirente havia atestado
nada.

Aqui a prontidão tem eixos separados, porque as perguntas são independentes:

* **implementação** — o código faz o trabalho inteiro do contrato dela? Declarado,
  mas obrigado a apontar evidência que existe, e `PARTIAL` obrigado a dizer o que
  falta. É o eixo que governa venda.
* **homologação** — um terceiro atestou? Declarada **por integração**, nunca por
  capability: TEF homologado com um adquirente não diz nada sobre outro.
* **elegibilidade** — consegue chegar a este tenant? Não mora aqui de propósito.
  É **contextual** e derivada da composição plano + atividades no momento da
  pergunta, em `eligibility.py`. Declará-la teria repetido o defeito original.

A evidência é sempre vinculada à **versão avaliada** do contrato. Uma capability
que muda de versão volta a não ter prontidão provada, e o teste de arquitetura
recusa a divergência — é isso que impede a declaração de envelhecer em silêncio.
"""

from dataclasses import dataclass, field
from enum import Enum


class ImplementationState(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class HomologationState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"


@dataclass(frozen=True)
class Homologation:
    """O atestado de um terceiro, sobre uma integração concreta.

    `integration` é o que foi homologado — um adquirente, uma SEFAZ, um PSP.
    Homologar a capability inteira não quer dizer nada: quem certifica certifica
    a sua própria integração.
    """

    integration: str
    state: HomologationState
    evidence: str | None = None
    certified_on: str | None = None


@dataclass(frozen=True)
class CapabilityReadiness:
    """O que o sistema afirma sobre si mesmo, e com base em quê."""

    key: str
    evaluated_version: str
    implementation: ImplementationState
    evidence: tuple[str, ...] = ()
    missing: str | None = None
    homologations: tuple[Homologation, ...] = ()

    def __post_init__(self) -> None:
        if self.implementation is ImplementationState.PARTIAL and not self.missing:
            raise ValueError(
                f"{self.key}: prontidão PARTIAL precisa dizer o que falta."
            )
        if self.implementation is not ImplementationState.NONE and not self.evidence:
            raise ValueError(
                f"{self.key}: prontidão declarada precisa apontar evidência."
            )

    @property
    def sellable(self) -> bool:
        """Só integração completa pode ser vendida como software que funciona."""
        return self.implementation is ImplementationState.COMPLETE

    @property
    def homologation_state(self) -> HomologationState:
        if not self.homologations:
            return HomologationState.NOT_APPLICABLE
        if any(item.state is HomologationState.CERTIFIED for item in self.homologations):
            return HomologationState.CERTIFIED
        return HomologationState.PENDING


def _complete(key: str, version: str, *evidence: str, homologations: tuple[Homologation, ...] = ()) -> CapabilityReadiness:
    return CapabilityReadiness(
        key=key, evaluated_version=version, implementation=ImplementationState.COMPLETE,
        evidence=evidence, homologations=homologations,
    )


def _partial(key: str, version: str, missing: str, *evidence: str, homologations: tuple[Homologation, ...] = ()) -> CapabilityReadiness:
    return CapabilityReadiness(
        key=key, evaluated_version=version, implementation=ImplementationState.PARTIAL,
        evidence=evidence, missing=missing, homologations=homologations,
    )


def _none(key: str, version: str) -> CapabilityReadiness:
    return CapabilityReadiness(
        key=key, evaluated_version=version, implementation=ImplementationState.NONE,
    )


# A evidência aponta para arquivos que existem no repositório, e o teste de
# arquitetura falha quando um caminho declarado some. `{"passed": true}` não é
# prova, e um caminho quebrado é a mesma dívida com outro nome.
CAPABILITY_READINESS: dict[str, CapabilityReadiness] = {
    item.key: item for item in (
        _complete("catalog", "1.0.0",
                  "backend/tests/test_s4_catalog_gate.py",
                  "backend/tests/test_catalog_editing_flow.py"),
        _complete("inventory", "1.0.0", "backend/tests/test_pos2_gates.py"),
        _complete("customer", "1.0.0", "backend/tests/test_pos5_operational_flows.py"),
        _complete("cash_management", "1.0.0", "backend/tests/test_cash_shift_authority.py"),
        _complete("payments", "1.0.0",
                  "backend/tests/test_s8_checkout_negotiation.py",
                  "backend/tests/test_s25_live_settlement.py",
                  "backend/tests/test_s25_2_open_account_reversal.py"),
        _complete("barcode_scanning", "1.0.0", "backend/tests/test_pos3_gates.py"),
        _complete("modifiers", "1.0.0", "backend/tests/test_s13_1_backoffice.py"),
        _complete("combos", "1.0.0", "backend/tests/test_s13_1_backoffice.py"),
        _complete("kitchen_routing", "1.0.0", "backend/tests/test_s11_production_kds.py"),
        _complete("delivery_orders", "1.0.0", "backend/tests/test_s10_channel_hub.py"),
        _complete("counter_order", "1.0.0", "backend/tests/test_s5_counter_gate.py"),
        _complete("table_service", "1.0.0",
                  "backend/tests/test_s7_table_service.py",
                  "backend/tests/test_s12_transfers.py",
                  "docs/quality/s23-shared-selector-acceptance.md"),
        _complete("high_speed_checkout", "1.0.0", "backend/tests/test_pos3_gates.py"),
        # A capability declarava-se completa quando só existia a permissão no
        # perfil: nenhum mecanismo de elevação, e o operador que não tinha a
        # permissão simplesmente via o botão apagado. A prova agora é a
        # autorização presencial e o cenário percorrido em duas estações.
        _complete("supervisor_override", "1.0.0",
                  "backend/tests/test_supervisor_authorization.py",
                  "backend/tests/test_permission_engine.py"),
        _complete("receivables", "1.0.0",
                  "backend/tests/test_s14_receivables.py",
                  "backend/tests/test_s15_receivable_collection.py"),
        # A configuração, o pareamento e o callback existem e são exercidos. O
        # que não existe é o caminho pelo qual o comando chega ao bridge: sem
        # ele, nenhuma cobrança sai daqui nem com adquirente contratado.
        _partial(
            "tef", "1.0.0",
            "transporte de comandos ao bridge (docs/product/bridge-command-transport.md, frente A)",
            "backend/tests/test_s9_payment_providers.py",
            "backend/tests/test_gate_c_payment_device_binding.py",
            "backend/tests/test_s25_1_payment_recovery.py",
            "docs/quality/s25-1-staged-restart-drill.md",
            homologations=(
                Homologation(integration="SITEF", state=HomologationState.PENDING),
            ),
        ),
        # Duas coisas diferentes faltam aqui, e só uma delas é homologação.
        #
        # O ciclo do documento existe — emissão, contingência, rejeição,
        # cancelamento, armazenamento. Mas o único gateway que existe é o
        # `FakeFiscalGateway`, ligado como singleton global: ele fabrica a chave
        # de acesso com `uuid4` e devolve uma URL de DANFE que não existe. Isso
        # é implementação incompleta, não atestado pendente — nenhuma
        # certificação da SEFAZ conserta um emissor que inventa a chave.
        _partial(
            "fiscal_nfce", "1.0.0",
            "gateway fiscal real; hoje `FakeFiscalGateway` fabrica chave de acesso e DANFE",
            "backend/app/providers/fiscal_provider.py",
            "backend/tests/test_s21_commercial_pilot.py",
            homologations=(
                Homologation(integration="SEFAZ", state=HomologationState.PENDING),
            ),
        ),
    )
}

# Contratos desenhados cujo módulo executável não existe. Ficam visíveis para a
# arquitetura e para o Owner — sumir da tela foi o que escondeu a TEF —, mas não
# podem ser vendidos.
for _planned in (
    "quotes", "weighted_products", "customer_display", "self_checkout",
    "serial_tracking", "batch_tracking", "multi_price", "pix", "fiscal_nfe",
):
    CAPABILITY_READINESS[_planned] = _none(_planned, "1.0.0")


def readiness(key: str) -> CapabilityReadiness:
    return CAPABILITY_READINESS[key]


def sellable_capabilities() -> frozenset[str]:
    """As que podem ser vendidas como software que funciona."""
    return frozenset(key for key, item in CAPABILITY_READINESS.items() if item.sellable)
