"""A autorização de acesso ganha uma razão, e os fluxos só acrescentam nela.

A 095 preservou a aprovação anterior nas próprias colunas da concessão, e isso
resolvia **um** momento: a invalidação em massa. Não resolvia o seguinte.

Quando o responsável pelo tenant aprova de novo, `approved_by` e `approved_at`
são sobrescritos e `invalidated_at`/`invalidated_reason` são limpos — porque
estado atual é sempre uma coisa só. A transição que estava gravada some, e a
pergunta "quem já teve acesso a estes dados, e por que aquela aprovação caiu?"
fica sem resposta exatamente onde ela mais importa.

Esta migração dá à concessão a mesma forma que as contas a pagar têm desde a
UX-10: **uma razão de lançamentos**. Cada decisão é uma linha, e o histórico se
lê de ponta a ponta — pedido, aprovação, invalidação, nova aprovação, revogação.

A preservação vem do **fluxo da aplicação**, que só acrescenta: as políticas
abaixo dão à plataforma acesso completo à tabela, e não trancam `UPDATE` nem
`DELETE`. Uma tabela imutável de verdade é outra decisão, e ela não foi tomada
aqui.

O que já estava registrado nas colunas vira linha aqui, para o histórico não
começar do zero na data desta migração.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "096_the_grant_keeps_its_history"
down_revision: Union[str, None] = "095_the_shop_sees_its_own_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MOTIVO_DA_INVALIDACAO = (
    "Aprovada pela plataforma antes de 08/09/2026, quando a autorização passou "
    "a exigir o responsável do tenant (UX-12)."
)


def upgrade() -> None:
    op.create_table(
        "assisted_support_grant_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "grant_id", sa.Uuid(),
            sa.ForeignKey("assisted_support_grants.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_label", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    for coluna in ("tenant_id", "grant_id", "event_type", "actor_id", "occurred_at"):
        op.create_index(
            f"ix_assisted_support_grant_events_{coluna}",
            "assisted_support_grant_events", [coluna],
        )

    op.execute('ALTER TABLE "assisted_support_grant_events" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "assisted_support_grant_events" FORCE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY assisted_support_grant_events_platform
        ON assisted_support_grant_events FOR ALL
        USING (nullif(current_setting('app.platform_access', true), '') = 'true')
        WITH CHECK (nullif(current_setting('app.platform_access', true), '') = 'true')
        """
    )
    # O tenant lê o histórico dos acessos aos dados dele, e escreve as próprias
    # decisões. Ler é o que a tela promete; escrever é aprovar e revogar.
    op.execute(
        """
        CREATE POLICY assisted_support_grant_events_tenant_reads
        ON assisted_support_grant_events FOR SELECT
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY assisted_support_grant_events_tenant_writes
        ON assisted_support_grant_events FOR INSERT
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    # --- o que já estava gravado vira linha ---------------------------------
    # Sem isto, o histórico começaria vazio para toda concessão existente, e a
    # migração que existe para preservar histórico teria apagado o que havia.
    op.execute(
        """
        INSERT INTO assisted_support_grant_events
          (id, tenant_id, grant_id, event_type, actor_id, actor_label, reason, occurred_at)
        SELECT gen_random_uuid(), g.tenant_id, g.id, 'REQUESTED', g.requested_by,
               u.full_name, g.reason, g.created_at
        FROM assisted_support_grants g
        LEFT JOIN users u ON u.id = g.requested_by
        """
    )
    op.execute(
        """
        INSERT INTO assisted_support_grant_events
          (id, tenant_id, grant_id, event_type, actor_id, actor_label, reason, occurred_at)
        SELECT gen_random_uuid(), g.tenant_id, g.id, 'APPROVED', g.approved_by,
               u.full_name, NULL, g.approved_at
        FROM assisted_support_grants g
        LEFT JOIN users u ON u.id = g.approved_by
        WHERE g.approved_at IS NOT NULL
        """
    )
    op.execute(
        f"""
        INSERT INTO assisted_support_grant_events
          (id, tenant_id, grant_id, event_type, actor_id, actor_label, reason, occurred_at)
        SELECT gen_random_uuid(), g.tenant_id, g.id, 'INVALIDATED', NULL, NULL,
               coalesce(g.invalidated_reason, '{MOTIVO_DA_INVALIDACAO}'), g.invalidated_at
        FROM assisted_support_grants g
        WHERE g.invalidated_at IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO assisted_support_grant_events
          (id, tenant_id, grant_id, event_type, actor_id, actor_label, reason, occurred_at)
        SELECT gen_random_uuid(), g.tenant_id, g.id, 'REVOKED', g.revoked_by,
               u.full_name, NULL, g.revoked_at
        FROM assisted_support_grants g
        LEFT JOIN users u ON u.id = g.revoked_by
        WHERE g.revoked_at IS NOT NULL
        """
    )


def downgrade() -> None:
    for politica in (
        "assisted_support_grant_events_tenant_writes",
        "assisted_support_grant_events_tenant_reads",
        "assisted_support_grant_events_platform",
    ):
        op.execute(f"DROP POLICY IF EXISTS {politica} ON assisted_support_grant_events")
    op.drop_table("assisted_support_grant_events")
