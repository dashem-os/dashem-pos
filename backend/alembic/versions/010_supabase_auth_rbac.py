"""Supabase identity mapping and credential separation.

Revision ID: 010_supabase_auth_rbac
Revises: 009_platform_foundation
Create Date: 2026-08-21 20:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_supabase_auth_rbac"
down_revision: Union[str, None] = "009_platform_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=True)
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_subject", sa.String(), nullable=False),
        sa.Column("provider_email", sa.String(), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_auth_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_auth_provider"),
    )
    op.create_index(op.f("ix_auth_identities_user_id"), "auth_identities", ["user_id"])
    op.create_index(op.f("ix_auth_identities_provider"), "auth_identities", ["provider"])
    op.create_index(op.f("ix_auth_identities_provider_subject"), "auth_identities", ["provider_subject"])
    op.create_index(op.f("ix_auth_identities_provider_email"), "auth_identities", ["provider_email"])

    # Prototype tenants existed before lifecycle states were introduced.
    op.execute("UPDATE tenants SET status = 'ACTIVE' WHERE status = 'PROVISIONING'")


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_identities_provider_email"), table_name="auth_identities")
    op.drop_index(op.f("ix_auth_identities_provider_subject"), table_name="auth_identities")
    op.drop_index(op.f("ix_auth_identities_provider"), table_name="auth_identities")
    op.drop_index(op.f("ix_auth_identities_user_id"), table_name="auth_identities")
    op.drop_table("auth_identities")
    op.execute("UPDATE users SET password_hash = '' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=False)
