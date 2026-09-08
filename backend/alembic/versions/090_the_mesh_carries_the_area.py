"""A área de cada destino vira dado da malha, junto com a frase que ele promete.

A navegação da Gestão precisa de sete áreas em ordem fixa, e cada card precisa
dizer numa frase o que a pessoa vai fazer ali. Nada disso existia como dado: o
agrupamento vinha de `group_key` sem ordem declarada, e a frase não existia em
lugar nenhum — estava só na tabela de um plano.

Seguindo a 088, isso não vira lista dentro do componente. Cada contribuição
declara em `metadata_json`:

* `area` — chave, rótulo e ordem da área a que o card pertence;
* `description` — a frase de tarefa que o card mostra.

Quem abrir uma área nova, ou mudar a ordem delas, insere ou edita linhas de
dado. Nenhum código de projeção precisa saber quantas áreas existem.

Três decisões que esta migração grava, e que não são cosméticas:

1. **`overview` deixa de ser área.** O contrato pede exatamente sete áreas e
   proíbe uma oitava aba "Visão geral". A linha continua existindo, com a mesma
   permissão, marcada como `placement: "ENTRY"`: ela é o conteúdo da entrada,
   não um destino da barra.
2. **`payment_providers` muda de ADMINISTRAÇÃO para FINANCEIRO**, que é onde
   configurar recebimento pertence, e onde o contrato pede que ela continue
   alcançável sem virar oitava área.
3. **`inventory` passa a se chamar "Estoques"**, a correção de escrita pedida
   no mapa. `contribution_key`, permissão e ordenação não se movem.

`sort_order` não muda: a ordem dentro de cada área já correspondia ao mapa.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "090_the_mesh_carries_the_area"
down_revision: Union[str, None] = "089_the_till_asks_to_authorize"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (contribution_key, chave da área, rótulo da área, ordem da área, frase do card)
DESTINOS = (
    ("sales", "OPERACAO", "Operação", 1, "Consulte vendas e acompanhe pagamentos."),
    ("cash", "OPERACAO", "Operação", 1, "Confira aberturas, movimentos e fechamentos."),
    ("channels", "OPERACAO", "Operação", 1, "Acompanhe pedidos dos seus canais."),
    ("products", "MERCADORIAS", "Mercadorias", 2, "Cadastre produtos e atualize preços."),
    ("assortments", "MERCADORIAS", "Mercadorias", 2, "Escolha os produtos vendidos em cada canal."),
    ("categories", "MERCADORIAS", "Mercadorias", 2, "Organize produtos para encontrá-los facilmente."),
    ("inventory", "MERCADORIAS", "Mercadorias", 2, "Receba mercadorias e confira quantidades."),
    ("tables", "ESTRUTURA", "Estrutura", 3, "Organize os espaços e mesas do atendimento."),
    ("devices", "ESTRUTURA", "Estrutura", 3, "Gerencie os equipamentos da operação."),
    ("team", "PESSOAS", "Pessoas", 4, "Cadastre a equipe e defina acessos."),
    ("customers", "RELACIONAMENTO", "Relacionamento", 5, "Encontre e atualize seus clientes."),
    ("receivables", "FINANCEIRO", "Financeiro", 6, "Acompanhe valores que seus clientes devem."),
    ("payment_providers", "FINANCEIRO", "Financeiro", 6, "Configure como você recebe pagamentos."),
    ("subscription", "ADMINISTRACAO", "Administração", 7, "Consulte seu plano e acompanhe solicitações."),
)


def upgrade() -> None:
    for chave, area_key, area_label, area_order, descricao in DESTINOS:
        op.execute(
            f"""
            UPDATE module_contributions
            SET group_key = '{area_key}',
                metadata_json = (
                    COALESCE(metadata_json::jsonb, '{{}}'::jsonb) || '{{
                        "area": {{"key": "{area_key}", "label": "{area_label}", "order": {area_order}}},
                        "description": "{descricao}"
                    }}'::jsonb
                )::json
            WHERE contribution_key = '{chave}' AND surface = 'MANAGEMENT_NAV'
            """
        )

    # A visão geral é o conteúdo da entrada, não a oitava área.
    op.execute(
        """
        UPDATE module_contributions
        SET metadata_json = (
            COALESCE(metadata_json::jsonb, '{}'::jsonb) || '{"placement": "ENTRY"}'::jsonb
        )::json
        WHERE contribution_key = 'overview' AND surface = 'MANAGEMENT_NAV'
        """
    )

    op.execute(
        """
        UPDATE module_contributions
        SET label = 'Estoques'
        WHERE contribution_key = 'inventory' AND surface = 'MANAGEMENT_NAV'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE module_contributions
        SET metadata_json = (
            (COALESCE(metadata_json::jsonb, '{}'::jsonb) - 'area') - 'description' - 'placement'
        )::json
        WHERE surface = 'MANAGEMENT_NAV'
        """
    )
    op.execute(
        """
        UPDATE module_contributions
        SET label = 'Estoque'
        WHERE contribution_key = 'inventory' AND surface = 'MANAGEMENT_NAV'
        """
    )
    for chave, grupo in (
        ("sales", "OPERAÇÃO"), ("cash", "OPERAÇÃO"), ("channels", "OPERAÇÃO"),
        ("products", "MERCADORIAS"), ("assortments", "MERCADORIAS"),
        ("categories", "MERCADORIAS"), ("inventory", "MERCADORIAS"),
        ("tables", "ESTRUTURA"), ("devices", "ESTRUTURA"),
        ("team", "PESSOAS"), ("customers", "RELACIONAMENTO"),
        ("receivables", "FINANCEIRO"), ("payment_providers", "ADMINISTRAÇÃO"),
        ("subscription", "ADMINISTRAÇÃO"),
    ):
        op.execute(
            f"""
            UPDATE module_contributions SET group_key = '{grupo}'
            WHERE contribution_key = '{chave}' AND surface = 'MANAGEMENT_NAV'
            """
        )
