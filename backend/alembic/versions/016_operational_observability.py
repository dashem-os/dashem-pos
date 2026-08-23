"""Operational service heartbeat foundation.

Revision ID: 016_operational_observability
Revises: 015_owner_customer_master
Create Date: 2026-08-23 13:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016_operational_observability"
down_revision: Union[str, None] = "015_owner_customer_master"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_heartbeats",
        sa.Column("service_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="HEALTHY"),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("service_key"),
    )
    op.create_index("ix_service_heartbeats_status", "service_heartbeats", ["status"])
    op.create_index("ix_service_heartbeats_last_seen_at", "service_heartbeats", ["last_seen_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON service_heartbeats TO dashem_runtime")


def downgrade() -> None:
    op.drop_table("service_heartbeats")
