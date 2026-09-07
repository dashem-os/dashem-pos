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
 * A saída é um relatório em JSON mais uma captura por tela e por tamanho.
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
  { nome: 'celular-390x844', width: 390, height: 844, nota: 'celular em retrato' },
  { nome: 'tablet-834x1112', width: 834, height: 1112, nota: 'tablet em retrato' },
  { nome: 'desktop-baixo-1366x640', width: 1366, height: 640, nota: 'altura reduzida' },
  { nome: 'zoom-150-1107x573', width: 1107, height: 573, nota: 'zoom de 150% sobre 1660x860' },
]

const TELAS = [
  { nome: 'produtos', rotulo: /^Produtos e pre/ },
  { nome: 'estoque', rotulo: /^Estoque$/ },
  { nome: 'sortimentos', rotulo: /^Sortimentos/ },
  { nome: 'categorias', rotulo: /^Categorias$/ },
]

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
  }
}

async function run() {
  const navegador = await chromium.launch()
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
      // Abaixo de 768px a navegação vive atrás do botão de menu.
      const menu = page.getByRole('button', { name: 'Abrir menu' })
      if (await menu.count() > 0 && await menu.isVisible()) await menu.click()
      await page.waitForTimeout(400)
      await page.getByRole('button', { name: tela.rotulo }).first().click()
      await page.waitForTimeout(2200)
      const medida = await page.evaluate(MEDIDA)
      relatorio.push({ tamanho: tamanho.nome, nota: tamanho.nota, tela: tela.nome, ...medida })
      await page.screenshot({ path: path.join(outDir, `${tamanho.nome}-${tela.nome}.png`), fullPage: false })
      const marca = medida.partidas.length === 0 && medida.transbordo <= 1 ? 'ok  ' : 'FALHA'
      console.log(`${marca} ${tamanho.nome.padEnd(24)} ${tela.nome.padEnd(12)} partidas=${medida.partidas.length} transbordo=${medida.transbordo}px`)
      for (const p of medida.partidas.slice(0, 4)) console.log(`        "${p.palavra}" em ${p.onde}`)
    }

    // O formulário é onde a largura aperta de verdade — e no celular a
    // navegação está atrás do menu, então voltar ao Estoque exige abri-lo.
    const menuDoFormulario = page.getByRole('button', { name: 'Abrir menu' })
    if (await menuDoFormulario.count() > 0 && await menuDoFormulario.isVisible()) {
      await menuDoFormulario.click()
      await page.waitForTimeout(400)
    }
    await page.getByRole('button', { name: /^Estoque$/ }).first().click().catch(() => undefined)
    await page.waitForTimeout(1800)
    const receber = page.getByRole('button', { name: 'Receber' }).first()
    if (await receber.count() > 0) {
      await receber.click()
      await page.waitForTimeout(900)
      const medida = await page.evaluate(MEDIDA)
      relatorio.push({ tamanho: tamanho.nome, nota: tamanho.nota, tela: 'formulario-receber', ...medida })
      await page.screenshot({ path: path.join(outDir, `${tamanho.nome}-formulario-receber.png`) })
      const marca = medida.partidas.length === 0 && medida.transbordo <= 1 ? 'ok  ' : 'FALHA'
      console.log(`${marca} ${tamanho.nome.padEnd(24)} ${'formulário'.padEnd(12)} partidas=${medida.partidas.length} transbordo=${medida.transbordo}px`)
      for (const p of medida.partidas.slice(0, 4)) console.log(`        "${p.palavra}" em ${p.onde}`)
    }
    await contexto.close()
  }

  fs.writeFileSync(path.join(outDir, 'relatorio.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  const falhas = relatorio.filter((linha) => linha.partidas.length > 0 || linha.transbordo > 1)
  console.log(`\n${relatorio.length} medições · ${falhas.length} com achado`)
  await navegador.close()
  process.exitCode = falhas.length === 0 ? 0 : 1
}

run().catch((erro) => { console.error(erro); process.exitCode = 1 })
