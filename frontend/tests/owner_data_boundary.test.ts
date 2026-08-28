import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path: string) => readFile(new URL(path, import.meta.url), 'utf8')

test('keeps tenant operational metrics out of Dashem Control', async () => {
  const shell = await source('../src/components/owner/OwnerConsoleShell.tsx')
  const api = await source('../src/services/api.ts')

  for (const forbidden of ['Unidades ativas', 'Usuários ativos', 'Caixas abertos']) {
    assert.doesNotMatch(shell, new RegExp(forbidden))
  }
  assert.doesNotMatch(shell, /tenant\.store_count/)
  assert.doesNotMatch(api, /TenantOperationalMetrics/)
  assert.doesNotMatch(api, /fetchTenantMetrics/)
  assert.doesNotMatch(api, /platform\/tenants\/\$\{tenantId\}\/metrics/)
  assert.match(api, /pending_outbox: number/)
  assert.match(api, /failed_outbox: number/)
})
