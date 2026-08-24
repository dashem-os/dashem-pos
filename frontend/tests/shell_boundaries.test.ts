import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path: string) => readFile(new URL(path, import.meta.url), 'utf8')

test('loads Control, Gestão, POS and KDS as independent route bundles', async () => {
  const app = await source('../src/App.tsx')
  assert.match(app, /lazy\(\(\) => import\('\.\/shells\/ManageShell'\)\)/)
  assert.match(app, /lazy\(\(\) => import\('\.\/shells\/PosShell'\)\)/)
  assert.match(app, /lazy\(\(\) => import\('\.\/shells\/KdsShell'\)\)/)
  assert.match(app, /lazy\(\(\) => import\('\.\/components\/owner\/PlatformOwnerConsole'\)/)
})

test('keeps technical diagnostics outside the tenant management shell', async () => {
  const management = await source('../src/layouts/ManagementLayout.tsx')
  assert.doesNotMatch(management, /Diagnostics|Diagnóstico|API conectada/)
})

test('keeps tenant management one-way: Gestão opens POS but POS and KDS never open Gestão', async () => {
  const pos = await source('../src/layouts/PosLayout.tsx')
  const kds = await source('../src/shells/KdsShell.tsx')
  const management = await source('../src/layouts/ManagementLayout.tsx')
  assert.doesNotMatch(pos, /navigateTo\('\/manage'\)/)
  assert.doesNotMatch(kds, /navigateTo\('\/manage'\)/)
  assert.match(management, /navigateTo\('\/pos'\)/)
})

test('lets an authenticated tenant manager open POS without a second login', async () => {
  const gate = await source('../src/components/auth/OperationalPinGate.tsx')
  assert.match(gate, /OWNER.*TENANT_OWNER.*ADMIN.*MANAGER/)
  assert.match(gate, /managementAuthorized/)
  assert.doesNotMatch(gate, /window\.location\.reload\(\)/)
})

test('keeps employee registration independent from operational credentials', async () => {
  const team = await source('../src/components/management/TeamManager.tsx')
  const api = await source('../src/services/api.ts')
  assert.match(team, /Buscar funcionário/)
  assert.match(team, /Novo cadastro/)
  assert.match(team, /Cadastro de funcionários/)
  assert.match(api, /fetchEmployees/)
  assert.match(api, /employee_id: string/)
})

test('never derives operational context from the first item of an authorized list', async () => {
  const context = await source('../src/context/PosContext.tsx')
  const gate = await source('../src/components/context/OperationalContextGate.tsx')
  assert.doesNotMatch(context, /tenants\[0\]|stores\[0\]|registers\[0\]/)
  assert.match(gate, /selectOnlyOption\(items\)/)
  assert.match(gate, /items\.find\(\(item\) => item\.id === stored\)/)
})

test('loads effective capabilities and permissions from the backend', async () => {
  const context = await source('../src/context/PosContext.tsx')
  assert.match(context, /fetchEffectiveAccess\(hdrs\)/)
  assert.match(context, /setPermissions\(access\.permissions\)/)
  assert.match(context, /setCapabilities\(access\.capabilities\)/)
})

test('filters every Gestão menu entry by backend permission and capability', async () => {
  const management = await source('../src/layouts/ManagementLayout.tsx')
  assert.match(management, /permissions\.includes\(item\.permission\)/)
  assert.match(management, /item\.capability in capabilities/)
  assert.match(management, /Equipe/)
  assert.match(management, /Ambientes e mesas/)
  assert.match(management, /Terminais e produção/)
})

test('renders management metrics from the aggregate API instead of browser reductions', async () => {
  const dashboard = await source('../src/components/management/DashboardBI.tsx')
  assert.match(dashboard, /fetchManagementOverview/)
  assert.doesNotMatch(dashboard, /salesHistory\.filter|salesHistory\.reduce/)
})
