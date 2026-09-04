import os,uuid
import httpx,pytest
from sqlmodel import Session
from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.platform import TenantCapability, EntitlementStatusEnum
BASE_URL=os.getenv("TEST_BASE_URL","http://localhost:8002")
async def base(client,label):
 s=uuid.uuid4().hex[:8];actor=str(uuid.uuid4());tenant=(await client.post('/api/v1/identity/tenants',json={'name':label,'slug':f'{label.lower()}-{s}'})).json();store=(await client.post('/api/v1/identity/stores',json={'tenant_id':tenant['id'],'name':'Matriz','code':s})).json()
 with Session(engine) as db:
  set_platform_db_context(db)
  db.add(TenantCapability(tenant_id=uuid.UUID(tenant['id']), key='table_service', enabled=True, status=EntitlementStatusEnum.ACTIVE))
  db.commit()
 h={'X-Tenant-ID':tenant['id'],'X-Store-ID':store['id']};return tenant,store,h,actor
async def tab(client,h,store,actor,label):
 r=await client.post('/api/v1/tables/sessions',headers={**h,'Idempotency-Key':f'tab-{uuid.uuid4()}'},json={'store_id':store['id'],'display_label':label,'actor_id':actor});assert r.status_code==200,r.text;return r.json()
@pytest.mark.asyncio
async def test_s12_conserves_item_value_records_lineage_conflicts_and_merges_explicitly():
 async with httpx.AsyncClient(base_url=BASE_URL) as client:
  tenant,store,h,actor=await base(client,'Transfer');source=await tab(client,h,store,actor,'Origem');dest=await tab(client,h,store,actor,'Destino')
  product=(await client.post('/api/v1/catalog/products',headers=h,json={'name':'Produto transferível','sku':f'T-{uuid.uuid4().hex[:8]}','unit':'UN'})).json();await client.post('/api/v1/catalog/prices',headers=h,json={'product_id':product['id'],'store_id':store['id'],'cost_price':4,'sale_price':15})
  await client.post('/api/v1/catalog/assortments',headers=h,json={'code':f'ASSORT-TR-{uuid.uuid4().hex[:8]}','name':'Mesas','scopes':[{'store_id':store['id'],'sales_context':'TABLE'}],'product_ids':[product['id']]})
  item=(await client.post(f"/api/v1/orders/{source['orders'][0]['id']}/items",headers={**h,'Idempotency-Key':f'item-{uuid.uuid4()}'},json={'product_id':product['id'],'quantity':3,'actor_id':actor})).json()
  source=(await client.get(f"/api/v1/tables/sessions/{source['id']}",headers=h)).json();dest=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json();key=f'transfer-{uuid.uuid4()}'
  payload={'source_session_id':source['id'],'destination_session_id':dest['id'],'order_item_id':item['id'],'quantity':1,'expected_source_version':source['version'],'expected_destination_version':dest['version'],'reason':'Cliente mudou de comanda','actor_id':actor}
  moved=await client.post('/api/v1/transfers/items',headers={**h,'Idempotency-Key':key},json=payload);assert moved.status_code==200,moved.text;record=moved.json();assert float(record['quantity'])*float(record['unit_price_snapshot'])==15
  retry=await client.post('/api/v1/transfers/items',headers={**h,'Idempotency-Key':key},json=payload);assert retry.json()['id']==record['id']
  source_after=(await client.get(f"/api/v1/tables/sessions/{source['id']}",headers=h)).json();dest_after=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json()
  sq=sum(float(i['quantity'])*float(i['unit_price']) for o in source_after['orders'] for i in o['items'] if i['status']=='ACTIVE');dq=sum(float(i['quantity'])*float(i['unit_price']) for o in dest_after['orders'] for i in o['items'] if i['status']=='ACTIVE');assert sq+dq==45 and sq==30 and dq==15
  stale=await client.post('/api/v1/transfers/items',headers={**h,'Idempotency-Key':f'transfer-{uuid.uuid4()}'},json={**payload,'quantity':0.5});assert stale.status_code==409 and stale.json()['detail']['code']=='TRANSFER_VERSION_CONFLICT'
  history=(await client.get(f"/api/v1/transfers?table_session_id={source['id']}",headers=h)).json();assert history[0]['derived_order_item_id']==record['derived_order_item_id']
  order=(await client.post(f"/api/v1/tables/sessions/{source['id']}/orders",headers={**h,'Idempotency-Key':f'order-{uuid.uuid4()}'},json={'display_reference':'Grupo varanda','actor_id':actor})).json()
  await client.post(f"/api/v1/orders/{order['id']}/items",headers={**h,'Idempotency-Key':f'item-{uuid.uuid4()}'},json={'product_id':product['id'],'quantity':2,'actor_id':actor})
  source=(await client.get(f"/api/v1/tables/sessions/{source['id']}",headers=h)).json();dest_after=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json();order_key=f'order-transfer-{uuid.uuid4()}'
  order_payload={'source_session_id':source['id'],'destination_session_id':dest_after['id'],'order_id':order['id'],'expected_source_version':source['version'],'expected_destination_version':dest_after['version'],'reason':'Grupo mudou para a varanda','actor_id':actor}
  order_move=await client.post('/api/v1/transfers/orders',headers={**h,'Idempotency-Key':order_key},json=order_payload);assert order_move.status_code==200,order_move.text
  assert order_move.json()['transfer_type']=='ORDER' and order_move.json()['source_order_id']==order['id'] and order_move.json()['destination_order_id']==order['id']
  order_retry=await client.post('/api/v1/transfers/orders',headers={**h,'Idempotency-Key':order_key},json=order_payload);assert order_retry.json()['id']==order_move.json()['id']
  source_after=(await client.get(f"/api/v1/tables/sessions/{source['id']}",headers=h)).json();dest_after=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json()
  assert all(item['id']!=order['id'] for item in source_after['orders']) and any(item['id']==order['id'] for item in dest_after['orders'])
  assert any(event['event_type']=='table_session.order.transferred_out' and event['actor_id']==actor for event in source_after['events'])
  assert any(event['event_type']=='table_session.order.transferred_in' and event['actor_id']==actor for event in dest_after['events'])
  empty=await tab(client,h,store,actor,'Unir');empty=(await client.get(f"/api/v1/tables/sessions/{empty['id']}",headers=h)).json();dest_after=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json()
  merged=await client.post('/api/v1/transfers/merge',headers={**h,'Idempotency-Key':f'merge-{uuid.uuid4()}'},json={'source_session_id':empty['id'],'destination_session_id':dest_after['id'],'expected_source_version':empty['version'],'expected_destination_version':dest_after['version'],'reason':'Consolidar atendimento','actor_id':actor});assert merged.status_code==200,merged.text
  dest_after=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json();assert any(event['event_type']=='table_session.merged_in' and event['actor_id']==actor for event in dest_after['events'])
  _,other_store,other_h,_=await base(client,'OtherTransfer');foreign=await client.get('/api/v1/transfers',headers=other_h);assert all(x['id']!=record['id'] for x in foreign.json())

@pytest.mark.asyncio
async def test_individual_orders_can_pay_and_leave_the_other_groups_active():
 async with httpx.AsyncClient(base_url=BASE_URL) as client:
  _,store,h,actor=await base(client,'IndividualPay');table_session=await tab(client,h,store,actor,'Mesa grupos');first=table_session['orders'][0]
  second=(await client.post(f"/api/v1/tables/sessions/{table_session['id']}/orders",headers={**h,'Idempotency-Key':f'order-{uuid.uuid4()}'},json={'display_reference':'Grupo B','actor_id':actor})).json()
  product=(await client.post('/api/v1/catalog/products',headers=h,json={'name':'Consumo individual','sku':f'I-{uuid.uuid4().hex[:8]}','unit':'UN'})).json();await client.post('/api/v1/catalog/prices',headers=h,json={'product_id':product['id'],'store_id':store['id'],'cost_price':3,'sale_price':12})
  await client.post('/api/v1/catalog/assortments',headers=h,json={'code':f'ASSORT-IP-{uuid.uuid4().hex[:8]}','name':'Pagamento individual','scopes':[{'store_id':store['id'],'sales_context':'TABLE'}],'product_ids':[product['id']]})
  for order in (first,second):
   added=await client.post(f"/api/v1/orders/{order['id']}/items",headers={**h,'Idempotency-Key':f'item-{uuid.uuid4()}'},json={'product_id':product['id'],'quantity':1,'actor_id':actor});assert added.status_code==200,added.text
  async def pay(order_id):
   opened=await client.post('/api/v1/negotiations',headers={**h,'Idempotency-Key':f'neg-{uuid.uuid4()}'},json={'store_id':store['id'],'order_ids':[order_id],'actor_id':actor});assert opened.status_code==200,opened.text;negotiation=opened.json()
   created=await client.post(f"/api/v1/negotiations/{negotiation['id']}/intents",headers={**h,'Idempotency-Key':f'intent-{uuid.uuid4()}'},json={'method':'PIX','amount':12,'allocations':[{'amount':12,'order_id':order_id}],'actor_id':actor});assert created.status_code==200,created.text;intent=created.json()['intents'][-1]
   confirmed=await client.post(f"/api/v1/negotiations/intents/{intent['id']}/confirm",headers={**h,'Idempotency-Key':f'confirm-{uuid.uuid4()}'},json={'actor_id':actor});assert confirmed.status_code==200,confirmed.text
   finalized=await client.post(f"/api/v1/negotiations/{negotiation['id']}/finalize",headers={**h,'Idempotency-Key':f'final-{uuid.uuid4()}'},json={'expected_version':confirmed.json()['version'],'actor_id':actor});assert finalized.status_code==200,finalized.text
   return finalized.json()
  first_payment=await pay(first['id']);assert first_payment['allocations'][0]['order_id']==first['id']
  remaining=(await client.get(f"/api/v1/tables/sessions/{table_session['id']}",headers=h)).json();assert remaining['active_item_count']==1 and float(remaining['consolidated_total'])==12
  assert next(order for order in remaining['orders'] if order['id']==first['id'])['status']=='CLOSED' and next(order for order in remaining['orders'] if order['id']==second['id'])['status']=='OPEN'
  destination=await tab(client,h,store,actor,'Destino ainda aberto')
  blocked_merge=await client.post('/api/v1/transfers/merge',headers={**h,'Idempotency-Key':f'merge-{uuid.uuid4()}'},json={'source_session_id':remaining['id'],'destination_session_id':destination['id'],'expected_source_version':remaining['version'],'expected_destination_version':destination['version'],'reason':'Tentativa após pagamento individual','actor_id':actor});assert blocked_merge.status_code==409 and 'cobertos por pagamento' in blocked_merge.text
  await pay(second['id']);empty=(await client.get(f"/api/v1/tables/sessions/{table_session['id']}",headers=h)).json();assert empty['active_item_count']==0 and float(empty['consolidated_total'])==0
  closed=await client.post(f"/api/v1/tables/sessions/{table_session['id']}/close",headers={**h,'Idempotency-Key':f'close-{uuid.uuid4()}'},json={'expected_version':empty['version'],'reason':'Todas as comandas foram pagas individualmente','actor_id':actor});assert closed.status_code==200,closed.text

@pytest.mark.asyncio
async def test_s12_splits_a_group_and_moves_a_whole_session_to_free_tables():
 async with httpx.AsyncClient(base_url=BASE_URL) as client:
  _,store,h,actor=await base(client,'FreeTableMove');source=await tab(client,h,store,actor,'Grupo de origem')
  group=(await client.post(f"/api/v1/tables/sessions/{source['id']}/orders",headers={**h,'Idempotency-Key':f'order-{uuid.uuid4()}'},json={'display_reference':'Grupo separado','actor_id':actor})).json()
  async def create_table(label):
   response=await client.post('/api/v1/tables',headers={**h,'Idempotency-Key':f'table-{uuid.uuid4()}'},json={'store_id':store['id'],'code':f'M-{uuid.uuid4().hex[:6]}','name':label,'capacity':4,'actor_id':actor});assert response.status_code==200,response.text;return response.json()
  varanda=await create_table('Varanda');source=(await client.get(f"/api/v1/tables/sessions/{source['id']}",headers=h)).json()
  split=await client.post('/api/v1/transfers/orders/to-table',headers={**h,'Idempotency-Key':f'split-{uuid.uuid4()}'},json={'source_session_id':source['id'],'destination_table_id':varanda['id'],'order_id':group['id'],'expected_source_version':source['version'],'expected_table_version':varanda['version'],'reason':'Grupo escolheu a varanda','actor_id':actor});assert split.status_code==200,split.text;record=split.json()
  destination=(await client.get(f"/api/v1/tables/sessions/{record['destination_session_id']}",headers=h)).json();assert destination['service_table_id']==varanda['id'] and [order['id'] for order in destination['orders']]==[group['id']]
  assert any(event['event_type']=='table_session.opened_by_transfer' and event['actor_id']==actor for event in destination['events'])
  movable=await tab(client,h,store,actor,'Balcão para mesa');sala=await create_table('Segundo andar')
  moved=await client.post('/api/v1/transfers/sessions/to-table',headers={**h,'Idempotency-Key':f'move-{uuid.uuid4()}'},json={'source_session_id':movable['id'],'destination_table_id':sala['id'],'expected_source_version':movable['version'],'expected_table_version':sala['version'],'reason':'Cliente mudou para o segundo andar','actor_id':actor});assert moved.status_code==200,moved.text
  assert moved.json()['transfer_type']=='SESSION_MOVE' and moved.json()['source_session_id']==movable['id'] and moved.json()['destination_session_id']==movable['id']
  same_session=(await client.get(f"/api/v1/tables/sessions/{movable['id']}",headers=h)).json();assert same_session['service_table_id']==sala['id'] and same_session['kind']=='TABLE'
  assert any(event['event_type']=='table_session.moved' and event['actor_id']==actor for event in same_session['events'])
