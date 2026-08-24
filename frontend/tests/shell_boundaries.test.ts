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

test('keeps PIN away from the public management login and binds it to an authorized terminal', async () => {
  const app = await source('../src/App.tsx')
  const login = await source('../src/components/auth/SignInScreen.tsx')
  const entry = await source('../src/components/auth/OperationalEntryScreen.tsx')
  const devices = await source('../src/components/management/DeviceManager.tsx')
  assert.match(app, /pathname === '\/operate'/)
  assert.doesNotMatch(login, /navigateTo\('\/operate'\)|Entrar com código e PIN/)
  assert.match(entry, /resolveOperationalTerminal\(terminalToken\)/)
  assert.match(entry, /loginOperationalTerminal\(terminalToken/)
  assert.match(devices, /authorizeOperationalTerminal\(headers, device\.id\)/)
  assert.match(devices, /device\.device_type === 'POS'/)
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

test('exposes real customer and employee workspaces in tenant management', async () => {
  const management = await source('../src/layouts/ManagementLayout.tsx')
  const customers = await source('../src/components/management/CustomerManager.tsx')
  const team = await source('../src/components/management/TeamManager.tsx')
  assert.match(management, /case 'customers': return <CustomerManager/)
  assert.match(management, /case 'team': return <TeamManager/)
  assert.match(customers, /fetchCustomers\(headers\)/)
  assert.match(customers, /createCustomer\(headers/)
  assert.match(customers, /updateCustomer\(headers/)
  assert.match(team, /Cadastro de funcionários/)
})

test('keeps POS terminal management usable without kitchen routing', async () => {
  const devices = await source('../src/components/management/DeviceManager.tsx')
  assert.match(devices, /productionEnabled \? \['POS', 'KDS', 'PRINTER'\] : \['POS'\]/)
  assert.match(devices, /if \(productionEnabled\)/)
  assert.match(devices, /\{productionEnabled && <section/)
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

test('renders only backend-authorized module contributions in Gestão', async () => {
  const management = await source('../src/layouts/ManagementLayout.tsx')
  const context = await source('../src/context/PosContext.tsx')
  assert.match(context, /setContributions\(access\.contributions\)/)
  assert.match(management, /contributions\.filter\(item => item\.surface === 'MANAGEMENT_NAV'/)
  assert.match(management, /MODULE_IDS\.has\(item\.implementation_key/)
  assert.doesNotMatch(management, /capability: 'delivery_orders'/)
})

test('renders management metrics from the aggregate API instead of browser reductions', async () => {
  const dashboard = await source('../src/components/management/DashboardBI.tsx')
  assert.match(dashboard, /fetchManagementOverview/)
  assert.doesNotMatch(dashboard, /salesHistory\.filter|salesHistory\.reduce/)
})
