/**
 * A frente de caixa percorrida como quem vende.
 *
 * Quatro coisas: encontrar produto, adicionar, conferir a venda e receber. O
 * roteiro faz exatamente isso, com o caso que expôs o problema — sete unidades
 * da mesma bebida — e grava cada passo no tamanho real.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'pdv')
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
    await page.goto(`${appUrl}/pos?access=management`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(5000)
    await shot(page, 'caixa-fechado')

    // Abrir o caixa é pré-requisito da venda, e é a única coisa que a tela
    // oferece enquanto ele estiver fechado.
    const abrir = page.getByRole('button', { name: /ABRIR CAIXA/i })
    if (await abrir.count() > 0) {
      // O campo tem máscara de moeda e o rótulo não o embrulha: alcançar o
      // input pelo modo de entrada é o que funciona sem inventar id.
      const fundo = page.locator('input[inputmode="numeric"]').last()
      await fundo.click()
      await fundo.pressSequentially('10000', { delay: 80 })
      await page.waitForTimeout(600)
      await abrir.click()
      await page.waitForTimeout(3500)
    }
    await shot(page, 'venda-vazia')

    // Sete da mesma bebida: o caso que produzia sete linhas iguais.
    const bebida = page.getByRole('button', { name: /Coca-Cola Sem Açucar/ }).first()
    for (let i = 0; i < 7; i += 1) {
      await bebida.click()
      await page.waitForTimeout(700)
    }
    await shot(page, 'sete-unidades-uma-linha')

    const lanche = page.getByRole('button', { name: /Hambúrguer Artesanal Bacon/ }).first()
    await lanche.click()
    await page.waitForTimeout(700)
    await lanche.click()
    await page.waitForTimeout(1500)
    await shot(page, 'venda-conferida')

    // A ação dominante carrega o valor.
    await page.getByRole('button', { name: /^Receber/ }).first().click()
    await page.waitForTimeout(2500)
    await shot(page, 'recebimento')
  } finally {
    await navegador.close()
  }
}

run().catch((erro) => { console.error(erro); process.exitCode = 1 })
