"""Quem fornece a mercadoria passa a existir.

O inventário da UX-09 não achou nada: nem tabela, nem rota, nem tela. A pergunta
"de quem veio esta mercadoria?" não tinha onde ser respondida, e o card de
Fornecedores era um destino ausente no mapa das sete áreas.

Esta migração cria três coisas e nada além:

* **`suppliers`** — quem fornece, com documento opcional e único quando existe;
* **`supplier_contacts`** — com quem se fala lá dentro, porque um fornecedor tem
  o vendedor, o financeiro e quem entrega, e guardar um telefone só obriga a
  escolher qual deles cabe;
* **`inventory_movements.supplier_id`** — o vínculo do recebimento, que é a
  resposta da pergunta acima.

**Não há pedido de compra.** O enunciado proíbe inventá-lo como entregue, e
nenhuma coluna aqui finge que ele existe.

As duas permissões nascem junto, e o card só entra na malha porque a API e a
tela vêm no mesmo commit — ativar destino antes de existir jornada é o botão
morto que o contrato de navegação proíbe.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "092_who_supplies_the_goods"
down_revision: Union[str, None] = "091_permission_needs_presence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCOPE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR nullif(current_setting('app.platform_access', true), '') = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("document", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="ACTIVE"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "document", name="uq_tenant_supplier_document"),
    )
    op.create_index("ix_suppliers_tenant_id", "suppliers", ["tenant_id"])
    op.create_index("ix_suppliers_name", "suppliers", ["name"])
    op.create_index("ix_suppliers_document", "suppliers", ["document"])
    op.create_index("ix_suppliers_status", "suppliers", ["status"])

    op.create_table(
        "supplier_contacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_supplier_contacts_tenant_id", "supplier_contacts", ["tenant_id"])
    op.create_index("ix_supplier_contacts_supplier_id", "supplier_contacts", ["supplier_id"])
    op.create_index("ix_supplier_contacts_is_primary", "supplier_contacts", ["is_primary"])

    for tabela in ("suppliers", "supplier_contacts"):
        op.execute(f'ALTER TABLE "{tabela}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{tabela}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY dashem_tenant_isolation ON "{tabela}" FOR ALL '
            f"USING ({SCOPE}) WITH CHECK ({SCOPE})"
        )

    # O vínculo do recebimento: de quem veio esta mercadoria.
    op.add_column(
        "inventory_movements",
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id"), nullable=True),
    )
    op.create_index("ix_inventory_movements_supplier_id", "inventory_movements", ["supplier_id"])

    op.execute(
        """
        INSERT INTO permissions (key, name, description, created_at)
        VALUES
          ('supplier.read', 'Ver fornecedores', 'Consultar quem fornece as mercadorias', now()),
          ('supplier.manage', 'Cadastrar fornecedores', 'Cadastrar e editar fornecedores e seus contatos', now())
        ON CONFLICT (key) DO NOTHING
        """
    )
    # Quem já administra o tenant administra fornecedores; quem opera o caixa
    # não precisa disso para vender.
    op.execute(
        """
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp
        CROSS JOIN (VALUES ('supplier.read'), ('supplier.manage')) AS p(key)
        WHERE rp.is_system AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER')
        ON CONFLICT ON CONSTRAINT uq_role_profile_permission DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO module_contributions
          (id, capability_key, surface, contribution_key, label, group_key, route,
           permission_key, implementation_key, sort_order, metadata_json, is_active)
        VALUES (
          gen_random_uuid(), NULL, 'MANAGEMENT_NAV', 'suppliers', 'Fornecedores',
          'RELACIONAMENTO', '/manage/suppliers', 'supplier.read', 'suppliers', 87,
          '{"area": {"key": "RELACIONAMENTO", "label": "Relacionamento", "order": 5},
            "description": "Organize quem fornece suas mercadorias."}',
          true
        )
        ON CONFLICT ON CONSTRAINT uq_module_contribution_surface_key DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM module_contributions WHERE contribution_key = 'suppliers' AND surface = 'MANAGEMENT_NAV'")
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key IN ('supplier.read', 'supplier.manage')")
    op.drop_index("ix_inventory_movements_supplier_id", table_name="inventory_movements")
    op.drop_column("inventory_movements", "supplier_id")
    for tabela in ("supplier_contacts", "suppliers"):
        op.execute(f'DROP POLICY IF EXISTS dashem_tenant_isolation ON "{tabela}"')
    op.drop_table("supplier_contacts")
    op.drop_table("suppliers")
    op.execute("DELETE FROM permissions WHERE key IN ('supplier.read', 'supplier.manage')")
