import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

const root = join(import.meta.dirname, '..', 'src')
const apiTs = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
const posContext = readFileSync(join(root, 'context', 'PosContext.tsx'), 'utf8')
const search = readFileSync(join(root, 'components', 'pos', 'ProductSearch.tsx'), 'utf8')
const catalog = readFileSync(join(root, 'components', 'management', 'CatalogManager.tsx'), 'utf8')
const assortmentManager = readFileSync(join(root, 'components', 'management', 'AssortmentManager.tsx'), 'utf8')
const managementLayout = readFileSync(join(root, 'layouts', 'ManagementLayout.tsx'), 'utf8')

test('api client declares explicit SalesContext and canonical assortment endpoints', () => {
  assert.match(apiTs, /type SalesContext = 'COUNTER' \| 'TAKEAWAY' \| 'TABLE' \| 'DELIVERY' \| 'ECOMMERCE'/)
  assert.match(apiTs, /fetchSellableProducts/)
  assert.match(apiTs, /params\.set\('sales_context', options\.sales_context\)/)
  assert.match(apiTs, /fetchAssortments/)
  assert.match(apiTs, /createAssortment/)
  assert.match(apiTs, /updateAssortment/)
  assert.match(apiTs, /linkAssortmentProducts/)
  assert.match(apiTs, /unlinkAssortmentProducts/)
  assert.match(apiTs, /deleteAssortment/)
})

test('POS context requests sellable products bound to current operationMode and reloads on change', () => {
  assert.match(posContext, /sales_context:\s*mode/)
  assert.match(posContext, /setOperationModeState\(mode\)/)
  assert.match(posContext, /void refreshData\(mode\)/)
  // Blocks switching when active sale has items
  assert.match(posContext, /currentSale\.items\.length > 0/)
  assert.match(posContext, /Finalize ou cancele a operação atual antes de trocar o modo/)
})

test('ProductSearch executes barcode and query searches strictly under operational mode', () => {
  assert.match(search, /sales_context:\s*operationMode/)
})

test('CatalogManager allows selecting explicit sales context for store inventory view', () => {
  assert.match(catalog, /sales_context:\s*salesContext/)
  assert.match(catalog, /setSalesContext/)
  assert.match(catalog, /Contexto de Venda:/)
})

test('AssortmentManager supports scopes, product links, and handles optimistic concurrency conflict', () => {
  // The heading follows the contracted activity: a beauty reseller has no menus.
  assert.match(assortmentManager, /setsLabel/)
  assert.match(assortmentManager, /Sortimentos e cardápios/)
  assert.match(assortmentManager, /Sortimentos e catálogos/)
  assert.match(assortmentManager, /expected_version/)
  assert.match(assortmentManager, /Conflito de concorrência detectado/)
  assert.match(assortmentManager, /linkAssortmentProducts/)
  assert.match(assortmentManager, /unlinkAssortmentProducts/)
})

test('ManagementLayout mounts assortments module in Gestão navigation', () => {
  assert.match(managementLayout, /'assortments'/)
  assert.match(managementLayout, /<AssortmentManager \/>/)
})
