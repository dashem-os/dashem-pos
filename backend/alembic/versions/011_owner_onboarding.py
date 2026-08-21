"""Platform Owner first-access state.

Revision ID: 011_owner_onboarding
Revises: 010_supabase_auth_rbac
Create Date: 2026-08-21 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011_owner_onboarding"
down_revision: Union[str, None] = "010_supabase_auth_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_setup_completed_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed_at")
    op.drop_column("users", "password_setup_completed_at")
