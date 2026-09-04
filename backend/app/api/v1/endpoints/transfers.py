import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter,Depends,Header
from pydantic import BaseModel,ConfigDict,Field
from sqlmodel import Session
from app.core.context import TenantContext,get_tenant_context
from app.core.database import get_session
from app.models.transfer import TransferTypeEnum
from app.services import transfer_service
router=APIRouter()
class ItemTransferDTO(BaseModel):
    source_session_id:uuid.UUID;destination_session_id:uuid.UUID;order_item_id:uuid.UUID;quantity:Decimal=Field(gt=0)
    expected_source_version:int=Field(ge=1);expected_destination_version:int=Field(ge=1);reason:str=Field(min_length=3,max_length=500);actor_id:Optional[uuid.UUID]=None
class OrderTransferDTO(BaseModel):
    source_session_id:uuid.UUID;destination_session_id:uuid.UUID;order_id:uuid.UUID
    expected_source_version:int=Field(ge=1);expected_destination_version:int=Field(ge=1);reason:str=Field(min_length=3,max_length=500);actor_id:Optional[uuid.UUID]=None
class OrderToTableDTO(BaseModel):
    source_session_id:uuid.UUID;destination_table_id:uuid.UUID;order_id:uuid.UUID
    expected_source_version:int=Field(ge=1);expected_table_version:int=Field(ge=1);reason:str=Field(min_length=3,max_length=500);actor_id:Optional[uuid.UUID]=None
class SessionMoveDTO(BaseModel):
    source_session_id:uuid.UUID;destination_table_id:uuid.UUID
    expected_source_version:int=Field(ge=1);expected_table_version:int=Field(ge=1);reason:str=Field(min_length=3,max_length=500);actor_id:Optional[uuid.UUID]=None
class MergeDTO(BaseModel):
    source_session_id:uuid.UUID;destination_session_id:uuid.UUID;expected_source_version:int=Field(ge=1);expected_destination_version:int=Field(ge=1);reason:str=Field(min_length=3,max_length=500);actor_id:Optional[uuid.UUID]=None
class TransferDTO(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:uuid.UUID;tenant_id:uuid.UUID;store_id:uuid.UUID;transfer_type:TransferTypeEnum;source_session_id:uuid.UUID;destination_session_id:uuid.UUID
    source_order_id:Optional[uuid.UUID];destination_order_id:Optional[uuid.UUID];source_order_item_id:Optional[uuid.UUID];derived_order_item_id:Optional[uuid.UUID]
    quantity:Optional[Decimal];unit_price_snapshot:Optional[Decimal];source_version_before:int;destination_version_before:int;actor_id:uuid.UUID;reason:str;production_compensation_required:bool;created_at:datetime
@router.post("/items",response_model=TransferDTO)
def transfer_item_endpoint(data:ItemTransferDTO,idempotency_key:str=Header(alias="Idempotency-Key",min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):
    return transfer_service.transfer_item(session,context,source_session_id=data.source_session_id,destination_session_id=data.destination_session_id,order_item_id=data.order_item_id,quantity=data.quantity,expected_source_version=data.expected_source_version,expected_destination_version=data.expected_destination_version,reason=data.reason,actor_id=data.actor_id,idempotency_key=idempotency_key)
@router.post("/orders",response_model=TransferDTO)
def transfer_order_endpoint(data:OrderTransferDTO,idempotency_key:str=Header(alias="Idempotency-Key",min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):
    return transfer_service.transfer_order(session,context,source_session_id=data.source_session_id,destination_session_id=data.destination_session_id,order_id=data.order_id,expected_source_version=data.expected_source_version,expected_destination_version=data.expected_destination_version,reason=data.reason,actor_id=data.actor_id,idempotency_key=idempotency_key)
@router.post("/orders/to-table",response_model=TransferDTO)
def transfer_order_to_table_endpoint(data:OrderToTableDTO,idempotency_key:str=Header(alias="Idempotency-Key",min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):
    return transfer_service.transfer_order_to_table(session,context,source_session_id=data.source_session_id,destination_table_id=data.destination_table_id,order_id=data.order_id,expected_source_version=data.expected_source_version,expected_table_version=data.expected_table_version,reason=data.reason,actor_id=data.actor_id,idempotency_key=idempotency_key)
@router.post("/sessions/to-table",response_model=TransferDTO)
def move_session_to_table_endpoint(data:SessionMoveDTO,idempotency_key:str=Header(alias="Idempotency-Key",min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):
    return transfer_service.move_session_to_table(session,context,source_session_id=data.source_session_id,destination_table_id=data.destination_table_id,expected_source_version=data.expected_source_version,expected_table_version=data.expected_table_version,reason=data.reason,actor_id=data.actor_id,idempotency_key=idempotency_key)
@router.post("/merge",response_model=TransferDTO)
def merge_endpoint(data:MergeDTO,idempotency_key:str=Header(alias="Idempotency-Key",min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):
    return transfer_service.merge_sessions(session,context,source_session_id=data.source_session_id,destination_session_id=data.destination_session_id,expected_source_version=data.expected_source_version,expected_destination_version=data.expected_destination_version,reason=data.reason,actor_id=data.actor_id,idempotency_key=idempotency_key)
@router.get("",response_model=list[TransferDTO])
def list_endpoint(table_session_id:Optional[uuid.UUID]=None,context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):
    return transfer_service.list_transfers(session,context,table_session_id)
