"""O aviso ao canal sai, e diz o que aconteceu com ele.

S10.1, passo 6 (docs/product/proposta-s10-1-channel-hub.md, §3.6).

`channel_outbound_messages` passa a ser a fila do executor: lease, instante de
entrega, referência devolvida pelo canal e código do último erro. Os estados
`SENDING` e `UNCONFIRMED` entram no vocabulário da coluna, que já é texto.
`last_error`, texto livre do S10, fica sem escrita nova: o executor grava só o
código.

Nenhum dado é alterado.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "100_the_notice_leaves"
down_revision: Union[str, None] = "099_the_inbox_resumes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("channel_outbound_messages", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("channel_outbound_messages", sa.Column("delivered_at", sa.DateTime(), nullable=True))
    op.add_column("channel_outbound_messages", sa.Column("provider_reference", sa.String(length=200), nullable=True))
    op.add_column("channel_outbound_messages", sa.Column("last_error_code", sa.String(length=80), nullable=True))
    op.create_index("ix_channel_outbound_messages_delivered_at", "channel_outbound_messages", ["delivered_at"])


def downgrade() -> None:
    op.execute("SELECT set_config('app.platform_access', 'true', true)")
    op.execute("""
        UPDATE channel_outbound_messages SET status = 'RETRY'
         WHERE status IN ('SENDING', 'UNCONFIRMED')
    """)
    op.execute("SELECT set_config('app.platform_access', 'false', true)")
    op.drop_index("ix_channel_outbound_messages_delivered_at", table_name="channel_outbound_messages")
    for column in ("last_error_code", "provider_reference", "delivered_at", "lease_expires_at"):
        op.drop_column("channel_outbound_messages", column)
