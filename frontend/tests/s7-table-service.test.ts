import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'


const root = join(import.meta.dirname, '..', 'src')
const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
const workspace = readFileSync(join(root, 'components', 'tables', 'TableServiceWorkspace.tsx'), 'utf8')
const management = readFileSync(join(root, 'layouts', 'ManagementLayout.tsx'), 'utf8')

test('uses persistent table session APIs and idempotency keys', () => {
  assert.match(api, /fetchServiceTables/)
  assert.match(api, /openTableSession/)
  assert.match(api, /getTableSession/)
  assert.match(api, /addTableSessionOrder/)
  assert.match(api, /'Idempotency-Key': idempotencyKey/)
})

test('activates the table-service capability instead of a sprint placeholder', () => {
  assert.match(management, /permission: 'table\.read'/)
  assert.match(management, /capability: 'table_service'/)
  assert.match(management, /case 'tables': return <TableServiceWorkspace/)
})

test('renders real empty state and server-composed totals without fixtures', () => {
  assert.match(workspace, /Nenhuma mesa cadastrada/)
  assert.match(workspace, /consolidated_total/)
  assert.doesNotMatch(workspace, /mock|fixture|Mesa 2.*120/)
})
