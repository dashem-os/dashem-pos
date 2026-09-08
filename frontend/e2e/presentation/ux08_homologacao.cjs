/**
 * UX-08 — a homologação integrada: Gestão → operação → conferência na Gestão.
 *
 * As sprints anteriores mediram cada superfície por si. Esta percorre a volta
 * inteira, que é a única que o lojista faz de verdade: cadastrar a mercadoria,
 * publicá-la, vendê-la no balcão, e voltar à Gestão para conferir que a venda e
 * o estoque contam a mesma história.
 *
 * O enunciado é explícito: *captura bonita não substitui comportamento
 * correto*. Então cada etapa afirma um número que veio do servidor, e a volta
 * fecha comparando o estoque de antes com o de depois.
 *
 * Os quatro tamanhos do aceite são percorridos na conferência final — é onde a
 * tabela aperta — e a acessibilidade é medida onde ela decide: o foco depois de
 * navegar e o rótulo de cada controle sem texto visível.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux08')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const marca = Date.now().toString().slice(-6)
const PRODUTO = { nome: `Caneca esmaltada ${marca}`, sku: `CAN-${marca}`, preco: '2500', estoque: '4' }

const TAMANHOS = [
  { nome: 'desktop-1366x768', width: 1366, height: 768 },
  { nome: 'desktop-baixo-1366x640', width: 1366, height: 640 },
  { nome: 'tablet-834x1112', width: 834, height: 1112 },
  { nome: 'celular-390x844', width: 390, height: 844 },
]

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [], acessibilidade: {} }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux08-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

async function novaPagina(navegador, tamanho) {
  const contexto = await navegador.newContext({
    viewport: { width: tamanho.width, height: tamanho.height }, deviceScaleFactor: 1, locale: 'pt-BR',
  })
  await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
    ['sb-127-auth-token', JSON.stringify(sessao())])
  const page = await contexto.newPage()
  page.setDefaultTimeout(25000)
  return { contexto, page }
}

const shot = async (page, nome) => {
  await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
  relatorio.telas.push(nome)
}

/** O disponível que a Gestão anuncia para esta mercadoria, lido da tabela. */
const disponivelNoEstoque = (page, sku) => page.evaluate((alvo) => {
  const linha = [...document.querySelectorAll('main tbody tr')].find((tr) => tr.innerText.includes(alvo))
  if (!linha) return null
  const achado = linha.innerText.match(/(\d+(?:[.,]\d+)?)\s*(?:UN|un)/)
  return achado ? Number(achado[1].replace(',', '.')) : null
}, sku)

async function main() {
  const navegador = await chromium.launch()
  try {
    const { contexto, page } = await novaPagina(navegador, TAMANHOS[0])

    // ============================================= 1. Gestão: cadastrar
    await page.goto(appUrl + '/manage?area=MERCADORIAS&module=products', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    if (!(await page.getByRole('button', { name: /Cadastrar Novo Produto/i }).count())) {
      throw new Error('A Gestão não carregou: ' + (await page.evaluate(() => (document.querySelector('main')?.innerText || '').slice(0, 200))))
    }
    await page.getByRole('button', { name: /Cadastrar Novo Produto/i }).first().click()
    await page.waitForTimeout(900)
    await page.getByPlaceholder(/Hambúrguer artesanal/).fill(PRODUTO.nome)
    await page.getByPlaceholder('Ex: CAB-25').fill(PRODUTO.sku)
    await page.getByPlaceholder('Ex.: 0,00').fill(PRODUTO.preco)
    // O campo de estoque inicial não tem placeholder: é alcançado pelo rótulo.
    await page.locator('label', { hasText: 'Estoque Inicial' }).locator('xpath=following-sibling::input[1]')
      .or(page.locator('input#estoque-inicial'))
      .first().fill(PRODUTO.estoque)

    // Publicar já no cadastro: é o caminho que leva a mercadoria ao balcão.
    const cardapio = page.locator('#new-product-assortment')
    const temCardapio = await cardapio.count() > 0
    if (temCardapio) {
      const opcoes = await cardapio.locator('option').allTextContents()
      const alvo = opcoes.find((o) => /Cardápio Principal/i.test(o))
      if (alvo) await cardapio.selectOption({ label: alvo })
    }
    await shot(page, '1-gestao-cadastro')
    await page.getByRole('button', { name: /Cadastrar e publicar produto|Cadastrar produto|Salvar alterações/i }).last().click()
    await page.waitForTimeout(3600)
    relatorio.etapas.push({ etapa: 'Gestão: cadastrar e publicar', sku: PRODUTO.sku, publicado: temCardapio })

    // ============================================= 2. Gestão: estoque de partida
    await page.goto(appUrl + '/manage?area=MERCADORIAS&module=inventory', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    await page.getByPlaceholder(/Buscar por produto ou SKU/).fill(PRODUTO.sku)
    await page.waitForTimeout(1500)
    const antes = await disponivelNoEstoque(page, PRODUTO.sku)
    await shot(page, '2-gestao-estoque-antes')
    relatorio.etapas.push({ etapa: 'Gestão: disponível antes da venda', disponivel: antes })
    exigir(antes === Number(PRODUTO.estoque),
      `o estoque inicial deveria ser ${PRODUTO.estoque} e a Gestão anunciou ${antes}`)

    // ============================================= 3. Operação: vender
    await page.goto(appUrl + '/pos?access=management', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3200)
    const abrirCaixa = page.getByRole('button', { name: /ABRIR CAIXA E INICIAR VENDAS/i })
    if (await abrirCaixa.count()) {
      await page.getByPlaceholder('0,00').first().fill('100,00')
      await abrirCaixa.click()
      await page.waitForTimeout(3200)
    }
    await page.getByPlaceholder(/Buscar produto ou escanear/).fill(PRODUTO.sku)
    await page.waitForTimeout(2200)
    await page.keyboard.press('Enter')
    await page.waitForTimeout(2600)
    await shot(page, '3-pdv-item-no-carrinho')

    const noCarrinho = await page.evaluate((alvo) => (document.body.innerText || '').includes(alvo), PRODUTO.nome)
    exigir(noCarrinho, 'a mercadoria cadastrada na Gestão não chegou ao balcão')

    await page.getByRole('button', { name: /^Receber/ }).first().click()
    await page.waitForTimeout(1400)
    await page.getByRole('button', { name: /Confirmar|Finalizar|Receber/i }).last().click()
    await page.waitForTimeout(4200)
    await shot(page, '4-pdv-venda-concluida')
    relatorio.etapas.push({ etapa: 'Operação: vender uma unidade', sku: PRODUTO.sku })

    // ============================================= 4. Gestão: conferir a volta
    await page.goto(appUrl + '/manage?area=MERCADORIAS&module=inventory', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    await page.getByPlaceholder(/Buscar por produto ou SKU/).fill(PRODUTO.sku)
    await page.waitForTimeout(1500)
    const depois = await disponivelNoEstoque(page, PRODUTO.sku)
    await shot(page, '5-gestao-estoque-depois')
    relatorio.etapas.push({ etapa: 'Gestão: disponível depois da venda', disponivel: depois })
    exigir(depois === antes - 1,
      `vender uma unidade deveria levar o disponível de ${antes} para ${antes - 1}, e a Gestão anuncia ${depois}`)

    await page.goto(appUrl + '/manage?area=OPERACAO&module=sales', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    // A vírgula é parte da afirmação: a tela mostrava "R$ 25.00" com ponto,
    // enquanto o PDV ao lado mostrava "R$ 80,00". Exigir o formato do país é o
    // que faz a travessia integrada valer mais que duas auditorias separadas.
    const naListaDeVendas = await page.evaluate(() => {
      const main = document.querySelector('main')
      const texto = main ? (main.innerText || '') : ''
      return { achou: /R\$\s*25,00/.test(texto), comPonto: /R\$\s*25\.00/.test(texto) }
    })
    await shot(page, '6-gestao-vendas')
    relatorio.etapas.push({ etapa: 'Gestão: a venda aparece em Vendas', ...naListaDeVendas })
    exigir(naListaDeVendas.achou, 'a venda feita no balcão não aparece na lista de Vendas da Gestão')
    exigir(!naListaDeVendas.comPonto, 'a lista de Vendas mostra dinheiro com ponto, e o resto do sistema usa vírgula')

    // ============================================= 5. Acessibilidade
    await page.goto(appUrl + '/manage', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2600)
    await page.getByRole('button', { name: 'Mercadorias' }).first().click()
    await page.waitForTimeout(1400)
    const foco = await page.evaluate(() => {
      const a = document.activeElement
      return { tag: a ? a.tagName : null, dentro_do_main: !!(a && a.closest('main')) }
    })
    const semRotulo = await page.evaluate(() => {
      return [...document.querySelectorAll('button, a[href], input, select')]
        .filter((el) => {
          const texto = (el.innerText || '').trim()
          const rotulo = el.getAttribute('aria-label') || el.getAttribute('title')
            || (el.id && document.querySelector(`label[for="${el.id}"]`))
            || el.closest('label')
            || el.getAttribute('placeholder')
          return !texto && !rotulo
        })
        .map((el) => el.tagName + (el.className ? '.' + String(el.className).split(' ')[0] : ''))
    })
    relatorio.acessibilidade = { foco, controles_sem_rotulo: [...new Set(semRotulo)] }
    exigir(foco.dentro_do_main, 'o foco não entrou no conteúdo depois de navegar')
    exigir(semRotulo.length === 0, `controles sem nome acessível: ${JSON.stringify([...new Set(semRotulo)])}`)

    await contexto.close()

    // ============================================= 6. Os quatro tamanhos
    for (const tamanho of TAMANHOS) {
      const { contexto: ctx, page: p } = await novaPagina(navegador, tamanho)
      await p.goto(appUrl + '/manage?area=MERCADORIAS&module=inventory', { waitUntil: 'domcontentloaded' })
      await p.waitForTimeout(2800)
      await shot(p, `7-conferencia-${tamanho.nome}`)
      const transbordo = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      relatorio.etapas.push({ etapa: `conferência em ${tamanho.nome}`, transbordo_horizontal: transbordo })
      exigir(transbordo <= 1, `em ${tamanho.nome} a página rola ${transbordo}px para o lado`)
      await ctx.close()
    }
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux08-homologacao.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
