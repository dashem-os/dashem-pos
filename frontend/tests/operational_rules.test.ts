import assert from 'node:assert/strict'
import test from 'node:test'

import {
  authenticatedHome,
  canNavigateToManagement,
  canOperateCart,
  deviceKindAvailability,
  expectedCashBalance,
  hasManagementAccess,
  initialPosDeviceDraft,
  normalizeAuthenticatedRoute,
  operationalRoleLabel,
  paymentProgress,
  requireAuthenticatedActor,
  saleNeedsCreation,
  selectOnlyOption,
  unboundRegisterCandidates,
} from '../src/domain/operationalRules.ts'

test('requires every mutation actor to come from the authenticated identity', () => {
  assert.equal(requireAuthenticatedActor({ id: 'actor-real' }), 'actor-real')
  assert.throws(() => requireAuthenticatedActor(null), /ator válido/)
  assert.throws(() => requireAuthenticatedActor({ id: '' }), /ator válido/)
})

test('routes platform identities only to the owner control plane', () => {
  assert.equal(authenticatedHome('PLATFORM_OWNER'), '/owner')
  assert.equal(normalizeAuthenticatedRoute('/pos', 'PLATFORM_ADMIN'), '/owner')
})

test('keeps tenant identities out of owner and preserves an allowed tenant shell', () => {
  assert.equal(normalizeAuthenticatedRoute('/owner', null), '/pos')
  assert.equal(authenticatedHome(null, true), '/manage')
  assert.equal(normalizeAuthenticatedRoute('/login', null, true), '/manage')
  assert.equal(normalizeAuthenticatedRoute('/', null, true), '/manage')
  assert.equal(normalizeAuthenticatedRoute('/manage', null, false), '/pos')
  assert.equal(normalizeAuthenticatedRoute('/manage', null, true), '/manage')
  assert.equal(normalizeAuthenticatedRoute('/pos', null, true), '/pos')
  assert.equal(normalizeAuthenticatedRoute('/kds', null, false, true), '/kds')
})

test('derives management authority from an active management membership and backend permission', () => {
  assert.equal(hasManagementAccess([{ role: 'MANAGER', status: 'ACTIVE' }]), true)
  assert.equal(hasManagementAccess([{ role: 'MANAGER', status: 'SUSPENDED' }]), false)
  assert.equal(hasManagementAccess([{ role: 'OPERATOR', status: 'ACTIVE' }]), false)
  assert.equal(canNavigateToManagement(true, ['management.read']), true)
  assert.equal(canNavigateToManagement(false, ['management.read']), false)
  assert.equal(canNavigateToManagement(true, ['sale.read']), false)
})

test('shows the operational role resolved by the backend in human language', () => {
  assert.equal(operationalRoleLabel('SUPERVISOR'), 'Supervisor')
  assert.equal(operationalRoleLabel('CASHIER'), 'Caixa')
  assert.equal(operationalRoleLabel('OPERATOR'), 'Operador')
  assert.equal(operationalRoleLabel(undefined), '')
})

test('publishes every device kind with honest capability availability', () => {
  assert.deepEqual(deviceKindAvailability(false), [
    { kind: 'POS', enabled: true },
    { kind: 'KDS', enabled: false, unavailableReason: 'Requer a capacidade kitchen_routing.' },
    { kind: 'PRINTER', enabled: false, unavailableReason: 'Requer a capacidade kitchen_routing.' },
  ])
  assert.deepEqual(deviceKindAvailability(true).map(({ kind, enabled }) => ({ kind, enabled })), [
    { kind: 'POS', enabled: true },
    { kind: 'KDS', enabled: true },
    { kind: 'PRINTER', enabled: true },
  ])
})

test('links a new POS to a real unbound register instead of inventing infrastructure', () => {
  const registers = [
    { id: 'register-a', code: 'CAIXA-01', name: 'Caixa principal' },
    { id: 'register-b', code: 'CAIXA-02', name: 'Caixa apoio' },
  ]
  assert.deepEqual(unboundRegisterCandidates(registers, [{ register_id: 'register-a' }]), [registers[1]])
  assert.deepEqual(initialPosDeviceDraft(registers, [{ register_id: 'register-a' }]), {
    device_type: 'POS', register_id: 'register-b', code: 'CAIXA-02', name: 'Caixa apoio',
  })
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
