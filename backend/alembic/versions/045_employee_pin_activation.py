"""Make the operational PIN an employee-controlled secret.

Revision ID: 045_employee_pin_activation
Revises: 044_gate_d_audit
"""

from alembic import op
import sqlalchemy as sa


revision = "045_employee_pin_activation"
down_revision = "044_gate_d_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("operational_credentials", "pin_salt", existing_type=sa.String(length=64), nullable=True)
    op.alter_column("operational_credentials", "pin_hash", existing_type=sa.String(length=128), nullable=True)
    op.add_column("operational_credentials", sa.Column("activation_secret_hash", sa.String(length=64), nullable=True))
    op.add_column("operational_credentials", sa.Column("activation_expires_at", sa.DateTime(), nullable=True))
    op.add_column(
        "operational_credentials",
        sa.Column("activation_failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("operational_credentials", sa.Column("pin_activated_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE operational_credentials SET pin_activated_at = COALESCE(updated_at, created_at, now()) WHERE pin_hash IS NOT NULL")
    op.create_index(
        "ix_operational_credentials_activation_expires_at",
        "operational_credentials", ["activation_expires_at"],
    )
    op.create_index(
        "ix_operational_credentials_pin_activated_at",
        "operational_credentials", ["pin_activated_at"],
    )


def downgrade() -> None:
    # Pending credentials cannot exist in the legacy schema. Downgrade keeps
    # only credentials that already have a personal PIN.
    op.execute("DELETE FROM operational_credentials WHERE pin_hash IS NULL OR pin_salt IS NULL")
    op.drop_index("ix_operational_credentials_pin_activated_at", table_name="operational_credentials")
    op.drop_index("ix_operational_credentials_activation_expires_at", table_name="operational_credentials")
    op.drop_column("operational_credentials", "pin_activated_at")
    op.drop_column("operational_credentials", "activation_failed_attempts")
    op.drop_column("operational_credentials", "activation_expires_at")
    op.drop_column("operational_credentials", "activation_secret_hash")
    op.alter_column("operational_credentials", "pin_hash", existing_type=sa.String(length=128), nullable=False)
    op.alter_column("operational_credentials", "pin_salt", existing_type=sa.String(length=64), nullable=False)
