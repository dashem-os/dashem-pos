from pathlib import Path

from app.main import app


FRONTEND_API = Path(__file__).resolve().parents[2] / "frontend" / "src" / "services" / "api.ts"

# Critical operations exercised by the current Control, Gestão and POS clients.
# The frontend marker makes an endpoint rename fail here instead of at runtime.
CONTRACTS = [
    ("GET", "/health", "/health`"),
    ("GET", "/api/v1/identity/me", "/api/v1/identity/me`"),
    ("GET", "/api/v1/identity/tenants", "/api/v1/identity/tenants`"),
    ("GET", "/api/v1/identity/stores", "/api/v1/identity/stores`"),
    ("GET", "/api/v1/identity/platform/overview", "/api/v1/identity/platform/overview`"),
    ("GET", "/api/v1/identity/platform/health", "/api/v1/identity/platform/health`"),
    ("POST", "/api/v1/identity/platform/tenants", "/api/v1/identity/platform/tenants`"),
    ("GET", "/api/v1/catalog/categories", "/api/v1/catalog/categories`"),
    ("POST", "/api/v1/catalog/categories", "/api/v1/catalog/categories`"),
    ("GET", "/api/v1/catalog/products", "/api/v1/catalog/products`"),
    ("POST", "/api/v1/catalog/products", "/api/v1/catalog/products`"),
    ("GET", "/api/v1/catalog/sellable-products", "/api/v1/catalog/sellable-products?"),
    ("PUT", "/api/v1/catalog/quick-access/{product_id}", "/api/v1/catalog/quick-access/${productId}`"),
    ("GET", "/api/v1/catalog/prices", "/api/v1/catalog/prices`"),
    ("POST", "/api/v1/catalog/prices", "/api/v1/catalog/prices`"),
    ("GET", "/api/v1/inventory/balance", "/api/v1/inventory/balance?"),
    ("POST", "/api/v1/inventory/adjust", "/api/v1/inventory/adjust`"),
    ("PUT", "/api/v1/inventory/minimum", "/api/v1/inventory/minimum`"),
    ("GET", "/api/v1/inventory/movements", "/api/v1/inventory/movements`"),
    ("GET", "/api/v1/sales", "/api/v1/sales`"),
    ("POST", "/api/v1/sales", "/api/v1/sales`"),
    ("GET", "/api/v1/sales/active", "/api/v1/sales/active?"),
    ("GET", "/api/v1/cash/registers", "/api/v1/cash/registers`"),
    ("POST", "/api/v1/cash/registers", "/api/v1/cash/registers`"),
    ("GET", "/api/v1/cash/sessions", "/api/v1/cash/sessions`"),
    ("POST", "/api/v1/cash/sessions/open", "/api/v1/cash/sessions/open`"),
    ("GET", "/api/v1/payments", "/api/v1/payments?sale_id="),
    ("POST", "/api/v1/payments", "/api/v1/payments`"),
    ("POST", "/api/v1/fiscal/documents/issue", "/api/v1/fiscal/documents/issue`"),
    ("GET", "/api/v1/capabilities/effective", "/api/v1/capabilities/effective`"),
    ("GET", "/api/v1/team", "/api/v1/team`"),
    ("POST", "/api/v1/team/invitations", "/api/v1/team/invitations`"),
    ("GET", "/api/v1/management/overview", "/api/v1/management/overview`"),
]


def test_frontend_critical_api_contracts_exist_in_fastapi_and_client():
    source = FRONTEND_API.read_text(encoding="utf-8")
    routes = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }

    missing_backend = [(method, path) for method, path, _ in CONTRACTS if (method, path) not in routes]
    missing_frontend = [(method, path) for method, path, marker in CONTRACTS if marker not in source]

    assert not missing_backend, f"Frontend contracts missing in FastAPI: {missing_backend}"
    assert not missing_frontend, f"FastAPI contracts missing in frontend client: {missing_frontend}"


def test_every_tenant_critical_contract_keeps_context_headers_in_client():
    source = FRONTEND_API.read_text(encoding="utf-8")
    for function_name in (
        "fetchProducts",
        "fetchSellableProducts",
        "fetchInventoryBalance",
        "createSale",
        "fetchActiveSale",
        "addItemToSale",
        "openCashSession",
        "createPayment",
        "issueFiscalDocument",
        "fetchEffectiveAccess",
        "fetchTeam",
        "inviteTeamMember",
        "fetchManagementOverview",
    ):
        start = source.index(f"export async function {function_name}")
        next_export = source.find("export async function ", start + 1)
        body = source[start: next_export if next_export >= 0 else None]
        assert "headers" in body, f"{function_name} lost tenant/store context headers"
