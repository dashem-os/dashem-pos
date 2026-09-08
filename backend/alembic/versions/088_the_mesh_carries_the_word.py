"""A palavra do nicho vira dado da malha, e não uma lista dentro do endpoint.

A 086 trocou o rótulo do menu por "Cardápios" para todos os tenants. Padaria
acertou; revendedora de beleza passou a ver um cardápio que ela não tem. O
conserto não é um `if` a mais no servidor: é a contribuição declarar, na
própria linha, qual palavra vale para qual atividade contratada.

O rótulo base volta a ser o neutro — "Catálogos", que serve comércio e beleza
— e a variante de FOOD_SERVICE viaja em `metadata_json.label_variants`, em
ordem de precedência. Quem quiser uma palavra nova para um nicho novo insere
uma linha de dado; ninguém precisa editar código de projeção.

Nada de estrutura muda: `metadata_json` já existe desde a 038.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "088_the_mesh_carries_the_word"
down_revision: Union[str, None] = "087_inventory_reservation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VARIANTES = (
    '{"label_variants": [{"when_activity": "FOOD_SERVICE", "label": "Cardápios"}]}'
)


def upgrade() -> None:
    op.execute(
        """
        UPDATE module_contributions
        SET label = 'Catálogos',
            metadata_json = (
                COALESCE(metadata_json::jsonb, '{}'::jsonb) || '"""
        + VARIANTES
        + """'::jsonb
            )::json
        WHERE contribution_key = 'assortments' AND surface = 'MANAGEMENT_NAV'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE module_contributions
        SET label = 'Cardápios',
            metadata_json = (COALESCE(metadata_json::jsonb, '{}'::jsonb) - 'label_variants')::json
        WHERE contribution_key = 'assortments' AND surface = 'MANAGEMENT_NAV'
        """
    )
