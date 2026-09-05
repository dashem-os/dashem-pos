import uuid
from datetime import date,datetime
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter,Depends,Header
from pydantic import BaseModel,ConfigDict,Field
from sqlmodel import Session
from app.core.context import TenantContext,get_tenant_context
from app.core.database import get_session
from app.models.channel_catalog import *
from app.services import channel_catalog_service as service
router=APIRouter()
class MappingIn(BaseModel):connection_id:uuid.UUID;entity_type:CatalogEntityTypeEnum;internal_id:uuid.UUID;external_id:str=Field(min_length=1,max_length=200);actor_id:Optional[uuid.UUID]=None
class OfferIn(BaseModel):connection_id:uuid.UUID;product_id:uuid.UUID;price:Decimal=Field(ge=0);available:bool=True;stock_quantity:Optional[Decimal]=Field(default=None,ge=0);actor_id:Optional[uuid.UUID]=None
class BatchIn(BaseModel):connection_id:uuid.UUID;offer_ids:list[uuid.UUID]=Field(min_length=1);actor_id:Optional[uuid.UUID]=None
class ResultIn(BaseModel):offer_id:uuid.UUID;success:bool;provider_result_ref:Optional[str]=None;error_code:Optional[str]=None;error_message:Optional[str]=None
class ResultsIn(BaseModel):results:list[ResultIn]=Field(min_length=1);actor_id:Optional[uuid.UUID]=None
class SettlementIn(BaseModel):
 connection_id:uuid.UUID;provider_document_ref:str;external_order_id:Optional[str]=None;order_id:Optional[uuid.UUID]=None;competence_date:date;gross_amount:Decimal=Field(ge=0);commission_amount:Decimal=Field(ge=0);fee_amount:Decimal=Field(ge=0);promotion_amount:Decimal=Field(ge=0);adjustment_amount:Decimal=Decimal('0');actor_id:Optional[uuid.UUID]=None
class PaymentIn(BaseModel):provider_payment_ref:str;amount:Decimal=Field(gt=0);paid_at:datetime;actor_id:Optional[uuid.UUID]=None
@router.post('/mappings')
def mapping(data:MappingIn,key:str=Header(alias='Idempotency-Key',min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):return service.upsert_mapping(session,context,connection_id=data.connection_id,entity_type=data.entity_type,internal_id=data.internal_id,external_id=data.external_id,actor_id=data.actor_id,idempotency_key=key).model_dump()
@router.post('/offers')
def offer(data:OfferIn,key:str=Header(alias='Idempotency-Key',min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):return service.upsert_offer(session,context,connection_id=data.connection_id,product_id=data.product_id,price=data.price,available=data.available,stock_quantity=data.stock_quantity,actor_id=data.actor_id,idempotency_key=key).model_dump()
@router.post('/publications')
def batch(data:BatchIn,key:str=Header(alias='Idempotency-Key',min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):
 value=service.create_batch(session,context,connection_id=data.connection_id,offer_ids=data.offer_ids,actor_id=data.actor_id,idempotency_key=key);return {'batch':value['batch'].model_dump(),'items':[row.model_dump() for row in value['items']]}
@router.post('/publications/{batch_id}/results')
def results(batch_id:uuid.UUID,data:ResultsIn,context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):
 value=service.apply_results(session,context,batch_id,[row.model_dump() for row in data.results],data.actor_id);return {'batch':value['batch'].model_dump(),'items':[row.model_dump() for row in value['items']]}
@router.get('/catalog')
def catalog(context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):return service.list_catalog(session,context)
@router.post('/settlements')
def settlement(data:SettlementIn,key:str=Header(alias='Idempotency-Key',min_length=8,max_length=160),context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):return service.create_settlement(session,context,connection_id=data.connection_id,provider_document_ref=data.provider_document_ref,external_order_id=data.external_order_id,order_id=data.order_id,competence_date=data.competence_date,gross=data.gross_amount,commission=data.commission_amount,fee=data.fee_amount,promotion=data.promotion_amount,adjustment=data.adjustment_amount,actor_id=data.actor_id,idempotency_key=key).model_dump()
@router.post('/settlements/{settlement_id}/payments')
def payment(settlement_id:uuid.UUID,data:PaymentIn,context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):return service.record_payment(session,context,settlement_id,provider_payment_ref=data.provider_payment_ref,amount=data.amount,paid_at=data.paid_at,actor_id=data.actor_id).model_dump()
@router.get('/settlements')
def settlements(context:TenantContext=Depends(get_tenant_context),session:Session=Depends(get_session)):return service.list_settlements(session,context)
