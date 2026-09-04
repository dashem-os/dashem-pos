const assert = require('node:assert/strict')
const { spawn } = require('node:child_process')
const path = require('node:path')
const fs = require('node:fs')
const { chromium } = require('playwright')

const frontend = path.resolve(__dirname, '../..')
const url = 'http://127.0.0.1:5192/e2e/payment_providers/index.html'
// Intentionally restricted to the local development API used by verify-local.
const apiUrl = 'http://localhost:8002'
const artifacts = path.join(frontend, 'test-results/payment-providers')

async function http(route, body, headers = {}, method = body ? 'POST' : 'GET') {
  const response = await fetch(`${apiUrl}/api/v1${route}`, {
    method, headers: { 'Content-Type': 'application/json', ...headers },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  assert.ok(response.ok, `${method} ${route}: ${response.status} ${await response.clone().text()}`)
  return response.json()
}

async function run() {
  const suffix = crypto.randomUUID().slice(0, 8)
  const tenant = await http('/identity/tenants', { name: 'Aceitação provedores', slug: `provider-ui-${suffix}` })
  const store = await http('/identity/stores', { tenant_id: tenant.id, name: 'Unidade de aceitação', code: 'MAIN' })
  const headers = { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
  const register = await http('/cash/registers', { store_id: store.id, code: 'CX-01', name: 'Caixa principal' }, headers)
  const device = await http('/devices', { store_id: store.id, register_id: register.id, device_type: 'POS', code: 'POS-01', name: 'POS principal' }, headers)
  const register2 = await http('/cash/registers', { store_id: store.id, code: 'CX-02', name: 'Caixa secundário' }, headers)
  await http('/devices', { store_id: store.id, register_id: register2.id, device_type: 'POS', code: 'POS-02', name: 'POS secundário' }, headers)
  const context = { tenant, store, permissions: ['provider.read', 'provider.configure', 'cash.read', 'device.read'], capabilities: { tef: {} } }
  let server, browser
  try {
    try {
      await fetch(url, { signal: AbortSignal.timeout(500) })
      throw new Error('Port 5192 is already in use.')
    } catch (error) { if (error.message.includes('already in use')) throw error }
    server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--config', 'e2e/payment_providers/vite.config.mjs'], { cwd: frontend, stdio: 'inherit', windowsHide: true })
    let ready = false
    for (let attempt = 0; attempt < 60; attempt++) {
      if (server.exitCode !== null) throw new Error('Acceptance server exited.')
      try { if ((await fetch(url)).ok) { ready = true; break } } catch {}
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    assert.ok(ready, 'Acceptance server did not start.')
    browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width: 1024, height: 900 } })
    page.setDefaultTimeout(15_000)
    const errors = []
    const posts = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', request => {
      if (request.method() === 'POST' && request.url().includes('/providers/')) posts.push({ url: request.url(), key: request.headers()['idempotency-key'], data: request.postDataJSON() })
    })
    await page.addInitScript(value => { window.__providerContext = value; window.__toasts = [] }, context)
    await page.goto(url)
    await page.getByText('Nenhum provedor configurado nesta unidade.', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Parear bridge', exact: true }).isDisabled(), true)
    assert.equal(await page.getByRole('button', { name: 'Vincular maquininha', exact: true }).isDisabled(), true)

    await page.getByRole('button', { name: 'Configurar provedor', exact: true }).click()
    await page.getByLabel('Código do provedor', { exact: true }).fill(`UI-${suffix}`)
    await page.getByLabel('Referência segura das credenciais').fill('secret://acceptance/provider')
    // A real backend rejection must stay in the form without inventing success.
    await page.getByLabel('Código do provedor', { exact: true }).fill('CONTRACT_TEST')
    await page.getByRole('button', { name: 'Salvar', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: 'somente em testes automatizados' }).waitFor()
    assert.equal((await page.evaluate(() => window.__toasts)).length, 0)
    // Repeating an unchanged failed payload keeps its idempotency key.
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/providers/configurations') && response.status() === 422),
      page.getByRole('button', { name: 'Salvar', exact: true }).click(),
    ])
    assert.equal(posts[0].key, posts[1].key)
    await page.getByLabel('Código do provedor', { exact: true }).fill(`UI-${suffix}`)
    await page.getByRole('button', { name: 'Salvar', exact: true }).click()
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: 'Parear bridge', exact: true }).click()
    await page.getByLabel('Caixa', { exact: true }).selectOption(register.id)
    const providers = await http('/providers/configurations', undefined, headers)
    assert.equal(providers.length, 1)
    await page.getByLabel('Provedor', { exact: true }).selectOption(providers[0].id)
    await page.getByLabel('Código do terminal', { exact: true }).fill('BRIDGE-01')
    await page.getByRole('button', { name: 'Gerar código de pareamento' }).click()
    await page.getByText('Código de pareamento', { exact: true }).waitFor()
    const secret = await page.locator('dt').filter({ hasText: /^Código de pareamento$/ }).locator('..').locator('dd').textContent()
    const terminals = await http('/providers/bridge/terminals', undefined, headers)
    assert.equal(terminals[0].status, 'UNPAIRED')
    await page.getByRole('button', { name: 'Concluir', exact: true }).click()
    await page.getByText('Aguardando pareamento', { exact: true }).first().waitFor()
    // Only the authenticated bridge heartbeat makes this terminal online.
    await http(`/providers/bridge/terminals/${terminals[0].id}/heartbeat`, { tenant_id: tenant.id, store_id: store.id, pairing_code: secret, bridge_version: 'acceptance-1.0' })
    await page.getByRole('button', { name: 'Atualizar', exact: true }).click()
    await page.getByText('Online', { exact: true }).first().waitFor()
    await page.getByRole('button', { name: 'Vincular maquininha', exact: true }).click()
    await page.getByLabel('Caixa', { exact: true }).selectOption(register.id)
    assert.equal(await page.getByLabel('POS', { exact: true }).locator('option').filter({ hasText: 'POS secundário' }).count(), 0)
    await page.getByLabel('POS', { exact: true }).selectOption(device.id)
    await page.getByLabel('Provedor', { exact: true }).selectOption(providers[0].id)
    await page.getByLabel('Terminal de bridge', { exact: true }).selectOption(terminals[0].id)
    await page.getByRole('button', { name: 'Salvar', exact: true }).click()
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: 'Pausar', exact: true }).first().click()
    await page.getByLabel('Motivo', { exact: true }).fill('Manutenção da maquininha')
    await page.getByRole('button', { name: 'Salvar', exact: true }).click()
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    assert.equal((await http('/providers/device-bindings', undefined, headers))[0].status, 'PAUSED')
    await page.reload()
    await page.getByText('Pausado', { exact: true }).first().waitFor()
    console.log('PASS real API: configure, pair, heartbeat, bind, pause and reload; failure and idempotency')

    await page.getByRole('button', { name: 'Vincular maquininha', exact: true }).click()
    await page.getByLabel('Caixa', { exact: true }).selectOption(register2.id)
    await page.getByLabel('POS', { exact: true }).selectOption({ label: 'POS secundário · POS-02' })
    await page.getByLabel('Provedor', { exact: true }).selectOption(providers[0].id)
    assert.equal(await page.getByLabel('Terminal de bridge', { exact: true }).locator('option').count(), 1)
    await page.getByLabel('Modo de execução').selectOption('SMARTPOS')
    await page.getByLabel('Referência de pareamento da maquininha').fill('acceptance-smartpos')
    await page.getByRole('button', { name: 'Salvar', exact: true }).click()
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    await page.getByText('SmartPOS · execução indisponível', { exact: true }).first().waitFor()
    assert.ok(posts.every(item => item.key && item.key.length >= 8))
    assert.ok(posts.every(item => !item.url.endsWith('/transactions')))
    assert.ok(posts.every(item => !('actor_id' in item.data)))
    console.log('PASS SmartPOS registration without transaction; matching POS and bridge options')

    fs.mkdirSync(artifacts, { recursive: true })
    for (const width of [360, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 })
      if (width >= 1024) assert.ok((await page.locator('main').boundingBox()).x >= 288, 'Reserve the real management sidebar width')
      await page.screenshot({ path: path.join(artifacts, `providers-${width}.png`), fullPage: true })
      const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth > innerWidth + 1, tables: [...document.querySelectorAll('table')].filter(table => table.getBoundingClientRect().width > 0).some(table => table.scrollWidth > table.parentElement.clientWidth + 1) }))
      assert.deepEqual(overflow, { page: false, tables: false }, `Overflow at ${width}`)
      await page.getByRole('button', { name: 'Configurar provedor', exact: true }).click()
      const dialogBox = await page.getByRole('dialog').boundingBox()
      assert.ok(dialogBox.x >= 0 && dialogBox.x + dialogBox.width <= width, `Dialog outside viewport at ${width}`)
      await page.screenshot({ path: path.join(artifacts, `provider-form-${width}.png`), fullPage: true })
      await page.getByRole('button', { name: 'Cancelar', exact: true }).click()
    }
    const smartRow = page.getByRole('row').filter({ hasText: 'SmartPOS · execução indisponível' })
    await smartRow.getByRole('button', { name: 'Revogar', exact: true }).click()
    await page.getByLabel('Motivo', { exact: true }).fill('Encerramento do vínculo de aceitação')
    await page.getByRole('button', { name: 'Confirmar revogação' }).click()
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    await smartRow.getByText('Revogado', { exact: true }).waitFor()
    assert.equal(await smartRow.getByRole('button').count(), 0)
    assert.equal((await http('/providers/device-bindings', undefined, headers)).find(item => item.execution_mode === 'SMARTPOS').status, 'REVOKED')
    console.log('PASS revocation persists and removes reactivation actions')
    // The read-only page uses the same persisted records but offers no mutation.
    const readOnly = await browser.newPage()
    await readOnly.addInitScript(value => { window.__providerContext = value; window.__toasts = [] }, { ...context, permissions: ['provider.read'] })
    await readOnly.goto(url)
    await readOnly.getByText('Acesso somente para consulta.', { exact: false }).waitFor()
    await readOnly.getByText('Pausado', { exact: true }).first().waitFor()
    assert.equal(await readOnly.getByRole('button', { name: /Configurar provedor|Parear bridge|Vincular maquininha|Pausar|Revogar|Reconfigurar/ }).count(), 0)
    for (const restricted of [{ ...context, capabilities: {} }, { ...context, permissions: [] }]) {
      const denied = await browser.newPage()
      let calls = 0
      denied.on('request', request => { if (request.url().includes('/api/v1/')) calls++ })
      await denied.addInitScript(value => { window.__providerContext = value; window.__toasts = [] }, restricted)
      await denied.goto(url)
      await denied.getByText('Consulta de provedores indisponível para este acesso.').waitFor()
      assert.equal(calls, 0)
      await denied.close()
    }
    assert.deepEqual(errors, [])
    console.log('PASS responsive 360/768/1024/1440; read-only and missing capability/permission')
    console.log('Local acceptance complete. Test records are isolated under tenant ' + tenant.slug)
  } finally {
    if (browser) await browser.close()
    if (server) server.kill()
  }
}

run().catch(error => { console.error(error); process.exitCode = 1 })
