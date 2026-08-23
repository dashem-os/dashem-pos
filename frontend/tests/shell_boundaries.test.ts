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

test('does not expose the management shortcut to an unauthorized POS operator', async () => {
  const pos = await source('../src/layouts/PosLayout.tsx')
  assert.match(pos, /canManage && <button/)
  assert.match(pos, /navigateTo\('\/manage'\)/)
})
