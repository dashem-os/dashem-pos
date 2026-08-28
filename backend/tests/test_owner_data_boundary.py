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


def test_control_has_no_tenant_operational_metrics_route():
    assert "/api/v1/identity/platform/tenants/{tenant_id}/metrics" not in app.openapi()["paths"]
    assert "/api/v1/identity/platform/finance/overview" in app.openapi()["paths"]


def test_owner_identity_does_not_import_operational_finance_models():
    source = "\n".join((
        IDENTITY_ENDPOINT.read_text(encoding="utf-8"),
        OWNER_FINANCE_MODEL.read_text(encoding="utf-8"),
    ))
    forbidden_imports = (
        "from app.models.payment import",
        "from app.models.sale import",
        "from app.models.catalog import",
        "from app.models.intelligence import",
    )

    assert not [item for item in forbidden_imports if item in source]


def test_owner_finance_has_no_manual_delinquency_source():
    identity_source = IDENTITY_ENDPOINT.read_text(encoding="utf-8")

    assert "overdue_subscriptions" not in identity_source
    assert "item.billing_status" not in identity_source
    assert "delinquency: bool = False" in identity_source
