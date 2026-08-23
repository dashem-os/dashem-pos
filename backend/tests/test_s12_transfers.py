import os,uuid
import httpx,pytest
BASE_URL=os.getenv("TEST_BASE_URL","http://localhost:8002")
async def base(client,label):
 s=uuid.uuid4().hex[:8];actor=str(uuid.uuid4());tenant=(await client.post('/api/v1/identity/tenants',json={'name':label,'slug':f'{label.lower()}-{s}'})).json();store=(await client.post('/api/v1/identity/stores',json={'tenant_id':tenant['id'],'name':'Matriz','code':s})).json();h={'X-Tenant-ID':tenant['id'],'X-Store-ID':store['id']};return tenant,store,h,actor
async def tab(client,h,store,actor,label):
 r=await client.post('/api/v1/tables/sessions',headers={**h,'Idempotency-Key':f'tab-{uuid.uuid4()}'},json={'store_id':store['id'],'display_label':label,'actor_id':actor});assert r.status_code==200,r.text;return r.json()
@pytest.mark.asyncio
async def test_s12_conserves_item_value_records_lineage_conflicts_and_merges_explicitly():
 async with httpx.AsyncClient(base_url=BASE_URL) as client:
  tenant,store,h,actor=await base(client,'Transfer');source=await tab(client,h,store,actor,'Origem');dest=await tab(client,h,store,actor,'Destino')
  product=(await client.post('/api/v1/catalog/products',headers=h,json={'name':'Produto transferível','sku':f'T-{uuid.uuid4().hex[:8]}','unit':'UN'})).json();await client.post('/api/v1/catalog/prices',headers=h,json={'product_id':product['id'],'store_id':store['id'],'cost_price':4,'sale_price':15})
  item=(await client.post(f"/api/v1/orders/{source['orders'][0]['id']}/items",headers={**h,'Idempotency-Key':f'item-{uuid.uuid4()}'},json={'product_id':product['id'],'quantity':3,'actor_id':actor})).json()
  source=(await client.get(f"/api/v1/tables/sessions/{source['id']}",headers=h)).json();dest=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json();key=f'transfer-{uuid.uuid4()}'
  payload={'source_session_id':source['id'],'destination_session_id':dest['id'],'order_item_id':item['id'],'quantity':1,'expected_source_version':source['version'],'expected_destination_version':dest['version'],'reason':'Cliente mudou de comanda','actor_id':actor}
  moved=await client.post('/api/v1/transfers/items',headers={**h,'Idempotency-Key':key},json=payload);assert moved.status_code==200,moved.text;record=moved.json();assert float(record['quantity'])*float(record['unit_price_snapshot'])==15
  retry=await client.post('/api/v1/transfers/items',headers={**h,'Idempotency-Key':key},json=payload);assert retry.json()['id']==record['id']
  source_after=(await client.get(f"/api/v1/tables/sessions/{source['id']}",headers=h)).json();dest_after=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json()
  sq=sum(float(i['quantity'])*float(i['unit_price']) for o in source_after['orders'] for i in o['items'] if i['status']=='ACTIVE');dq=sum(float(i['quantity'])*float(i['unit_price']) for o in dest_after['orders'] for i in o['items'] if i['status']=='ACTIVE');assert sq+dq==45 and sq==30 and dq==15
  stale=await client.post('/api/v1/transfers/items',headers={**h,'Idempotency-Key':f'transfer-{uuid.uuid4()}'},json={**payload,'quantity':0.5});assert stale.status_code==409 and stale.json()['detail']['code']=='TRANSFER_VERSION_CONFLICT'
  history=(await client.get(f"/api/v1/transfers?table_session_id={source['id']}",headers=h)).json();assert history[0]['derived_order_item_id']==record['derived_order_item_id']
  empty=await tab(client,h,store,actor,'Unir');empty=(await client.get(f"/api/v1/tables/sessions/{empty['id']}",headers=h)).json();dest_after=(await client.get(f"/api/v1/tables/sessions/{dest['id']}",headers=h)).json()
  merged=await client.post('/api/v1/transfers/merge',headers={**h,'Idempotency-Key':f'merge-{uuid.uuid4()}'},json={'source_session_id':empty['id'],'destination_session_id':dest_after['id'],'expected_source_version':empty['version'],'expected_destination_version':dest_after['version'],'reason':'Consolidar atendimento','actor_id':actor});assert merged.status_code==200,merged.text
  _,other_store,other_h,_=await base(client,'OtherTransfer');foreign=await client.get('/api/v1/transfers',headers=other_h);assert all(x['id']!=record['id'] for x in foreign.json())
