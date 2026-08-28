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


def test_control_has_no_tenant_operational_metrics_route():
    assert "/api/v1/identity/platform/tenants/{tenant_id}/metrics" not in app.openapi()["paths"]


def test_owner_identity_does_not_import_operational_finance_models():
    source = IDENTITY_ENDPOINT.read_text(encoding="utf-8")
    forbidden_imports = (
        "from app.models.payment import",
        "from app.models.sale import",
        "from app.models.catalog import",
        "from app.models.intelligence import",
    )

    assert not [item for item in forbidden_imports if item in source]
