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

test('lets email managers move between Gestão and PDV without exposing Gestão to PIN operators', async () => {
  const pos = await source('../src/layouts/PosLayout.tsx')
  const kds = await source('../src/shells/KdsShell.tsx')
  const management = await source('../src/layouts/ManagementLayout.tsx')
  assert.match(pos, /managementAvailable && <button/)
  assert.match(pos, /canNavigateToManagement\(Boolean\(session\), permissions\)/)
  assert.match(pos, /navigateTo\('\/manage'\)/)
  assert.doesNotMatch(kds, /navigateTo\('\/manage'\)/)
  assert.match(management, /navigateTo\('\/pos'\)/)
})

test('lets an authenticated tenant manager open POS without a second login', async () => {
  const gate = await source('../src/components/auth/OperationalPinGate.tsx')
  assert.match(gate, /hasManagementAccess/)
  assert.match(gate, /managementAuthorized/)
  assert.doesNotMatch(gate, /window\.location\.reload\(\)/)
})

test('keeps PIN fields away from management login but exposes the operator entry route', async () => {
  const app = await source('../src/App.tsx')
  const login = await source('../src/components/auth/SignInScreen.tsx')
  const entry = await source('../src/components/auth/OperationalEntryScreen.tsx')
  const devices = await source('../src/components/management/DeviceManager.tsx')
  assert.match(app, /pathname === '\/operate'/)
  assert.match(app, /me && pathname !== '\/operate'/)
  assert.match(login, /navigateTo\('\/operate'\)/)
  assert.match(login, /Entrar como operador/)
  assert.doesNotMatch(login, /employee_code|loginOperationalTerminal/)
  assert.match(entry, /resolveOperationalTerminal\(terminalToken\)/)
  assert.match(entry, /loginOperationalTerminal\(terminalToken/)
  assert.match(devices, /authorizeOperationalTerminal\(headers, device\.id\)/)
  assert.match(devices, /navigateTo\('\/operate'\)/)
  assert.match(devices, /device\.device_type === 'POS'/)
})

test('keeps the persisted operational session alive and returns to PIN after server rejection', async () => {
  const auth = await source('../src/context/AuthContext.tsx')
  const api = await source('../src/services/api.ts')
  assert.match(auth, /heartbeatOperationalSession\(operationalToken\)/)
  assert.match(auth, /window\.setInterval\(heartbeat, 30_000\)/)
  assert.match(auth, /window\.location\.assign\('\/operate'\)/)
  assert.match(api, /operational-access\/session\/heartbeat/)
  assert.match(api, /\[401, 403, 409\]\.includes\(res\.status\)/)
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
  assert.match(devices, /deviceKindAvailability\(productionEnabled\)/)
  assert.match(devices, /const locked = !option\.enabled/)
  assert.match(devices, /if \(productionEnabled\)/)
  assert.match(devices, /\{productionEnabled && <section/)
})

test('reuses an existing unbound register when creating the POS device', async () => {
  const devices = await source('../src/components/management/DeviceManager.tsx')
  assert.match(devices, /unboundRegisterCandidates\(registers, devices\)/)
  assert.match(devices, /initialPosDeviceDraft\(registers, devices\)/)
  assert.match(devices, /register_id: form\.device_type === 'POS'/)
  assert.match(devices, /Caixa existente/)
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

test('renders operational productivity from the rebuildable backend projection', async () => {
  const dashboard = await source('../src/components/management/DashboardBI.tsx')
  const api = await source('../src/services/api.ts')
  assert.match(dashboard, /fetchOperationalProductivity/)
  assert.match(dashboard, /rebuildOperationalProductivity/)
  assert.match(dashboard, /Produtividade por operador e turno/)
  assert.match(api, /management\/productivity/)
  assert.doesNotMatch(dashboard, /providerTransactions\.reduce|paymentEvents\.reduce/)
})
