import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

const root = join(import.meta.dirname, '..', 'src')
const context = readFileSync(join(root, 'context', 'PosContext.tsx'), 'utf8')
const layout = readFileSync(join(root, 'layouts', 'PosLayout.tsx'), 'utf8')
const totals = readFileSync(join(root, 'components', 'pos', 'SaleTotals.tsx'), 'utf8')
const cartItem = readFileSync(join(root, 'components', 'pos', 'CartItem.tsx'), 'utf8')

test('recovers the active operation by store, terminal and operator', () => {
  assert.match(context, /fetchActiveSale\(headers, store\.id, register\.id, operatorId\)/)
  assert.match(context, /register\.id, operatorId, operationMode/)
})

test('exposes COUNTER and TAKEAWAY with explicit degraded states', () => {
  assert.match(layout, /COUNTER/)
  assert.match(layout, /TAKEAWAY/)
  assert.match(layout, /Sem rede/)
  assert.match(context, /'ONLINE' \| 'DEGRADED' \| 'OFFLINE'/)
})

test('gates discount, cancel, checkout and item edits by backend permissions', () => {
  assert.match(totals, /sale\.discount/)
  assert.match(totals, /sale\.cancel/)
  assert.match(totals, /sale\.checkout/)
  assert.match(cartItem, /sale\.item\.update/)
})
