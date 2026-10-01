"""O snapshot de publicação congela a versão e o conteúdo de cada oferta.

S13.2, primeira fatia — publicação de catálogo fundacional (docs/product/proposta-s13-2-publicacao-catalogo.md).

- `channel_publication_batches` recebe `snapshot_version` (versão do snapshot/lote,
  separada da `desired_version` individual de cada oferta) e `content_hash`
  (hash do conteúdo congelado, separado do `request_hash` de idempotência).
- `channel_publication_items` recebe `frozen_payload` (JSON congelado com os dados
  e atributos do produto enviados ao canal no momento da geração do lote).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "102_the_catalog_snapshot_freezes"
down_revision: Union[str, None] = "101_the_channel_price_stands"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_publication_batches",
        sa.Column("snapshot_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "channel_publication_batches",
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "channel_publication_items",
        sa.Column("frozen_payload", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_publication_items", "frozen_payload")
    op.drop_column("channel_publication_batches", "content_hash")
    op.drop_column("channel_publication_batches", "snapshot_version")
