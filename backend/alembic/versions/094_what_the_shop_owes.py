"""O que a loja deve passa a existir.

O inventário da UX-10 não achou nada de contas a pagar. Achou o espelho inteiro
— `receivables`, com razão, idempotência, `version` e estorno — e esta migração
segue a mesma gramática: um produto não precisa de duas formas de escrever
dinheiro.

Cria duas tabelas e nada além:

* **`payables`** — a obrigação: favorecido, vencimento, valor, saldo;
* **`payable_ledger_entries`** — a razão: lançar, baixar, ajustar, reverter.

**Nenhum gatilho.** Receber mercadoria não cria conta a pagar e dar baixa não
movimenta estoque — as duas direções, porque a segunda é a que costuma ser
esquecida. O elo é a coluna `supplier_id`, preenchida por quem lança.

`due_on` é `date`, não `timestamp`: vencimento é dia de calendário, e guardar
hora faria "vence hoje" depender do fuso de quem pergunta.

**Não há situação "vencida" gravada.** Ela é derivada de `due_on` contra hoje;
gravá-la exigiria um processo virando linhas à meia-noite, que não existe — e um
processo que não existe é como a lista fica mentindo por um dia inteiro.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "094_what_the_shop_owes"
down_revision: Union[str, None] = "093_one_primary_contact_only"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCOPE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR nullif(current_setting('app.platform_access', true), '') = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "payables",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id"), nullable=True),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id"), nullable=True),
        sa.Column("payee_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="OPEN"),
        sa.Column("principal_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("paid_amount", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("balance", sa.Numeric(14, 4), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("issue_idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "issue_idempotency_key", name="uq_tenant_payable_issue_key"),
        sa.CheckConstraint("principal_amount > 0", name="ck_payable_principal_positive"),
        sa.CheckConstraint("paid_amount >= 0", name="ck_payable_paid_nonnegative"),
        sa.CheckConstraint("balance >= 0", name="ck_payable_balance_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_payable_version_positive"),
    )
    for coluna in ("tenant_id", "store_id", "supplier_id", "payee_name", "status",
                   "due_on", "issued_at", "issue_idempotency_key", "archived_at",
                   "created_by", "created_at"):
        op.create_index(f"ix_payables_{coluna}", "payables", [coluna])

    op.create_table(
        "payable_ledger_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("payable_id", sa.Uuid(), sa.ForeignKey("payables.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entry_type", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("method", sa.String(length=60), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reverses_entry_id", sa.Uuid(),
                  sa.ForeignKey("payable_ledger_entries.id"), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_payable_ledger_key"),
        sa.CheckConstraint("amount <> 0", name="ck_payable_ledger_amount_nonzero"),
    )
    for coluna in ("tenant_id", "payable_id", "entry_type", "reverses_entry_id",
                   "occurred_on", "idempotency_key", "created_by", "created_at"):
        op.create_index(f"ix_payable_ledger_entries_{coluna}", "payable_ledger_entries", [coluna])

    # Uma baixa só pode ser desfeita uma vez. Sem isto, dois cliques em
    # "Reverter" devolveriam o saldo duas vezes, e a conta passaria a dever
    # mais do que devia — em silêncio, porque cada lançamento é válido sozinho.
    op.create_index(
        "uq_payable_reversal_once", "payable_ledger_entries", ["reverses_entry_id"],
        unique=True, postgresql_where=sa.text("reverses_entry_id IS NOT NULL"),
    )

    for tabela in ("payables", "payable_ledger_entries"):
        op.execute(f'ALTER TABLE "{tabela}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{tabela}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY dashem_tenant_isolation ON "{tabela}" FOR ALL '
            f"USING ({SCOPE}) WITH CHECK ({SCOPE})"
        )

    op.execute(
        """
        INSERT INTO permissions (key, name, description, created_at)
        VALUES
          ('payable.read', 'Ver contas a pagar', 'Consultar o que a loja deve e quando vence', now()),
          ('payable.manage', 'Lançar contas a pagar', 'Lançar, editar e arquivar contas', now()),
          ('payable.settle', 'Dar baixa em contas', 'Registrar o pagamento de uma conta', now()),
          ('payable.reverse', 'Reverter baixa', 'Desfazer um pagamento registrado por engano', now())
        ON CONFLICT (key) DO NOTHING
        """
    )
    # Reverter fica separado de dar baixa de propósito: quem registra o dia a
    # dia não precisa poder desfazer o de ontem. Por isso ele não entra em
    # MANAGER, que é o perfil de quem opera a loja.
    op.execute(
        """
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp
        CROSS JOIN (VALUES ('payable.read'), ('payable.manage'), ('payable.settle')) AS p(key)
        WHERE rp.is_system AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER')
        ON CONFLICT ON CONSTRAINT uq_role_profile_permission DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'payable.reverse'
        FROM role_profiles rp
        WHERE rp.is_system AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN')
        ON CONFLICT ON CONSTRAINT uq_role_profile_permission DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO module_contributions
          (id, capability_key, surface, contribution_key, label, group_key, route,
           permission_key, implementation_key, sort_order, metadata_json, is_active)
        VALUES (
          gen_random_uuid(), NULL, 'MANAGEMENT_NAV', 'payables', 'Contas a pagar',
          'FINANCEIRO', '/manage/payables', 'payable.read', 'payables', 62,
          '{"area": {"key": "FINANCEIRO", "label": "Financeiro", "order": 6},
            "description": "Acompanhe o que você deve e quando vence."}',
          true
        )
        ON CONFLICT ON CONSTRAINT uq_module_contribution_surface_key DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM module_contributions WHERE contribution_key = 'payables' AND surface = 'MANAGEMENT_NAV'")
    op.execute(
        "DELETE FROM role_profile_permissions WHERE permission_key IN "
        "('payable.read', 'payable.manage', 'payable.settle', 'payable.reverse')"
    )
    for tabela in ("payable_ledger_entries", "payables"):
        op.execute(f'DROP POLICY IF EXISTS dashem_tenant_isolation ON "{tabela}"')
    op.drop_table("payable_ledger_entries")
    op.drop_table("payables")
    op.execute(
        "DELETE FROM permissions WHERE key IN "
        "('payable.read', 'payable.manage', 'payable.settle', 'payable.reverse')"
    )
