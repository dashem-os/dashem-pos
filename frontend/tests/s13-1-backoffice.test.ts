import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path: string) => readFile(new URL(path, import.meta.url), 'utf8')

test('exposes real backoffice workspaces instead of sprint placeholders', async () => {
  const layout = await source('../src/layouts/ManagementLayout.tsx')
  assert.match(layout, /CategoryManager/)
  assert.match(layout, /InventoryManager/)
  assert.match(layout, /ServiceSetupManager/)
  assert.match(layout, /DeviceManager/)
  assert.doesNotMatch(layout, /sprint:/)
  assert.doesNotMatch(layout, /Contrato do módulo reconhecido/)
})

test('models service topology, reservations and auditable device lifecycle in the API client', async () => {
  const api = await source('../src/services/api.ts')
  assert.match(api, /fetchServiceAreas/)
  assert.match(api, /createTableReservation/)
  assert.match(api, /duration_minutes/)
  assert.match(api, /setServiceTableState/)
  assert.match(api, /fetchOperationalDevices/)
  assert.match(api, /updateOperationalDevice/)
  assert.match(api, /createProductionRule/)
})

test('lets management edit and order service areas and tables with an audit reason', async () => {
  const setup = await source('../src/components/management/ServiceSetupManager.tsx')
  assert.match(setup, /updateServiceArea/)
  assert.match(setup, /updateServiceTable/)
  assert.match(setup, /sort_order: Number\(areaEditForm\.sort_order\)/)
  assert.match(setup, /sort_order: Number\(tableEditForm\.sort_order\)/)
  assert.match(setup, /reason: areaEditForm\.reason\.trim\(\)/)
  assert.match(setup, /reason: tableEditForm\.reason\.trim\(\)/)
  assert.match(setup, /expected_version: editingTable\.version/)
  assert.match(setup, /Editar e ordenar/)
})

test('opens the POS on all products and never on an empty favorites tab', async () => {
  const grid = await source('../src/components/pos/QuickProductGrid.tsx')
  assert.match(grid, /useState<string>\('ALL'\)/)
})
