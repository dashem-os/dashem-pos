import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

const api = readFileSync(join(import.meta.dirname, '..', 'src', 'services', 'api.ts'), 'utf8')

test('declares Order separately from Sale and carries operational snapshots', () => {
  assert.match(api, /export interface Order \{/)
  assert.match(api, /export interface Sale \{/)
  assert.match(api, /modifier_snapshot/)
  assert.match(api, /production_state/)
})

test('sends idempotency keys for every repeatable order command', () => {
  for (const functionName of ['createOrder', 'addOrderItem', 'updateOrderItem', 'cancelOrderItem']) {
    const start = api.indexOf(`export async function ${functionName}`)
    const end = api.indexOf('export async function ', start + 1)
    const body = api.slice(start, end < 0 ? undefined : end)
    assert.match(body, /'Idempotency-Key': idempotencyKey/)
  }
})
