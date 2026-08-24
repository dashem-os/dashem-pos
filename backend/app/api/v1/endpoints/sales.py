import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session
from app.core.database import get_session
from app.core.context import TenantContext, get_tenant_context, resolve_actor
from app.models.sale import Customer, Sale, SaleItem, SaleStatusEnum, DiscountTypeEnum, SaleOperationModeEnum
from app.services import sale_service, reliability_service

router = APIRouter()

class CustomerCreateDTO(BaseModel):
    name: str
    cpf_cnpj: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class CustomerUpdateDTO(BaseModel):
    name: Optional[str] = None
    cpf_cnpj: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class SaleCreateDTO(BaseModel):
    store_id: uuid.UUID
    register_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    seller_id: Optional[uuid.UUID] = None
    operation_mode: SaleOperationModeEnum = SaleOperationModeEnum.COUNTER
    notes: Optional[str] = None

class SaleItemAddDTO(BaseModel):
    product_id: uuid.UUID
    quantity: float
    requested_discount: float = 0.0

class SaleCheckoutDTO(BaseModel):
    actor_id: uuid.UUID
    requested_discount: float = 0.0
    discount_type: Optional[DiscountTypeEnum] = None

class SaleItemReadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    sale_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    item_type_snapshot: str
    tracks_inventory_snapshot: bool
    requires_fulfillment_snapshot: bool
    unit_price: Decimal
    quantity: Decimal
    discount_amount: Decimal
    gross_total: Decimal
    net_total: Decimal
    created_at: datetime

class SaleReadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    register_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    seller_id: Optional[uuid.UUID] = None
    operation_mode: SaleOperationModeEnum = SaleOperationModeEnum.COUNTER
    operator_action_count: int = 0
    last_activity_at: datetime
    status: SaleStatusEnum
    discount_type: Optional[DiscountTypeEnum] = None
    requested_discount: Decimal
    approved_discount: Decimal
    gross_total: Decimal
    discount_total: Decimal
    net_total: Decimal
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[SaleItemReadDTO] = []

class SaleDiscountDTO(BaseModel):
    discount_type: DiscountTypeEnum = DiscountTypeEnum.FIXED
    value: float

class SaleItemUpdateDTO(BaseModel):
    quantity: float
    requested_discount: Optional[float] = None

class SaleCancelDTO(BaseModel):
    actor_id: Optional[uuid.UUID] = None
    reason: Optional[str] = None

@router.post("/customers", response_model=Customer)
def create_customer_endpoint(
    data: CustomerCreateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.create_customer(
        session, context, name=data.name, cpf_cnpj=data.cpf_cnpj, phone=data.phone, email=data.email
    )

@router.get("/customers", response_model=List[Customer])
def list_customers_endpoint(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.list_customers(session, context)

@router.patch("/customers/{customer_id}", response_model=Customer)
def update_customer_endpoint(
    customer_id: uuid.UUID,
    data: CustomerUpdateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return sale_service.update_customer(
        session, context, customer_id=customer_id, **data.model_dump(exclude_unset=True)
    )

@router.post("", response_model=SaleReadDTO)
def create_sale_endpoint(
    data: SaleCreateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.create_sale(
        session, context, store_id=data.store_id, customer_id=data.customer_id,
        seller_id=data.seller_id, notes=data.notes, actor_id=data.seller_id or context.user_id,
        register_id=data.register_id, operation_mode=data.operation_mode,
    )

@router.get("", response_model=List[SaleReadDTO])
def list_sales_endpoint(
    store_id: Optional[uuid.UUID] = None,
    status: Optional[SaleStatusEnum] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.list_sales(session, context, store_id=store_id, status_filter=status)


@router.get("/active", response_model=Optional[SaleReadDTO])
def get_active_sale_endpoint(
    store_id: uuid.UUID,
    register_id: uuid.UUID,
    seller_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return sale_service.get_active_sale(session, context, store_id, register_id, seller_id)

@router.get("/{sale_id}", response_model=SaleReadDTO)
def get_sale_endpoint(
    sale_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.get_sale(session, context, sale_id=sale_id)

@router.post("/{sale_id}/items", response_model=SaleItemReadDTO)
def add_sale_item_endpoint(
    sale_id: uuid.UUID,
    data: SaleItemAddDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.add_sale_item(
        session,
        context,
        sale_id=sale_id,
        product_id=data.product_id,
        quantity=Decimal(str(data.quantity)),
        requested_discount=Decimal(str(data.requested_discount))
    )

@router.patch("/{sale_id}/items/{item_id}", response_model=SaleItemReadDTO)
def update_sale_item_endpoint(
    sale_id: uuid.UUID,
    item_id: uuid.UUID,
    data: SaleItemUpdateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.update_sale_item(
        session,
        context,
        sale_id=sale_id,
        item_id=item_id,
        quantity=Decimal(str(data.quantity)),
        requested_discount=Decimal(str(data.requested_discount)) if data.requested_discount is not None else None
    )

@router.delete("/{sale_id}/items/{item_id}", response_model=SaleReadDTO)
def delete_sale_item_endpoint(
    sale_id: uuid.UUID,
    item_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.delete_sale_item(
        session,
        context,
        sale_id=sale_id,
        item_id=item_id
    )

@router.post("/{sale_id}/discount", response_model=SaleReadDTO)
def apply_sale_discount_endpoint(
    sale_id: uuid.UUID,
    data: SaleDiscountDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.apply_sale_discount(
        session,
        context,
        sale_id=sale_id,
        discount_type=data.discount_type,
        value=Decimal(str(data.value))
    )

@router.post("/{sale_id}/cancel", response_model=SaleReadDTO)
def cancel_sale_endpoint(
    sale_id: uuid.UUID,
    data: Optional[SaleCancelDTO] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return sale_service.cancel_sale(
        session,
        context,
        sale_id=sale_id,
        actor_id=data.actor_id if data else None,
        reason=data.reason if data else None
    )

@router.post("/{sale_id}/checkout", response_model=SaleReadDTO)
def checkout_sale_endpoint(
    sale_id: uuid.UUID,
    data: SaleCheckoutDTO,
    context: TenantContext = Depends(get_tenant_context),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    session: Session = Depends(get_session)
):
    actor_id = resolve_actor(context, data.actor_id)
    # Check Idempotency if key header is provided
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            operation=f"POST /api/v1/sales/{sale_id}/checkout",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict()
        )
        if is_cached and status_code and body:
            return body

    sale = sale_service.checkout_sale(
        session=session,
        context=context,
        sale_id=sale_id,
        actor_id=actor_id,
        requested_discount=Decimal(str(data.requested_discount)),
        discount_type=data.discount_type,
        correlation_id=x_correlation_id
    )

    response_data = sale_service.get_sale(session, context, sale_id=sale.id)

    # Save Idempotency record if key header was provided
    if x_idempotency_key:
        reliability_service.save_idempotency_record(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            operation=f"POST /api/v1/sales/{sale_id}/checkout",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict(),
            response_status=200,
            response_body=response_data.dict()
        )

    session.commit()
    return response_data
