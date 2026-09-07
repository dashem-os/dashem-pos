import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path: string) => readFile(new URL(path, import.meta.url), 'utf8')

test('renders persisted media in Gestão and refreshes both catalogue projections after attachment', async () => {
  const manager = await source('../src/components/management/CatalogManager.tsx')
  assert.match(manager, /prod\.image\?\.url \|\| prod\.image_url/)
  assert.match(manager, /await api\.setProductMedia/)
  assert.match(manager, /await refreshData\(\)/)
  assert.match(manager, /setReloadKey\(\(key\) => key \+ 1\)/)
})

test('keeps product registration legible and makes publication an explicit choice', async () => {
  const manager = await source('../src/components/management/CatalogManager.tsx')
  const picker = await source('../src/components/management/ProductMediaPicker.tsx')
  assert.match(manager, /maxWidth="2xl"/)
  assert.match(manager, /Todos os produtos/)
  assert.match(manager, /Publicados por contexto/)
  // A escolha continua explícita; o que saiu foi a explicação do modelo de
  // dados no meio do cadastro — "tenant", "cota" e "produto é o cadastro" são
  // vocabulário nosso, não de quem cadastra mercadoria.
  assert.match(manager, /Onde este item será vendido/)
  assert.match(manager, /Não publicar agora/)
  assert.doesNotMatch(manager, /Produto é o cadastro/)
  assert.match(picker, /sm:grid-cols-\[6rem_minmax\(0,1fr\)\]/)
  assert.match(picker, /só o seu negócio a vê/)
  assert.doesNotMatch(picker, /privada para este tenant/)
  assert.doesNotMatch(picker, /consome a sua cota/)
  assert.match(picker, /somente leitura/)
})

test('gives only the Control plane a platform-library upload surface', async () => {
  const owner = await source('../src/components/owner/OwnerConsoleShell.tsx')
  const library = await source('../src/components/owner/MediaLibraryView.tsx')
  const api = await source('../src/services/api.ts')
  assert.match(owner, /label="Biblioteca de imagens"/)
  assert.match(owner, /<MediaLibraryView/)
  assert.match(library, /Arquivos enviados por clientes nunca aparecem nesta tela/)
  assert.match(library, /uploadPlatformMediaLibrary/)
  assert.match(api, /catalog\/platform\/media-library/)
})
