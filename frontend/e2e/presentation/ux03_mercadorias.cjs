/**
 * UX-03 — a jornada de Mercadorias, percorrida em vez de descrita.
 *
 * O aceite da sprint é uma jornada, não uma tela: cadastrar sem foto,
 * categorizar, decidir onde vender, conferir a publicação; e depois editar
 * preço, salvar e voltar ao filtro onde se estava.
 *
 * Duas afirmações que este roteiro existe para não deixar passar:
 *
 *  - **cadastrar não é publicar.** Salvar o produto sem escolher cardápio tem
 *    de dizer que ele está no acervo e ainda não é vendável. Anunciar
 *    publicação completa quando só o cadastro foi salvo é a mentira que o
 *    enunciado proíbe;
 *  - **categorizar tem de ser possível aqui.** Até a UX-03 só o banco
 *    categorizava: a tela de Categorias criava categorias que nenhum produto
 *    podia usar.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux03')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const marca = Date.now().toString().slice(-6)
const PRODUTO = { nome: `Camiseta de algodão ${marca}`, sku: `CAM-${marca}`, preco: '4990' }
const CATEGORIA = `Vestuário ${marca}`

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux03-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

const PRODUTOS = '/manage?area=MERCADORIAS&module=products'
const CATEGORIAS = '/manage?area=MERCADORIAS&module=categories'

async function shot(page, nome) {
  await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
  relatorio.telas.push(nome)
}

/** O texto do aviso que a tela acabou de dar. */
async function aviso(page) {
  const texto = await page.evaluate(() => {
    const alvos = [...document.querySelectorAll('body *')]
      .filter((el) => /Produto (cadastrado|atualizado|publicado)|publicado em/i.test(el.textContent || ''))
    const ultimo = alvos[alvos.length - 1]
    return ultimo ? ultimo.textContent.trim().slice(0, 220) : ''
  })
  return texto
}

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

    // ---------------------------------------------- 1. cadastrar sem foto
    await page.goto(appUrl + PRODUTOS, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2800)
    if (!(await page.getByRole('button', { name: /Cadastrar Novo Produto/i }).count())) {
      throw new Error('A tela de Produtos não carregou: ' + (await page.evaluate(() => (document.querySelector('main')?.innerText || '').slice(0, 200))))
    }
    await page.getByRole('button', { name: /Cadastrar Novo Produto/i }).first().click()
    await page.waitForTimeout(900)

    await page.getByPlaceholder(/Hambúrguer artesanal/).fill(PRODUTO.nome)
    await page.getByPlaceholder('Ex: CAB-25').fill(PRODUTO.sku)
    await page.getByPlaceholder('Ex.: 0,00').fill(PRODUTO.preco)

    // ---------------------------------------------- 2. categorizar aqui mesmo
    const seletor = page.locator('#new-product-category')
    exigir(await seletor.count() > 0, 'o formulário de produto não tem campo de categoria')
    await page.getByRole('button', { name: 'Nova categoria' }).first().click()
    await page.waitForTimeout(400)
    await page.getByLabel('Nome da nova categoria').fill(CATEGORIA)
    await page.getByRole('button', { name: /Criar e usar/ }).click()
    await page.waitForTimeout(1800)
    const escolhida = await seletor.evaluate((el) => el.options[el.selectedIndex].textContent.trim())
    exigir(escolhida === CATEGORIA, `a categoria criada não ficou escolhida: "${escolhida}"`)
    await shot(page, '1-cadastro-com-categoria-sem-foto')

    // ---------------------------------------------- 3. salvar sem publicar
    await page.getByRole('button', { name: /Cadastrar e publicar produto|Cadastrar produto|Salvar alterações/i }).last().click()
    await page.waitForTimeout(3200)
    const avisoDoCadastro = await aviso(page)
    relatorio.etapas.push({ etapa: 'cadastro sem publicação', aviso: avisoDoCadastro })
    exigir(/acervo/i.test(avisoDoCadastro), `o aviso não diz que ficou no acervo: "${avisoDoCadastro}"`)
    exigir(!/publicado/i.test(avisoDoCadastro), `o aviso anuncia publicação sem que se tenha publicado: "${avisoDoCadastro}"`)
    await shot(page, '2-salvo-no-acervo-sem-publicar')

    // ---------------------------------------------- 4. a categoria conta o novo
    await page.goto(appUrl + CATEGORIAS, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2800)
    const contagem = await page.evaluate((nome) => {
      const cartao = [...document.querySelectorAll('main article')].find((el) => el.textContent.includes(nome))
      if (!cartao) return null
      const achado = cartao.textContent.match(/(\d+)\s+itens/)
      return achado ? Number(achado[1]) : null
    }, CATEGORIA)
    relatorio.etapas.push({ etapa: 'categoria conta o produto novo', contagem })
    exigir(contagem === 1, `a categoria nova deveria contar 1 produto, contou ${contagem}`)
    await shot(page, '3-categoria-conta-o-produto')

    // ---------------------------------------------- 5. editar preço e voltar ao filtro
    await page.goto(appUrl + PRODUTOS, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2800)
    const busca = page.getByPlaceholder(/Buscar produto/)
    await busca.fill(PRODUTO.sku)
    await page.waitForTimeout(2200)
    await page.getByRole('button', { name: /^Editar$/ }).first().click()
    await page.waitForTimeout(1200)
    await page.getByPlaceholder('Ex.: 0,00').fill('5990')
    await page.getByRole('button', { name: /Cadastrar e publicar produto|Cadastrar produto|Salvar alterações/i }).last().click()
    await page.waitForTimeout(3200)
    const filtroDepois = await busca.inputValue().catch(() => '(campo ausente)')
    relatorio.etapas.push({ etapa: 'editar preço e voltar ao filtro', filtro: filtroDepois })
    exigir(filtroDepois === PRODUTO.sku, `o filtro não sobreviveu à edição: "${filtroDepois}"`)
    const precoNaLista = await page.evaluate(() => (document.querySelector('main')?.innerText || ''))
    exigir(/59,90/.test(precoNaLista), 'o preço editado não aparece na lista depois de salvar')
    await shot(page, '4-preco-editado-com-filtro-preservado')
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux03-mercadorias.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
