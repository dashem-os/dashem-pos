"""Pin search paths for database trigger functions.

Revision ID: 053_secure_function_paths
Revises: 052_saas_invoicing
"""

from alembic import op


revision = "053_secure_function_paths"
down_revision = "052_saas_invoicing"
branch_labels = None
depends_on = None


FUNCTIONS = (
    "public.dashem_reject_immutable_mutation()",
    "public.protect_issued_saas_invoice_snapshot()",
    "public.protect_issued_saas_invoice_line()",
)


def upgrade() -> None:
    for function in FUNCTIONS:
        op.execute(
            f"ALTER FUNCTION {function} SET search_path = pg_catalog, public"
        )


def downgrade() -> None:
    for function in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} RESET search_path")
