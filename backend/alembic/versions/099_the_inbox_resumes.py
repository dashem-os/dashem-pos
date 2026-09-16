"""A caixa de entrada retoma, e a pessoa mora num lugar só.

S10.1, passos 3 e 4 (docs/product/proposta-s10-1-channel-hub.md, revisão 3).

Caixa de entrada: estados retomáveis, lease, tentativas, versão do parser, chave
de ordem e o instante da primeira quarentena — que prende o prazo do payload à
recepção mesmo depois de a causa ser corrigida (D6). Os estados do S10 são
traduzidos: `PROCESSED` vira `APPLIED`, `NORMALIZED` volta a `RECEIVED` para ser
retomado, `DUPLICATE` vira `SUPERSEDED`. Motivos de quarentena antigos são
apagados, porque guardavam o texto da exceção e podiam carregar o que chegou
(C12); o código fica.

`external_order_lines`: a linha como o canal a declarou, identificada pela linha
externa (H3), com os valores declarados.

`channel_order_contacts`: nome, telefone, endereço e instruções de entrega, com
pseudônimo, prazo e legal hold completo. É a única casa desses dados (H13).

`external_order_mappings`: última chave de ordem aplicada, valores declarados do
pedido e a âncora terminal dos prazos (D3).

Nenhum dado é removido. Os prazos são política técnica inicial, não jurídica.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "099_the_inbox_resumes"
down_revision: Union[str, None] = "098_the_event_has_a_deadline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UID = postgresql.UUID(as_uuid=True)
PLATFORM = "current_setting('app.platform_access', true) = 'true'"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
STORE = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
SCOPE = f"({PLATFORM}) OR (({TENANT}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {STORE}))"
LEGAL_HOLD_COMPLETE = (
    "(legal_hold_until IS NULL AND legal_hold_reason IS NULL AND legal_hold_reference IS NULL"
    " AND legal_hold_by IS NULL AND legal_hold_review_at IS NULL)"
    " OR (legal_hold_until IS NOT NULL AND legal_hold_reason IS NOT NULL"
    " AND legal_hold_reference IS NOT NULL AND legal_hold_by IS NOT NULL"
    " AND legal_hold_review_at IS NOT NULL)"
)
MONEY = sa.Numeric(14, 4)


def _isolate(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY {table}_isolation ON "{table}" FOR ALL USING ({SCOPE}) WITH CHECK ({SCOPE})')


def upgrade() -> None:
    # O segredo por conexão morre com a rota antiga: o canal assina com a credencial
    # do aplicativo na plataforma (§3.3).
    op.alter_column("merchant_connections", "webhook_secret_hash", existing_type=sa.String(length=64), nullable=True)
    op.add_column("channel_inbox_events", sa.Column("parser_version", sa.String(length=40), nullable=True))
    op.add_column("channel_inbox_events", sa.Column("order_key", sa.String(length=40), nullable=True))
    op.add_column("channel_inbox_events", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("channel_inbox_events", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("channel_inbox_events", sa.Column("last_error_code", sa.String(length=80), nullable=True))
    op.add_column("channel_inbox_events", sa.Column("first_quarantined_at", sa.DateTime(), nullable=True))

    op.execute("SELECT set_config('app.platform_access', 'true', true)")
    op.execute("UPDATE channel_inbox_events SET status = 'APPLIED' WHERE status = 'PROCESSED'")
    op.execute("UPDATE channel_inbox_events SET status = 'RECEIVED' WHERE status = 'NORMALIZED'")
    op.execute("UPDATE channel_inbox_events SET status = 'SUPERSEDED' WHERE status = 'DUPLICATE'")
    op.execute("""
        UPDATE channel_inbox_events
           SET first_quarantined_at = coalesce(processed_at, received_at), quarantine_reason = NULL
         WHERE status = 'QUARANTINED'
    """)
    op.execute("SELECT set_config('app.platform_access', 'false', true)")

    op.add_column("external_order_mappings", sa.Column("last_order_key", sa.String(length=40), nullable=True))
    for column in ("delivery_fee", "channel_discount", "channel_subsidy", "declared_total"):
        op.add_column("external_order_mappings", sa.Column(column, MONEY, nullable=True))
    op.add_column("external_order_mappings", sa.Column("terminal_state", sa.String(length=50), nullable=True))
    op.add_column("external_order_mappings", sa.Column("terminal_at", sa.DateTime(), nullable=True))
    op.create_index("ix_external_order_mappings_terminal_at", "external_order_mappings", ["terminal_at"])

    op.create_table(
        "external_order_lines",
        sa.Column("id", UID, primary_key=True),
        sa.Column("tenant_id", UID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", UID, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("external_order_mapping_id", UID, sa.ForeignKey("external_order_mappings.id"), nullable=False),
        sa.Column("external_line_id", sa.String(length=160), nullable=False),
        sa.Column("external_item_code", sa.String(length=160), nullable=False),
        sa.Column("order_item_id", UID, sa.ForeignKey("order_items.id"), nullable=True),
        sa.Column("quantity", MONEY, nullable=False),
        sa.Column("unit_amount", MONEY, nullable=True),
        sa.Column("discount_amount", MONEY, nullable=True),
        sa.Column("modifier_codes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("external_order_mapping_id", "external_line_id", name="uq_external_order_line"),
    )
    for column in ("tenant_id", "store_id", "external_order_mapping_id", "order_item_id"):
        op.create_index(f"ix_external_order_lines_{column}", "external_order_lines", [column])
    _isolate("external_order_lines")

    op.create_table(
        "channel_order_contacts",
        sa.Column("id", UID, primary_key=True),
        sa.Column("tenant_id", UID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", UID, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("external_order_mapping_id", UID, sa.ForeignKey("external_order_mappings.id"), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("delivery_address", sa.JSON(), nullable=True),
        sa.Column("delivery_instructions", sa.String(length=500), nullable=True),
        sa.Column("pseudonym", sa.String(length=40), nullable=False),
        sa.Column("retention_basis", sa.String(length=50), nullable=False),
        sa.Column("retention_until", sa.DateTime(), nullable=True),
        sa.Column("redacted_at", sa.DateTime(), nullable=True),
        sa.Column("redaction_method", sa.String(length=50), nullable=True),
        sa.Column("legal_hold_until", sa.DateTime(), nullable=True),
        sa.Column("legal_hold_reason", sa.String(length=300), nullable=True),
        sa.Column("legal_hold_reference", sa.String(length=160), nullable=True),
        sa.Column("legal_hold_by", UID, nullable=True),
        sa.Column("legal_hold_review_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("external_order_mapping_id", name="uq_channel_order_contact_mapping"),
        sa.CheckConstraint(LEGAL_HOLD_COMPLETE, name="ck_channel_contact_legal_hold_complete"),
    )
    for column in ("tenant_id", "store_id", "external_order_mapping_id", "retention_until", "legal_hold_until"):
        op.create_index(f"ix_channel_order_contacts_{column}", "channel_order_contacts", [column])
    _isolate("channel_order_contacts")


def downgrade() -> None:
    for table in ("channel_order_contacts", "external_order_lines"):
        op.execute(f'DROP POLICY IF EXISTS {table}_isolation ON "{table}"')
        op.drop_table(table)
    op.drop_index("ix_external_order_mappings_terminal_at", table_name="external_order_mappings")
    for column in ("terminal_at", "terminal_state", "declared_total", "channel_subsidy",
                   "channel_discount", "delivery_fee", "last_order_key"):
        op.drop_column("external_order_mappings", column)
    op.execute("SELECT set_config('app.platform_access', 'true', true)")
    op.execute("UPDATE channel_inbox_events SET status = 'PROCESSED' WHERE status = 'APPLIED'")
    op.execute("UPDATE channel_inbox_events SET status = 'DUPLICATE' WHERE status = 'SUPERSEDED'")
    op.execute("""
        UPDATE channel_inbox_events SET status = 'QUARANTINED'
         WHERE status IN ('PROCESSING', 'NEEDS_REVIEW', 'DISCARDED', 'EXPIRED')
    """)
    op.execute("SELECT set_config('app.platform_access', 'false', true)")
    for column in ("first_quarantined_at", "last_error_code", "lease_expires_at", "attempts", "order_key", "parser_version"):
        op.drop_column("channel_inbox_events", column)
    op.execute("SELECT set_config('app.platform_access', 'true', true)")
    op.execute("UPDATE merchant_connections SET webhook_secret_hash = repeat('0', 64) WHERE webhook_secret_hash IS NULL")
    op.execute("SELECT set_config('app.platform_access', 'false', true)")
    op.alter_column("merchant_connections", "webhook_secret_hash", existing_type=sa.String(length=64), nullable=False)
