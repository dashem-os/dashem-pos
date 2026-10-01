"""Aquisição durável de execução de lotes de publicação de catálogo.

S13.2, primeira fatia — concessão de execução com expiração e token (docs/product/proposta-s13-2-publicacao-catalogo.md).

- `channel_publication_batches` recebe:
  - `lease_token`: identificador efêmero do executor ativo.
  - `lease_expires_at`: instante limite da concessão durável contra múltiplos despachos simultâneos.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "103_the_publication_batch_leases"
down_revision: Union[str, None] = "102_the_catalog_snapshot_freezes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_publication_batches",
        sa.Column("lease_token", sa.String(64), nullable=True),
    )
    op.add_column(
        "channel_publication_batches",
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_channel_publication_batches_lease_expires_at",
        "channel_publication_batches",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_publication_batches_lease_expires_at",
        table_name="channel_publication_batches",
    )
    op.drop_column("channel_publication_batches", "lease_expires_at")
    op.drop_column("channel_publication_batches", "lease_token")
