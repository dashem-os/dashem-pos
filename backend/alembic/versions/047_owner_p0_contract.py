"""Owner P0 niche, quota and entitlement contract.

Revision ID: 047_owner_p0_contract
Revises: 046_operational_role_alignment
"""

from alembic import op
import sqlalchemy as sa


revision = "047_owner_p0_contract"
down_revision = "046_operational_role_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_plans", sa.Column("storage_limit_mb", sa.Integer(), nullable=True))

    profiles = {
        "10000000-0000-0000-0000-000000000011": (
            "FOOD_SERVICE", "Food Service", [
                "catalog", "customer", "cash_management", "payments", "counter_order", "delivery_orders",
            ],
        ),
        "10000000-0000-0000-0000-000000000012": (
            "RETAIL", "Retail", [
                "catalog", "inventory", "customer", "cash_management", "payments",
                "barcode_scanning", "counter_order", "delivery_orders",
            ],
        ),
        "10000000-0000-0000-0000-000000000013": (
            "BEAUTY_RESELLER", "Beauty Reseller", [
                "catalog", "inventory", "customer", "cash_management", "payments", "delivery_orders",
            ],
        ),
    }
    for revision_id, (key, name, items) in profiles.items():
        op.execute(sa.text("""
            INSERT INTO capability_profile_revisions
                (id, profile_key, version, name, description, status, created_at)
            VALUES
                (:id, :key, '2.0.0', :name, :description, 'ACTIVE', now())
        """).bindparams(
            id=revision_id,
            key=key,
            name=name,
            description=f"Contrato base OWNER-P0 para {name}; add-ons são persistidos no contrato do tenant.",
        ))
        for capability in items:
            op.execute(sa.text("""
                INSERT INTO capability_profile_revision_items
                    (id, revision_id, capability_key, required, default_configuration)
                VALUES (gen_random_uuid(), :revision_id, :capability, true, '{}'::json)
            """).bindparams(revision_id=revision_id, capability=capability))


def downgrade() -> None:
    op.execute("DELETE FROM capability_profile_revision_items WHERE revision_id IN ('10000000-0000-0000-0000-000000000011', '10000000-0000-0000-0000-000000000012', '10000000-0000-0000-0000-000000000013')")
    op.execute("DELETE FROM capability_profile_revisions WHERE id IN ('10000000-0000-0000-0000-000000000011', '10000000-0000-0000-0000-000000000012', '10000000-0000-0000-0000-000000000013')")
    op.drop_column("service_plans", "storage_limit_mb")
