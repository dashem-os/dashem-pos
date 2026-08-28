import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path: string) => readFile(new URL(path, import.meta.url), 'utf8')

test('exposes a real SaaS finance view without tenant operating data', async () => {
  const shell = await source('../src/components/owner/OwnerConsoleShell.tsx')
  const finance = await source('../src/components/owner/FinanceSaasView.tsx')
  const workspace = await source('../src/components/owner/TenantWorkspace.tsx')
  const api = await source('../src/services/api.ts')

  assert.match(shell, /label="Financeiro SaaS"/)
  assert.match(finance, /fetchPlatformFinanceOverview/)
  assert.match(finance, /Disponível com fonte real/)
  assert.match(finance, /Em implementação/)
  assert.match(finance, /não recebem valor zero fictício/)
  assert.doesNotMatch(finance, /overview\?\.overdue_subscriptions/)
  assert.doesNotMatch(finance, /billing_status/)
  assert.match(api, /platform\/finance\/overview/)
  assert.match(api, /platform\/finance\/billing-accounts/)
  assert.match(workspace, /Conta de cobrança/)
  assert.match(workspace, /expected_version: account\?\.version \?\? 0/)
  assert.match(workspace, /Não contém faturamento, caixa, vendas ou lucro do tenant/)
  for (const forbidden of ['vendas do tenant', 'caixas abertos', 'lucro do tenant']) {
    assert.doesNotMatch(finance.toLowerCase(), new RegExp(forbidden))
  }
})
