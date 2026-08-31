"""Connect storage governance to Supabase inventory and shared capacity.

Revision ID: 065_supabase_storage
Revises: 064_storage_metering
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "065_supabase_storage"
down_revision = "064_storage_metering"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_provider_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
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
        sa.CheckConstraint("status IN ('RECONCILED', 'DIVERGENT', 'UNAVAILABLE')", name="ck_storage_provider_measurement_status"),
        sa.CheckConstraint("used_bytes IS NULL OR used_bytes >= 0", name="ck_storage_provider_used_bytes"),
        sa.CheckConstraint("object_count IS NULL OR object_count >= 0", name="ck_storage_provider_object_count"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "source_fingerprint", name="uq_storage_provider_measurement_fingerprint"),
    )
    for column in ("provider", "status", "source_fingerprint", "measured_at", "recorded_by", "recorded_at"):
        op.create_index(f"ix_storage_provider_measurements_{column}", "storage_provider_measurements", [column])
    op.add_column("storage_reservations", sa.Column("bucket_id", sa.String(80), nullable=True))
    op.add_column("storage_reservations", sa.Column("object_path", sa.String(500), nullable=True))
    op.add_column("storage_reservations", sa.Column("provider_reference", sa.String(500), nullable=True))
    op.execute("ALTER TABLE storage_provider_measurements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE storage_provider_measurements FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY storage_provider_measurements_read ON storage_provider_measurements FOR SELECT USING (true)")
    op.execute("CREATE POLICY storage_provider_measurements_platform_write ON storage_provider_measurements FOR INSERT WITH CHECK (current_setting('app.platform_access', true) = 'true')")
    op.execute("GRANT SELECT, INSERT ON storage_provider_measurements TO dashem_runtime")

    op.execute("""
      CREATE FUNCTION dashem_storage_reserved_after(p_reconciled_through timestamp)
      RETURNS bigint LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        SELECT COALESCE(sum(requested_bytes), 0)::bigint FROM storage_reservations
        WHERE (status = 'ACTIVE' AND expires_at > timezone('utc', now()))
           OR (status = 'COMMITTED' AND (finalized_at IS NULL OR finalized_at > p_reconciled_through))
      $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION dashem_storage_reserved_after(timestamp) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION dashem_storage_reserved_after(timestamp) TO dashem_runtime")

    op.execute("DROP TRIGGER storage_reservations_guard ON storage_reservations")
    op.execute("DROP FUNCTION protect_storage_reservation()")
    op.execute("""
      CREATE FUNCTION protect_storage_reservation() RETURNS trigger LANGUAGE plpgsql
      SET search_path = pg_catalog, public AS $$ BEGIN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'storage reservations cannot be deleted'; END IF;
        IF NEW.tenant_id <> OLD.tenant_id OR NEW.operation_key <> OLD.operation_key
           OR NEW.requested_bytes <> OLD.requested_bytes OR NEW.contract_id <> OLD.contract_id
           OR NEW.contract_version <> OLD.contract_version OR NEW.measurement_id <> OLD.measurement_id
           OR NEW.created_by <> OLD.created_by OR NEW.expires_at <> OLD.expires_at
           OR NEW.created_at <> OLD.created_at OR NEW.bucket_id IS DISTINCT FROM OLD.bucket_id
           OR NEW.object_path IS DISTINCT FROM OLD.object_path THEN
          RAISE EXCEPTION 'storage reservation authority fields are immutable';
        END IF;
        IF OLD.status <> 'ACTIVE' OR NEW.status NOT IN ('COMMITTED', 'RELEASED', 'EXPIRED') THEN
          RAISE EXCEPTION 'invalid storage reservation state transition';
        END IF;
        IF NEW.status <> 'COMMITTED' AND NEW.provider_reference IS NOT NULL THEN
          RAISE EXCEPTION 'only committed reservations may carry provider evidence';
        END IF;
        IF NEW.finalized_at IS NULL OR NEW.final_reason IS NULL OR length(trim(NEW.final_reason)) < 4 THEN
          RAISE EXCEPTION 'storage reservation finalization requires evidence';
        END IF;
        RETURN NEW;
      END; $$
    """)
    op.execute("CREATE TRIGGER storage_reservations_guard BEFORE UPDATE OR DELETE ON storage_reservations FOR EACH ROW EXECUTE FUNCTION protect_storage_reservation()")


def downgrade() -> None:
    op.execute("DROP TRIGGER storage_reservations_guard ON storage_reservations")
    op.execute("DROP FUNCTION protect_storage_reservation()")
    op.execute("DROP FUNCTION dashem_storage_reserved_after(timestamp)")
    op.execute("""
      CREATE FUNCTION protect_storage_reservation() RETURNS trigger LANGUAGE plpgsql
      SET search_path = pg_catalog, public AS $$ BEGIN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'storage reservations cannot be deleted'; END IF;
        IF NEW.tenant_id <> OLD.tenant_id OR NEW.operation_key <> OLD.operation_key
           OR NEW.requested_bytes <> OLD.requested_bytes OR NEW.contract_id <> OLD.contract_id
           OR NEW.contract_version <> OLD.contract_version OR NEW.measurement_id <> OLD.measurement_id
           OR NEW.created_by <> OLD.created_by OR NEW.expires_at <> OLD.expires_at
           OR NEW.created_at <> OLD.created_at THEN
          RAISE EXCEPTION 'storage reservation authority fields are immutable';
        END IF;
        IF OLD.status <> 'ACTIVE' OR NEW.status NOT IN ('COMMITTED', 'RELEASED', 'EXPIRED') THEN
          RAISE EXCEPTION 'invalid storage reservation state transition';
        END IF;
        IF NEW.finalized_at IS NULL OR NEW.final_reason IS NULL OR length(trim(NEW.final_reason)) < 4 THEN
          RAISE EXCEPTION 'storage reservation finalization requires evidence';
        END IF;
        RETURN NEW;
      END; $$
    """)
    op.execute("CREATE TRIGGER storage_reservations_guard BEFORE UPDATE OR DELETE ON storage_reservations FOR EACH ROW EXECUTE FUNCTION protect_storage_reservation()")
    op.drop_column("storage_reservations", "provider_reference")
    op.drop_column("storage_reservations", "object_path")
    op.drop_column("storage_reservations", "bucket_id")
    op.drop_table("storage_provider_measurements")
