import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path: string) => readFile(new URL(path, import.meta.url), 'utf8')

test('gives the Owner a real commercial plan catalog before tenant contracting', async () => {
  const shell = await source('../src/components/owner/OwnerConsoleShell.tsx')
  const plans = await source('../src/components/owner/ServicePlansView.tsx')
  const workspace = await source('../src/components/owner/TenantWorkspace.tsx')
  const api = await source('../src/services/api.ts')

  assert.match(shell, /label="Planos comerciais"/)
  assert.match(shell, /fetchServicePlans\(\)/)
  assert.match(shell, /Verificando…/)
  assert.match(plans, /Nenhum plano comercial cadastrado/)
  assert.match(plans, /Cadastrar primeiro plano/)
  assert.match(plans, /Salvando…/)
  assert.match(workspace, /Cadastrar plano comercial/)
  assert.match(api, /createServicePlan/)
  assert.match(api, /updateServicePlan/)
  assert.match(api, /method: 'PUT'/)
})
