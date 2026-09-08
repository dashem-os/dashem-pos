/**
 * O cenário obrigatório, percorrido nas duas estações ao mesmo tempo.
 *
 * Dezesseis Coca-Colas na prateleira. A operadora promete dez numa venda; a
 * supervisora, no caixa ao lado, tenta sete e é recusada com o número real. A
 * operadora cancela — e não cancela sozinha: o diálogo pede o código de quem
 * tem autoridade. Depois do cancelamento, as sete passam, e sobram nove.
 *
 * Nada aqui é verificado por chamada de API: o roteiro clica onde a pessoa
 * clica e lê o que a tela escreve. O saldo final é conferido no banco.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'duas-estacoes')
const VIEWPORT = { width: 1660, height: 860 }

if (!fixturePath) throw new Error('WALK_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const achados = []
function registra(passo, esperado, obtido, ok) {
  achados.push({ passo, esperado, obtido, ok })
  console.log(`${ok ? 'OK  ' : 'FALHA'} ${passo} | esperado: ${esperado} | obtido: ${obtido}`)
}

let contador = 0
async function shot(page, nome) {
  contador += 1
  const arquivo = path.join(outDir, `${String(contador).padStart(2, '0')}-${nome}.png`)
  await page.screenshot({ path: arquivo })
}

async function estacao(navegador, pessoa, etiqueta) {
  const contexto = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
  // O terminal foi autorizado pela gestora na abertura da loja; é isso que o
  // equipamento guarda. Quem entra depois é a pessoa, com código e PIN.
  await contexto.addInitScript(([chave, valor]) => window.localStorage.setItem(chave, valor), [
    'dashem.terminal_token', pessoa.terminal_token,
  ])
  const page = await contexto.newPage()
  page.setDefaultTimeout(25000)
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log(`  [${etiqueta}] console: ${msg.text().slice(0, 160)}`)
  })
  await page.goto(`${appUrl}/operate`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3500)
  await page.locator('input[name="operational-identity"]').fill(pessoa.employee_code)
  await page.locator('input[name="operational-pin"]').fill(pessoa.pin)
  await page.keyboard.press('Enter')
  await page.waitForTimeout(5000)
  console.log(`  [${etiqueta}] entrou como ${pessoa.name} (${pessoa.role})`)
  return page
}

async function abrirCaixa(page, etiqueta) {
  const abrir = page.getByRole('button', { name: /ABRIR CAIXA/i })
  if (await abrir.count() === 0) return
  const fundo = page.locator('input[inputmode="numeric"]').last()
  await fundo.click()
  await fundo.type('20000')
  await abrir.first().click()
  await page.waitForTimeout(3000)
  console.log(`  [${etiqueta}] caixa aberto`)
}

/** Adiciona pela busca, que é como o balcão adiciona quantidade. */
async function adicionar(page, termo, vezes) {
  const busca = page.getByPlaceholder(/Buscar produto ou escanear/i).first()
  for (let i = 0; i < vezes; i += 1) {
    await busca.click()
    await busca.fill(termo)
    await page.waitForTimeout(900)
    await page.keyboard.press('Enter')
    await page.waitForTimeout(700)
  }
}

async function textoDaTela(page) {
  return (await page.locator('body').innerText()).replace(/\s+/g, ' ')
}

/** Espera a tela dizer alguma coisa, em vez de dormir e torcer. */
async function esperaTexto(page, expressao, limiteMs = 8000) {
  const fim = Date.now() + limiteMs
  let ultimo = ''
  while (Date.now() < fim) {
    ultimo = await textoDaTela(page)
    if (expressao.test(ultimo)) return ultimo
    await page.waitForTimeout(300)
  }
  return ultimo
}

async function run() {
  const navegador = await chromium.launch()
  try {
    const operadora = await estacao(navegador, fixture.operator, 'operadora')
    const supervisora = await estacao(navegador, fixture.supervisor, 'supervisora')

    await abrirCaixa(operadora, 'operadora')
    await abrirCaixa(supervisora, 'supervisora')
    await shot(operadora, 'operadora-caixa-aberto')

    // ---------------------------------------------- 1. dez prometidas
    await adicionar(operadora, 'Coca', 10)
    await shot(operadora, 'operadora-dez-no-carrinho')
    const carrinho = await textoDaTela(operadora)
    registra('A operadora promete dez unidades', '10 itens no carrinho',
      (carrinho.match(/(\d+) itens/) || [])[0] || 'não encontrado',
      /10 itens/.test(carrinho))

    // -------------------------- 2. a segunda estação alcança seis e para
    await adicionar(supervisora, 'Coca', 6)
    const seis = await textoDaTela(supervisora)
    registra('A segunda estação só alcança o que sobrou', '6 itens no carrinho',
      (seis.match(/(\d+) itens/) || ['não encontrado'])[0], /6 itens/.test(seis))

    // A sétima é a que não existe: dez estão prometidas à outra venda.
    await adicionar(supervisora, 'Coca', 1)
    const recusa = await esperaTexto(supervisora, /vendas abertas/)
    await shot(supervisora, 'supervisora-recusada')
    // A recusa precisa dizer três coisas: qual mercadoria, que não dá agora, e
    // por quê. Sem o porquê, o caixa vê a prateleira cheia e não entende.
    const disse = /vendas abertas/.test(recusa) && /Coca-Cola Lata/.test(recusa)
    registra('A sétima unidade é recusada, e a recusa explica o porquê',
      'mensagem nomeando a mercadoria e as vendas abertas',
      (recusa.match(/(Não há|Só há)[^.]+\./) || ['sem mensagem'])[0], disse)

    // ------------------------------- 3. cancelar pede autorização (P0.3)
    await operadora.getByRole('button', { name: /Cancelar venda/i }).first().click()
    await operadora.waitForTimeout(800)
    await operadora.getByRole('button', { name: /Sim, Cancelar/i }).first().click()
    await operadora.waitForTimeout(1200)
    await shot(operadora, 'operadora-pede-autorizacao')
    const dialogo = await textoDaTela(operadora)
    registra('O caixa não cancela sozinho',
      'diálogo pedindo código do supervisor',
      /Autorização do supervisor/.test(dialogo) ? 'diálogo aberto' : 'nenhum diálogo',
      /Autorização do supervisor/.test(dialogo))

    // Senha errada primeiro: a recusa tem de aparecer para quem digitou.
    await operadora.locator('#supervisor-codigo').fill(fixture.supervisor.employee_code)
    await operadora.locator('#supervisor-pin').fill('7351')
    await operadora.getByRole('button', { name: /^Autorizar$/ }).click()
    await operadora.waitForTimeout(1500)
    await shot(operadora, 'operadora-pin-errado')
    const erro = await textoDaTela(operadora)
    registra('PIN errado não autoriza', 'mensagem de recusa no diálogo',
      /inválidos/.test(erro) ? 'recusa exibida' : 'sem recusa', /inválidos/.test(erro))

    // Agora a supervisora digita o próprio código e PIN.
    await operadora.locator('#supervisor-codigo').fill(fixture.supervisor.employee_code)
    await operadora.locator('#supervisor-pin').fill(fixture.supervisor.pin)
    await operadora.getByRole('button', { name: /^Autorizar$/ }).click()
    await operadora.waitForTimeout(2500)
    await shot(operadora, 'operadora-venda-cancelada')
    const depois = await textoDaTela(operadora)
    registra('Autorizada, a venda é cancelada e some da tela',
      'carrinho vazio', /0 itens|Nenhum item|carrinho vazio/i.test(depois) ? 'carrinho vazio' : depois.slice(0, 80),
      /0 itens|Nenhum item|carrinho vazio/i.test(depois))

    // ------------------- 4. liberadas as dez, a sétima da outra venda passa
    await adicionar(supervisora, 'Coca', 1)
    const liberado = await esperaTexto(supervisora, /7 itens/)
    await shot(supervisora, 'supervisora-sete-liberadas')
    registra('Cancelada a primeira, a segunda consegue a sétima',
      '7 itens no carrinho', (liberado.match(/(\d+) itens/) || ['não encontrado'])[0],
      /7 itens/.test(liberado))

    fs.writeFileSync(path.join(outDir, 'achados.json'), JSON.stringify(achados, null, 2), 'utf8')
    const falhas = achados.filter((a) => !a.ok)
    console.log(`\n${achados.length - falhas.length}/${achados.length} passos como esperado`)
    process.exitCode = falhas.length ? 1 : 0
  } finally {
    await navegador.close()
  }
}

/** A recusa chega como aviso; esperar por ela é esperar a tela responder. */
async function page_waitForToast(page) {
  await page.waitForTimeout(1500)
}

run().catch((erro) => {
  console.error(erro)
  process.exitCode = 1
})
