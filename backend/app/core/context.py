import uuid
from typing import Optional, Type, TypeVar
from fastapi import Header, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.sql.expression import SelectOfScalar

class TenantContext(BaseModel):
    tenant_id: uuid.UUID
    store_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    role: Optional[str] = None

def get_tenant_context(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    x_store_id: Optional[str] = Header(None, alias="X-Store-ID"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_role: Optional[str] = Header(None, alias="X-Role")
) -> TenantContext:
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'X-Tenant-ID' is required for multi-tenant context."
        )
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid X-Tenant-ID UUID.")
    
    store_uuid = None
    if x_store_id:
        try:
            store_uuid = uuid.UUID(x_store_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid X-Store-ID UUID.")
            
    user_uuid = None
    if x_user_id:
        try:
            user_uuid = uuid.UUID(x_user_id)
        except ValueError:
            pass

    return TenantContext(
        tenant_id=tenant_uuid,
        store_id=store_uuid,
        user_id=user_uuid,
        role=x_role
    )

T = TypeVar("T")

def scope_tenant_query(query: SelectOfScalar[T], model_class: Type[T], context: TenantContext) -> SelectOfScalar[T]:
    """
    Centralized query builder helper ensuring multi-tenant isolation.
    Automatically scopes queries by tenant_id (and store_id if applicable).
    """
    if hasattr(model_class, "tenant_id"):
        query = query.where(getattr(model_class, "tenant_id") == context.tenant_id)
    if context.store_id and hasattr(model_class, "store_id"):
        query = query.where(getattr(model_class, "store_id") == context.store_id)
    return query
