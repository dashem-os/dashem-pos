"""Persist operational hardening runs and evidence.

Revision ID: 039_operational_hardening
Revises: 038_capability_profiles
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "039_operational_hardening"
down_revision = "038_capability_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "operational_hardening_runs",
        sa.Column("id", uid, nullable=False),
        sa.Column("release_sha", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("rpo_target_minutes", sa.Integer(), nullable=False),
        sa.Column("rto_target_minutes", sa.Integer(), nullable=False),
        sa.Column("initiated_by", uid, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("rpo_target_minutes >= 0", name="ck_hardening_rpo_nonnegative"),
        sa.CheckConstraint("rto_target_minutes >= 1", name="ck_hardening_rto_positive"),
    )
    for column in ("release_sha", "environment", "status", "initiated_by", "started_at"):
        op.create_index(f"ix_operational_hardening_runs_{column}", "operational_hardening_runs", [column])
    op.create_table(
        "operational_hardening_evidence",
        sa.Column("id", uid, nullable=False),
        sa.Column("run_id", uid, nullable=False),
        sa.Column("check_key", sa.String(80), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("evidence_ref", sa.String(500), nullable=False),
        sa.Column("observed", sa.JSON(), nullable=False),
        sa.Column("recorded_by", uid, nullable=False),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["operational_hardening_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "check_key", name="uq_operational_hardening_evidence_check"),
    )
    for column in ("run_id", "check_key", "category", "status", "recorded_by", "measured_at"):
        op.create_index(f"ix_operational_hardening_evidence_{column}", "operational_hardening_evidence", [column])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON operational_hardening_runs, operational_hardening_evidence TO dashem_runtime")


def downgrade() -> None:
    op.drop_table("operational_hardening_evidence")
    op.drop_table("operational_hardening_runs")
