from fastapi import HTTPException, status

from app.models.identity import RoleEnum


FULL_ACCESS_ROLES = {RoleEnum.OWNER, RoleEnum.TENANT_OWNER, RoleEnum.ADMIN}


def tenant_role_allows(role: RoleEnum, method: str, path: str) -> bool:
    """Central permission matrix. Deny by default for unknown route families."""
    method = method.upper()
    if role in FULL_ACCESS_ROLES:
        return True
    if role == RoleEnum.SUPERVISOR:
        return not path.startswith(("/api/v1/identity/memberships", "/api/v1/team"))
    if role == RoleEnum.MANAGER:
        return not path.startswith("/api/v1/identity/memberships")
    if role in {RoleEnum.CASHIER, RoleEnum.OPERATOR}:
        if method == "GET":
            return path.startswith((
                "/api/v1/catalog", "/api/v1/inventory", "/api/v1/sales",
                "/api/v1/cash", "/api/v1/payments", "/api/v1/fiscal",
            ))
        return path.startswith((
            "/api/v1/sales", "/api/v1/cash", "/api/v1/payments", "/api/v1/fiscal",
        ))
    return False


def enforce_tenant_permission(role: RoleEnum, method: str, path: str) -> None:
    if not tenant_role_allows(role, method, path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your tenant role does not allow this operation.",
        )
