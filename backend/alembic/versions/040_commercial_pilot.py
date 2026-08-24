"""Persist commercial pilot scope, observations and incident gates.

Revision ID: 040_commercial_pilot
Revises: 039_operational_hardening
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "040_commercial_pilot"
down_revision = "039_operational_hardening"
branch_labels = None
depends_on = None


def _index(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "commercial_pilots",
        sa.Column("id", uid, nullable=False), sa.Column("tenant_id", uid, nullable=False),
        sa.Column("store_id", uid, nullable=False), sa.Column("hardening_run_id", uid, nullable=False),
        sa.Column("status", sa.String(40), nullable=False), sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("created_by", uid, nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("field_started_at", sa.DateTime(), nullable=True), sa.Column("field_completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]), sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["hardening_run_id"], ["operational_hardening_runs.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    _index("commercial_pilots", "tenant_id", "store_id", "hardening_run_id", "status", "created_by", "created_at")
    op.create_table(
        "pilot_observations",
        sa.Column("id", uid, nullable=False), sa.Column("pilot_id", uid, nullable=False),
        sa.Column("task_type", sa.String(60), nullable=False), sa.Column("source_ref", sa.String(180), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False), sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("observed_by", uid, nullable=False), sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pilot_id"], ["commercial_pilots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["observed_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pilot_id", "source_ref", name="uq_pilot_observation_source"),
    )
    _index("pilot_observations", "pilot_id", "task_type", "observed_by", "observed_at")
    op.create_table(
        "pilot_incident_gates",
        sa.Column("id", uid, nullable=False), sa.Column("pilot_id", uid, nullable=False),
        sa.Column("incident_id", uid, nullable=False), sa.Column("blocks_expansion", sa.Boolean(), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False), sa.Column("decided_by", uid, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pilot_id"], ["commercial_pilots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["incident_id"], ["platform_incidents.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pilot_id", "incident_id", name="uq_pilot_incident_gate"),
    )
    _index("pilot_incident_gates", "pilot_id", "incident_id", "blocks_expansion", "decided_by", "created_at")
    for table in ("commercial_pilots", "pilot_observations", "pilot_incident_gates"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_platform_only ON {table} FOR ALL USING (current_setting('app.platform_access', true) = 'true') WITH CHECK (current_setting('app.platform_access', true) = 'true')")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def downgrade() -> None:
    op.drop_table("pilot_incident_gates")
    op.drop_table("pilot_observations")
    op.drop_table("commercial_pilots")
