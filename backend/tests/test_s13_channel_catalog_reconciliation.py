import os,uuid
from datetime import datetime,date
import httpx,pytest
BASE_URL=os.getenv('TEST_BASE_URL','http://localhost:8002')
async def setup(client,label):
 s=uuid.uuid4().hex[:8];actor=str(uuid.uuid4());tenant=(await client.post('/api/v1/identity/tenants',json={'name':label,'slug':f'{label.lower()}-{s}'})).json();store=(await client.post('/api/v1/identity/stores',json={'tenant_id':tenant['id'],'name':'Matriz','code':s})).json();h={'X-Tenant-ID':tenant['id'],'X-Store-ID':store['id']};key=f'conn-{uuid.uuid4()}';created=(await client.post('/api/v1/channels/connections',headers={**h,'Idempotency-Key':key},json={'store_id':store['id'],'provider_code':'CONTRACT_TEST','merchant_external_id':f'm-{s}','channel_name':'Canal','credentials_ref':'secret://test','actor_id':actor})).json();conn=created['connection'];await client.post(f"/api/v1/channels/connections/{conn['id']}/validate",headers={**h,'Idempotency-Key':f'validate-{uuid.uuid4()}'},json={'actor_id':actor});return tenant,store,h,actor,conn
async def product(client,h,store,name):
 p=(await client.post('/api/v1/catalog/products',headers=h,json={'name':name,'sku':f'SKU-{uuid.uuid4().hex[:8]}','unit':'UN'})).json();await client.post('/api/v1/catalog/prices',headers=h,json={'product_id':p['id'],'store_id':store['id'],'cost_price':3,'sale_price':10});return p
@pytest.mark.asyncio
async def test_s13_keeps_canonical_identity_partial_publication_and_settlement_separate():
 async with httpx.AsyncClient(base_url=BASE_URL) as client:
  tenant,store,h,actor,conn=await setup(client,'CatalogChannel');p1=await product(client,h,store,'Produto A');p2=await product(client,h,store,'Produto B')
  for p,external in ((p1,'EXT-A'),(p2,'EXT-B')):
   mapped=await client.post('/api/v1/channel-catalog/mappings',headers={**h,'Idempotency-Key':f'map-{uuid.uuid4()}'},json={'connection_id':conn['id'],'entity_type':'PRODUCT','internal_id':p['id'],'external_id':external,'actor_id':actor});assert mapped.status_code==200,mapped.text
  offers=[]
  for p in (p1,p2):
   offer=await client.post('/api/v1/channel-catalog/offers',headers={**h,'Idempotency-Key':f'offer-{uuid.uuid4()}'},json={'connection_id':conn['id'],'product_id':p['id'],'price':12,'available':True,'stock_quantity':5,'actor_id':actor});assert offer.status_code==200,offer.text;assert 'id' in offer.json(),offer.text;offers.append(offer.json())
  key=f'batch-{uuid.uuid4()}';payload={'connection_id':conn['id'],'offer_ids':[o['id'] for o in offers],'actor_id':actor};batch=await client.post('/api/v1/channel-catalog/publications',headers={**h,'Idempotency-Key':key},json=payload);assert batch.status_code==200,batch.text;body=batch.json();retry=await client.post('/api/v1/channel-catalog/publications',headers={**h,'Idempotency-Key':key},json=payload);assert retry.json()['batch']['id']==body['batch']['id']
  results=await client.post(f"/api/v1/channel-catalog/publications/{body['batch']['id']}/results",headers=h,json={'actor_id':actor,'results':[{'offer_id':offers[0]['id'],'success':True,'provider_result_ref':'provider-ok'},{'offer_id':offers[1]['id'],'success':False,'error_code':'INVALID_CATEGORY','error_message':'Documento provider 55'}]});assert results.status_code==200,results.text;assert results.json()['batch']['status']=='PARTIAL';states={x['offer_id']:x['status'] for x in results.json()['items']};assert states[offers[0]['id']]=='SUCCEEDED' and states[offers[1]['id']]=='FAILED'
  retry_failed=await client.post('/api/v1/channel-catalog/publications',headers={**h,'Idempotency-Key':f'batch-{uuid.uuid4()}'},json={'connection_id':conn['id'],'offer_ids':[offers[1]['id']],'actor_id':actor});assert retry_failed.status_code==200;old_key=next(x['provider_operation_key'] for x in body['items'] if x['offer_id']==offers[1]['id']);assert retry_failed.json()['items'][0]['provider_operation_key']==old_key
  settlement=await client.post('/api/v1/channel-catalog/settlements',headers={**h,'Idempotency-Key':f'settlement-{uuid.uuid4()}'},json={'connection_id':conn['id'],'provider_document_ref':'DOC-55','external_order_id':'ORDER-EXT-1','competence_date':str(date.today()),'gross_amount':100,'commission_amount':20,'fee_amount':5,'promotion_amount':0,'adjustment_amount':-2,'actor_id':actor});assert settlement.status_code==200,settlement.text;settlement=settlement.json();assert settlement['status']=='PENDING' and float(settlement['expected_net_amount'])==73 and float(settlement['paid_amount'])==0
  paid=await client.post(f"/api/v1/channel-catalog/settlements/{settlement['id']}/payments",headers=h,json={'provider_payment_ref':'PAY-1','amount':70,'paid_at':datetime.utcnow().isoformat(),'actor_id':actor});assert paid.status_code==200 and paid.json()['status']=='PARTIAL';repeat=await client.post(f"/api/v1/channel-catalog/settlements/{settlement['id']}/payments",headers=h,json={'provider_payment_ref':'PAY-1','amount':70,'paid_at':datetime.utcnow().isoformat(),'actor_id':actor});assert float(repeat.json()['paid_amount'])==70
  _,_,foreign_h,_,_=await setup(client,'OtherCatalog');assert all(x['id']!=settlement['id'] for x in (await client.get('/api/v1/channel-catalog/settlements',headers=foreign_h)).json())

@pytest.mark.asyncio
async def test_s13_the_window_hands_the_screen_names_and_never_the_neighbours():
 """What the shopkeeper reads must be resolved by the server.

 Publishing to a marketplace is only usable if the person recognises the row:
 the product by its name, the channel by its merchant. Making the browser join
 two lists to find that out is how a screen ends up showing an identifier, or
 the wrong name, or a name from another tenant."""
 async with httpx.AsyncClient(base_url=BASE_URL) as client:
  tenant,store,h,actor,conn=await setup(client,'ChannelWindow');p1=await product(client,h,store,'Pizza Marguerita');p2=await product(client,h,store,'Refrigerante Lata')
  await client.post('/api/v1/channel-catalog/mappings',headers={**h,'Idempotency-Key':f'map-{uuid.uuid4()}'},json={'connection_id':conn['id'],'entity_type':'PRODUCT','internal_id':p1['id'],'external_id':'EXT-PIZZA','actor_id':actor})
  offers=[(await client.post('/api/v1/channel-catalog/offers',headers={**h,'Idempotency-Key':f'offer-{uuid.uuid4()}'},json={'connection_id':conn['id'],'product_id':p['id'],'price':29,'available':True,'actor_id':actor})).json() for p in (p1,p2)]
  batch=(await client.post('/api/v1/channel-catalog/publications',headers={**h,'Idempotency-Key':f'batch-{uuid.uuid4()}'},json={'connection_id':conn['id'],'offer_ids':[o['id'] for o in offers],'actor_id':actor})).json()
  await client.post(f"/api/v1/channel-catalog/publications/{batch['batch']['id']}/results",headers=h,json={'actor_id':actor,'results':[{'offer_id':offers[1]['id'],'success':False,'error_code':'INVALID_CATEGORY','error_message':'Categoria inexistente no canal'}]})

  state=(await client.get('/api/v1/channel-catalog/catalog',headers=h)).json()
  named={row['product_name'] for row in state['offers']};assert named=={'Pizza Marguerita','Refrigerante Lata'},state['offers']
  assert all(row['product_sku'] and row['provider_code']=='CONTRACT_TEST' and row['merchant_external_id'] for row in state['offers'])
  # The item-by-item answer travels with the batch, named, so a partial failure
  # is readable without a second round trip per row.
  published=next(row for row in state['batches'] if row['id']==batch['batch']['id'])
  assert published['status']=='PARTIAL',published
  failed=next(item for item in published['items'] if item['status']=='FAILED')
  assert failed['product_name']=='Refrigerante Lata' and failed['error_code']=='INVALID_CATEGORY'
  assert any(item['status']=='PENDING' and item['product_name']=='Pizza Marguerita' for item in published['items'])
  assert [row['internal_name'] for row in state['mappings']]==['Pizza Marguerita']

  settlement=(await client.post('/api/v1/channel-catalog/settlements',headers={**h,'Idempotency-Key':f'settlement-{uuid.uuid4()}'},json={'connection_id':conn['id'],'provider_document_ref':'DOC-WINDOW','competence_date':str(date.today()),'gross_amount':100,'commission_amount':20,'fee_amount':0,'promotion_amount':0,'adjustment_amount':0,'actor_id':actor})).json()
  await client.post(f"/api/v1/channel-catalog/settlements/{settlement['id']}/payments",headers=h,json={'provider_payment_ref':'PAY-WINDOW','amount':30,'paid_at':datetime.utcnow().isoformat(),'actor_id':actor})
  listed=next(row for row in (await client.get('/api/v1/channel-catalog/settlements',headers=h)).json() if row['id']==settlement['id'])
  assert listed['provider_code']=='CONTRACT_TEST' and listed['status']=='PARTIAL'
  assert [pay['provider_payment_ref'] for pay in listed['payments']]==['PAY-WINDOW']

  # The enriched shape is where a join could leak a neighbour. It does not.
  _,_,foreign_h,_,_=await setup(client,'ForeignWindow')
  foreign=(await client.get('/api/v1/channel-catalog/catalog',headers=foreign_h)).json()
  assert foreign['offers']==[] and foreign['batches']==[] and foreign['mappings']==[]
  assert (await client.get('/api/v1/channel-catalog/settlements',headers=foreign_h)).json()==[]
