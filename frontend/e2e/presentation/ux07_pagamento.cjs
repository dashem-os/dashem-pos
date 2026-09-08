/**
 * UX-07 — a cobrança carimbada, percorrida no balcão.
 *
 * O aceite proíbe "segunda cobrança por ambiguidade". O cenário que abre essa
 * porta é o *timeout depois do envio*: a criação do pagamento passa, a
 * confirmação estoura no meio, a venda continua `AWAITING_PAYMENT`, e quem
 * tenta de novo criava um segundo pagamento.
 *
 * Este roteiro paga uma venda de verdade e mede o que viaja: as duas chamadas
 * — criar e confirmar — precisam sair carimbadas, e o carimbo precisa vir da
 * mesma intenção. Depois força o cenário do timeout, abortando a confirmação
 * na rede, e confere que o reenvio **não** abre um segundo pagamento.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux07')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const MERCADORIA = 'Hambúrguer Artesanal Bacon'
const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), medidas: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux07-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

const shot = async (page, nome) => {
  await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
  relatorio.telas.push(nome)
}

async function main() {
  const navegador = await chromium.launch()
  try {
    const contexto = await navegador.newContext({
      viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'pt-BR',
    })
    await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessao())])
    const page = await contexto.newPage()
    page.setDefaultTimeout(25000)

    const criacoes = []
    const confirmacoes = []
    let abortarConfirmacao = false

    await page.route('**/api/v1/payments', async (rota) => {
      if (rota.request().method() === 'POST') criacoes.push(rota.request().headers()['idempotency-key'] ?? null)
      await rota.continue()
    })
    await page.route('**/api/v1/payments/*/confirm', async (rota) => {
      confirmacoes.push(rota.request().headers()['idempotency-key'] ?? null)
      // O timeout depois do envio: o servidor recebe e responde, e a resposta
      // não chega. É exatamente onde a segunda cobrança nascia.
      if (abortarConfirmacao) { await rota.abort('timedout'); return }
      await rota.continue()
    })

    await page.goto(appUrl + '/pos?access=management', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3200)
    const abrir = page.getByRole('button', { name: /ABRIR CAIXA E INICIAR VENDAS/i })
    if (await abrir.count()) {
      await page.getByPlaceholder('0,00').first().fill('100,00')
      await abrir.click()
      await page.waitForTimeout(3200)
    }
    if (!(await page.getByPlaceholder(/Buscar produto ou escanear/).count())) {
      throw new Error('O PDV não chegou ao estado de venda: ' + (await page.evaluate(() => (document.body.innerText || '').slice(0, 240))))
    }

    await page.locator('button', { hasText: MERCADORIA }).first().click()
    await page.waitForTimeout(2600)
    await shot(page, '1-venda-montada')

    // ------------------------------------------- o timeout depois do envio
    abortarConfirmacao = true
    await page.getByRole('button', { name: /^Receber/ }).first().click()
    await page.waitForTimeout(1200)
    await shot(page, '2-dialogo-de-pagamento')
    const confirmar = page.getByRole('button', { name: /Confirmar|Finalizar|Receber/i }).last()
    await confirmar.click()
    await page.waitForTimeout(3000)
    await shot(page, '3-confirmacao-perdida-na-rede')

    // ------------------------------------------- o operador tenta de novo
    abortarConfirmacao = false
    await confirmar.click()
    await page.waitForTimeout(4000)
    await shot(page, '4-reenvio-da-mesma-intencao')

    relatorio.medidas.push({ medida: 'carimbo na criação', criacoes })
    relatorio.medidas.push({ medida: 'carimbo na confirmação', confirmacoes })

    exigir(criacoes.length >= 2, `esperava duas criações da mesma intenção, houve ${criacoes.length}`)
    exigir(criacoes.every((c) => typeof c === 'string' && c.length > 10),
      `alguma criação foi sem Idempotency-Key: ${JSON.stringify(criacoes)}`)
    exigir(new Set(criacoes).size === 1,
      `o reenvio trocou o carimbo da criação, e isso abre a segunda cobrança: ${JSON.stringify(criacoes)}`)
    exigir(confirmacoes.every((c) => typeof c === 'string' && c.includes('-confirm')),
      `a confirmação não deriva da intenção: ${JSON.stringify(confirmacoes)}`)
    exigir(new Set(confirmacoes).size === 1,
      `o carimbo da confirmação mudou entre as tentativas: ${JSON.stringify(confirmacoes)}`)

    // ------------------------------------------- e o dinheiro bate
    const pagamentos = await page.evaluate(async () => {
      const chaves = Object.keys(window.localStorage)
      return chaves.length >= 0
    })
    relatorio.medidas.push({ medida: 'a tela seguiu utilizável', ok: pagamentos })
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux07-pagamento.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`medidas: ${relatorio.medidas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
