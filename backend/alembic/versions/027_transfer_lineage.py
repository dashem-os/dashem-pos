"""S12 immutable transfer lineage.
Revision ID: 027_transfer_lineage
Revises: 026_production_routing_kds
"""
from datetime import datetime
from typing import Sequence,Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="027_transfer_lineage";down_revision="026_production_routing_kds";branch_labels=None;depends_on=None
def upgrade()->None:
    uid=postgresql.UUID(as_uuid=True);now=datetime.utcnow()
    op.create_table("transfer_records",
      sa.Column("id",uid,primary_key=True),sa.Column("tenant_id",uid,sa.ForeignKey("tenants.id"),nullable=False),sa.Column("store_id",uid,sa.ForeignKey("stores.id"),nullable=False),
      sa.Column("transfer_type",sa.String(50),nullable=False),sa.Column("source_session_id",uid,sa.ForeignKey("table_sessions.id"),nullable=False),sa.Column("destination_session_id",uid,sa.ForeignKey("table_sessions.id"),nullable=False),
      sa.Column("source_order_id",uid,sa.ForeignKey("orders.id")),sa.Column("destination_order_id",uid,sa.ForeignKey("orders.id")),sa.Column("source_order_item_id",uid,sa.ForeignKey("order_items.id")),sa.Column("derived_order_item_id",uid,sa.ForeignKey("order_items.id")),
      sa.Column("quantity",sa.Numeric(14,4)),sa.Column("unit_price_snapshot",sa.Numeric(14,4)),sa.Column("source_version_before",sa.Integer(),nullable=False),sa.Column("destination_version_before",sa.Integer(),nullable=False),
      sa.Column("actor_id",uid,nullable=False),sa.Column("reason",sa.Text(),nullable=False),sa.Column("production_compensation_required",sa.Boolean(),nullable=False),sa.Column("idempotency_key",sa.String(160),nullable=False),sa.Column("request_hash",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(),nullable=False),
      sa.UniqueConstraint("tenant_id","idempotency_key",name="uq_tenant_transfer_key"))
    for c in ("tenant_id","store_id","transfer_type","source_session_id","destination_session_id","source_order_id","destination_order_id","source_order_item_id","derived_order_item_id","actor_id","production_compensation_required","idempotency_key","created_at"):op.create_index(f"ix_transfer_records_{c}","transfer_records",[c])
    permissions=sa.table("permissions",sa.column("key",sa.String),sa.column("name",sa.String),sa.column("description",sa.Text),sa.column("capability_key",sa.String),sa.column("created_at",sa.DateTime))
    op.bulk_insert(permissions,[{"key":"transfer.read","name":"Consultar transferências","description":"Consultar linhagem","capability_key":"table_service","created_at":now},{"key":"transfer.execute","name":"Executar transferências","description":"Mover itens e sessões","capability_key":"table_service","created_at":now}])
    op.execute(sa.text("""INSERT INTO role_profile_permissions(id,role_profile_id,permission_key) SELECT gen_random_uuid(),rp.id,p.key FROM role_profiles rp CROSS JOIN permissions p WHERE rp.is_system=true AND p.key IN('transfer.read','transfer.execute') AND rp.code IN('OWNER','TENANT_OWNER','ADMIN','MANAGER','CASHIER','OPERATOR')"""))
    op.execute("ALTER TABLE transfer_records ENABLE ROW LEVEL SECURITY");op.execute("ALTER TABLE transfer_records FORCE ROW LEVEL SECURITY")
    exp="(current_setting('app.platform_access', true) = 'true') OR ((tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR store_id = nullif(current_setting('app.store_id', true), '')::uuid))"
    op.execute(f"CREATE POLICY transfer_records_isolation ON transfer_records FOR ALL USING ({exp}) WITH CHECK ({exp})")
def downgrade()->None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key LIKE 'transfer.%'");op.execute("DELETE FROM permissions WHERE key LIKE 'transfer.%'");op.drop_table("transfer_records")
