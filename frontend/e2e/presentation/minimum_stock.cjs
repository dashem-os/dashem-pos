/**
 * Homologação do mínimo independente: configurar não movimenta.
 *
 * O cenário é o exigido na revisão: saldo 10, definir mínimo 5, depois editar
 * para 12. Ao final o saldo continua 10, nenhum movimento foi criado e a
 * situação passa a acusar falta. O roteiro percorre as duas listas — Estoque e
 * Produtos — porque a ação precisa existir nas duas.
 *
 * O que ele prova é o que ele mede: a conferência do saldo e da ausência de
 * movimento é feita contra o banco, fora da tela, em `verificar_minimo.py`.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'minimo')
const VIEWPORT = { width: 1660, height: 860 }

if (!fixturePath) throw new Error('WALK_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

let passo = 0
async function shot(page, nome) {
  passo += 1
  const arquivo = path.join(outDir, `${String(passo).padStart(2, '0')}-${nome}.png`)
  await page.screenshot({ path: arquivo })
  console.log(`captura ${path.basename(arquivo)}`)
}

async function abrirModulo(page, rotulo) {
  await page.getByRole('button', { name: rotulo }).first().click()
  await page.waitForTimeout(1800)
}

async function run() {
  const navegador = await chromium.launch()
  try {
    const contexto = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
    const agora = Math.floor(Date.now() / 1000)
    const sub = JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub
    await contexto.addInitScript(([chave, valor]) => window.localStorage.setItem(chave, valor), [
      'sb-127-auth-token',
      JSON.stringify({
        access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
        expires_at: agora + 28800, refresh_token: 'walk',
        user: {
          id: sub, aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
          app_metadata: { provider: 'email' }, user_metadata: {}, created_at: new Date().toISOString(),
        },
      }),
    ])

    const page = await contexto.newPage()
    page.setDefaultTimeout(20000)
    await page.goto(appUrl, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(4000)

    // ------------------------------------------------- Estoque: definir 5
    await abrirModulo(page, /^Estoque$/)
    await shot(page, 'estoque-antes-sem-minimo')

    const linha = page.getByRole('row').filter({ hasText: 'Coca-Cola Lata' })
    await linha.getByRole('button', { name: 'Definir mínimo' }).click()
    await page.waitForTimeout(800)
    await page.getByLabel(/Quantidade mínima/).fill('5')
    await page.waitForTimeout(300)
    await shot(page, 'estoque-definir-minimo-5')
    await page.getByRole('button', { name: /Salvar mínimo|Salvando/ }).click()
    await page.waitForTimeout(2500)
    await shot(page, 'estoque-com-minimo-5')

    // -------------------------------------------------- Estoque: editar 12
    await linha.getByRole('button', { name: /Editar/ }).click()
    await page.waitForTimeout(800)
    await page.getByLabel(/Quantidade mínima/).fill('12')
    await page.waitForTimeout(300)
    await shot(page, 'estoque-editar-minimo-12')
    await page.getByRole('button', { name: /Salvar mínimo|Salvando/ }).click()
    await page.waitForTimeout(2500)
    await shot(page, 'estoque-abaixo-do-minimo')

    // O histórico é a prova visual de que nada foi movimentado.
    await page.mouse.wheel(0, 1200)
    await page.waitForTimeout(800)
    await shot(page, 'estoque-historico-sem-movimento-novo')

    // ------------------------------------------------- Produtos: a mesma ação
    await page.mouse.wheel(0, -1200)
    await abrirModulo(page, /^Produtos e pre/)
    await shot(page, 'produtos-com-minimo')
    await page.getByRole('button', { name: /^Definir mínimo$/ }).first().click()
    await page.waitForTimeout(800)
    await shot(page, 'produtos-definir-minimo')
    await page.getByLabel(/Quantidade mínima/).fill('4')
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: 'Salvar mínimo' }).click()
    await page.waitForTimeout(2500)
    await shot(page, 'produtos-depois-de-salvar')
  } finally {
    await navegador.close()
  }
}

run().catch((erro) => { console.error(erro); process.exitCode = 1 })
