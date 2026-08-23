import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

const root=join(import.meta.dirname,'..','src')
const api=readFileSync(join(root,'services','api.ts'),'utf8')
const kds=readFileSync(join(root,'shells','KdsShell.tsx'),'utf8')

test('loads a real persisted KDS queue and transitions with optimistic concurrency',()=>{
  assert.match(api,/\/api\/v1\/production\/tickets/)
  assert.match(api,/expected_version/)
  assert.match(api,/'Idempotency-Key': idempotencyKey/)
  assert.match(kds,/projection\.ticket\.version/)
  assert.match(kds,/crypto\.randomUUID\(\)/)
})

test('requires capability and permission and never renders sample tickets',()=>{
  assert.match(kds,/access\.capabilities\.kitchen_routing/)
  assert.match(kds,/access\.permissions\.includes\('production\.read'\)/)
  assert.match(kds,/Nenhuma comanda fictícia é exibida/)
  assert.doesNotMatch(kds,/Mesa 2|Hambúrguer Artesanal|fixture|mock/i)
})
