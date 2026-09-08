/**
 * UX-04 — o estoque orientado à ação, medido no que o aceite exige.
 *
 * Três coisas que esta sprint mudou, e que só se provam na tela:
 *
 *  1. **a pendência tem caminho** — o resumo diz quantas mercadorias precisam
 *     de atenção, e clicar nele leva exatamente a elas. Antes o número era um
 *     aviso e a pessoa procurava as três na lista inteira;
 *  2. **movimentações têm visão própria** — "quanto tenho agora" e "o que
 *     aconteceu" pararam de disputar a mesma rolagem;
 *  3. **dois cliques não viram dois movimentos** — o servidor sempre soube
 *     deduplicar por `Idempotency-Key`; esta tela nunca mandava uma.
 *
 * O terceiro é medido interceptando a requisição: o que importa é que a
 * intenção viaje carimbada, e que o carimbo **não mude** entre a tentativa que
 * falhou e o reenvio.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux04')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const ESTOQUE = '/manage?area=MERCADORIAS&module=inventory'
const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), medidas: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux04-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

async function shot(page, nome) {
  await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
  relatorio.telas.push(nome)
}

const linhasDaTabela = (page) => page.evaluate(() => {
  const corpo = document.querySelector('main tbody')
  return corpo ? [...corpo.querySelectorAll('tr')].map((tr) => tr.innerText.split('\n')[0].trim()) : []
})

async function main() {
  const navegador = await chromium.launch()
  try {
    const contexto = await navegador.newContext({
      viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1, locale: 'pt-BR',
    })
    await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessao())])
    const page = await contexto.newPage()
    page.setDefaultTimeout(25000)

    // A intenção carimbada: guardamos a chave de cada envio a /inventory/adjust.
    const carimbos = []
    await page.route('**/api/v1/inventory/adjust', async (route) => {
      carimbos.push(route.request().headers()['idempotency-key'] ?? null)
      await route.continue()
    })

    await page.goto(appUrl + ESTOQUE, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    const todas = await linhasDaTabela(page)
    if (!todas.length) {
      throw new Error('A tela de Estoques não carregou lista: ' + (await page.evaluate(() => (document.querySelector('main')?.innerText || '').slice(0, 200))))
    }
    await shot(page, '1-estoque-com-a-faixa-de-atencao')

    // ------------------------------------------- 1. a pendência tem caminho
    const faixa = page.getByRole('button', { name: /precisa[m]? de atenção/ }).first()
    exigir(await faixa.count() > 0, 'o resumo de atenção não é acionável')
    const anunciado = Number(((await faixa.innerText()).match(/(\d+)\s+produtos?\s+precisa/) || [])[1])
    await faixa.click()
    await page.waitForTimeout(1200)
    const filtradas = await linhasDaTabela(page)
    await shot(page, '2-so-o-que-precisa-de-atencao')
    relatorio.medidas.push({ medida: 'filtro de atenção', anunciado, antes: todas.length, depois: filtradas.length })
    exigir(filtradas.length === anunciado,
      `a faixa anuncia ${anunciado} e o filtro mostrou ${filtradas.length}`)
    exigir(filtradas.length < todas.length, 'o filtro de atenção não reduziu a lista')
    const pressionada = await faixa.getAttribute('aria-pressed')
    exigir(pressionada === 'true', `a faixa não se diz pressionada: aria-pressed=${pressionada}`)

    await faixa.click()
    await page.waitForTimeout(1000)
    exigir((await linhasDaTabela(page)).length === todas.length, 'desligar o filtro não devolveu a lista inteira')

    // ------------------------------------------- 2. movimentações à parte
    const abaMovimentacoes = page.getByRole('tab', { name: 'Movimentações' })
    exigir(await abaMovimentacoes.count() > 0, 'não há visão própria de movimentações')
    await abaMovimentacoes.click()
    await page.waitForTimeout(1200)
    const semTabela = await page.evaluate(() => !document.querySelector('main tbody'))
    const temHistorico = await page.evaluate(() => /Movimenta(ç|c)ões recentes/i.test(document.querySelector('main')?.innerText || ''))
    await shot(page, '3-movimentacoes-em-visao-propria')
    relatorio.medidas.push({ medida: 'visão própria', lista_de_estoque_saiu: semTabela, historico_presente: temHistorico })
    exigir(semTabela, 'a lista de estoque continua na visão de movimentações')
    exigir(temHistorico, 'a visão de movimentações não mostra o histórico')
    await page.getByRole('tab', { name: 'Estoque' }).click()
    await page.waitForTimeout(1000)

    // ------------------------------------------- 3. a intenção vai carimbada
    await page.getByRole('button', { name: /^Receber$/ }).first().click()
    await page.waitForTimeout(900)
    // Zero é recusado pelo servidor, com a mensagem junto ao campo. Serve de
    // primeira tentativa: a intenção é a mesma, e o reenvio não pode trocar de
    // carimbo — se trocar, o retry vira um segundo movimento.
    await page.getByPlaceholder('Ex.: 24').fill('0')
    await page.getByRole('button', { name: /Registrar|Salvar|Confirmar/i }).last().click()
    await page.waitForTimeout(2000)
    const recusa = await page.evaluate(() => {
      const alvo = [...document.querySelectorAll('[role="alert"], p')].find((el) => /zero não movimenta/i.test(el.textContent || ''))
      return alvo ? alvo.textContent.trim() : ''
    })
    await shot(page, '4-recebimento-zero-recusado-junto-ao-campo')
    exigir(/zero não movimenta/i.test(recusa), `a recusa de zero não apareceu junto ao campo: "${recusa}"`)

    await page.getByPlaceholder('Ex.: 24').fill('3')
    await page.getByRole('button', { name: /Registrar|Salvar|Confirmar/i }).last().click()
    await page.waitForTimeout(2600)

    relatorio.medidas.push({ medida: 'carimbo da intenção', carimbos })
    exigir(carimbos.length >= 2, `esperava duas tentativas da mesma intenção, houve ${carimbos.length}`)
    exigir(carimbos.every((chave) => typeof chave === 'string' && chave.length > 10),
      `alguma tentativa foi sem Idempotency-Key: ${JSON.stringify(carimbos)}`)
    exigir(new Set(carimbos).size === 1,
      `o reenvio trocou de carimbo, então o retry viraria um segundo movimento: ${JSON.stringify(carimbos)}`)
    await shot(page, '5-recebimento-registrado')
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux04-estoque.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`medidas: ${relatorio.medidas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
