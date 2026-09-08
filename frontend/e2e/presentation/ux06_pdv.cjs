/**
 * UX-06 — a escada de avisos do PDV, percorrida no balcão.
 *
 * O ADR-032 entregou a recusa antes do pagamento. O degrau que faltava é o
 * anterior: a pessoa descobrir que está no fim **enquanto** monta a venda, e
 * não quando o cliente já está com o cartão na mão.
 *
 * Este roteiro abre o caixa, monta uma venda com uma mercadoria de saldo
 * conhecido e percorre os quatro degraus do plano corretivo — silêncio,
 * crítico, última, bloqueio — conferindo também que a grade para de anunciar o
 * número de antes depois que a reserva acontece.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux06')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

// Coca-Cola Sem Açúcar 600ml: nove na prateleira, semeadas de propósito. É o
// exemplo que o plano corretivo usa na tabela da escada.
const MERCADORIA = 'Coca-Cola Sem Açucar 600ml'
const DISPONIVEL_INICIAL = 9

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), degraus: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux06-local',
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

/**
 * O aviso que a tela acabou de dar. Ele vive no recipiente fixo do Toast e some
 * sozinho — ler folha por folha do documento, como a primeira versão fazia, não
 * achava nada porque o texto mora num elemento com filhos.
 */
const avisoNaTela = (page) => page.evaluate(() => {
  const caixa = document.querySelector('div.pointer-events-none.fixed')
  return caixa ? (caixa.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 200) : ''
})

/**
 * O que o cartão diz sobre disponibilidade. A grade não anuncia número: ela
 * mostra um selo quando o saldo aperta, e é isso que o operador lê. Medir um
 * número que a tela não escreve reprovava o produto pelo erro da medida.
 */
const seloNaGrade = (page, nome) => page.evaluate((alvo) => {
  const cartao = [...document.querySelectorAll('button')]
    .filter((el) => (el.textContent || '').includes(alvo))
    .sort((a, b) => a.textContent.length - b.textContent.length)[0]
  if (!cartao) return null
  const texto = (cartao.innerText || '').replace(/\s+/g, ' ')
  const achado = texto.match(/Última unidade|Sem estoque|Restam? \d+|\d+ un/i)
  return achado ? achado[0] : ''
}, nome)


/** Inclui e lê o aviso enquanto ele ainda está na tela. */
async function incluirELer(page, cartao) {
  await cartao.click()
  // Só interessa o aviso desta inclusão. O da abertura de caixa ainda pode
  // estar na tela, e lê-lo faria a medida reprovar por causa do relógio.
  const desteItem = (t) => /adicionado|Indisponível|restarão|Última unidade|para vender agora/i.test(t)
  let texto = ''
  for (let tentativa = 0; tentativa < 14 && !desteItem(texto); tentativa += 1) {
    await page.waitForTimeout(180)
    texto = await avisoNaTela(page)
  }
  if (!desteItem(texto)) texto = ''
  await page.waitForTimeout(1600)
  return texto
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

    await page.goto(appUrl + '/pos?access=management', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3200)

    // ------------------------------------------------ abrir o caixa
    const abrir = page.getByRole('button', { name: /ABRIR CAIXA E INICIAR VENDAS/i })
    if (await abrir.count()) {
      await page.getByPlaceholder('0,00').first().fill('100,00')
      await abrir.click()
      await page.waitForTimeout(3200)
    }
    if (!(await page.getByPlaceholder(/Buscar produto ou escanear/).count())) {
      throw new Error('O PDV não chegou ao estado de venda: ' + (await page.evaluate(() => (document.body.innerText || '').slice(0, 240))))
    }
    await shot(page, '1-pdv-com-caixa-aberto')

    const seloAntes = await seloNaGrade(page, MERCADORIA)
    exigir(seloAntes === '', `com ${DISPONIVEL_INICIAL} disponíveis o cartão não devia alarmar, e dizia "${seloAntes}"`)

    const cartao = page.locator('button', { hasText: MERCADORIA }).first()

    // ------------------------------------------------ degrau 1: silêncio
    const primeiro = await incluirELer(page, cartao)
    relatorio.degraus.push({ degrau: 'folga confortável', pedido: 1, aviso: primeiro })
    exigir(/adicionado/i.test(primeiro) && !/restarão|Última|Indisponível/i.test(primeiro),
      `com folga o aviso deveria ser só confirmação, e veio "${primeiro}"`)

    relatorio.degraus.push({ degrau: 'o cartão em silêncio', selo: seloAntes })
    await shot(page, '2-primeira-inclusao-sem-alarme')

    // ------------------------------------------------ degrau 2 e 3
    // Restam 8. Incluindo de um em um, o crítico aparece quando restarem 2.
    let critico = ''
    let ultima = ''
    for (let volta = 0; volta < 8; volta += 1) {
      const texto = await incluirELer(page, cartao)
      if (!critico && /restarão/i.test(texto)) { critico = texto; await shot(page, '3-critico') }
      if (!ultima && /Última unidade/i.test(texto)) { ultima = texto; await shot(page, '4-ultima-unidade'); break }
    }
    relatorio.degraus.push({ degrau: 'crítico', aviso: critico })
    relatorio.degraus.push({ degrau: 'última unidade', aviso: ultima })
    exigir(/restarão 2 un/i.test(critico), `o aviso de crítico não apareceu com a conta do plano: "${critico}"`)
    exigir(/Última unidade disponível/i.test(ultima), `o aviso de última unidade não apareceu: "${ultima}"`)

    // ------------------------------------------------ degrau 4: bloqueio
    const bloqueio = await incluirELer(page, cartao)
    relatorio.degraus.push({ degrau: 'bloqueio', aviso: bloqueio })
    exigir(/Indisponível\. Disponível: 0/i.test(bloqueio),
      `pedir além do disponível deveria bloquear dizendo quanto há, e veio "${bloqueio}"`)
    await shot(page, '5-bloqueio-antes-de-incluir')

    // A grade releu a reserva: o cartão que estava calado agora alarma sozinho.
    const seloDepois = await seloNaGrade(page, MERCADORIA)
    relatorio.degraus.push({ degrau: 'o cartão relê a reserva', antes: seloAntes, depois: seloDepois })
    exigir(/Sem estoque|Última unidade/i.test(seloDepois),
      `depois de reservar tudo, o cartão deveria alarmar e dizia "${seloDepois}"`)
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux06-pdv.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`degraus: ${relatorio.degraus.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
