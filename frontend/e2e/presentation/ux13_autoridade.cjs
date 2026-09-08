/**
 * UX-13 — quem pode o quê, dito na tela de acessos e obedecido no balcão.
 *
 * O ADR-028 tornou cancelar e descontar operações de duas pessoas, e a regra já
 * era verdadeira no servidor. O que não existia era **mudá-la sem mexer no
 * banco**: a tela de Funcionários e Acessos não mostrava nem permitia marcar o
 * que a pessoa faz sozinha.
 *
 * Esta travessia prova os três pontos do aceite pelo caminho mais curto que
 * ainda é honesto — usando o próprio gestor como sujeito:
 *
 *  1. a marcação aparece na Gestão, em nome de operação e não de chave;
 *  2. **tirar** autoridade muda o comportamento do PDV: o que antes acontecia
 *     sozinho passa a abrir o diálogo de autorização;
 *  3. **devolver a si mesmo** é recusado — ninguém amplia a própria autoridade,
 *     ou a autorização presencial deixaria de ser de duas pessoas.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux13')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const EQUIPE = '/manage?area=PESSOAS&module=team'
const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux13-local',
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

    // ============================== 1. a marcação está visível, em operações
    await page.goto(appUrl + EQUIPE, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    const naTabela = await page.evaluate(() => (document.querySelector('main')?.innerText || ''))
    // O cabeçalho é maiúsculo por CSS, e `innerText` devolve o texto já
    // transformado: comparar a forma escrita reprova a tela certa.
    if (!/faz sozinho/i.test(naTabela)) {
      throw new Error('A tela de acessos não mostrou a coluna de autoridade: ' + naTabela.slice(0, 200))
    }
    await shot(page, '1-acessos-com-a-autoridade-visivel')
    relatorio.etapas.push({ etapa: 'a marcação aparece na Gestão', mostra: /Cancelar venda|Aplicar desconto/.test(naTabela) })
    exigir(/Cancelar venda/.test(naTabela) && /Aplicar desconto/.test(naTabela),
      'a tela deveria nomear as operações, e não mostrar chaves')
    exigir(!/sale\.cancel|sale\.discount/.test(naTabela),
      'a tela expôs a chave técnica da permissão ao lojista')

    // ============================== 2. tirar autoridade muda o PDV
    await page.getByRole('button', { name: /Autoridade/ }).first().click()
    await page.waitForTimeout(1000)
    await page.getByLabel(/Por que está mudando/i).fill('Passa a pedir a outra pessoa durante o treinamento.')
    await shot(page, '2-dialogo-da-autoridade')
    // A linha certa, não a primeira: o diálogo lista as operações em ordem
    // alfabética, e "Aplicar desconto" vem antes de "Cancelar venda".
    const linhaCancelar = page.locator('div').filter({ hasText: /^Cancelar venda/ }).filter({ has: page.getByRole('button') }).first()
    await linhaCancelar.getByRole('button', { name: 'Passar a pedir' }).click()
    await page.waitForTimeout(3000)
    const depoisDeTirar = await page.evaluate(() => (document.body.innerText || ''))
    relatorio.etapas.push({ etapa: 'autoridade retirada', confirmou: /passa a pedir autorização/i.test(depoisDeTirar) })
    exigir(/passa a pedir autorização/i.test(depoisDeTirar),
      'a tela deveria confirmar que a pessoa passa a pedir autorização')
    await shot(page, '3-autoridade-retirada')
    await page.keyboard.press('Escape').catch(() => null)
    await page.waitForTimeout(600)

    // ============================== 3. o PDV obedece
    await page.goto(appUrl + '/pos?access=management', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3400)
    const abrirCaixa = page.getByRole('button', { name: /ABRIR CAIXA E INICIAR VENDAS/i })
    if (await abrirCaixa.count()) {
      await page.getByPlaceholder('0,00').first().fill('100,00')
      await abrirCaixa.click()
      await page.waitForTimeout(3200)
    }
    await page.locator('button', { hasText: 'Coca-Cola Lata' }).first().click()
    await page.waitForTimeout(2600)
    // O caminho real do balcão: o link do carrinho abre o diálogo, e a
    // confirmação de lá é que dispara a operação sensível.
    await page.getByRole('button', { name: 'Cancelar venda' }).first().click()
    await page.waitForTimeout(1400)
    await page.getByRole('button', { name: 'Sim, Cancelar' }).click()
    await page.waitForTimeout(3200)
    const pediuAutorizacao = await page.evaluate(() =>
      /Autorização do supervisor/i.test(document.body.innerText || ''))
    await shot(page, '4-pdv-pede-autorizacao')
    relatorio.etapas.push({ etapa: 'o PDV passou a pedir autorização', pediu: pediuAutorizacao })
    exigir(pediuAutorizacao,
      'depois de tirar a autoridade, cancelar deveria abrir o diálogo de autorização presencial')

    // ============================== 4. devolver a si mesmo é recusado
    await page.goto(appUrl + EQUIPE, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    await page.getByRole('button', { name: /Autoridade/ }).first().click()
    await page.waitForTimeout(1000)
    await page.getByLabel(/Por que está mudando/i).fill('Quero voltar a cancelar sozinha.')
    await page.locator('div').filter({ hasText: /^Cancelar venda/ }).filter({ has: page.getByRole('button') }).first()
      .getByRole('button', { name: 'Deixar fazer sozinha' }).click()
    await page.waitForTimeout(3000)
    const recusa = await page.evaluate(() => {
      const alerta = [...document.querySelectorAll('[role="alert"]')]
        .map((el) => (el.innerText || '').trim()).filter(Boolean)
      return alerta.join(' · ').slice(0, 220)
    })
    await shot(page, '5-ampliar-a-propria-autoridade-recusado')
    relatorio.etapas.push({ etapa: 'ampliar a própria autoridade', recusa })
    exigir(/própria autoridade/i.test(recusa),
      `devolver autoridade a si mesmo deveria ser recusado, e a tela disse "${recusa}"`)
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux13-autoridade.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
