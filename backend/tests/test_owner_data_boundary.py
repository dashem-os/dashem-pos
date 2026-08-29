from pathlib import Path

from app.main import app


IDENTITY_ENDPOINT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "api"
    / "v1"
    / "endpoints"
    / "identity.py"
)
OWNER_FINANCE_MODEL = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "models"
    / "owner_finance.py"
)
OWNER_FINANCE_ENDPOINT = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "v1" / "endpoints" / "owner_finance.py"
)
OWNER_FINANCE_SERVICE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "owner_finance_service.py"
)
FINANCE_PERMISSION_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "051_platform_finance_permissions.py"
)


def test_control_has_no_tenant_operational_metrics_route():
    assert "/api/v1/identity/platform/tenants/{tenant_id}/metrics" not in app.openapi()["paths"]
    assert "/api/v1/identity/platform/finance/overview" in app.openapi()["paths"]


def test_owner_identity_does_not_import_operational_finance_models():
    source = "\n".join((
        IDENTITY_ENDPOINT.read_text(encoding="utf-8"),
        OWNER_FINANCE_MODEL.read_text(encoding="utf-8"),
        OWNER_FINANCE_ENDPOINT.read_text(encoding="utf-8"),
        OWNER_FINANCE_SERVICE.read_text(encoding="utf-8"),
    ))
    forbidden_imports = (
        "from app.models.payment import",
        "from app.models.sale import",
        "from app.models.catalog import",
        "from app.models.intelligence import",
    )

    assert not [item for item in forbidden_imports if item in source]


def test_owner_invoicing_routes_are_platform_scoped_and_visible():
    paths = app.openapi()["paths"]
    assert "/api/v1/control/finance/invoices" in paths
    assert "/api/v1/control/finance/invoices/generate" in paths
    assert "/api/v1/control/finance/invoices/{invoice_id}" in paths
    assert "/api/v1/control/finance/invoices/{invoice_id}/issue" in paths
    assert "/api/v1/control/finance/invoices/{invoice_id}/void" in paths


def test_owner_receipt_and_collection_routes_are_platform_scoped_and_visible():
    paths = app.openapi()["paths"]
    assert "/api/v1/control/finance/payments" in paths
    assert "/api/v1/control/finance/payments/manual" in paths
    assert "/api/v1/control/finance/payments/{payment_id}/reconcile" in paths
    assert "/api/v1/control/finance/payments/{payment_id}/refunds" in paths
    assert "/api/v1/control/finance/collections/mark-overdue" in paths
    assert "/api/v1/control/finance/collections/events" in paths
    assert "/api/v1/control/finance/provider/webhooks/{provider}" in paths
    assert "/api/v1/control/finance/projections" in paths
    assert "/api/v1/control/finance/projections/latest" in paths
    assert "/api/v1/control/finance/projections/rebuild" in paths
    assert "/api/v1/control/finance/projections/{metric_date}" in paths


def test_owner_finance_has_no_manual_delinquency_source():
    identity_source = IDENTITY_ENDPOINT.read_text(encoding="utf-8")

    assert "overdue_subscriptions" not in identity_source
    assert "item.billing_status" not in identity_source
    assert "delinquency: bool = True" in identity_source
    assert "SaasInvoiceStatusEnum.OVERDUE" in identity_source


def test_finance_authorization_tables_are_platform_only():
    source = FINANCE_PERMISSION_MIGRATION.read_text(encoding="utf-8")

    for table in (
        "platform_permission_definitions",
        "platform_role_permissions",
        "platform_permission_grants",
    ):
        assert f'"{table}"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "CREATE POLICY {table}_platform_only" in source
