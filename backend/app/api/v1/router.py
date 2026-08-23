from fastapi import APIRouter
from app.api.v1.endpoints import identity, catalog, inventory, sales, cash, payments, fiscal, capabilities, team, management

api_router = APIRouter()
api_router.include_router(identity.router, prefix="/identity", tags=["Identity & Tenancy"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["Catalog & Products"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["Inventory Ledger & Balances"])
api_router.include_router(sales.router, prefix="/sales", tags=["Sales & Checkout Engine"])
api_router.include_router(cash.router, prefix="/cash", tags=["Cash Sessions & Movements"])
api_router.include_router(payments.router, prefix="/payments", tags=["Payment Engine & Confirmation"])
api_router.include_router(fiscal.router, prefix="/fiscal", tags=["Fiscal Gateway & Issuance"])
api_router.include_router(capabilities.router, prefix="/capabilities", tags=["Capability Mesh"])
api_router.include_router(team.router, prefix="/team", tags=["Tenant Team & Permissions"])
api_router.include_router(management.router, prefix="/management", tags=["Tenant Management"])
