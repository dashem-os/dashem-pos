import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'


const root = join(import.meta.dirname, '..', 'src')
const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
const workspace = readFileSync(join(root, 'components', 'tables', 'TableServiceWorkspace.tsx'), 'utf8')
const management = readFileSync(join(root, 'layouts', 'ManagementLayout.tsx'), 'utf8')
const context = readFileSync(join(root, 'context', 'PosContext.tsx'), 'utf8')

test('uses persistent table session APIs and idempotency keys', () => {
  assert.match(api, /fetchServiceTables/)
  assert.match(api, /openTableSession/)
  assert.match(api, /getTableSession/)
  assert.match(api, /addTableSessionOrder/)
  assert.match(api, /'Idempotency-Key': idempotencyKey/)
})

test('keeps table configuration in Gestão instead of the attendant workspace', () => {
  assert.match(context, /setContributions\(access\.contributions\)/)
  assert.match(management, /contributions\.filter\(item => item\.surface === 'MANAGEMENT_NAV'/)
  assert.match(management, /case 'tables': return <ServiceSetupManager/)
  assert.doesNotMatch(workspace, /Cadastrar mesa/)
  assert.match(workspace, /Mesa reservada/)
  assert.match(workspace, /Sinalizar impedimento/)
  assert.match(workspace, /Bloquear após fechamento/)
  assert.doesNotMatch(workspace, /window\.prompt/)
})

test('renders real empty state and server-composed totals without fixtures', () => {
  assert.match(workspace, /Mapa ainda não configurado/)
  assert.match(workspace, /consolidated_total/)
  assert.doesNotMatch(workspace, /mock|fixture|Mesa 2.*120/)
})
