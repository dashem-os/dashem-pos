/**
 * Homologação — o acervo grande, na grade do balcão e no seletor da Gestão.
 *
 * A UX-08 deixou registrado: "catálogo volumoso não exercitado — seis produtos
 * no acervo; busca e grade não foram medidas sob carga". Seis produtos cabem em
 * qualquer tela. Mil e duzentos revelam quem lê o acervo inteiro de uma vez.
 *
 * A semeadura é a das duas estações, com `--volume 1200`. Os nomes se espalham
 * pelo alfabeto de propósito, e um produto fica no fim dele — "Zimbro
 * Desidratado 5kg". Ele é o pente-fino: qualquer corte por ordem de nome o
 * deixa de fora, e é por ele que as duas telas são cobradas.
 *
 * O que se mede aqui:
 *
 * 1. a grade do PDV sob 1.203 produtos vendáveis — ela pagina, e o tempo é medido;
 * 2. a busca do balcão encontrando o produto do fim do alfabeto e vendendo-o;
 * 3. o que o servidor devolve no catálogo mestre — quantos, e até que letra;
 * 4. o seletor de produtos do sortimento, na Gestão, alcançando o mesmo produto.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5199'
const apiUrl = process.env.WALK_API_URL || 'http://127.0.0.1:8004'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'hom-volumoso')
const VIEWPORT = { width: 1660, height: 860 }

if (!fixturePath) throw new Error('WALK_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
if (!fixture.volume || !fixture.volume.produto_do_fim) {
  throw new Error('semeie com --volume: esta travessia mede acervo grande, e a fixture veio sem ele')
}
const DO_FIM = fixture.volume.produto_do_fim
const PRIMEIRA_PALAVRA = new RegExp(DO_FIM.nome.split(' ')[0])
fs.mkdirSync(outDir, { recursive: true })

const relatorio = {
  app: appUrl,
  gerado_em: new Date().toISOString(),
  acervo: { vendaveis: fixture.volume.quantos + 2, produto_do_fim: DO_FIM.nome },
  etapas: [], telas: [], medidas: {}, servidor: {},
}
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

let contador = 0
async function shot(page, nome) {
  contador += 1
  const arquivo = `${String(contador).padStart(2, '0')}-${nome}`
  await page.screenshot({ path: path.join(outDir, `${arquivo}.png`) })
  relatorio.telas.push(arquivo)
}

function sessaoDeGestao(token, email, nome) {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'hom05',
    user: {
      id: JSON.parse(Buffer.from(token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: nome },
      created_at: new Date().toISOString(),
    },
  }
}

const naTela = async (page) => (await page.locator('body').innerText()).replace(/\s+/g, ' ')

async function esperaTexto(page, expressao, limiteMs = 20000) {
  const fim = Date.now() + limiteMs
  let ultimo = ''
  while (Date.now() < fim) {
    ultimo = await naTela(page)
    if (expressao.test(ultimo)) return ultimo
    await page.waitForTimeout(250)
  }
  return ultimo
}

async function estacao(navegador, pessoa, etiqueta) {
  const contexto = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
  await contexto.addInitScript(([chave, valor]) => window.localStorage.setItem(chave, valor), [
    'dashem.terminal_token', pessoa.terminal_token,
  ])
  const page = await contexto.newPage()
  page.setDefaultTimeout(30000)
  await page.goto(`${appUrl}/operate`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3500)
  await page.locator('input[name="operational-identity"]').fill(pessoa.employee_code)
  await page.locator('input[name="operational-pin"]').fill(pessoa.pin)
  await page.keyboard.press('Enter')
  await page.waitForTimeout(5000)
  console.log(`  [${etiqueta}] entrou como ${pessoa.name} (${pessoa.role})`)
  return page
}

async function abrirCaixa(page) {
  const abrir = page.getByRole('button', { name: /ABRIR CAIXA/i })
  if (await abrir.count() === 0) return
  await abrir.first().waitFor({ state: 'visible' })
  const fundo = page.locator('input[inputmode="numeric"]').last()
  await fundo.click()
  await fundo.type('20000')
  await abrir.first().click()
  await page.waitForTimeout(3000)
}

/** O que o servidor devolve no catálogo mestre — a lista que alimenta o seletor. */
async function catalogoMestre(page) {
  return page.evaluate(async ([api, tenant, store, token, skuDoFim]) => {
    const inicio = performance.now()
    const resposta = await fetch(`${api}/api/v1/catalog/products`, {
      headers: { 'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}` },
    })
    const ms = Math.round(performance.now() - inicio)
    if (!resposta.ok) return { status: resposta.status, ms, quantos: null }
    const linhas = await resposta.json()
    return {
      status: resposta.status, ms, quantos: linhas.length,
      primeiro: linhas.length ? linhas[0].name : null,
      ultimo: linhas.length ? linhas[linhas.length - 1].name : null,
      tem_o_do_fim: linhas.some((p) => p.sku === skuDoFim),
    }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager.token, DO_FIM.sku])
}

/**
 * O tempo da página da grade, medido no servidor.
 *
 * O relógio da tela inclui o servidor de desenvolvimento do Vite, que entrega
 * centenas de módulos soltos a cada recarregamento — em duas execuções seguidas
 * ele deu 1.299ms e 5.520ms com o mesmo acervo. Esse número não fala sobre o
 * catálogo. O que fala é quanto custa a página de produtos vendáveis.
 */
async function gradeNoServidor(page, pagina) {
  return page.evaluate(async ([api, tenant, store, token, numero]) => {
    const endereco = `${api}/api/v1/catalog/sellable-products?sales_context=COUNTER&page=${numero}&page_size=50`
    const cabecalhos = { 'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}` }
    const tempos = []
    let ultima = null
    // Quatro batidas, e a primeira é descartada: ela paga a conexão e o plano
    // da consulta, e uma medida única viraria sorteio. O que fica é a mediana
    // das três seguintes, com os números crus ao lado.
    for (let i = 0; i < 4; i += 1) {
      const inicio = performance.now()
      const resposta = await fetch(endereco, { headers: cabecalhos })
      const ms = Math.round(performance.now() - inicio)
      if (!resposta.ok) return { status: resposta.status, ms, total: null, itens: null, tempos }
      const corpo = await resposta.json()
      ultima = { status: resposta.status, total: corpo.total, itens: corpo.items.length }
      tempos.push(ms)
    }
    const medidas = tempos.slice(1).sort((a, b) => a - b)
    return { ...ultima, ms: medidas[1], tempos }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager.token, pagina])
}

async function run() {
  const navegador = await chromium.launch()
  try {
    const contextoGestao = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
    await contextoGestao.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(
        sessaoDeGestao(fixture.manager.token, fixture.manager.email, fixture.manager.name))])
    const gestao = await contextoGestao.newPage()
    gestao.setDefaultTimeout(30000)

    // ---------------------------------------- 1. a grade do balcão, sob carga
    const operadora = await estacao(navegador, fixture.operator, 'operadora')
    await abrirCaixa(operadora)

    // A grade já está pintada quando o caixa termina de abrir. Cronometrar
    // daqui mediria a espera do próprio roteiro — deu 6ms na primeira execução,
    // um número que não significa nada. O que o balcão vive é a tela subindo do
    // zero: recarrega-se, e conta-se do endereço até o primeiro cartão.
    const antesDaGrade = Date.now()
    await operadora.reload({ waitUntil: 'domcontentloaded' })
    const comGrade = await esperaTexto(operadora, /Arroz Tipo 001/, 30000)
    const msDaGrade = Date.now() - antesDaGrade
    relatorio.medidas.primeira_pagina_da_grade_ms = msDaGrade
    await shot(operadora, 'grade-sob-mil-e-duzentos')
    relatorio.etapas.push({
      etapa: 'a grade do balcão abre com o acervo grande',
      ms: msDaGrade,
      abrange: 'do recarregamento até o primeiro cartão; inclui o Vite de '
             + 'desenvolvimento, então NÃO é medida do produto — fica como '
             + 'sinal de que a tela subiu, não como prova de desempenho',
    })
    exigir(/Arroz Tipo 001/.test(comGrade),
      `a grade não pintou o acervo em 30s: "${comGrade.slice(0, 200)}"`)

    // O relógio da tela não é cobrado: ele inclui o Vite de desenvolvimento.
    // Cobra-se o que o acervo grande de fato encarece — a página do servidor,
    // na primeira e na última janela da grade.
    // A sonda sai da aba da operadora porque ela já está na origem do
    // aplicativo — a aba da Gestão ainda não navegou, e `fetch` de uma página em
    // branco morre no CORS antes de medir coisa alguma.
    const primeira = await gradeNoServidor(operadora, 1)
    const ultima = await gradeNoServidor(operadora, Math.ceil(relatorio.acervo.vendaveis / 50))
    relatorio.medidas.pagina_1_do_servidor_ms = primeira.ms
    relatorio.medidas.ultima_pagina_do_servidor_ms = ultima.ms
    relatorio.servidor.grade = { primeira, ultima }
    relatorio.etapas.push({
      etapa: 'a grade pagina o acervo grande, e o servidor responde',
      total: primeira.total, por_pagina: primeira.itens,
      pagina_1_ms: primeira.ms, ultima_pagina_ms: ultima.ms,
      medida: 'mediana de três, descartada a primeira batida',
      cruas: { pagina_1: primeira.tempos, ultima: ultima.tempos },
    })
    exigir(primeira.total === relatorio.acervo.vendaveis,
      `a grade deveria contar ${relatorio.acervo.vendaveis} vendáveis, e conta ${primeira.total}`)
    exigir(ultima.itens > 0,
      `a última janela da grade veio vazia: com ${primeira.total} produtos, paginar não alcança o fim`)
    // Um segundo é o que separa "a grade virou" de "a grade travou" para quem
    // tem fila na frente. A última página custa o mesmo que a primeira, ou a
    // paginação está varrendo o acervo inteiro a cada virada.
    exigir(primeira.ms < 1000 && ultima.ms < 1000,
      `paginar custou ${primeira.ms}ms na primeira e ${ultima.ms}ms na última janela`)

    // ---------------------------------------- 2. a busca acha o fim do alfabeto
    const busca = operadora.getByPlaceholder(/Buscar produto ou escanear/i).first()
    await busca.click()
    const antesDaBusca = Date.now()
    await busca.fill('Zimbro')
    const achou = await esperaTexto(operadora, PRIMEIRA_PALAVRA, 15000)
    relatorio.medidas.busca_ms = Date.now() - antesDaBusca
    exigir(PRIMEIRA_PALAVRA.test(achou),
      `a busca do balcão não achou "${DO_FIM.nome}" entre ${relatorio.acervo.vendaveis} produtos`)
    await operadora.keyboard.press('Enter')
    const noCarrinho = await esperaTexto(operadora, /1 item/, 15000)
    await shot(operadora, 'busca-acha-o-fim-do-alfabeto')
    relatorio.etapas.push({
      etapa: 'a busca acha e vende o produto do fim do alfabeto',
      produto: DO_FIM.nome, ms: relatorio.medidas.busca_ms,
    })
    exigir(/1 item/.test(noCarrinho),
      `o produto do fim do alfabeto não entrou no carrinho: "${noCarrinho.slice(0, 200)}"`)

    // ---------------------------------------- 3. o que o servidor devolve à Gestão
    await gestao.goto(`${appUrl}/manage?module=assortments`, { waitUntil: 'domcontentloaded' })
    await gestao.waitForTimeout(5000)
    await shot(gestao, 'gestao-sortimentos')

    const mestre = await catalogoMestre(gestao)
    relatorio.servidor.catalogo_mestre = mestre
    relatorio.etapas.push({
      etapa: 'o catálogo mestre, como o seletor o recebe',
      devolvidos: mestre.quantos, de: relatorio.acervo.vendaveis,
      ultimo_nome: mestre.ultimo, ms: mestre.ms,
    })

    // ---------------------------------------- 4. o seletor do sortimento
    await gestao.getByRole('button', { name: /^Produtos \(/ }).first().click()
    await gestao.waitForTimeout(3000)

    const campoDeBusca = gestao.getByPlaceholder(/Buscar no catálogo mestre/i)
    const temBusca = await campoDeBusca.count() > 0
    relatorio.etapas.push({ etapa: 'o seletor de produtos do sortimento', tem_busca: temBusca })

    if (temBusca) {
      // Antes de digitar: a resposta veio no teto, e a tela precisa **dizer**
      // isso. O defeito não era o corte — era o silêncio dele.
      const semBuscaAinda = await esperaTexto(gestao, /Há mais produtos do que cabe/i, 15000)
      const avisaDoTeto = /Há mais produtos do que cabe/i.test(semBuscaAinda)
      relatorio.servidor.aviso_do_teto = avisaDoTeto
      await shot(gestao, 'seletor-avisa-que-ha-mais-do-que-cabe')
      exigir(avisaDoTeto,
        'com o acervo maior que o teto, o seletor precisa avisar que há mais — '
        + `e a tela diz: "${semBuscaAinda.slice(0, 200)}"`)

      await campoDeBusca.first().fill('Zimbro')
      const achouNaGestao = await esperaTexto(gestao, PRIMEIRA_PALAVRA, 15000)
      await shot(gestao, 'seletor-acha-o-fim-do-alfabeto')
      exigir(PRIMEIRA_PALAVRA.test(achouNaGestao),
        `o seletor não achou "${DO_FIM.nome}" pela busca: "${achouNaGestao.slice(0, 200)}"`)
    } else {
      // Sem busca, o seletor depende de a lista inteira caber nele. Conta-se
      // quantas opções chegaram e se o produto do fim está entre elas — devolver
      // menos do que existe **sem dizer** é o defeito: nem a tela nem o lojista
      // têm como saber que estão vendo um pedaço.
      const opcoes = await gestao.locator('select option').allTextContents()
      const ultima = opcoes.length ? opcoes[opcoes.length - 1] : '—'
      relatorio.servidor.seletor = {
        opcoes: opcoes.length,
        tem_o_do_fim: opcoes.some((t) => t.includes(DO_FIM.nome)),
        ultima,
      }
      await shot(gestao, 'seletor-sem-busca-nao-alcanca-o-fim')
      exigir(false,
        `o seletor de produtos não oferece busca: são ${opcoes.length} opções numa lista `
        + `que termina em "${ultima}", e "${DO_FIM.nome}" `
        + `${opcoes.some((t) => t.includes(DO_FIM.nome)) ? 'está' : 'NÃO está'} entre elas`)
    }
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom05-volumoso.json'),
                   JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  console.log(`medidas: ${JSON.stringify(relatorio.medidas)}`)
  console.log(`servidor: ${JSON.stringify(relatorio.servidor)}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exitCode = 1
}

run().catch((erro) => { console.error('FALHOU:', erro.message); process.exitCode = 1 })
