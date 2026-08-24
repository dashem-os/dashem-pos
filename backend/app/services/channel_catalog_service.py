import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from fastapi import HTTPException
from sqlmodel import Session,select
from app.core.context import TenantContext,resolve_actor,scope_tenant_query
from app.models.catalog import Product
from app.models.channel_catalog import *
from app.models.channel_hub import MerchantConnection
from app.models.order import Order
from app.services import reliability_service

def actor(context,actor_id):
 return resolve_actor(context,actor_id)
def connection(session,context,cid):
 row=session.exec(scope_tenant_query(select(MerchantConnection).where(MerchantConnection.id==cid),MerchantConnection,context)).first()
 if not row:raise HTTPException(404,"Conexão não encontrada.")
 return row
def upsert_mapping(session,context,*,connection_id,entity_type,internal_id,external_id,actor_id,idempotency_key):
 a=actor(context,actor_id);conn=connection(session,context,connection_id);payload={"connection_id":str(connection_id),"entity_type":entity_type.value,"internal_id":str(internal_id),"external_id":external_id};cached,_,body=reliability_service.check_idempotency(session,context.tenant_id,a,"channel.catalog.mapping",idempotency_key,payload)
 if cached and body:return session.get(ChannelCatalogMapping,uuid.UUID(body["mapping_id"]))
 if entity_type==CatalogEntityTypeEnum.PRODUCT and not session.exec(scope_tenant_query(select(Product).where(Product.id==internal_id),Product,context)).first():raise HTTPException(404,"Produto canônico não encontrado.")
 row=session.exec(select(ChannelCatalogMapping).where(ChannelCatalogMapping.merchant_connection_id==connection_id,ChannelCatalogMapping.entity_type==entity_type,ChannelCatalogMapping.internal_id==internal_id)).first()
 if row:row.external_id=external_id;row.updated_at=datetime.utcnow()
 else:row=ChannelCatalogMapping(tenant_id=context.tenant_id,store_id=conn.store_id,merchant_connection_id=conn.id,entity_type=entity_type,internal_id=internal_id,external_id=external_id);session.add(row)
 session.commit();session.refresh(row);reliability_service.save_idempotency_record(session,context.tenant_id,a,"channel.catalog.mapping",idempotency_key,payload,200,{"mapping_id":str(row.id)});session.commit();session.refresh(row);return row
def upsert_offer(session,context,*,connection_id,product_id,price,available,stock_quantity,actor_id,idempotency_key):
 a=actor(context,actor_id);conn=connection(session,context,connection_id);product=session.exec(scope_tenant_query(select(Product).where(Product.id==product_id),Product,context)).first()
 if not product:raise HTTPException(404,"Produto canônico não encontrado.")
 payload={"connection_id":str(connection_id),"product_id":str(product_id),"price":str(price),"available":available,"stock_quantity":str(stock_quantity) if stock_quantity is not None else None};cached,_,body=reliability_service.check_idempotency(session,context.tenant_id,a,"channel.catalog.offer",idempotency_key,payload)
 if cached and body:return session.get(ChannelCatalogOffer,uuid.UUID(body["offer_id"]))
 row=session.exec(select(ChannelCatalogOffer).where(ChannelCatalogOffer.merchant_connection_id==connection_id,ChannelCatalogOffer.product_id==product_id).with_for_update()).first()
 if row:row.price=price;row.available=available;row.stock_quantity=stock_quantity;row.desired_version+=1;row.last_publication_status=PublicationItemStatusEnum.PENDING;row.updated_at=datetime.utcnow()
 else:row=ChannelCatalogOffer(tenant_id=context.tenant_id,store_id=conn.store_id,merchant_connection_id=conn.id,product_id=product_id,price=price,available=available,stock_quantity=stock_quantity);session.add(row)
 session.commit();session.refresh(row);reliability_service.save_idempotency_record(session,context.tenant_id,a,"channel.catalog.offer",idempotency_key,payload,200,{"offer_id":str(row.id)});session.commit();session.refresh(row);return row
def create_batch(session,context,*,connection_id,offer_ids,actor_id,idempotency_key):
 a=actor(context,actor_id);conn=connection(session,context,connection_id);payload={"connection_id":str(connection_id),"offer_ids":sorted(map(str,offer_ids))};digest=reliability_service.compute_request_hash(payload);existing=session.exec(select(ChannelPublicationBatch).where(ChannelPublicationBatch.tenant_id==context.tenant_id,ChannelPublicationBatch.idempotency_key==idempotency_key)).first()
 if existing:
  if existing.request_hash!=digest:raise HTTPException(409,"Idempotency-Key reutilizada.")
  return batch_projection(session,existing)
 offers=list(session.exec(select(ChannelCatalogOffer).where(ChannelCatalogOffer.id.in_(offer_ids),ChannelCatalogOffer.merchant_connection_id==conn.id)).all())
 if len(offers)!=len(set(offer_ids)):raise HTTPException(404,"Oferta de canal não encontrada.")
 batch=ChannelPublicationBatch(tenant_id=context.tenant_id,store_id=conn.store_id,merchant_connection_id=conn.id,idempotency_key=idempotency_key,request_hash=digest,created_by=a);session.add(batch);session.flush()
 for offer in offers:session.add(ChannelPublicationItem(tenant_id=context.tenant_id,batch_id=batch.id,offer_id=offer.id,desired_version=offer.desired_version,provider_operation_key=f"catalog:{conn.id}:{offer.id}:v{offer.desired_version}"))
 session.commit();session.refresh(batch);return batch_projection(session,batch)
def batch_projection(session,batch):return {"batch":batch,"items":list(session.exec(select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id==batch.id).order_by(ChannelPublicationItem.created_at)).all())}
def apply_results(session,context,batch_id,results,actor_id):
 a=actor(context,actor_id);batch=session.exec(scope_tenant_query(select(ChannelPublicationBatch).where(ChannelPublicationBatch.id==batch_id).with_for_update(),ChannelPublicationBatch,context)).first()
 if not batch:raise HTTPException(404,"Lote não encontrado.")
 items={row.offer_id:row for row in session.exec(select(ChannelPublicationItem).where(ChannelPublicationItem.batch_id==batch.id)).all()}
 for result in results:
  item=items.get(result["offer_id"])
  if not item:raise HTTPException(404,"Item não pertence ao lote.")
  item.attempt_count+=1;item.updated_at=datetime.utcnow();offer=session.get(ChannelCatalogOffer,item.offer_id)
  if result["success"]:item.status=PublicationItemStatusEnum.SUCCEEDED;item.provider_result_ref=result.get("provider_result_ref");item.error_code=None;item.error_message=None;offer.published_version=max(offer.published_version,item.desired_version);offer.last_publication_status=PublicationItemStatusEnum.SUCCEEDED
  else:item.status=PublicationItemStatusEnum.FAILED;item.error_code=result.get("error_code") or "PROVIDER_REJECTED";item.error_message=result.get("error_message");offer.last_publication_status=PublicationItemStatusEnum.FAILED
 statuses=[i.status for i in items.values()];batch.status=PublicationStatusEnum.SUCCEEDED if all(s==PublicationItemStatusEnum.SUCCEEDED for s in statuses) else PublicationStatusEnum.FAILED if all(s==PublicationItemStatusEnum.FAILED for s in statuses) else PublicationStatusEnum.PARTIAL;batch.updated_at=datetime.utcnow()
 reliability_service.write_audit_and_outbox(session,context.tenant_id,batch.store_id,a,"channel.catalog.results",f"PUBLICATION-{batch.id}",{"status":batch.status.value},"channel_publication",str(batch.id),"channel.catalog.results",{"status":batch.status.value});session.commit();return batch_projection(session,batch)
def list_catalog(session,context):
 offers=list(session.exec(scope_tenant_query(select(ChannelCatalogOffer).order_by(ChannelCatalogOffer.updated_at.desc()),ChannelCatalogOffer,context)).all());batches=list(session.exec(scope_tenant_query(select(ChannelPublicationBatch).order_by(ChannelPublicationBatch.created_at.desc()).limit(50),ChannelPublicationBatch,context)).all());return {"offers":offers,"batches":batches}
def create_settlement(session,context,*,connection_id,provider_document_ref,external_order_id,order_id,competence_date,gross,commission,fee,promotion,adjustment,actor_id,idempotency_key):
 a=actor(context,actor_id);conn=connection(session,context,connection_id);expected=gross-commission-fee-promotion+adjustment;payload={"connection_id":str(connection_id),"provider_document_ref":provider_document_ref,"external_order_id":external_order_id,"order_id":str(order_id) if order_id else None,"competence_date":str(competence_date),"gross":str(gross),"commission":str(commission),"fee":str(fee),"promotion":str(promotion),"adjustment":str(adjustment)};digest=reliability_service.compute_request_hash(payload);existing=session.exec(select(MarketplaceSettlement).where(MarketplaceSettlement.tenant_id==context.tenant_id,MarketplaceSettlement.idempotency_key==idempotency_key)).first()
 if existing:
  if existing.request_hash!=digest:raise HTTPException(409,"Idempotency-Key reutilizada.")
  return existing
 if order_id:
  order=session.exec(scope_tenant_query(select(Order).where(Order.id==order_id),Order,context)).first()
  if not order:raise HTTPException(404,"Order canônico não encontrado.")
 row=MarketplaceSettlement(tenant_id=context.tenant_id,store_id=conn.store_id,merchant_connection_id=conn.id,provider_document_ref=provider_document_ref,external_order_id=external_order_id,order_id=order_id,competence_date=competence_date,gross_amount=gross,commission_amount=commission,fee_amount=fee,promotion_amount=promotion,adjustment_amount=adjustment,expected_net_amount=expected,idempotency_key=idempotency_key,request_hash=digest,created_by=a);session.add(row);session.commit();session.refresh(row);return row
def record_payment(session,context,settlement_id,*,provider_payment_ref,amount,paid_at,actor_id):
 a=actor(context,actor_id);row=session.exec(scope_tenant_query(select(MarketplaceSettlement).where(MarketplaceSettlement.id==settlement_id).with_for_update(),MarketplaceSettlement,context)).first()
 if not row:raise HTTPException(404,"Repasse não encontrado.")
 existing=session.exec(select(MarketplaceSettlementPayment).where(MarketplaceSettlementPayment.settlement_id==row.id,MarketplaceSettlementPayment.provider_payment_ref==provider_payment_ref)).first()
 if existing:return row
 session.add(MarketplaceSettlementPayment(tenant_id=context.tenant_id,settlement_id=row.id,provider_payment_ref=provider_payment_ref,amount=amount,paid_at=paid_at));row.paid_amount+=amount;row.status=SettlementStatusEnum.PAID if row.paid_amount==row.expected_net_amount else SettlementStatusEnum.PARTIAL if row.paid_amount<row.expected_net_amount else SettlementStatusEnum.DIVERGENT;row.updated_at=datetime.utcnow();reliability_service.write_audit_and_outbox(session,context.tenant_id,row.store_id,a,"marketplace.settlement.paid",f"SETTLEMENT-{row.id}",{"provider_payment_ref":provider_payment_ref,"amount":str(amount),"status":row.status.value},"marketplace_settlement",str(row.id),"marketplace.settlement.paid",{"status":row.status.value});session.commit();session.refresh(row);return row
def list_settlements(session,context):return list(session.exec(scope_tenant_query(select(MarketplaceSettlement).order_by(MarketplaceSettlement.competence_date.desc()),MarketplaceSettlement,context)).all())
