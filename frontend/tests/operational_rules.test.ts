import assert from 'node:assert/strict'
import test from 'node:test'

import {
  authenticatedHome,
  canOperateCart,
  expectedCashBalance,
  normalizeAuthenticatedRoute,
  paymentProgress,
  saleNeedsCreation,
  selectOnlyOption,
} from '../src/domain/operationalRules.ts'

test('routes platform identities only to the owner control plane', () => {
  assert.equal(authenticatedHome('PLATFORM_OWNER'), '/owner')
  assert.equal(normalizeAuthenticatedRoute('/pos', 'PLATFORM_ADMIN'), '/owner')
})

test('keeps tenant identities out of owner and preserves an allowed tenant shell', () => {
  assert.equal(normalizeAuthenticatedRoute('/owner', null), '/pos')
  assert.equal(normalizeAuthenticatedRoute('/manage', null, false), '/pos')
  assert.equal(normalizeAuthenticatedRoute('/manage', null, true), '/manage')
  assert.equal(normalizeAuthenticatedRoute('/kds', null, false, true), '/kds')
})

test('auto-selects organizational context only when there is exactly one option', () => {
  assert.equal(selectOnlyOption([]), null)
  assert.equal(selectOnlyOption([{ id: 'tenant-a' }, { id: 'tenant-b' }]), null)
  assert.deepEqual(selectOnlyOption([{ id: 'tenant-a' }]), { id: 'tenant-a' })
})

test('requires an open cash session and starts a new cart only after terminal states', () => {
  assert.equal(canOperateCart('CLOSED'), false)
  assert.equal(canOperateCart('OPEN'), true)
  assert.equal(saleNeedsCreation('DRAFT'), false)
  assert.equal(saleNeedsCreation('AWAITING_PAYMENT'), false)
  assert.equal(saleNeedsCreation('COMPLETED'), true)
  assert.equal(saleNeedsCreation('CANCELED'), true)
})

test('calculates split payment balance and cash change without negative values', () => {
  assert.deepEqual(paymentProgress(100, [30, 20], 100, 50), {
    totalPaid: 50,
    remaining: 50,
    change: 50,
    settled: false,
  })
  assert.deepEqual(paymentProgress(100, [60, 40], 30, 40), {
    totalPaid: 100,
    remaining: 0,
    change: 0,
    settled: true,
  })
})

test('derives expected cash exclusively from the movement ledger', () => {
  assert.equal(expectedCashBalance(100, [
    { movement_type: 'OPENING', amount: 100 },
    { movement_type: 'SALE_PAYMENT', amount: 80 },
    { movement_type: 'REINFORCEMENT', amount: 20 },
    { movement_type: 'BLEED', amount: 50 },
    { movement_type: 'CLOSING', amount: 0 },
  ]), 150)
})
