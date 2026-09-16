"""O evento de canal nasce com prazo, e o merchant conectado tem um único dono.

S10.1, passo 2 (docs/product/proposta-s10-1-channel-hub.md, revisão 3).

O ingresso passa a resolver a conexão pelo provedor e pelo merchant, no servidor,
sem tenant no corpo (H9). Isso só é seguro se um merchant conectado pertencer a
um único tenant: o índice parcial `uq_connected_provider_merchant` garante. Se já
houver o mesmo merchant conectado em mais de um tenant, fica conectada a conexão
atualizada por último, e as outras voltam a `DEGRADED` com o motivo nomeado —
nenhuma é escolhida em silêncio.

Todo evento passa a ter prazo (D6): `retention_basis` e `retention_until`. Os
eventos que já existem recebem o prazo contado da recepção, a regra mais curta
que a política permite para eles. Nada é removido aqui; a purga é etapa
posterior. Os prazos são política técnica inicial, não orientação jurídica.

Legal hold só existe completo (H16): a restrição exige motivo, referência,
responsável e revisão juntos com o fim do hold, ou nenhum deles.

As quatro permissões da D7 entram no catálogo **sem concessão a nenhum perfil**.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "098_the_event_has_a_deadline"
down_revision: Union[str, None] = "097_the_pinpad_is_occupied"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSIONS = (
    ("channel.order_contact.read", "Ver contato do pedido de canal",
     "Ver nome, telefone e endereço do cliente para preparar e entregar um pedido de canal"),
    ("channel.legal_hold.manage", "Registrar retenção legal de dado de canal",
     "Registrar ou liberar legal hold sobre dados de pedidos de canal"),
    ("channel.retention.extend", "Estender retenção de dado de canal",
     "Estender o prazo de retenção de dados de canal além do padrão"),
    ("channel.retention.purge", "Executar limpeza de dado de canal",
     "Executar ou solicitar a limpeza de dados de canal vencidos"),
)

LEGAL_HOLD_COMPLETE = (
    "(legal_hold_until IS NULL AND legal_hold_reason IS NULL AND legal_hold_reference IS NULL"
    " AND legal_hold_by IS NULL AND legal_hold_review_at IS NULL)"
    " OR (legal_hold_until IS NOT NULL AND legal_hold_reason IS NOT NULL"
    " AND legal_hold_reference IS NOT NULL AND legal_hold_by IS NOT NULL"
    " AND legal_hold_review_at IS NOT NULL)"
)


def upgrade() -> None:
    # Escrita autorizada pela migração, explícita em vez de depender de o papel
    # ser superusuário, como na 069 e na 097. Desligada logo depois.
    op.execute("SELECT set_config('app.platform_access', 'true', true)")
    op.execute("""
        UPDATE merchant_connections AS c
           SET status = 'DEGRADED',
               last_error_code = 'MERCHANT_CONNECTED_ELSEWHERE',
               last_error_message = 'O mesmo merchant está conectado em outro tenant.',
               updated_at = (now() AT TIME ZONE 'utc')
          FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY provider_code, merchant_external_id
                    ORDER BY updated_at DESC, id
                ) AS ordem
                  FROM merchant_connections
                 WHERE status = 'CONNECTED'
               ) AS r
         WHERE c.id = r.id AND r.ordem > 1
    """)
    op.create_index(
        "uq_connected_provider_merchant", "merchant_connections",
        ["provider_code", "merchant_external_id"], unique=True,
        postgresql_where=sa.text("status = 'CONNECTED'"),
    )

    op.alter_column("channel_inbox_events", "raw_payload", existing_type=sa.JSON(), nullable=True)
    op.add_column("channel_inbox_events", sa.Column(
        "retention_basis", sa.String(length=50), nullable=False, server_default="RECEPCAO",
    ))
    op.alter_column("channel_inbox_events", "retention_basis", server_default=None)
    op.add_column("channel_inbox_events", sa.Column("retention_until", sa.DateTime(), nullable=True))
    op.execute("UPDATE channel_inbox_events SET retention_until = received_at + interval '30 days'")
    op.create_index("ix_channel_inbox_events_retention_until", "channel_inbox_events", ["retention_until"])

    op.add_column("channel_inbox_events", sa.Column("legal_hold_until", sa.DateTime(), nullable=True))
    op.add_column("channel_inbox_events", sa.Column("legal_hold_reason", sa.String(length=300), nullable=True))
    op.add_column("channel_inbox_events", sa.Column("legal_hold_reference", sa.String(length=160), nullable=True))
    op.add_column("channel_inbox_events", sa.Column("legal_hold_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("channel_inbox_events", sa.Column("legal_hold_review_at", sa.DateTime(), nullable=True))
    op.create_index("ix_channel_inbox_events_legal_hold_until", "channel_inbox_events", ["legal_hold_until"])
    op.create_check_constraint(
        "ck_channel_inbox_legal_hold_complete", "channel_inbox_events", LEGAL_HOLD_COMPLETE,
    )
    op.execute("SELECT set_config('app.platform_access', 'false', true)")

    values = ", ".join(
        f"('{key}', '{name}', '{description}', now())" for key, name, description in PERMISSIONS
    )
    op.execute(f"""
        INSERT INTO permissions (key, name, description, created_at)
        VALUES {values}
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    keys = ", ".join(f"'{key}'" for key, _, _ in PERMISSIONS)
    op.execute(f"DELETE FROM permission_grants WHERE permission_key IN ({keys})")
    op.execute(f"DELETE FROM role_profile_permissions WHERE permission_key IN ({keys})")
    op.execute(f"DELETE FROM permissions WHERE key IN ({keys})")

    op.execute("SELECT set_config('app.platform_access', 'true', true)")
    op.drop_constraint("ck_channel_inbox_legal_hold_complete", "channel_inbox_events", type_="check")
    op.drop_index("ix_channel_inbox_events_legal_hold_until", table_name="channel_inbox_events")
    for column in ("legal_hold_review_at", "legal_hold_by", "legal_hold_reference", "legal_hold_reason", "legal_hold_until"):
        op.drop_column("channel_inbox_events", column)
    op.drop_index("ix_channel_inbox_events_retention_until", table_name="channel_inbox_events")
    op.drop_column("channel_inbox_events", "retention_until")
    op.drop_column("channel_inbox_events", "retention_basis")
    op.execute("UPDATE channel_inbox_events SET raw_payload = '{}' WHERE raw_payload IS NULL")
    op.alter_column("channel_inbox_events", "raw_payload", existing_type=sa.JSON(), nullable=False)
    # Conexões rebaixadas na subida não voltam a CONNECTED: reconectar é validar de novo.
    op.drop_index("uq_connected_provider_merchant", table_name="merchant_connections")
    op.execute("SELECT set_config('app.platform_access', 'false', true)")
