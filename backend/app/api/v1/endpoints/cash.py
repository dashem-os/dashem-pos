import uuid
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session
from app.core.database import get_session
from app.core.context import TenantContext, get_tenant_context
from app.models.payment import Register, CashSession, CashMovement, CashMovementTypeEnum, CashSessionStatusEnum
from app.services import cash_service

router = APIRouter()

class RegisterCreateDTO(BaseModel):
    store_id: uuid.UUID
    name: str
    code: str

class OpenCashSessionDTO(BaseModel):
    store_id: uuid.UUID
    register_id: uuid.UUID
    operator_id: uuid.UUID
    opening_balance: float

class CloseCashSessionDTO(BaseModel):
    operator_id: uuid.UUID
    closing_balance: float

class CashMovementDTO(BaseModel):
    actor_id: uuid.UUID
    movement_type: CashMovementTypeEnum
    amount: float
    notes: Optional[str] = None

@router.post("/registers", response_model=Register)
def create_register_endpoint(
    data: RegisterCreateDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return cash_service.create_register(
        session, context, store_id=data.store_id, name=data.name, code=data.code
    )

@router.get("/registers", response_model=List[Register])
def list_registers_endpoint(
    store_id: Optional[uuid.UUID] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return cash_service.list_registers(session, context, store_id=store_id)

@router.get("/sessions/active", response_model=Optional[CashSession])
def get_active_cash_session_endpoint(
    store_id: Optional[uuid.UUID] = None,
    register_id: Optional[uuid.UUID] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return cash_service.get_active_cash_session(session, context, store_id=store_id, register_id=register_id)

@router.get("/sessions", response_model=List[CashSession])
def list_cash_sessions_endpoint(
    store_id: Optional[uuid.UUID] = None,
    status: Optional[CashSessionStatusEnum] = None,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return cash_service.list_cash_sessions(session, context, store_id=store_id, status_filter=status)

@router.post("/sessions/open", response_model=CashSession)
def open_cash_session_endpoint(
    data: OpenCashSessionDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return cash_service.open_cash_session(
        session,
        context,
        store_id=data.store_id,
        register_id=data.register_id,
        operator_id=data.operator_id,
        opening_balance=Decimal(str(data.opening_balance))
    )

@router.post("/sessions/{session_id}/close", response_model=CashSession)
def close_cash_session_endpoint(
    session_id: uuid.UUID,
    data: CloseCashSessionDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return cash_service.close_cash_session(
        session,
        context,
        session_id=session_id,
        closing_balance=Decimal(str(data.closing_balance)),
        operator_id=data.operator_id
    )

@router.post("/sessions/{session_id}/movements", response_model=CashMovement)
def add_cash_movement_endpoint(
    session_id: uuid.UUID,
    data: CashMovementDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return cash_service.add_cash_movement(
        session,
        context,
        session_id=session_id,
        actor_id=data.actor_id,
        movement_type=data.movement_type,
        amount=Decimal(str(data.amount)),
        notes=data.notes
    )

@router.get("/sessions/{session_id}/movements", response_model=List[CashMovement])
def list_cash_movements_endpoint(
    session_id: uuid.UUID,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session)
):
    return cash_service.list_cash_movements(session, context, session_id=session_id)

