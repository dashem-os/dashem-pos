/**
 * UX-01 — a navegação de sete áreas, medida contra os atritos da UX-00.
 *
 * O baseline mediu seis atritos. Este roteiro os remede um a um, com a mesma
 * definição, mais o que o contrato de navegação pede: sete áreas na entrada,
 * barra lateral que some ao escolher, topo com Menu principal e Sair, e retorno
 * ao hub por um caminho que diz para onde vai.
 *
 * Ele reprova quando qualquer medição prevista não acontece. Uma medida que
 * nunca acusa não prova nada — foi assim que a primeira rodada da UX-00
 * devolveu quinze fotos de um cartão de erro.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux01')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const TAMANHOS = [
  { nome: 'desktop-1440x900', width: 1440, height: 900, dsf: 1 },
  { nome: 'desktop-baixo-1366x640', width: 1366, height: 640, dsf: 1 },
  { nome: 'celular-390x844', width: 390, height: 844, dsf: 2 },
]
const AREAS_ESPERADAS = ['Operação', 'Mercadorias', 'Estrutura', 'Pessoas', 'Relacionamento', 'Financeiro', 'Administração']

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), entrada: null, atritos: [], telas: [], contrato: [] }
const falhas = []

function exigir(condicao, oQue) {
  if (!condicao) falhas.push(oQue)
  return !!condicao
}

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux01-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

async function novoContexto(navegador, tamanho) {
  const contexto = await navegador.newContext({
    viewport: { width: tamanho.width, height: tamanho.height },
    deviceScaleFactor: tamanho.dsf, locale: 'pt-BR',
  })
  await contexto.addInitScript(([chave, valor]) => {
    window.localStorage.setItem(chave, valor)
  }, ['sb-127-auth-token', JSON.stringify(sessao())])
  return contexto
}

const abrir = async (page, url) => {
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2200)
}

async function shot(page, nome) {
  await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
  relatorio.telas.push(nome)
}

/** O que a tela mostra: áreas da barra, cards do hub, ações do topo, título. */
async function ler(page) {
  return page.evaluate(() => {
    const asides = [...document.querySelectorAll('aside')]
      .map((el) => ({ el, caixa: el.getBoundingClientRect() }))
      .filter((m) => m.caixa.width > 0 && m.caixa.height > 0)
    const barra = asides[0]
    const main = document.querySelector('main')
    const cabecalho = document.querySelector('header')
    const cards = main ? [...main.querySelectorAll(':scope > div > div > button, :scope > div > .grid > button')] : []
    return {
      barra_visivel: !!barra,
      areas_na_barra: barra ? [...barra.el.querySelectorAll('nav button')].map((b) => b.textContent.replace(/\d+$/, '').trim()) : [],
      acoes_do_topo: cabecalho
        ? [...cabecalho.querySelectorAll('button')].map((b) => b.getAttribute('aria-label') || b.textContent.trim()).filter(Boolean)
        : [],
      titulo_do_topo: document.querySelector('header p') ? document.querySelector('header p').textContent.trim() : null,
      titulo_da_pagina: document.querySelector('main h1') ? document.querySelector('main h1').textContent.trim() : null,
      cards: cards.map((b) => b.innerText.split('\n').map((t) => t.trim()).filter(Boolean)),
      texto: main ? (main.innerText || '').trim().slice(0, 220) : '',
    }
  })
}

async function main() {
  const navegador = await chromium.launch()
  try {
    const grande = TAMANHOS[0]
    const contexto = await novoContexto(navegador, grande)
    const page = await contexto.newPage()
    page.setDefaultTimeout(20000)

    // ------------------------------------------------------ Entrada
    await abrir(page, appUrl + '/manage')
    const entrada = await ler(page)
    if (!entrada.barra_visivel || entrada.areas_na_barra.length === 0) {
      throw new Error('A entrada da Gestão não carregou; a tela dizia: ' + JSON.stringify(entrada.texto))
    }
    relatorio.entrada = entrada
    await shot(page, 'entrada-' + grande.nome)

    exigir(entrada.areas_na_barra.length === 7, `a entrada tem ${entrada.areas_na_barra.length} áreas, e o contrato pede 7`)
    exigir(
      AREAS_ESPERADAS.every((nome, i) => entrada.areas_na_barra[i] === nome),
      'as sete áreas não estão na ordem pedida: ' + JSON.stringify(entrada.areas_na_barra),
    )
    exigir(!entrada.areas_na_barra.includes('Visão geral'), 'a Visão geral voltou a ser uma oitava aba')
    relatorio.contrato.push({ item: 'sete áreas na entrada, sem oitava aba', areas: entrada.areas_na_barra })

    // ------------------------------------------------------ Hub
    await page.getByRole('button', { name: 'Mercadorias' }).first().click()
    await page.waitForTimeout(1200)
    const hub = await ler(page)
    await shot(page, 'hub-mercadorias-' + grande.nome)
    exigir(!hub.barra_visivel, 'a barra lateral não sumiu ao escolher a área')
    exigir(hub.cards.length === 4, `Mercadorias mostrou ${hub.cards.length} cards`)
    exigir(hub.cards.every((card) => card.length >= 2 && card[1].length > 0), 'card sem frase de tarefa')
    exigir(
      hub.acoes_do_topo.includes('Menu principal') && hub.acoes_do_topo.includes('Sair')
        && !hub.acoes_do_topo.includes('Validar no PDV'),
      'o topo do hub não é apenas Menu principal e Sair: ' + JSON.stringify(hub.acoes_do_topo),
    )
    relatorio.contrato.push({ item: 'hub de cards com barra oculta e topo de duas ações', cards: hub.cards, topo: hub.acoes_do_topo })

    // ------------------------------------------------------ Módulo
    await page.getByRole('button', { name: /^Estoques/ }).first().click()
    await page.waitForTimeout(1800)
    const modulo = await ler(page)
    await shot(page, 'modulo-estoques-' + grande.nome)
    exigir(modulo.titulo_do_topo === 'Estoques', 'o topo do módulo não nomeia o destino: ' + modulo.titulo_do_topo)
    exigir(
      await page.getByRole('button', { name: 'Voltar para Mercadorias' }).count() > 0,
      'o módulo não oferece "Voltar para Mercadorias"',
    )

    // --------------------------------------------- A1: voltar do navegador
    await page.goBack()
    await page.waitForTimeout(1500)
    const aposVoltar = await ler(page)
    await page.goBack()
    await page.waitForTimeout(1500)
    const aposVoltarDeNovo = await ler(page)
    await page.goForward()
    await page.waitForTimeout(1500)
    const aposAvancar = await ler(page)
    relatorio.atritos.push({
      atrito: 'A1 voltar-do-navegador-entre-modulos',
      medida: {
        depoisDoPrimeiroVoltar: aposVoltar.titulo_da_pagina,
        depoisDoSegundoVoltar: aposVoltar.titulo_da_pagina && aposVoltarDeNovo.titulo_da_pagina,
        depoisDeAvancar: aposAvancar.titulo_da_pagina,
      },
      resolvido: aposVoltar.titulo_da_pagina === 'Mercadorias'
        && aposVoltarDeNovo.titulo_da_pagina === 'O que você quer fazer?'
        && aposAvancar.titulo_da_pagina === 'Mercadorias',
    })

    // --------------------------------------------- A2: foco depois de navegar
    await abrir(page, appUrl + '/manage')
    await page.getByRole('button', { name: 'Operação' }).first().click()
    await page.waitForTimeout(1200)
    const foco = await page.evaluate(() => {
      const a = document.activeElement
      return { tag: a ? a.tagName : null, texto: ((a && a.textContent) || '').trim().slice(0, 40), dentro_do_main: !!(a && a.closest('main')) }
    })
    relatorio.atritos.push({ atrito: 'A2 foco-apos-navegar', medida: foco, resolvido: foco.dentro_do_main })

    // --------------------------------------------- A3: filtro preservado
    await abrir(page, appUrl + '/manage?area=MERCADORIAS')
    await page.getByRole('button', { name: /^Produtos e pre/ }).first().click()
    await page.waitForTimeout(1800)
    const busca = page.locator('main input[type="search"], main input[type="text"]').first()
    let filtro = { aplicavel: false }
    if (await busca.count()) {
      await busca.fill('coca')
      await page.waitForTimeout(900)
      await page.getByRole('button', { name: 'Voltar para Mercadorias' }).first().click()
      await page.waitForTimeout(1200)
      await page.getByRole('button', { name: /^Produtos e pre/ }).first().click()
      await page.waitForTimeout(1500)
      const depois = page.locator('main input[type="search"], main input[type="text"]').first()
      filtro = { aplicavel: true, digitado: 'coca', apos_retorno: (await depois.count()) ? await depois.inputValue() : '(campo ausente)' }
    }
    relatorio.atritos.push({ atrito: 'A3 filtro-preservado-ao-retornar', medida: filtro, resolvido: filtro.apos_retorno === 'coca' })

    // --------------------------------------------- A4 e A5: destinos que não existem
    for (const [nome, pedido] of [['A4 destino-desconhecido', 'fornecedores'], ['A5 destino-nao-autorizado', 'tables']]) {
      await abrir(page, appUrl + '/manage?module=' + pedido)
      const tela = await ler(page)
      await shot(page, 'indisponivel-' + pedido + '-' + grande.nome)
      relatorio.atritos.push({
        atrito: nome,
        medida: { titulo: tela.titulo_da_pagina, mostra_o_pedido: tela.texto.includes(pedido) },
        resolvido: tela.titulo_da_pagina === 'Este destino não está disponível' && tela.texto.includes(pedido),
      })
    }

    // --------------------------------------------- não pode regredir
    await abrir(page, appUrl + '/manage?module=inventory')
    const legado = await ler(page)
    const urlNormalizada = page.url()
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2200)
    const aposAtualizar = await ler(page)
    relatorio.atritos.push({
      atrito: 'link legado, link direto e atualizar (não podem regredir)',
      medida: { titulo: legado.titulo_do_topo, urlNormalizada, aposAtualizar: aposAtualizar.titulo_do_topo },
      resolvido: legado.titulo_do_topo === 'Estoques'
        && urlNormalizada.includes('area=MERCADORIAS')
        && aposAtualizar.titulo_do_topo === 'Estoques',
    })

    // --------------------------------------------- Menu principal volta à entrada
    // Este bloco existe porque a primeira versão deste roteiro passou com a
    // correção da `navigateTo` desfeita de propósito: ela nunca clicava aqui.
    // Só `goBack` e endereço direto eram exercitados, e nenhum dos dois usa
    // este caminho. Medida que não toca o botão não prova o botão.
    const voltasAoMenu = []
    for (const partida of ['/manage?area=MERCADORIAS', '/manage?area=MERCADORIAS&module=inventory']) {
      await abrir(page, appUrl + partida)
      await page.getByRole('button', { name: 'Menu principal' }).first().click()
      await page.waitForTimeout(1500)
      const depois = await ler(page)
      voltasAoMenu.push({ de: partida, titulo: depois.titulo_da_pagina, url: page.url() })
    }
    relatorio.atritos.push({
      atrito: 'Menu principal volta à entrada, do hub e do módulo',
      medida: voltasAoMenu,
      resolvido: voltasAoMenu.every((v) => v.titulo === 'O que você quer fazer?' && !v.url.includes('area=')),
    })

    await contexto.close()

    // --------------------------------------------- A6 e a dobra, por tamanho
    for (const tamanho of TAMANHOS.slice(1)) {
      const ctx = await novoContexto(navegador, tamanho)
      const p = await ctx.newPage()
      p.setDefaultTimeout(20000)
      await abrir(p, appUrl + '/manage')
      await shot(p, 'entrada-' + tamanho.nome)
      const tela = await ler(p)
      // A dobra da UX-00 media destinos de navegação, não botões de conteúdo.
      // Contar `main button` misturava o painel e inflava o número — medida
      // diferente não compara com a anterior. Aqui só as sete áreas contam, em
      // qualquer tamanho, porque nos dois lugares elas têm o mesmo nome.
      const areas = await p.evaluate(() => {
        // Há dois `nav` com esse nome — a barra do desktop e os cards do
        // celular — e um deles está sempre escondido por CSS. Pegar o primeiro
        // do documento faz o celular ser medido pela barra que ele não vê.
        const nav = [...document.querySelectorAll('nav[aria-label="Áreas da Gestão"]')]
          .find((el) => { const c = el.getBoundingClientRect(); return c.width > 0 && c.height > 0 })
        const alvos = nav ? [...nav.querySelectorAll('button')] : []
        return {
          total: alvos.length,
          rotulos: alvos.map((b) => (b.innerText || '').trim().split(/\r?\n/)[0].trim()),
          abaixo_da_dobra: alvos.filter((b) => b.getBoundingClientRect().bottom > window.innerHeight).length,
        }
      })
      relatorio['entrada_' + tamanho.nome] = {
        barra_visivel: tela.barra_visivel,
        areas: areas.total,
        rotulos: areas.rotulos,
        destinos_abaixo_da_dobra: areas.abaixo_da_dobra,
        acoes_do_topo: tela.acoes_do_topo,
      }
      exigir(areas.total === 7, `em ${tamanho.nome} a entrada mostrou ${areas.total} áreas`)
      // A dobra da UX-00 era sobre a tela fixa do balcão, onde rolar a barra
      // para achar "Estoques" é defeito. No celular, rolar a página é o idioma
      // do aparelho — o que não pode é a página rolar para o lado. Então o
      // critério de dobra zero vale para o desktop, e o celular responde outra
      // pergunta: as sete cabem na largura sem transbordar?
      if (tamanho.width >= 1024) {
        exigir(areas.abaixo_da_dobra === 0, `em ${tamanho.nome} ${areas.abaixo_da_dobra} áreas ficaram abaixo da dobra`)
      } else {
        const transbordo = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
        relatorio['entrada_' + tamanho.nome].transbordo_horizontal = transbordo
        exigir(!transbordo, `em ${tamanho.nome} a página transborda para o lado`)
      }
      await abrir(p, appUrl + '/manage?area=MERCADORIAS')
      await shot(p, 'hub-mercadorias-' + tamanho.nome)
      await ctx.close()
    }

    // A6 deixou de existir: sem gaveta no celular, não há menu para o Escape fechar.
    const celular = relatorio['entrada_celular-390x844']
    relatorio.atritos.push({
      atrito: 'A6 escape-nao-fecha-o-menu-do-celular',
      medida: { gaveta: !celular.acoes_do_topo.includes('Abrir menu') ? 'não existe mais' : 'ainda existe' },
      resolvido: !celular.acoes_do_topo.includes('Abrir menu'),
    })
  } finally {
    await navegador.close()
  }

  const naoResolvidos = relatorio.atritos.filter((a) => a.resolvido === false).map((a) => a.atrito)
  relatorio.falhas = [...falhas, ...naoResolvidos.map((a) => 'atrito não resolvido: ' + a)]
  fs.writeFileSync(path.join(outDir, 'ux01-navegacao.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`telas: ${relatorio.telas.length} · atritos remedidos: ${relatorio.atritos.length} · falhas: ${relatorio.falhas.length}`)
  if (relatorio.falhas.length) {
    relatorio.falhas.forEach((f) => console.error('  REPROVOU: ' + f))
    process.exit(1)
  }
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
