const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.OA4_APP_URL || 'http://127.0.0.1:5173'
const apiUrl = process.env.OA4_API_URL || 'http://127.0.0.1:8003'
const fixturePath = process.env.OA4_FIXTURE_PATH
const artifactDir = process.env.OA4_ARTIFACT_DIR || path.resolve('test-results', 'oa4')

if (!fixturePath) throw new Error('OA4_FIXTURE_PATH is required.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(artifactDir, { recursive: true })

let activePage
let terminalToken

async function api(method, route, { token, tenantId, storeId, body } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (tenantId) headers['X-Tenant-ID'] = tenantId
  if (storeId) headers['X-Store-ID'] = storeId
  return fetch(`${apiUrl}${route}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

async function sanitize(page) {
  if (!page || page.isClosed()) return
  await page.locator('input[type="password"], input[autocomplete="one-time-code"]').evaluateAll(inputs => {
    for (const input of inputs) input.value = ''
  }).catch(() => undefined)
}

async function scenario(name, fn) {
  try {
    await fn()
    console.log(`PASS ${name}`)
  } catch (error) {
    if (activePage && !activePage.isClosed()) {
      await sanitize(activePage)
      const safeName = name.toLowerCase().replace(/[^a-z0-9]+/g, '-')
      await activePage.screenshot({ path: path.join(artifactDir, `${safeName}.png`), fullPage: true })
    }
    throw error
  }
}

async function activate(page, operator) {
  await page.getByRole('button', { name: 'Primeiro acesso / novo PIN' }).click()
  await page.getByLabel('Código do colaborador').fill(operator.employee_code)
  await page.getByLabel('Código temporário de ativação').fill(operator.activation_code)
  await page.getByLabel('Novo PIN').fill(operator.pin)
  await page.getByLabel('Confirmar PIN').fill(operator.pin)
  await page.getByRole('button', { name: 'Ativar meu PIN' }).click()
  await page.getByText('PIN pessoal ativado.').waitFor({ state: 'visible' })
}

async function login(page, operator) {
  await page.getByLabel('Código do colaborador').fill(operator.employee_code)
  await page.getByLabel('PIN pessoal').fill(operator.pin)
  await page.getByRole('button', { name: 'Entrar no turno' }).last().click()
  await page.waitForURL('**/pos', { timeout: 15_000 })
  await page.getByLabel('Encerrar sessão').waitFor({ state: 'visible', timeout: 15_000 })
}

function opaqueRgbs(value) {
  return [...value.matchAll(/\brgb\((\d+),\s*(\d+),\s*(\d+)\)/g)]
    .map(match => match.slice(1).map(Number))
}

function luminance([r, g, b]) {
  const channel = value => {
    const normalized = value / 255
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

function contrast(a, b) {
  const high = Math.max(luminance(a), luminance(b))
  const low = Math.min(luminance(a), luminance(b))
  return (high + 0.05) / (low + 0.05)
}

async function run() {
  const browser = await chromium.launch({ headless: true })
  try {
    await scenario('login público permanece exclusivamente gerencial', async () => {
      const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
      activePage = await context.newPage()
      await activePage.goto(`${appUrl}/login`, { waitUntil: 'domcontentloaded' })
      await activePage.getByRole('heading', { name: 'Bem-vindo de volta' }).waitFor()
      assert.equal(await activePage.getByText('Entrar como operador').count(), 0)
      assert.equal(await activePage.getByText('Entrar com PIN').count(), 0)
      await context.close()
    })

    await scenario('navegador sem autorização não expõe credenciais', async () => {
      const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
      activePage = await context.newPage()
      await activePage.goto(`${appUrl}/operate`, { waitUntil: 'domcontentloaded' })
      await activePage.getByRole('heading', { name: 'Ative este ponto de operação' }).waitFor()
      assert.equal(await activePage.getByLabel('Código do colaborador').count(), 0)
      assert.equal(await activePage.getByLabel('PIN pessoal').count(), 0)
      await context.close()
    })

    await scenario('gestor autoriza o POS no contexto persistido', async () => {
      const response = await api('POST', `/api/v1/operational-access/terminals/${fixture.device_id}/authorize`, {
        token: fixture.manager_token,
        tenantId: fixture.tenant_id,
        storeId: fixture.store_id,
      })
      assert.equal(response.status, 200)
      const authorization = await response.json()
      terminalToken = authorization.terminal_token
      assert.ok(terminalToken)
      assert.equal(authorization.device_id, fixture.device_id)
      assert.equal(authorization.store_id, fixture.store_id)
      assert.equal(authorization.register_id, fixture.register_id)
    })

    const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
    await context.addInitScript(token => localStorage.setItem('dashem.terminal_token', token), terminalToken)
    activePage = await context.newPage()

    await scenario('terminal autorizado mostra somente o portão clean do colaborador', async () => {
      await activePage.goto(`${appUrl}/operate`, { waitUntil: 'domcontentloaded' })
      await activePage.getByRole('heading', { name: 'Assumir operação' }).waitFor()
      const employeeCode = activePage.getByLabel('Código do colaborador')
      assert.equal(await employeeCode.getAttribute('autocomplete'), 'off')
      assert.equal(await employeeCode.inputValue(), '')
      assert.equal(await activePage.getByText('Terminal OA4').count(), 0)
      assert.equal(await activePage.getByText('Unidade OA4').count(), 0)
      assert.equal(await activePage.getByText('Caixa OA4').count(), 0)
      assert.equal(await activePage.getByText('Cada operação fica ligada à pessoa certa.').count(), 0)
      assert.equal(await activePage.getByRole('button', { name: 'Gestão' }).count(), 0)
      assert.equal(await activePage.locator('select').count(), 0)
      assert.equal(await activePage.getByText('Escolha onde você vai operar').count(), 0)
      assert.equal(await activePage.locator('input[type="password"]').count(), 0)
    })

    await scenario('entrada compacta cabe no viewport e não aceita autofill de e-mail', async () => {
      for (const viewport of [{ width: 1366, height: 768 }, { width: 1024, height: 768 }, { width: 480, height: 800 }]) {
        await activePage.setViewportSize(viewport)
        assert.equal(await activePage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
        assert.equal(await activePage.getByRole('heading', { name: 'Assumir operação' }).isVisible(), true)
        const formBox = await activePage.locator('form').boundingBox()
        assert.ok(formBox && formBox.y >= 0 && formBox.y + formBox.height <= viewport.height)
      }
      const employeeCode = activePage.getByLabel('Código do colaborador')
      await employeeCode.fill('marcelo@example.com')
      assert.equal(await employeeCode.inputValue(), '')
      assert.equal(await activePage.getByLabel('PIN pessoal').inputValue(), '')
      const modeButton = activePage.getByRole('button', { name: 'Entrar no turno' }).first()
      await modeButton.focus()
      const focusStyle = await modeButton.evaluate(element => getComputedStyle(element).boxShadow)
      assert.notEqual(focusStyle, 'none')
      assert.ok(opaqueRgbs(focusStyle).some(color => contrast(color, [255, 255, 255]) >= 3))
    })

    await scenario('offline preserva autorização do terminal', async () => {
      await context.setOffline(true)
      await activePage.getByText('Sem conexão. O terminal e o turno foram preservados.').waitFor()
      assert.equal(await activePage.evaluate(() => Boolean(localStorage.getItem('dashem.terminal_token'))), true)
      await context.setOffline(false)
      await activePage.getByRole('heading', { name: 'Assumir operação' }).waitFor()
    })

    await scenario('primeiro operador ativa o próprio PIN', async () => {
      await activate(activePage, fixture.operators[0])
    })

    await scenario('erro de PIN é neutro e não enumera pessoa', async () => {
      await activePage.getByLabel('Código do colaborador').fill(fixture.operators[0].employee_code)
      await activePage.getByLabel('PIN pessoal').fill('0000')
      await activePage.getByRole('button', { name: 'Entrar no turno' }).last().click()
      const alert = activePage.getByRole('alert')
      await alert.waitFor()
      assert.match(await alert.innerText(), /Código ou PIN inválido/)
      assert.doesNotMatch(await alert.innerText(), /Operadora OA4/)
    })

    let firstOperationalToken
    await scenario('código e PIN abrem POS sem seletor organizacional', async () => {
      await login(activePage, fixture.operators[0])
      firstOperationalToken = await activePage.evaluate(() => sessionStorage.getItem('dashem.operational_token'))
      assert.ok(firstOperationalToken)
      assert.equal(await activePage.getByText('Escolha onde você vai operar').count(), 0)
      assert.equal(await activePage.getByText(/Operadora OA4 A.*Caixa/).count(), 1)
      await activePage.reload({ waitUntil: 'domcontentloaded' })
      await activePage.getByLabel('Encerrar sessão').waitFor({ timeout: 15_000 })
      assert.equal(await activePage.getByText('Escolha onde você vai operar').count(), 0)
    })

    await scenario('operador não acessa Gestão e contexto adulterado é recusado', async () => {
      await activePage.goto(`${appUrl}/manage`, { waitUntil: 'domcontentloaded' })
      await activePage.waitForURL('**/pos')
      const adulterated = await api('GET', '/api/v1/operational-access/session/context', {
        token: firstOperationalToken,
        tenantId: fixture.tenant_id,
        storeId: '00000000-0000-0000-0000-000000000001',
      })
      assert.equal(adulterated.status, 403)
    })

    await scenario('saída encerra pessoa e preserva terminal', async () => {
      await activePage.getByLabel('Encerrar sessão').click()
      await activePage.waitForURL('**/operate')
      await activePage.getByRole('heading', { name: 'Assumir operação' }).waitFor()
      assert.equal(await activePage.evaluate(() => Boolean(localStorage.getItem('dashem.terminal_token'))), true)
      assert.equal(await activePage.evaluate(() => sessionStorage.getItem('dashem.operational_token')), null)
      const oldSession = await api('GET', '/api/v1/operational-access/session/context', {
        token: firstOperationalToken,
        tenantId: fixture.tenant_id,
        storeId: fixture.store_id,
      })
      assert.equal(oldSession.status, 403)
    })

    let secondOperationalToken
    await scenario('segundo operador assume o mesmo terminal', async () => {
      await activate(activePage, fixture.operators[1])
      await login(activePage, fixture.operators[1])
      secondOperationalToken = await activePage.evaluate(() => sessionStorage.getItem('dashem.operational_token'))
      assert.ok(secondOperationalToken && secondOperationalToken !== firstOperationalToken)
    })

    await scenario('gestor sem assunção não recebe contexto operacional', async () => {
      const response = await api('GET', '/api/v1/operational-access/session/context', {
        token: fixture.manager_token,
        tenantId: fixture.tenant_id,
        storeId: fixture.store_id,
      })
      assert.equal(response.status, 403)
    })

    await scenario('terminal pausado revoga a sessão e bloqueia nova entrada', async () => {
      const response = await api('PATCH', `/api/v1/devices/${fixture.device_id}`, {
        token: fixture.manager_token,
        tenantId: fixture.tenant_id,
        storeId: fixture.store_id,
        body: { status: 'PAUSED', reason: 'OA-4 revocation test' },
      })
      assert.equal(response.status, 200)
      await activePage.reload({ waitUntil: 'domcontentloaded' })
      await activePage.getByRole('heading', { name: 'Ative este ponto de operação' }).waitFor({ timeout: 15_000 })
      await activePage.getByRole('alert').getByText(/terminal foi pausado/i).waitFor()
      assert.equal(await activePage.getByLabel('Código do colaborador').count(), 0)
      assert.equal(await activePage.getByLabel('PIN pessoal').count(), 0)
      const stale = await api('GET', '/api/v1/operational-access/session/context', {
        token: secondOperationalToken,
        tenantId: fixture.tenant_id,
        storeId: fixture.store_id,
      })
      assert.equal(stale.status, 403)
    })

    await context.close()
  } finally {
    await browser.close()
  }
}

run().catch(error => {
  console.error(`OA-4 E2E failed: ${error.message}`)
  process.exitCode = 1
})
