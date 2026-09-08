/**
 * UX-00 — inventário e baseline medidos na tela, não deduzidos do código.
 *
 * Percorre a Gestão publicada hoje e registra, para cada destino do mapa das
 * sete áreas: se ele existe na navegação, o que a tela mostra ao abri-lo, e
 * qual atrito o contrato de navegação encontra. Cada atrito é MEDIDO no
 * navegador — voltar do navegador é clicado, o foco é lido, o rótulo é lido da
 * barra — porque afirmar atrito a partir da leitura do código é adivinhar.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5191'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux00')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const MODULOS = [
  'overview', 'sales', 'cash', 'channels', 'receivables', 'products',
  'assortments', 'categories', 'inventory', 'customers', 'tables',
  'devices', 'team', 'payment_providers', 'subscription',
]
const TAMANHOS = [
  { nome: 'desktop-1440x900', width: 1440, height: 900, dsf: 1 },
  { nome: 'desktop-baixo-1366x640', width: 1366, height: 640, dsf: 1 },
  { nome: 'celular-390x844', width: 390, height: 844, dsf: 2 },
]
const relatorio = {
  app: appUrl, gerado_em: new Date().toISOString(),
  navegacao: null, modulos: [], atritos: [], telas: [], pdv: null,
}

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux00-local',
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

async function abrir(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
}

async function shot(page, nome) {
  const arquivo = path.join(outDir, nome + '.png')
  await page.screenshot({ path: arquivo, fullPage: false })
  relatorio.telas.push(nome)
  return arquivo
}

/** Lê a navegação renderizada: grupos, itens e rótulos, como o lojista vê. */
async function lerNavegacao(page) {
  return page.evaluate(() => {
    // Presença no DOM não é visibilidade: a barra lateral é `hidden lg:flex`,
    // então no celular ela existe e não aparece. E quando a gaveta do celular
    // abre há DOIS `aside` — a escondida e a aberta. Medir o retângulo e
    // escolher o que o lojista realmente vê, não o primeiro do documento.
    const asides = [...document.querySelectorAll('aside')]
    const medido = asides.map((el) => ({ el, caixa: el.getBoundingClientRect() }))
    const aparente = medido.find((m) => m.caixa.width > 0 && m.caixa.height > 0)
    const escolhido = aparente || medido[0] || null
    const aside = escolhido ? escolhido.el : null
    const caixa = escolhido ? escolhido.caixa : null
    const visivel = !!aparente
    const cabecalho = document.querySelector('header')
    const acoes = cabecalho
      ? [...cabecalho.querySelectorAll('button')].map((b) => b.getAttribute('aria-label') || b.textContent.trim() || '(sem nome)')
      : []
    if (!aside) return { encontrada: false, visivel: false, grupos: [], total_itens: 0, acoes_do_topo: acoes }
    const grupos = [...aside.querySelectorAll('nav > section')].map((secao) => ({
      grupo: (secao.querySelector('p') || {}).textContent ? secao.querySelector('p').textContent.trim() : '(sem rotulo)',
      itens: [...secao.querySelectorAll('button')].map((b) => b.textContent.trim()),
    }))
    // Quantos destinos exigem rolagem da barra para serem alcançados. Treze
    // itens numa tela de 900px é o argumento concreto do hub de cards: o
    // lojista não vê "Funcionários e acessos" sem rolar.
    const itensDom = aside ? [...aside.querySelectorAll('nav button')] : []
    const abaixoDaDobra = itensDom
      .filter((b) => b.getBoundingClientRect().bottom > window.innerHeight)
      .map((b) => b.textContent.trim())

    return {
      encontrada: true,
      visivel,
      largura_da_barra: caixa ? Math.round(caixa.width) : 0,
      itens_abaixo_da_dobra: abaixoDaDobra,
      grupos,
      total_itens: grupos.reduce((s, g) => s + g.itens.length, 0),
      acoes_do_topo: acoes,
    }
  })
}

/** O que o módulo mostra: título da barra, e se o conteúdo é módulo ou carcaça. */
async function lerModulo(page) {
  return page.evaluate(() => {
    const main = document.querySelector('main')
    const barra = document.querySelector('header p')
    const titulo = barra ? barra.textContent.trim() : null
    if (!main) return { titulo, estado: 'sem-main', caracteres: 0, interativos: 0, cabecalhos: [] }
    const texto = (main.innerText || '').trim()
    const interativos = main.querySelectorAll('button, a, input, select, textarea').length
    const cabecalhos = [...main.querySelectorAll('h1,h2,h3')].map((h) => h.textContent.trim()).slice(0, 4)
    const carcaca = interativos === 0 && texto.length < 60
    return { titulo, caracteres: texto.length, interativos, cabecalhos, estado: carcaca ? 'carcaca' : 'conteudo' }
  })
}

async function main() {
  const navegador = await chromium.launch()
  try {
    const grande = TAMANHOS[0]
    const contexto = await novoContexto(navegador, grande)
    const page = await contexto.newPage()
    const erros = []
    const respostasRuins = []
    page.on('console', (m) => { if (m.type() === 'error') erros.push(m.text().slice(0, 200)) })
    // Qual chamada falhou importa mais que o número: 409 sem endereço não se investiga.
    page.on('response', (r) => {
      if (r.status() >= 400) respostasRuins.push(r.status() + ' ' + r.request().method() + ' ' + r.url().replace(appUrl, ''))
    })
    page.setDefaultTimeout(20000)

    // ------------------------------------------------ 1. Entrada e módulos
    await abrir(page, appUrl + '/manage')
    relatorio.navegacao = await lerNavegacao(page)
    await shot(page, 'entrada-' + grande.nome)

    // Portão: sem Gestão carregada, toda captura seguinte é foto de erro.
    // Um roteiro que fotografa 15 vezes o mesmo cartão de falha e conclui
    // "15 capturas" não mede nada. Aqui ele reprova e diz o que estava na tela.
    if (!relatorio.navegacao.encontrada || relatorio.navegacao.total_itens === 0) {
      const naTela = await page.evaluate(() => (document.body.innerText || '').trim().slice(0, 300))
      throw new Error('A Gestão não carregou; a tela dizia: ' + JSON.stringify(naTela))
    }

    for (const id of MODULOS) {
      await abrir(page, appUrl + '/manage?module=' + id)
      const leitura = await lerModulo(page)
      const arquivo = await shot(page, 'modulo-' + id + '-' + grande.nome)
      relatorio.modulos.push(Object.assign({ id }, leitura, { captura: path.basename(arquivo) }))
    }

    // ------------------------------------------------ 2. Atritos medidos
    // (a) voltar do navegador entre módulos
    await abrir(page, appUrl + '/manage?module=sales')
    const antesDoClique = page.url()
    await page.getByRole('button', { name: /^Estoque$/ }).first().click()
    await page.waitForTimeout(1200)
    const depoisDoClique = page.url()
    await page.goBack().catch(() => null)
    await page.waitForTimeout(1800)
    const aposVoltar = await lerModulo(page)
    relatorio.atritos.push({
      atrito: 'voltar-do-navegador-entre-modulos',
      medida: { antesDoClique, depoisDoClique, urlAposVoltar: page.url(), tituloAposVoltar: aposVoltar.titulo },
      voltou_para_o_modulo_anterior: aposVoltar.titulo === 'Vendas',
    })

    // (b) link direto e atualizar
    await abrir(page, appUrl + '/manage?module=inventory')
    const linkDireto = await lerModulo(page)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2500)
    const aposAtualizar = await lerModulo(page)
    relatorio.atritos.push({
      atrito: 'link-direto-e-atualizar',
      medida: { linkDireto: linkDireto.titulo, aposAtualizar: aposAtualizar.titulo },
      link_direto_funciona: linkDireto.titulo === 'Estoque',
      atualizar_preserva: aposAtualizar.titulo === 'Estoque',
    })

    // (c) foco depois de navegar por clique
    await abrir(page, appUrl + '/manage?module=sales')
    await page.getByRole('button', { name: /^Categorias$/ }).first().click()
    await page.waitForTimeout(1200)
    const foco = await page.evaluate(() => {
      const a = document.activeElement
      return {
        tag: a ? a.tagName : null,
        texto: ((a && a.textContent) || '').trim().slice(0, 40),
        dentro_do_main: !!(a && a.closest('main')),
      }
    })
    relatorio.atritos.push({ atrito: 'foco-apos-navegar', medida: foco, foco_vai_para_o_conteudo: foco.dentro_do_main })

    // (d) filtro preservado ao sair e voltar
    await abrir(page, appUrl + '/manage?module=products')
    let filtro = { aplicavel: false }
    const busca = page.locator('main input[type="search"], main input[type="text"]').first()
    if (await busca.count()) {
      await busca.fill('coca')
      await page.waitForTimeout(900)
      await page.getByRole('button', { name: /^Categorias$/ }).first().click()
      await page.waitForTimeout(1200)
      await page.getByRole('button', { name: /^Produtos e pre/ }).first().click()
      await page.waitForTimeout(1800)
      const depois = page.locator('main input[type="search"], main input[type="text"]').first()
      filtro = {
        aplicavel: true, valor_digitado: 'coca',
        valor_apos_retorno: (await depois.count()) ? await depois.inputValue() : '(campo ausente)',
      }
    }
    relatorio.atritos.push({
      atrito: 'filtro-preservado-ao-retornar', medida: filtro,
      preserva: filtro.aplicavel === true && filtro.valor_apos_retorno === 'coca',
    })

    // (e) destino ausente pedido na URL
    await abrir(page, appUrl + '/manage?module=fornecedores')
    const inexistente = await lerModulo(page)
    relatorio.atritos.push({ atrito: 'destino-ausente-na-url', medida: { titulo: inexistente.titulo, estado: inexistente.estado } })

    relatorio.erros_de_console = [...new Set(erros)]
    relatorio.respostas_com_falha = [...new Set(respostasRuins)]
    await contexto.close()

    // ------------------------------------------------ 3. Tela baixa e celular
    for (const tamanho of TAMANHOS.slice(1)) {
      const ctx = await novoContexto(navegador, tamanho)
      const p = await ctx.newPage()
      p.setDefaultTimeout(20000)
      await abrir(p, appUrl + '/manage')
      await shot(p, 'entrada-' + tamanho.nome)
      const nav = await lerNavegacao(p)
      relatorio['navegacao_' + tamanho.nome] = {
        barra_lateral_visivel: nav.visivel,
        largura_da_barra: nav.largura_da_barra,
        total_itens: nav.total_itens,
        itens_abaixo_da_dobra: nav.itens_abaixo_da_dobra,
        acoes_do_topo: nav.acoes_do_topo,
      }
      // No celular a navegação só existe atrás do botão: medir se ela abre.
      if (!nav.visivel) {
        const abrir_menu = p.getByRole('button', { name: 'Abrir menu' }).first()
        if (await abrir_menu.count()) {
          await abrir_menu.click()
          await p.waitForTimeout(900)
          await shot(p, 'menu-aberto-' + tamanho.nome)
          const aberto = await lerNavegacao(p)
          relatorio['navegacao_' + tamanho.nome].apos_abrir_menu = {
            itens: aberto.total_itens, grupos: aberto.grupos.map((g) => g.grupo),
          }
          await p.keyboard.press('Escape')
          await p.waitForTimeout(400)
          relatorio['navegacao_' + tamanho.nome].escape_fecha_o_menu = !(await lerNavegacao(p)).visivel
        }
      }
      for (const id of ['products', 'inventory', 'sales', 'team']) {
        await abrir(p, appUrl + '/manage?module=' + id)
        await shot(p, 'modulo-' + id + '-' + tamanho.nome)
      }
      await ctx.close()
    }

    // ------------------------------------------------ 4. PDV aberto pela Gestão
    for (const tamanho of TAMANHOS) {
      const ctx = await novoContexto(navegador, tamanho)
      const p = await ctx.newPage()
      p.setDefaultTimeout(20000)
      await abrir(p, appUrl + '/pos?access=management')
      await p.waitForTimeout(2500)
      await shot(p, 'pdv-' + tamanho.nome)
      if (tamanho === TAMANHOS[0]) {
        relatorio.pdv = await p.evaluate(() => ({
          texto: (document.body.innerText || '').trim().slice(0, 500),
          botoes_do_topo: [...document.querySelectorAll('header button')]
            .map((b) => b.getAttribute('aria-label') || b.textContent.trim()).slice(0, 12),
        }))
      }
      await ctx.close()
    }
  } finally {
    await navegador.close()
  }
  fs.writeFileSync(path.join(outDir, 'ux00-baseline.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log('capturas: ' + relatorio.telas.length + ' · modulos lidos: ' + relatorio.modulos.length + ' · atritos medidos: ' + relatorio.atritos.length)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
