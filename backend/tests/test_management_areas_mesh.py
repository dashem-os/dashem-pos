"""As sete áreas da Gestão são dado da malha, não constante do componente.

A UX-01 reorganizou a navegação em entrada → área → módulo. A pergunta "a que
área este destino pertence, e o que ele promete em uma frase" passou a ter
resposta em `module_contributions.metadata_json`, escrita pela migração 090 —
pelo mesmo motivo que a palavra do nicho virou dado na 088: quem abrir uma área
nova insere linha, não edita código de projeção.

Estes testes olham a malha publicada. Se alguém acrescentar uma contribuição de
navegação sem área, o frontend não a mostra como card — e é melhor descobrir
isso aqui do que numa tela sem o destino.
"""

from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.platform import ModuleContribution


AREAS_ESPERADAS = [
    (1, "OPERACAO", "Operação"),
    (2, "MERCADORIAS", "Mercadorias"),
    (3, "ESTRUTURA", "Estrutura"),
    (4, "PESSOAS", "Pessoas"),
    (5, "RELACIONAMENTO", "Relacionamento"),
    (6, "FINANCEIRO", "Financeiro"),
    (7, "ADMINISTRACAO", "Administração"),
]


def _navegacao(session: Session) -> list[ModuleContribution]:
    return list(session.exec(select(ModuleContribution).where(
        ModuleContribution.surface == "MANAGEMENT_NAV",
        ModuleContribution.is_active.is_(True),
    )).all())


def test_toda_contribuicao_de_navegacao_declara_area_ou_entrada():
    with Session(engine) as session:
        set_platform_db_context(session)
        for contribuicao in _navegacao(session):
            metadados = contribuicao.metadata_json or {}
            declarada = "area" in metadados or metadados.get("placement") == "ENTRY"
            assert declarada, (
                f"{contribuicao.contribution_key} não diz a que área pertence; "
                "sem isso ela não vira card em lugar nenhum"
            )


def test_a_malha_declara_exatamente_as_sete_areas_na_ordem_pedida():
    with Session(engine) as session:
        set_platform_db_context(session)
        areas = {}
        for contribuicao in _navegacao(session):
            area = (contribuicao.metadata_json or {}).get("area")
            if area:
                areas[area["key"]] = (area["order"], area["key"], area["label"])
        assert sorted(areas.values()) == AREAS_ESPERADAS


def test_a_visao_geral_e_conteudo_da_entrada_e_nao_a_oitava_area():
    with Session(engine) as session:
        set_platform_db_context(session)
        overview = next(c for c in _navegacao(session) if c.contribution_key == "overview")
        metadados = overview.metadata_json or {}
        assert metadados.get("placement") == "ENTRY"
        assert "area" not in metadados
        # A permissão não muda: quem não pode ler a gestão continua sem o resumo.
        assert overview.permission_key == "management.read"


def test_cada_card_promete_uma_frase_de_tarefa():
    with Session(engine) as session:
        set_platform_db_context(session)
        for contribuicao in _navegacao(session):
            metadados = contribuicao.metadata_json or {}
            if "area" not in metadados:
                continue
            frase = metadados.get("description") or ""
            assert frase.endswith("."), f"{contribuicao.contribution_key} sem frase de tarefa"
            assert len(frase.split()) >= 4, f"{contribuicao.contribution_key} com frase curta demais: {frase!r}"


def test_configurar_recebimento_mora_no_financeiro():
    """O contrato pede o provedor alcançável no Financeiro, sem oitava área."""
    with Session(engine) as session:
        set_platform_db_context(session)
        provedores = next(c for c in _navegacao(session) if c.contribution_key == "payment_providers")
        assert (provedores.metadata_json or {})["area"]["key"] == "FINANCEIRO"
        # A autorização continua sendo a mesma de antes da mudança de área.
        assert provedores.capability_key == "tef"
        assert provedores.permission_key == "provider.read"


def test_o_estoque_recebe_a_correcao_de_escrita_pedida_no_mapa():
    with Session(engine) as session:
        set_platform_db_context(session)
        estoque = next(c for c in _navegacao(session) if c.contribution_key == "inventory")
        assert estoque.label == "Estoques"
        assert estoque.implementation_key == "inventory"
