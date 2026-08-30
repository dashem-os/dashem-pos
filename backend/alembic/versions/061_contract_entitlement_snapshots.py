"""Materialize immutable canonical entitlement snapshots in contracts.

Revision ID: 061_contract_snapshots
Revises: 060_commercial_catalog
"""

from alembic import op
import sqlalchemy as sa


revision = "061_contract_snapshots"
down_revision = "060_commercial_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Capabilities that enrich an activity are selectable add-ons, not silent grants.
    # The operational core remains required for every contracted activity.
    op.execute(
        """
        UPDATE commercial_activity_capabilities
        SET role = 'OPTIONAL', default_selected = false
        WHERE (activity_key = 'FOOD_SERVICE' AND capability_key = 'delivery_orders')
           OR (activity_key = 'RETAIL' AND capability_key IN ('inventory', 'barcode_scanning', 'counter_order', 'delivery_orders'))
           OR (activity_key = 'BEAUTY_RESELLER' AND capability_key IN ('inventory', 'delivery_orders'))
        """
    )
    op.add_column(
        "tenant_contracts",
        sa.Column("activity_keys", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "tenant_contracts",
        sa.Column("capability_entitlements", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "tenant_contracts",
        sa.Column("limit_entitlements", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "tenant_contracts",
        sa.Column("storage_entitlement", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "tenant_contracts",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_tenant_contract_schema_version_positive",
        "tenant_contracts",
        "schema_version >= 1",
    )
    op.execute(
        """
        UPDATE tenant_contracts
        SET activity_keys = CASE
                WHEN json_typeof(limits->'business_niches') = 'array' THEN limits->'business_niches'
                WHEN NULLIF(limits->>'niche', '') IS NOT NULL THEN json_build_array(limits->>'niche')
                ELSE '[]'::json
            END,
            capability_entitlements = COALESCE((
                SELECT json_agg(json_build_object(
                    'key', cap.value,
                    'sources', json_build_array('LEGACY_MIGRATED'),
                    'activity_keys', CASE
                        WHEN json_typeof(tenant_contracts.limits->'business_niches') = 'array'
                            THEN tenant_contracts.limits->'business_niches'
                        WHEN NULLIF(tenant_contracts.limits->>'niche', '') IS NOT NULL
                            THEN json_build_array(tenant_contracts.limits->>'niche')
                        ELSE '[]'::json
                    END
                ) ORDER BY cap.value)
                FROM json_array_elements_text(tenant_contracts.capability_keys) AS cap(value)
            ), '[]'::json),
            limit_entitlements = json_build_object(
                'users', json_build_object('limit', limits->'users', 'sources', json_build_array('LEGACY_MIGRATED')),
                'devices', json_build_object('limit', limits->'devices', 'sources', json_build_array('LEGACY_MIGRATED')),
                'units', json_build_object('limit', limits->'units', 'sources', json_build_array('LEGACY_MIGRATED'))
            ),
            storage_entitlement = json_build_object(
                'limit_mb', limits->'storage_mb',
                'sources', json_build_array('LEGACY_MIGRATED'),
                'measurement_status', 'NOT_MEASURED'
            ),
            schema_version = 1
        """
    )
    op.execute(
        "CREATE TRIGGER tenant_contracts_immutable "
        "BEFORE UPDATE OR DELETE ON tenant_contracts "
        "FOR EACH ROW EXECUTE FUNCTION dashem_reject_immutable_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tenant_contracts_immutable ON tenant_contracts")
    op.drop_constraint(
        "ck_tenant_contract_schema_version_positive", "tenant_contracts", type_="check"
    )
    op.drop_column("tenant_contracts", "schema_version")
    op.drop_column("tenant_contracts", "storage_entitlement")
    op.drop_column("tenant_contracts", "limit_entitlements")
    op.drop_column("tenant_contracts", "capability_entitlements")
    op.drop_column("tenant_contracts", "activity_keys")
    op.execute(
        """
        UPDATE commercial_activity_capabilities
        SET role = 'REQUIRED', default_selected = true
        WHERE (activity_key = 'FOOD_SERVICE' AND capability_key = 'delivery_orders')
           OR (activity_key = 'RETAIL' AND capability_key IN ('inventory', 'barcode_scanning', 'counter_order', 'delivery_orders'))
           OR (activity_key = 'BEAUTY_RESELLER' AND capability_key IN ('inventory', 'delivery_orders'))
        """
    )
