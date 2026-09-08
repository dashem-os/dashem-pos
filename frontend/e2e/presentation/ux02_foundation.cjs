/**
 * UX-02 — a fundação visual, medida onde o aceite a define.
 *
 * O aceite da sprint fala de coisas que a auditoria de palavra partida não
 * pergunta: se a busca e o começo da lista aparecem sem rolar em 1366×640, se
 * a ação frequente está visível, se a tela repete o próprio título e se há
 * cartão dentro de cartão. Este roteiro mede essas quatro, nas quatro telas de
 * Mercadorias e nos dois estados novos da UX-01 — entrada e hub.
 *
 * `responsive_audit.cjs` continua respondendo a outra metade: palavra partida e
 * transbordo horizontal. Os dois juntos são o portão da UX-02.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux02')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

// 1366×640 é a tela do balcão, e é a medida que o aceite nomeia.
const TAMANHO = { nome: 'desktop-baixo-1366x640', width: 1366, height: 640 }
const CELULAR = { nome: 'celular-390x844', width: 390, height: 844 }

const TELAS = [
  { nome: 'entrada', endereco: '/manage', lista: false },
  { nome: 'hub-mercadorias', endereco: '/manage?area=MERCADORIAS', lista: false },
  { nome: 'produtos', endereco: '/manage?area=MERCADORIAS&module=products', lista: true },
  { nome: 'estoques', endereco: '/manage?area=MERCADORIAS&module=inventory', lista: true },
  { nome: 'catalogos', endereco: '/manage?area=MERCADORIAS&module=assortments', lista: true },
  { nome: 'categorias', endereco: '/manage?area=MERCADORIAS&module=categories', lista: true },
]

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), medicoes: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue) }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux02-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

const MEDIDA = () => {
  const main = document.querySelector('main')
  if (!main) return { erro: 'sem main' }
  const dentroDaTela = (el) => {
    if (!el) return null
    const c = el.getBoundingClientRect()
    if (c.width === 0 && c.height === 0) return null
    return { topo: Math.round(c.top), base: Math.round(c.bottom), visivel: c.bottom <= window.innerHeight && c.top >= 0 }
  }

  // Cartão: superfície com borda e canto arredondado. Cartão dentro de cartão é
  // moldura sobre moldura — o aceite pede para evitar, e o olho cansa antes de
  // contar. Aqui a contagem é do DOM.
  //
  // Duas coisas que parecem cartão e não são, e que o detector precisa deixar
  // passar para não gritar onde não há defeito:
  //  - **controle**: um seletor de período é um grupo com moldura contendo
  //    botões com moldura. É um controle, não moldura sobre moldura;
  //  - **estado vazio**: a moldura tracejada dentro de um painel é o padrão
  //    reconhecido de "aqui ainda não há nada", não um segundo cartão.
  const soContemControles = (el) => {
    const filhos = [...el.children]
    return filhos.length > 0 && filhos.every((f) => f.matches('button, a, input, select, label'))
  }
  const ehCartao = (el) => {
    if (el.closest('button, a, label, [role="button"], [role="tablist"], form')) return false
    // Cartão sem conteúdo não é cartão: o selo de ícone ao lado de um título
    // tem moldura, canto e fundo, e é decoração — moldura sobre moldura só
    // incomoda quando as duas emolduram texto.
    if (!(el.innerText || '').trim()) return false
    // Uma caixa com moldura cujos filhos são todos controles é um controle —
    // o seletor de período, por exemplo. Cartão é recipiente de conteúdo.
    if (soContemControles(el)) return false
    const s = getComputedStyle(el)
    if (s.borderTopStyle === 'dashed' || s.borderTopStyle === 'dotted') return false
    return parseFloat(s.borderTopLeftRadius) >= 12
      && parseFloat(s.borderTopWidth) > 0
      && s.backgroundColor !== 'rgba(0, 0, 0, 0)'
  }
  const cartoes = [...main.querySelectorAll('div, section, article, aside')].filter(ehCartao)
  const aninhados = cartoes
    .filter((el) => cartoes.some((outro) => outro !== el && outro.contains(el)))
    .map((el) => (el.innerText || '').trim().split('\n')[0].slice(0, 40))

  const titulos = [...main.querySelectorAll('h1')].map((h) => h.textContent.trim())
  const contexto = document.querySelector('header p')
  const busca = main.querySelector('input[type="search"], input[type="text"], input:not([type])')
  // O começo da lista: a primeira linha de tabela, ou o primeiro cartão de
  // uma grade de itens. Uma tela que mostra só o cabeçalho não mostra a lista.
  const primeiraLinha = main.querySelector('tbody tr, [role="row"]:not(:first-child), section.grid > article')

  return {
    titulos,
    titulo_repetido: !!(contexto && titulos.includes(contexto.textContent.trim())),
    cartoes_aninhados: [...new Set(aninhados)],
    busca: dentroDaTela(busca),
    primeira_linha: dentroDaTela(primeiraLinha),
    altura_da_janela: window.innerHeight,
  }
}

async function main() {
  const navegador = await chromium.launch()
  try {
    for (const tamanho of [TAMANHO, CELULAR]) {
      const contexto = await navegador.newContext({
        viewport: { width: tamanho.width, height: tamanho.height },
        deviceScaleFactor: 1, locale: 'pt-BR',
      })
      await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
        ['sb-127-auth-token', JSON.stringify(sessao())])
      const page = await contexto.newPage()
      page.setDefaultTimeout(20000)

      for (const tela of TELAS) {
        await page.goto(appUrl + tela.endereco, { waitUntil: 'domcontentloaded' })
        await page.waitForTimeout(2600)
        const medida = await page.evaluate(MEDIDA)
        if (medida.erro) throw new Error(`${tela.nome} em ${tamanho.nome}: ${medida.erro}`)
        await page.screenshot({ path: path.join(outDir, `${tamanho.nome}-${tela.nome}.png`) })
        relatorio.medicoes.push({ tamanho: tamanho.nome, tela: tela.nome, ...medida })

        exigir(medida.titulos.length === 1,
          `${tela.nome} em ${tamanho.nome}: ${medida.titulos.length} títulos de página (${JSON.stringify(medida.titulos)})`)
        exigir(!medida.titulo_repetido,
          `${tela.nome} em ${tamanho.nome}: o topo repete o título da página`)
        exigir(medida.cartoes_aninhados.length === 0,
          `${tela.nome} em ${tamanho.nome}: cartão dentro de cartão em ${JSON.stringify(medida.cartoes_aninhados)}`)

        // Busca e começo da lista só valem para telas de lista, e a exigência
        // de caber sem rolar é da tela do balcão — no celular a página rola.
        if (tela.lista && tamanho === TAMANHO) {
          exigir(medida.busca !== null, `${tela.nome}: não tem campo de busca`)
          exigir(medida.busca && medida.busca.visivel,
            `${tela.nome} em ${tamanho.nome}: a busca exige rolar (base ${medida.busca && medida.busca.base}px de ${medida.altura_da_janela}px)`)
          exigir(medida.primeira_linha !== null, `${tela.nome}: não achei o começo da lista`)
          exigir(medida.primeira_linha && medida.primeira_linha.visivel,
            `${tela.nome} em ${tamanho.nome}: o começo da lista exige rolar (base ${medida.primeira_linha && medida.primeira_linha.base}px de ${medida.altura_da_janela}px)`)
        }
      }
      await contexto.close()
    }
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux02-fundacao.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`medições: ${relatorio.medicoes.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
