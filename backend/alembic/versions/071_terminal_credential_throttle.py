"""The terminal counts credential failures, not only the credential.

Until this revision the only throttle on shift assumption lived on the
credential itself. A code that resolves to nobody left before the counter was
touched, so sweeping employee codes on an authorized terminal was unlimited:
the attacker never had to guess a PIN to keep guessing codes.

The counter therefore also belongs to the device, which is the one thing every
attempt shares regardless of which identity was typed.

Revision ID: 071_terminal_credential_throttle
Revises: 070_assortment_business_activity
Create Date: 2026-09-03 21:40:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "071_terminal_credential_throttle"
down_revision: Union[str, None] = "070_assortment_business_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operational_devices",
        sa.Column("auth_failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "operational_devices",
        sa.Column("auth_last_failed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "operational_devices",
        sa.Column("auth_locked_until", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_operational_devices_auth_locked_until",
        "operational_devices",
        ["auth_locked_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_operational_devices_auth_locked_until", table_name="operational_devices")
    op.drop_column("operational_devices", "auth_locked_until")
    op.drop_column("operational_devices", "auth_last_failed_at")
    op.drop_column("operational_devices", "auth_failed_attempts")
