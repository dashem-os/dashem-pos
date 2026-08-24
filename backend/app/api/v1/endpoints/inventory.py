import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session
from app.core.database import get_session
from app.core.context import TenantContext, get_tenant_context, resolve_actor
from app.models.catalog import InventoryMovement, InventoryBalance, MovementTypeEnum
from app.services import inventory_service, reliability_service

router = APIRouter()

class StockAdjustDTO(BaseModel):
    store_id: uuid.UUID
    product_id: uuid.UUID
    actor_id: uuid.UUID
    movement_type: MovementTypeEnum
    quantity: float
    reason: Optional[str] = None

class StockAdjustResponse(BaseModel):
    movement: Optional[InventoryMovement]
    balance: InventoryBalance
    movement_created: bool


class MinimumStockDTO(BaseModel):
    store_id: uuid.UUID
    product_id: uuid.UUID
    minimum_stock: float

@router.post("/adjust", response_model=StockAdjustResponse)
def adjust_stock_endpoint(
    data: StockAdjustDTO,
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
            operation="POST /api/v1/inventory/adjust",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict()
        )
        if is_cached and status_code and body:
            return body

    movement, balance, created = inventory_service.adjust_stock(
        session=session,
        context=context,
        store_id=data.store_id,
        product_id=data.product_id,
        actor_id=actor_id,
        movement_type=data.movement_type,
        quantity=data.quantity,
        reason=data.reason,
        correlation_id=x_correlation_id
    )

    response_data = {
        "movement": movement.dict() if movement else None,
        "balance": balance.dict(),
        "movement_created": created
    }

    # Save Idempotency record if key header was provided
    if x_idempotency_key:
        reliability_service.save_idempotency_record(
            session=session,
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            operation="POST /api/v1/inventory/adjust",
            idempotency_key=x_idempotency_key,
            request_payload=data.dict(),
            response_status=200,
            response_body=response_data
        )

    session.commit()
    return response_data

@router.get("/balance", response_model=InventoryBalance)
def get_balance_endpoint(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return inventory_service.get_balance(session, context, store_id=store_id, product_id=product_id)

@router.get("/movements", response_model=List[InventoryMovement])
def list_movements_endpoint(
    store_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return inventory_service.list_movements(session, context, store_id=store_id, product_id=product_id)


@router.put("/minimum", response_model=InventoryBalance)
def set_minimum_stock_endpoint(
    data: MinimumStockDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    if data.minimum_stock < 0:
        raise HTTPException(status_code=400, detail="minimum_stock não pode ser negativo.")
    return inventory_service.set_minimum_stock(
        session, context, data.store_id, data.product_id, data.minimum_stock,
    )
