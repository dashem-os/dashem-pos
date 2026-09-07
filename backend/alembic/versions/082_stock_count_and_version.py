"""Contar estoque: versão do saldo, registro da conferência e ajuste técnico restrito.

Contar estoque é a operação cotidiana: a pessoa informa **o total encontrado** e
o servidor calcula a diferença. Para isso a contagem precisa saber se o saldo
mudou entre a leitura e a confirmação — se uma venda entrou no meio, aceitar a
contagem apagaria essa venda do estoque.

Três coisas entram aqui:

* `inventory_balances.version`, incrementada por **toda** movimentação — venda,
  entrada, perda, devolução e ajuste. Uma versão que só algumas operações movem
  é uma proteção com buraco;
* `inventory_counts`, porque a conferência é fato mesmo quando não há diferença.
  Contar e encontrar exatamente o saldo é informação — significa que alguém
  olhou a prateleira naquele dia — e não pode virar movimento inventado;
* as permissões que separam as três autoridades. `ADJUSTMENT` era chamado de
  "operação técnica restrita" na documentação e estava aberto a quem pudesse
  movimentar estoque; documentação não restringe acesso. Ele passa a ter rota e
  permissão próprias.

`inventory.count` vai para quem já movimentava estoque. `inventory.adjust.technical`
não: lançar diferença assinada à mão contorna a conferência, e é autoridade de
administração, não de operação de loja.
"""

from datetime import datetime
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "082_stock_count_and_version"
down_revision: Union[str, None] = "081_plan_revision_no_nfce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCOPE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR nullif(current_setting('app.platform_access', true), '') = 'true'"
)

NEW_PERMISSIONS = (
    ("inventory.count", "Contar estoque", "inventory"),
    ("inventory.adjust.technical", "Lançar ajuste técnico de estoque", "inventory"),
)

# Quem conta é quem opera a loja. Quem lança diferença assinada à mão responde
# pela administração do tenant: essa operação passa por cima da conferência.
COUNT_ROLES = ("OWNER", "TENANT_OWNER", "ADMIN", "MANAGER")
TECHNICAL_ROLES = ("OWNER", "TENANT_OWNER", "ADMIN")


def _profile_id(code: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"https://dashem.com/role-profile/{code}")


def upgrade() -> None:
    # 1. A versão do saldo. Começa em 1 para toda linha existente: ninguém tem
    # contagem em curso agora, então não há expectativa a preservar.
    op.add_column(
        "inventory_balances",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    # 2. A conferência como fato próprio.
    op.create_table(
        "inventory_counts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        # O que a pessoa encontrou, o que o sistema tinha, e o que isso implicou.
        sa.Column("counted_quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("previous_balance", sa.Numeric(14, 4), nullable=False),
        sa.Column("difference", sa.Numeric(14, 4), nullable=False),
        # Nulo quando a contagem bateu com o saldo: conferência sem movimento.
        sa.Column("movement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("balance_version_before", sa.Integer(), nullable=False),
        sa.Column("balance_version_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        # Unicidade sozinha não distingue reenvio de reaproveitamento: ela deixa
        # a mesma chave devolver o resultado de outra contagem. O hash do comando
        # é o que separa "é o mesmo pedido" de "é outro pedido com a chave usada".
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["movement_id"], ["inventory_movements.id"]),
        # A guarda durável contra reenvio: repetir a confirmação não registra
        # outra diferença, mesmo que o cache de idempotência já tenha expirado.
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_count_idempotency"),
    )
    op.create_index("ix_inventory_counts_tenant_id", "inventory_counts", ["tenant_id"])
    op.create_index("ix_inventory_counts_store_id", "inventory_counts", ["store_id"])
    op.create_index("ix_inventory_counts_product_id", "inventory_counts", ["product_id"])
    op.execute('ALTER TABLE "inventory_counts" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "inventory_counts" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY dashem_tenant_isolation ON "inventory_counts" FOR ALL '
        f"USING ({SCOPE}) WITH CHECK ({SCOPE})"
    )

    # 3. As permissões que tornam a restrição real.
    now = datetime.utcnow()
    permission_table = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(permission_table, [
        {"key": key, "name": name, "description": name,
         "capability_key": capability, "created_at": now}
        for key, name, capability in NEW_PERMISSIONS
    ])
    grants = sa.table(
        "role_profile_permissions", sa.column("id", postgresql.UUID),
        sa.column("role_profile_id", postgresql.UUID),
        sa.column("permission_key", sa.String),
    )
    op.bulk_insert(grants, [
        {"id": uuid.uuid4(), "role_profile_id": _profile_id(role),
         "permission_key": "inventory.count"}
        for role in COUNT_ROLES
    ] + [
        {"id": uuid.uuid4(), "role_profile_id": _profile_id(role),
         "permission_key": "inventory.adjust.technical"}
        for role in TECHNICAL_ROLES
    ])


def downgrade() -> None:
    # Só o que esta migração criou.
    op.execute(
        "DELETE FROM role_profile_permissions WHERE permission_key IN "
        "('inventory.count', 'inventory.adjust.technical')"
    )
    op.execute(
        "DELETE FROM permissions WHERE key IN "
        "('inventory.count', 'inventory.adjust.technical')"
    )
    op.execute('DROP POLICY IF EXISTS dashem_tenant_isolation ON "inventory_counts"')
    op.drop_index("ix_inventory_counts_product_id", table_name="inventory_counts")
    op.drop_index("ix_inventory_counts_store_id", table_name="inventory_counts")
    op.drop_index("ix_inventory_counts_tenant_id", table_name="inventory_counts")
    op.drop_table("inventory_counts")
    op.drop_column("inventory_balances", "version")
