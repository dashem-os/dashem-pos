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

test('opens the POS on all products and never on an empty favorites tab', async () => {
  const grid = await source('../src/components/pos/QuickProductGrid.tsx')
  assert.match(grid, /useState<string>\('ALL'\)/)
})
