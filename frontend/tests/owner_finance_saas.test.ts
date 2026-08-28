import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path: string) => readFile(new URL(path, import.meta.url), 'utf8')

test('exposes a real SaaS finance view without tenant operating data', async () => {
  const shell = await source('../src/components/owner/OwnerConsoleShell.tsx')
  const finance = await source('../src/components/owner/FinanceSaasView.tsx')
  const api = await source('../src/services/api.ts')

  assert.match(shell, /label="Financeiro SaaS"/)
  assert.match(finance, /fetchPlatformFinanceOverview/)
  assert.match(finance, /Base real disponível agora/)
  assert.match(finance, /Clique para filtrar os contratos/)
  assert.match(api, /platform\/finance\/overview/)
  for (const forbidden of ['vendas do tenant', 'caixas abertos', 'lucro do tenant']) {
    assert.doesNotMatch(finance.toLowerCase(), new RegExp(forbidden))
  }
})
