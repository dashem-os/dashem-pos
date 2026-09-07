/**
 * A travessia da etapa 2, com o conteúdo real da homologação.
 *
 * O portão de apresentação não é build nem medida de geometria: é percorrer a
 * tela e olhar. Este roteiro abre as três superfícies corrigidas, preenche os
 * formulários, provoca um erro de verdade — recusa do servidor, não simulação —
 * conclui as ações e grava tudo no mesmo tamanho, para comparação lado a lado.
 *
 * A sessão de gestão é escrita direto no armazenamento do navegador com um
 * token assinado pelo segredo de teste. Nenhum código de produto é alterado
 * para isso: o aplicativo lê a sessão de onde sempre leu.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5191'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'apresentacao')
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
  const contexto = await navegador.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1, locale: 'pt-BR' })

  const agora = Math.floor(Date.now() / 1000)
  const sessao = {
    access_token: fixture.manager_token,
    token_type: 'bearer',
    expires_in: 28800,
    expires_at: agora + 28800,
    refresh_token: 'walkthrough-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
  await contexto.addInitScript(([chave, valor]) => {
    window.localStorage.setItem(chave, valor)
  }, ['sb-127-auth-token', JSON.stringify(sessao)])

  const page = await contexto.newPage()
  page.on('console', (msg) => { if (msg.type() === 'error') console.log('  [console]', msg.text().slice(0, 160)) })
  console.log('abrindo o aplicativo...')
  page.setDefaultTimeout(20000)
  await page.goto(appUrl, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)
  console.log('titulo:', await page.title())

  // ------------------------------------------------------------ Produtos
  await abrirModulo(page, /^Produtos e pre/)
  await shot(page, 'produtos-lista')

  await page.getByRole('button', { name: /Mais ações de Alicate/ }).click()
  await page.waitForTimeout(400)
  await shot(page, 'produtos-mais-acoes')
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Editar' }).first().click()
  await page.waitForTimeout(900)
  await shot(page, 'produtos-editar-preenchido')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  // -------------------------------------------------------------- Estoque
  await abrirModulo(page, /^Estoque$/)
  await page.waitForTimeout(1500)
  await shot(page, 'estoque-lista')

  // Entrada de mercadoria, preenchida.
  await page.getByRole('button', { name: 'Entrada ou perda' }).first().click()
  await page.waitForTimeout(700)
  await page.getByLabel('Quantidade').first().fill('24')
  await page.waitForTimeout(300)
  await shot(page, 'estoque-entrada-preenchida')
  await page.getByRole('button', { name: /Registrar movimentação|Registrando/ }).click()
  await page.waitForTimeout(2000)
  await shot(page, 'estoque-entrada-concluida')

  // Erro real: perda maior do que existe na prateleira. Quem recusa é o servidor.
  await page.getByRole('button', { name: 'Entrada ou perda' }).first().click()
  await page.waitForTimeout(700)
  await page.locator('select').first().selectOption('LOSS')
  await page.getByLabel('Quantidade').first().fill('999')
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: /Registrar movimentação|Registrando/ }).click()
  await page.waitForTimeout(2500)
  await shot(page, 'estoque-erro-recusa-do-servidor')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)

  // Contagem: saldo lido, diferença calculada à vista.
  await page.getByRole('button', { name: 'Contar' }).first().click()
  await page.waitForTimeout(1500)
  await page.getByLabel('Quantidade encontrada').fill('31')
  await page.waitForTimeout(400)
  await shot(page, 'estoque-contagem-com-diferenca')
  await page.getByRole('button', { name: /Confirmar contagem|Registrando/ }).click()
  await page.waitForTimeout(2500)
  await shot(page, 'estoque-depois-das-acoes')

  // O histórico é a prova de que cada ação virou registro legível.
  await page.mouse.wheel(0, 1200)
  await page.waitForTimeout(800)
  await shot(page, 'estoque-historico-legivel')

  // ---------------------------------------------------------- Sortimentos
  await abrirModulo(page, /^Sortimentos/)
  await page.waitForTimeout(1500)
  await shot(page, 'sortimentos-lista')

  await navegador.close()
}

run().catch((erro) => { console.error(erro); process.exitCode = 1 })
