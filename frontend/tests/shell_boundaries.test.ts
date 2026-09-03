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

test('lets Gestão open the terminal surface without granting management to operational sessions', async () => {
  const pos = await source('../src/layouts/PosLayout.tsx')
  const shell = await source('../src/shells/PosShell.tsx')
  const kds = await source('../src/shells/KdsShell.tsx')
  const management = await source('../src/layouts/ManagementLayout.tsx')
  assert.match(pos, /managementAvailable && !managementValidation && <button/)
  assert.match(pos, /canNavigateToManagement\(Boolean\(session\), permissions\)/)
  assert.match(pos, /navigateTo\('\/manage'\)/)
  assert.doesNotMatch(kds, /navigateTo\('\/manage'\)/)
  assert.match(management, /navigateTo\('\/pos\?access=management'\)/)
  assert.match(management, /Validar no PDV/)
  assert.match(shell, /managementAccess && session/)
  assert.match(shell, /<OperationalContextGate requireTerminal>/)
  assert.match(pos, /Acesso gerencial/)
  assert.match(pos, /ações executadas são reais e auditadas/)
  assert.match(await source('../src/App.tsx'), /releaseManagementSession\(\)\.finally/)
  assert.match(await source('../src/App.tsx'), /\/manage\?module=devices/)
})

test('requires a persisted operational session before POS or tables initialize', async () => {
  const app = await source('../src/App.tsx')
  const pos = await source('../src/shells/PosShell.tsx')
  const tables = await source('../src/shells/TablesShell.tsx')
  const gate = await source('../src/components/context/OperationalSessionGate.tsx')
  assert.match(app, /pathname !== '\/pos'/)
  assert.match(app, /replaceState\(\{\}, '', '\/operate'\)/)
  assert.match(pos, /<OperationalSessionGate>/)
  assert.match(pos, /managementAccess && session/)
  assert.match(tables, /<OperationalSessionGate>/)
  assert.match(gate, /fetchOperationalSessionContext\(operationalToken\)/)
  assert.match(gate, /\[401, 403, 409\]\.includes\(reason\.status\)/)
  assert.match(gate, /A sessão foi preservada/)
  assert.doesNotMatch(pos, /<OperationalPinGate/)
  assert.doesNotMatch(tables, /<OperationalContextGate|<OperationalPinGate/)
})

test('keeps management validation server-authorized and outside operational productivity', async () => {
  const app = await source('../src/App.tsx')
  const context = await source('../src/context/PosContext.tsx')
  const pos = await source('../src/layouts/PosLayout.tsx')
  assert.match(app, /managementPosRequested && !canManage/)
  assert.match(context, /source === 'MANAGEMENT' && !access\.permissions\.includes\('management\.read'\)/)
  assert.match(context, /accessMode: source/)
  assert.match(pos, /managementValidation = accessMode === 'MANAGEMENT'/)
  assert.match(pos, /Você está validando o PDV com sua identidade administrativa/)
})

test('keeps the management login exclusive and exposes credentials only on an authorized terminal', async () => {
  const app = await source('../src/App.tsx')
  const login = await source('../src/components/auth/SignInScreen.tsx')
  const entry = await source('../src/components/auth/OperationalEntryScreen.tsx')
  const devices = await source('../src/components/management/DeviceManager.tsx')
  assert.match(app, /pathname === '\/operate'/)
  assert.match(app, /me && pathname !== '\/operate'/)
  assert.doesNotMatch(login, /navigateTo\('\/operate'\)/)
  assert.doesNotMatch(login, /Entrar como operador|Entrar com PIN/)
  assert.match(login, /Esta entrada é exclusiva da Gestão/)
  assert.doesNotMatch(login, /employee_code|loginOperationalTerminal/)
  assert.match(entry, /resolveOperationalTerminal\(terminalToken\)/)
  assert.match(entry, /loginOperationalTerminal\(terminalToken/)
  assert.match(entry, /activateOperationalPin\(terminalToken/)
  assert.match(entry, /Primeiro acesso \/ novo PIN/)
  assert.match(entry, /name="operational-identity" autoComplete="off"/)
  assert.match(entry, /name="operational-pin" type="text" inputMode="numeric" autoComplete="one-time-code"/)
  assert.match(entry, /if \(\/\[@\.\]\/\.test\(value\)\) return ''/)
  assert.doesNotMatch(entry, /type="password"|autoFocus|\['1','2','3'/)
  assert.doesNotMatch(entry, /autoComplete="username"|autoComplete="current-password"/)
  assert.match(entry, /A autorização deste terminal foi preservada/)
  assert.doesNotMatch(entry, /context\.(?:device_name|tenant_name|store_name|register_name)/)
  assert.doesNotMatch(entry, /Cada operação fica ligada|jornada operacional/)
  assert.match(devices, /authorizeOperationalTerminal\(headers, device\.id\)/)
  assert.match(devices, /await releaseManagementSession\(\)/)
  assert.match(devices, /navigateTo\('\/operate'\)/)
  assert.match(devices, /device\.device_type === 'POS'/)
})

test('hydrates POS from the server-validated operational context without organizational discovery', async () => {
  const context = await source('../src/context/PosContext.tsx')
  const gate = await source('../src/components/context/OperationalSessionGate.tsx')
  const layout = await source('../src/layouts/PosLayout.tsx')
  const api = await source('../src/services/api.ts')
  assert.match(context, /source === 'OPERATIONAL_SESSION'/)
  assert.match(context, /tenantName \|\| 'Empresa'/)
  assert.match(context, /storeName \|\| 'Unidade'/)
  assert.match(context, /registerName \|\| 'Terminal'/)
  assert.match(api, /operational-access\/session\/context/)
  assert.match(api, /Authorization: `Bearer \$\{accessToken\}`/)
  assert.match(gate, /operatorName: context\.full_name/)
  assert.match(gate, /operatorRole: context\.role/)
  assert.match(context, /setOperatorName\(operationalOperatorName/)
  // The fallback must be a generic label, never a slice of an identifier.
  assert.match(layout, /operatorName \|\| ['`]Colaborador/)
  assert.doesNotMatch(layout, /operatorId\.slice/)
})

test('renders cash opening only for the effective cash.open permission', async () => {
  const context = await source('../src/context/PosContext.tsx')
  const layout = await source('../src/layouts/PosLayout.tsx')
  assert.match(layout, /const canOpenCash = permissions\.includes\('cash\.open'\)/)
  assert.match(layout, /canOpenCash \? <form onSubmit=\{handleOpenCash\}/)
  assert.match(layout, /Caixa ou Supervisor abrir este caixa/)
  assert.match(context, /if \(!permissions\.includes\('cash\.open'\)\)/)
  assert.doesNotMatch(layout, /Missing permission/)
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
  assert.match(team, /código de ativação temporário/)
  assert.match(team, /Acessos operacionais/)
  assert.match(team, /Código, PIN, função e unidade/)
  assert.match(team, /issueOperationalPinActivation/)
  assert.doesNotMatch(team, /pin: pinForm\.pin|resetOperationalPin|Novo PIN \(4 a 8/)
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
  assert.match(context, /access\.permissions\.includes\('cash\.read'\)/)
})

test('renders only backend-authorized module contributions in Gestão', async () => {
  const management = await source('../src/layouts/ManagementLayout.tsx')
  const overview = await source('../src/components/management/DashboardBI.tsx')
  const subscription = await source('../src/components/management/TenantPlanWorkspace.tsx')
  const context = await source('../src/context/PosContext.tsx')
  assert.match(context, /setContributions\(access\.contributions\)/)
  assert.match(management, /contributions\.filter\(item => item\.surface === 'MANAGEMENT_NAV'/)
  assert.match(management, /MODULE_IDS\.has\(item\.implementation_key/)
  assert.match(management, /case 'subscription': return <TenantPlanWorkspace/)
  assert.match(management, /if \(!selected\) return null/)
  assert.match(management, /if \(!availableModules\.has\(id\)\) return/)
  assert.match(overview, /availableModules\.has\(module\)/)
  assert.match(subscription, /Plano e solicitações/)
  assert.match(subscription, /CommercialRequestsPanel/)
  assert.doesNotMatch(overview, /CommercialRequestsPanel/)
  assert.doesNotMatch(management, /capability: 'delivery_orders'/)
})

test('renders management metrics from the aggregate API instead of browser reductions', async () => {
  const dashboard = await source('../src/components/management/DashboardBI.tsx')
  assert.match(dashboard, /fetchManagementOverview/)
  assert.match(dashboard, /Prontidão da configuração/)
  assert.match(dashboard, /overview\.resource_usage\.DEVICES\?\.configured/)
  assert.doesNotMatch(dashboard, /salesHistory\.filter|salesHistory\.reduce/)
  assert.match(dashboard, /formatProductDateTime\(overview\.generated_at\)/)
  // The absence of a source watermark must stay disclosed on screen, in operator
  // language rather than in the projection's technical vocabulary.
  assert.match(dashboard, /!overview\.source_watermark/)
  assert.match(dashboard, /Ainda não há movimento registrado neste período/)
  assert.match(dashboard, /overview\.projection_lag_seconds/)
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

test('never traps a person on the operational context gate', async () => {
  // The gate covers the whole screen and its own copy says the choice can be
  // changed on the way out, so an exit has to exist. A blocking surface whose
  // only escape is the browser back button is a dead end, not a gate.
  const gate = await source('../src/components/context/OperationalContextGate.tsx')
  assert.match(gate, /onSignOut/)
  assert.match(gate, /Voltar à Gestão/)
  assert.match(gate, /navigateTo\('\/manage'\)/)

  // The person staring at an empty terminal list may be the administrator the
  // old copy told them to go ask. Instead of a dead end they get a confirmed
  // provisioning: nothing is created silently, and the cash session stays closed
  // so opening it remains an explicit, valued act.
  assert.match(gate, /Nenhum terminal foi configurado nesta unidade/)
  assert.match(gate, /registra a ação na auditoria/)
  assert.match(gate, /O caixa continua fechado/)
  assert.match(gate, /createOperationalDevice/)
  assert.match(gate, /Configurar em Terminais e dispositivos/)
  assert.doesNotMatch(gate, /openCash|abrirCaixa/)
})
