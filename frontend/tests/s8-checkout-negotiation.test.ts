import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'


const root = join(import.meta.dirname, '..', 'src')
const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
const workspace = readFileSync(join(root, 'components', 'tables', 'TableServiceWorkspace.tsx'), 'utf8')

test('uses the server negotiation projection as the payment authority', () => {
  assert.match(api, /openCheckoutNegotiation/)
  assert.match(api, /createNegotiationPaymentIntent/)
  assert.match(api, /confirmNegotiationPaymentIntent/)
  assert.match(api, /finalizeCheckoutNegotiation/)
  assert.match(workspace, /negotiation\.remaining_amount/)
  assert.doesNotMatch(workspace, /total_due\s*-/)
})

test('keeps consumption frozen and releases the table only after explicit finalization', () => {
  assert.match(workspace, /permissions\.includes\('checkout\.open'\)/)
  assert.match(workspace, /permissions\.includes\('checkout\.payment'\)/)
  assert.match(workspace, /permissions\.includes\('checkout\.finalize'\)/)
  assert.match(workspace, /Finalizar venda e liberar mesa/)
  assert.match(workspace, /!negotiation/)
})

test('labels manual methods honestly and never presents a fake provider', () => {
  assert.match(workspace, /PIX manual/)
  assert.match(workspace, /Crédito manual/)
  assert.doesNotMatch(workspace, /FAKE_PSP|pagamento aprovado automaticamente/)
})
