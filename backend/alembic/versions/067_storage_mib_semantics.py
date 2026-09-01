"""Make binary storage units explicit in the commercial catalog.

Revision ID: 067_storage_mib
Revises: 066_published_event_stream
"""

from alembic import op


revision = "067_storage_mib"
down_revision = "066_published_event_stream"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "service_plans",
        "storage_limit_mb",
        new_column_name="storage_limit_mib",
    )
    op.alter_column(
        "service_plan_revisions",
        "storage_limit_mb",
        new_column_name="storage_limit_mib",
    )


def downgrade() -> None:
    op.alter_column(
        "service_plan_revisions",
        "storage_limit_mib",
        new_column_name="storage_limit_mb",
    )
    op.alter_column(
        "service_plans",
        "storage_limit_mib",
        new_column_name="storage_limit_mb",
    )
