import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'


const root = join(import.meta.dirname, '..', 'src')
const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
const workspace = readFileSync(join(root, 'components', 'tables', 'TableServiceWorkspace.tsx'), 'utf8')

test('talks to the provider API instead of a DLL SDK or pinpad from the browser', () => {
  assert.match(api, /executeProviderTransaction/)
  assert.match(api, /\/api\/v1\/providers\/transactions/)
  assert.doesNotMatch(api + workspace, /SiTef\.dll|PayGo\.dll|ActiveX|pinpad\.connect/)
})

test('shows real bridge state and never fakes TEF availability', () => {
  assert.match(api, /fetchTefBridgeTerminals/)
  assert.match(workspace, /TEF não configurado ou offline/)
  assert.match(workspace, /tefTerminal\?\.status === 'ONLINE'/)
  assert.match(workspace, /meios locais permanecem disponíveis/)
  assert.doesNotMatch(workspace, /FAKE_PSP|TEF aprovado automaticamente/)
})

test('keeps manual card explicitly distinct from TEF execution', () => {
  assert.match(workspace, /Crédito manual/)
  assert.match(workspace, /Débito manual/)
  assert.match(workspace, /Crédito via TEF/)
  assert.match(workspace, /Débito via TEF/)
})
