"""Add provider-backed storage measurements and fail-closed reservations.

Revision ID: 064_storage_metering
Revises: 063_commercial_requests
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "064_storage_metering"
down_revision = "063_commercial_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_meter_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("locator_reference", sa.String(240), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_storage_meter_source_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_key", name="uq_storage_meter_source_tenant_key"),
    )
    for column in ("tenant_id", "source_key", "provider", "status", "created_by", "created_at"):
        op.create_index(f"ix_storage_meter_sources_{column}", "storage_meter_sources", [column])

    op.create_table(
        "storage_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=True),
        sa.Column("object_count", sa.Integer(), nullable=True),
        sa.Column("source_keys", sa.JSON(), nullable=False),
        sa.Column("watermark", sa.String(240), nullable=False),
        sa.Column("source_fingerprint", sa.String(128), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PARTIAL', 'RECONCILED', 'DIVERGENT', 'UNAVAILABLE')",
            name="ck_storage_measurement_status",
        ),
        sa.CheckConstraint("used_bytes IS NULL OR used_bytes >= 0", name="ck_storage_measurement_used_bytes"),
        sa.CheckConstraint("object_count IS NULL OR object_count >= 0", name="ck_storage_measurement_object_count"),
        sa.CheckConstraint(
            "status <> 'RECONCILED' OR (used_bytes IS NOT NULL AND object_count IS NOT NULL)",
            name="ck_storage_measurement_reconciled_values",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_fingerprint", name="uq_storage_measurement_fingerprint"),
    )
    for column in ("tenant_id", "status", "source_fingerprint", "measured_at", "recorded_by", "recorded_at"):
        op.create_index(f"ix_storage_measurements_{column}", "storage_measurements", [column])

    op.create_table(
        "storage_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_key", sa.String(160), nullable=False),
        sa.Column("requested_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("measurement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("final_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("requested_bytes > 0", name="ck_storage_reservation_requested_bytes"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'COMMITTED', 'RELEASED', 'EXPIRED')",
            name="ck_storage_reservation_status",
        ),
        sa.CheckConstraint("contract_version >= 1", name="ck_storage_reservation_contract_version"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["contract_id"], ["tenant_contracts.id"]),
        sa.ForeignKeyConstraint(["measurement_id"], ["storage_measurements.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "operation_key", name="uq_storage_reservation_operation"),
    )
    for column in (
        "tenant_id", "status", "contract_id", "measurement_id", "created_by",
        "expires_at", "created_at", "finalized_at",
    ):
        op.create_index(f"ix_storage_reservations_{column}", "storage_reservations", [column])

    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    author = "created_by = nullif(current_setting('app.user_id', true), '')::uuid"
    platform = "current_setting('app.platform_access', true) = 'true'"
    for table in ("storage_meter_sources", "storage_measurements", "storage_reservations"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_platform_all ON {table} FOR ALL "
            f"USING ({platform}) WITH CHECK ({platform})"
        )
        op.execute(f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT USING ({tenant})")
    op.execute(
        "CREATE POLICY storage_reservations_tenant_insert ON storage_reservations "
        f"FOR INSERT WITH CHECK ({tenant} AND {author} AND status = 'ACTIVE')"
    )
    op.execute(
        "CREATE POLICY storage_reservations_tenant_update ON storage_reservations "
        f"FOR UPDATE USING ({tenant}) WITH CHECK ({tenant})"
    )
    op.execute(
        "CREATE TRIGGER storage_measurements_immutable BEFORE UPDATE OR DELETE ON storage_measurements "
        "FOR EACH ROW EXECUTE FUNCTION dashem_reject_immutable_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_storage_reservation() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'storage reservations cannot be deleted';
            END IF;
            IF NEW.tenant_id <> OLD.tenant_id
               OR NEW.operation_key <> OLD.operation_key
               OR NEW.requested_bytes <> OLD.requested_bytes
               OR NEW.contract_id <> OLD.contract_id
               OR NEW.contract_version <> OLD.contract_version
               OR NEW.measurement_id <> OLD.measurement_id
               OR NEW.created_by <> OLD.created_by
               OR NEW.expires_at <> OLD.expires_at
               OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'storage reservation authority fields are immutable';
            END IF;
            IF OLD.status <> 'ACTIVE'
               OR NEW.status NOT IN ('COMMITTED', 'RELEASED', 'EXPIRED') THEN
                RAISE EXCEPTION 'invalid storage reservation state transition';
            END IF;
            IF NEW.finalized_at IS NULL OR NEW.final_reason IS NULL OR length(trim(NEW.final_reason)) < 4 THEN
                RAISE EXCEPTION 'storage reservation finalization requires evidence';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER storage_reservations_guard BEFORE UPDATE OR DELETE ON storage_reservations "
        "FOR EACH ROW EXECUTE FUNCTION protect_storage_reservation()"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON storage_meter_sources TO dashem_runtime")
    op.execute("GRANT SELECT, INSERT ON storage_measurements TO dashem_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE ON storage_reservations TO dashem_runtime")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS storage_reservations_guard ON storage_reservations")
    op.execute("DROP FUNCTION IF EXISTS protect_storage_reservation()")
    op.execute("DROP TRIGGER IF EXISTS storage_measurements_immutable ON storage_measurements")
    op.drop_table("storage_reservations")
    op.drop_table("storage_measurements")
    op.drop_table("storage_meter_sources")
