import uuid
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.models.assortment import AssortmentStatusEnum, SalesContextEnum
from app.services import assortment_service

router = APIRouter()


class AssortmentScopeDTO(BaseModel):
    store_id: uuid.UUID
    channel_id: Optional[uuid.UUID] = None
    sales_context: SalesContextEnum


class AssortmentScopeReadDTO(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    channel_id: Optional[uuid.UUID] = None
    sales_context: SalesContextEnum
    created_at: datetime


class AssortmentCreateDTO(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    status: AssortmentStatusEnum = AssortmentStatusEnum.ACTIVE
    scopes: Optional[List[AssortmentScopeDTO]] = None
    product_ids: Optional[List[uuid.UUID]] = None
    actor_id: Optional[uuid.UUID] = None


class AssortmentUpdateDTO(BaseModel):
    expected_version: int = Field(ge=1)
    code: Optional[str] = Field(default=None, min_length=1, max_length=40)
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = None
    status: Optional[AssortmentStatusEnum] = None
    scopes: Optional[List[AssortmentScopeDTO]] = None
    actor_id: Optional[uuid.UUID] = None


class AssortmentProductsLinkDTO(BaseModel):
    expected_version: int = Field(ge=1)
    product_ids: List[uuid.UUID] = Field(min_length=1)
    actor_id: Optional[uuid.UUID] = None


class AssortmentReadDTO(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    description: Optional[str]
    status: AssortmentStatusEnum
    version: int
    created_at: datetime
    updated_at: datetime
    product_count: int
    scopes: List[AssortmentScopeReadDTO]


class AssortmentPageDTO(BaseModel):
    items: List[AssortmentReadDTO]
    total: int
    page: int
    page_size: int


class AssortmentProductItemDTO(BaseModel):
    id: uuid.UUID
    name: str
    sku: str
    barcode: Optional[str]
    unit: str
    category_id: Optional[uuid.UUID]
    is_active: bool
    available_for_sale: bool
    sort_order: int


class AssortmentProductPageDTO(BaseModel):
    items: List[AssortmentProductItemDTO]
    total: int
    page: int
    page_size: int


@router.get("", response_model=AssortmentPageDTO)
def list_assortments_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=160),
    status_filter: Optional[AssortmentStatusEnum] = Query(default=None, alias="status"),
    store_id: Optional[uuid.UUID] = Query(default=None),
    sales_context: Optional[SalesContextEnum] = Query(default=None),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return assortment_service.list_assortments(
        session,
        context,
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status_filter,
        store_id=store_id,
        sales_context=sales_context,
    )


@router.post("", response_model=AssortmentReadDTO, status_code=status.HTTP_201_CREATED)
def create_assortment_endpoint(
    data: AssortmentCreateDTO,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    scopes_data = [s.model_dump() for s in data.scopes] if data.scopes is not None else None
    return assortment_service.create_assortment(
        session,
        context,
        code=data.code,
        name=data.name,
        description=data.description,
        status=data.status,
        scopes=scopes_data,
        product_ids=data.product_ids,
        idempotency_key=idempotency_key,
        actor_id=data.actor_id,
    )


@router.get("/{assortment_id}", response_model=AssortmentReadDTO)
def get_assortment_endpoint(
    assortment_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return assortment_service.get_assortment(session, context, assortment_id)


@router.patch("/{assortment_id}", response_model=AssortmentReadDTO)
def update_assortment_endpoint(
    assortment_id: uuid.UUID,
    data: AssortmentUpdateDTO,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    scopes_data = [s.model_dump() for s in data.scopes] if data.scopes is not None else None
    return assortment_service.update_assortment(
        session,
        context,
        assortment_id,
        expected_version=data.expected_version,
        code=data.code,
        name=data.name,
        description=data.description,
        status=data.status,
        scopes=scopes_data,
        idempotency_key=idempotency_key,
        actor_id=data.actor_id,
    )


@router.post("/{assortment_id}/products", response_model=AssortmentReadDTO)
def link_assortment_products_endpoint(
    assortment_id: uuid.UUID,
    data: AssortmentProductsLinkDTO,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return assortment_service.link_products(
        session,
        context,
        assortment_id,
        product_ids=data.product_ids,
        expected_version=data.expected_version,
        idempotency_key=idempotency_key,
        actor_id=data.actor_id,
    )


@router.delete("/{assortment_id}/products", response_model=AssortmentReadDTO)
def unlink_assortment_products_endpoint(
    assortment_id: uuid.UUID,
    data: AssortmentProductsLinkDTO,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return assortment_service.unlink_products(
        session,
        context,
        assortment_id,
        product_ids=data.product_ids,
        expected_version=data.expected_version,
        idempotency_key=idempotency_key,
        actor_id=data.actor_id,
    )


@router.get("/{assortment_id}/products", response_model=AssortmentProductPageDTO)
def list_assortment_products_endpoint(
    assortment_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=160),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return assortment_service.list_assortment_products(
        session,
        context,
        assortment_id,
        page=page,
        page_size=page_size,
        search=search,
    )


@router.delete("/{assortment_id}")
def delete_assortment_endpoint(
    assortment_id: uuid.UUID,
    expected_version: int = Query(ge=1),
    actor_id: Optional[uuid.UUID] = Query(default=None),
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    assortment_service.delete_assortment(
        session,
        context,
        assortment_id,
        expected_version=expected_version,
        actor_id=actor_id,
    )
    return {"ok": True}
