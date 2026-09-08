/**
 * A prova de que a palavra não parte, medida em vez de olhada.
 *
 * `overflow-wrap: break-word` não é garantia universal: o resultado depende da
 * largura disponível e do layout. Então este roteiro não afirma a classe
 * inteira do problema a partir de uma captura de desktop — ele percorre as
 * quatro superfícies em quatro tamanhos e mede duas coisas em cada uma:
 *
 * 1. **palavra partida**: para cada palavra sem oportunidade natural de quebra
 *    (sem hífen, barra ou travessão), um `Range` sobre ela devolve os
 *    retângulos que ela ocupa. Se os retângulos estão em mais de uma linha, a
 *    palavra foi partida no meio. Isso é o defeito, medido no layout final —
 *    não no CSS declarado;
 * 2. **transbordo horizontal**: `scrollWidth` do documento maior que a largura
 *    visível significa a página inteira rolando para o lado, que é o outro
 *    lado da mesma moeda: quem impede a palavra de partir pode empurrar a
 *    página. As duas medidas juntas é que dizem se a correção se sustenta.
 *
 * O caso de zoom emula o que o navegador faz a 150%: menos pixels CSS **e**
 * densidade maior. O relatório grava a densidade medida em cada tela, e a
 * auditoria reprova se ela não for a esperada — para "zoom" não ser só uma
 * palavra no nome do arquivo.
 *
 * Nenhuma medição é opcional: o roteiro exige o plano inteiro e reprova quando
 * uma superfície prevista não é alcançada. Medir menos não pode passar por
 * medir bem.
 *
 * A saída é um relatório em JSON mais uma captura por tela e por tamanho. As
 * capturas existem porque medida e olho se complementam: a medida encontra o
 * que o olho deixa passar em vinte telas, e o olho encontra o que a medida não
 * sabe perguntar.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'responsivo')

if (!fixturePath) throw new Error('WALK_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const TAMANHOS = [
  { nome: 'celular-390x844', width: 390, height: 844, escala: 2, nota: 'celular em retrato' },
  { nome: 'tablet-834x1112', width: 834, height: 1112, escala: 2, nota: 'tablet em retrato' },
  { nome: 'desktop-baixo-1366x640', width: 1366, height: 640, escala: 1, nota: 'altura reduzida' },
  {
    // Zoom de navegador não é só janela menor: a 150% o documento passa a ter
    // 1660/1.5 pixels CSS de largura **e** cada pixel CSS passa a valer 1.5
    // pixels de dispositivo. Emular só o primeiro deixava de fora metade do
    // efeito — o texto e as bordas são renderizados na densidade maior.
    nome: 'zoom-150-em-1660x860', width: 1107, height: 573, escala: 1.5,
    nota: 'zoom de 150% sobre 1660x860: 1107x573 pixels CSS com densidade 1.5',
    densidadeEsperada: 1.5,
  },
]

// Endereço, não rótulo. Este roteiro procurava "Sortimentos" por texto e
// parou de achar quando a 088 renomeou o card para "Catálogos"; procurava o
// botão "Abrir menu" e parou de achar quando a UX-01 tirou a gaveta. O que
// ele mede é a tipografia da tela, não o caminho até ela — então o caminho
// passa a ser o endereço canônico, que os testes de navegação já vigiam.
const TELAS = [
  { nome: 'produtos', area: 'MERCADORIAS', modulo: 'products' },
  { nome: 'estoque', area: 'MERCADORIAS', modulo: 'inventory' },
  { nome: 'sortimentos', area: 'MERCADORIAS', modulo: 'assortments' },
  { nome: 'categorias', area: 'MERCADORIAS', modulo: 'categories' },
]

const enderecoDaTela = (tela) => `/manage?area=${tela.area}&module=${tela.modulo}`

const MEDIDA = () => {
  const visivel = (elemento) => {
    const estilo = getComputedStyle(elemento)
    if (estilo.visibility === 'hidden' || estilo.display === 'none' || estilo.opacity === '0') return false
    const caixa = elemento.getBoundingClientRect()
    return caixa.width > 0 && caixa.height > 0
  }
  const partidas = []
  const percorredor = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  let no
  while ((no = percorredor.nextNode())) {
    const texto = no.nodeValue
    if (!texto || !texto.trim()) continue
    const pai = no.parentElement
    if (!pai || !visivel(pai)) continue
    // Só sequências sem oportunidade natural de quebra: hífen, barra e
    // travessão são pontos onde quebrar é correto, e contá-los como defeito
    // encheria o relatório de falso positivo.
    const regra = /[^\s\-‐-―/­]{3,}/g
    let achado
    while ((achado = regra.exec(texto))) {
      const intervalo = document.createRange()
      intervalo.setStart(no, achado.index)
      intervalo.setEnd(no, achado.index + achado[0].length)
      const caixas = Array.from(intervalo.getClientRects()).filter((c) => c.width > 0.5 && c.height > 0)
      const linhas = new Set(caixas.map((c) => Math.round(c.top)))
      if (linhas.size > 1) {
        partidas.push({
          palavra: achado[0],
          onde: (pai.className || '').toString().slice(0, 70),
          texto: texto.trim().slice(0, 60),
        })
      }
    }
  }
  return {
    partidas,
    transbordo: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    largura: document.documentElement.clientWidth,
    // Vai para o relatório: sem isto, "zoom" seria só uma palavra no nome do
    // arquivo, e ninguém poderia conferir se a densidade valeu de fato.
    densidade: window.devicePixelRatio,
  }
}

async function run() {
  const navegador = await chromium.launch()
  try {
    return await auditar(navegador)
  } finally {
    // Sem isto, uma reprovação deixava o Chromium aberto e o processo pendurado
    // — a auditoria acusava o defeito e nunca chegava a dizer isso em voz alta.
    await navegador.close()
  }
}

async function auditar(navegador) {
  const agora = Math.floor(Date.now() / 1000)
  const sub = JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub
  const sessao = {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'walk',
    user: {
      id: sub, aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: {}, created_at: new Date().toISOString(),
    },
  }

  const relatorio = []
  for (const tamanho of TAMANHOS) {
    const contexto = await navegador.newContext({
      viewport: { width: tamanho.width, height: tamanho.height },
      deviceScaleFactor: tamanho.escala,
      locale: 'pt-BR',
      isMobile: tamanho.width < 500,
      hasTouch: tamanho.width < 900,
    })
    await contexto.addInitScript(([chave, valor]) => window.localStorage.setItem(chave, valor),
      ['sb-127-auth-token', JSON.stringify(sessao)])
    const page = await contexto.newPage()
    page.setDefaultTimeout(20000)
    await page.goto(appUrl, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(4000)

    for (const tela of TELAS) {
      await page.goto(appUrl + enderecoDaTela(tela), { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(2600)
      const medida = await page.evaluate(MEDIDA)
      relatorio.push({ tamanho: tamanho.nome, nota: tamanho.nota, tela: tela.nome, ...medida })
      await page.screenshot({ path: path.join(outDir, `${tamanho.nome}-${tela.nome}.png`), fullPage: false })
      const marca = medida.partidas.length === 0 && medida.transbordo <= 1 ? 'ok  ' : 'FALHA'
      console.log(`${marca} ${tamanho.nome.padEnd(24)} ${tela.nome.padEnd(12)} partidas=${medida.partidas.length} transbordo=${medida.transbordo}px`)
      for (const p of medida.partidas.slice(0, 4)) console.log(`        "${p.palavra}" em ${p.onde}`)
    }

    // O formulário é onde a largura aperta de verdade.
    await page.goto(appUrl + '/manage?area=MERCADORIAS&module=inventory', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2600)
    // Sem `if`: a ação de receber tem de existir em todo tamanho. Um roteiro
    // que pula a medição quando não encontra o botão termina verde justamente
    // no caso em que a ação sumiu da tela — e o silêncio vira aprovação.
    const receber = page.getByRole('button', { name: 'Receber' }).first()
    await receber.waitFor({ state: 'visible', timeout: 15000 })
    await receber.click()
    await page.waitForTimeout(900)
    const medidaDoFormulario = await page.evaluate(MEDIDA)
    relatorio.push({ tamanho: tamanho.nome, nota: tamanho.nota, tela: 'formulario-receber', ...medidaDoFormulario })
    await page.screenshot({ path: path.join(outDir, `${tamanho.nome}-formulario-receber.png`) })
    const marcaDoFormulario = medidaDoFormulario.partidas.length === 0 && medidaDoFormulario.transbordo <= 1 ? 'ok  ' : 'FALHA'
    console.log(`${marcaDoFormulario} ${tamanho.nome.padEnd(24)} ${'formulário'.padEnd(12)} partidas=${medidaDoFormulario.partidas.length} transbordo=${medidaDoFormulario.transbordo}px`)
    for (const p of medidaDoFormulario.partidas.slice(0, 4)) console.log(`        "${p.palavra}" em ${p.onde}`)
    await contexto.close()
  }

  fs.writeFileSync(path.join(outDir, 'relatorio.json'), JSON.stringify(relatorio, null, 2), 'utf8')

  // O plano é exigido, não observado. Antes, uma superfície inalcançável
  // simplesmente não entrava no relatório, e menos medições passavam por
  // sucesso.
  const previstas = TAMANHOS.length * (TELAS.length + 1)
  const faltando = []
  for (const tamanho of TAMANHOS) {
    for (const nome of [...TELAS.map((tela) => tela.nome), 'formulario-receber']) {
      if (!relatorio.some((linha) => linha.tamanho === tamanho.nome && linha.tela === nome)) {
        faltando.push(`${tamanho.nome}/${nome}`)
      }
    }
    const esperada = tamanho.densidadeEsperada
    if (esperada) {
      const medidas = relatorio.filter((linha) => linha.tamanho === tamanho.nome)
      const erradas = medidas.filter((linha) => linha.densidade !== esperada)
      if (erradas.length > 0) {
        console.log(`FALHA ${tamanho.nome}: densidade ${erradas[0].densidade}, esperada ${esperada}`)
        faltando.push(`${tamanho.nome}/densidade`)
      }
    }
  }

  const falhas = relatorio.filter((linha) => linha.partidas.length > 0 || linha.transbordo > 1)
  console.log(`\n${relatorio.length} de ${previstas} medições previstas · ${falhas.length} com achado`)
  if (faltando.length > 0) console.log(`não alcançado: ${faltando.join(', ')}`)
  process.exitCode = falhas.length === 0 && faltando.length === 0 && relatorio.length === previstas ? 0 : 1
}

run().catch((erro) => { console.error(erro); process.exitCode = 1 })
