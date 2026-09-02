import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

const root = join(import.meta.dirname, '..', 'src')
const posContext = readFileSync(join(root, 'context', 'PosContext.tsx'), 'utf8')
const quickGrid = readFileSync(join(root, 'components', 'pos', 'QuickProductGrid.tsx'), 'utf8')
const search = readFileSync(join(root, 'components', 'pos', 'ProductSearch.tsx'), 'utf8')
const catalog = readFileSync(join(root, 'components', 'management', 'CatalogManager.tsx'), 'utf8')

test('loads price, balance and catalog data through the paginated sellable projection', () => {
  assert.match(posContext, /fetchSellableProducts/)
  assert.doesNotMatch(posContext, /for \(const p of prods\)[\s\S]*fetchInventoryBalance/)
  assert.doesNotMatch(posContext, /fetchProductPrices\(hdrs/)
})

test('uses persisted quick access, category identity and minimum-stock policy', () => {
  assert.match(quickGrid, /quick_position/)
  assert.doesNotMatch(quickGrid, /slice\(0,\s*6\)/)
  assert.doesNotMatch(quickGrid, /p\.description === activeTab/)
  assert.match(quickGrid, /is_low_stock/)
  assert.doesNotMatch(quickGrid, /stock > 5/)
})

test('searches and paginates server-side in POS and Gestão', () => {
  assert.match(search, /fetchSellableProducts/)
  assert.match(catalog, /fetchSellableProducts/)
  assert.match(catalog, /pageSize: 25/)
  assert.doesNotMatch(catalog, /products\.filter/)
})

test('keeps the POS catalog readable and responsive without changing its data authority', () => {
  assert.match(quickGrid, /min-\[420px\]:grid-cols-2/)
  assert.match(quickGrid, /min-h-\[148px\]/)
  assert.match(quickGrid, /line-clamp-3/)
  assert.match(search, /h-16 items-center/)
  assert.match(search, /text-base font-semibold/)
})
