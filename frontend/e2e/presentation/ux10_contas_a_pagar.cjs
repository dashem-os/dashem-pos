/**
 * UX-10 — Contas a pagar: o que a loja deve, e o que continua não acontecendo.
 *
 * Metade desta travessia prova a fronteira que o dono nomeou: **receber
 * mercadoria não gera dívida**. Ela percorre o recebimento na tela de Estoques e
 * volta para conferir que nenhuma conta apareceu — que é a única forma de provar
 * que o gatilho proibido não existe *pelo caminho de quem usa*.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux10')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const marca = Date.now().toString().slice(-6)
const LUZ = { nome: `Companhia de Energia ${marca}`, valor: '480', descricao: 'Energia de setembro' }
const ATRASADA = { nome: `Aluguel ${marca}`, valor: '2500' }

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

const dia = (deslocamento) => {
  const d = new Date()
  d.setDate(d.getDate() + deslocamento)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux10-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

/**
 * Portão de carga: esperar no relógio fotografa a tela ainda vazia.
 *
 * `onde` importa. O diálogo é irmão de `main`, não filho: esperar o painel de
 * pagamento olhando só para `main` esgota o tempo com o painel aberto na tela,
 * e a mensagem de falha acusa o produto por um erro que é da medida.
 */
const esperar = async (page, padrao, oQue, limite = 20000, onde = 'main') => {
  const inicio = Date.now()
  let visto = ''
  while (Date.now() - inicio < limite) {
    visto = await page.evaluate((seletor) => {
      const alvo = seletor === 'dialog'
        ? document.querySelector('[role="dialog"]')
        : document.querySelector('main')
      return alvo ? alvo.innerText : ''
    }, onde)
    if (padrao.test(visto)) return visto
    await page.waitForTimeout(400)
  }
  throw new Error(`${oQue} não apareceu em ${limite}ms. Onde se olhou: ${visto.slice(0, 300)}`)
}

const naTela = (page) => page.evaluate(() => (document.querySelector('main')?.innerText || ''))
const noDialogo = (page) => page.evaluate(() => {
  const dialogo = document.querySelector('[role="dialog"]')
  return dialogo ? dialogo.innerText : ''
})

/**
 * A linha **desta** rodada.
 *
 * `.first()` clicava na conta da execução anterior, que já tinha baixa,
 * reversão e ajuste — e a medida reprovava saldos que estavam certos para
 * aquela conta. O alvo é o nome que esta rodada lançou.
 */
const linhaDe = (page, nome) => page.locator('tr').filter({ hasText: nome })

/** "Em aberto: R$ 9.970,00 em 8 contas" — o número que interessa é o 8. */
const quantasContas = (texto) => {
  const achado = texto.match(/em (\d+) contas?/)
  return achado ? Number(achado[1]) : 0
}

const shot = async (page, nome) => {
  await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
  relatorio.telas.push(nome)
}

async function lancar(page, { nome, valor, vencimento, descricao }) {
  await page.getByRole('button', { name: 'Lançar conta' }).first().click()
  await page.waitForTimeout(900)
  await page.getByLabel('Favorecido', { exact: true }).fill(nome)
  await page.getByLabel('Valor', { exact: true }).fill(valor)
  await page.getByLabel('Vencimento', { exact: true }).fill(vencimento)
  if (descricao) await page.getByLabel('Descrição', { exact: true }).fill(descricao)
  await page.getByRole('button', { name: 'Lançar conta' }).last().click()
  await esperar(page, new RegExp(nome), `a conta de ${nome}`)
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

    // ================== 1. o card existe em Financeiro
    await page.goto(appUrl + '/manage?area=FINANCEIRO', { waitUntil: 'domcontentloaded' })
    const noHub = await esperar(page, /Contas a pagar/i, 'o card de Contas a pagar')
    await shot(page, '1-card-em-financeiro')
    relatorio.etapas.push({ etapa: 'o card existe em Financeiro' })
    exigir(/Acompanhe o que você deve/i.test(noHub),
      'o card deveria trazer a frase de tarefa do mapa')

    await page.getByRole('button', { name: /^Contas a pagar/ }).first().click()
    await esperar(page, /Lançar conta/, 'a tela de Contas a pagar')
    await shot(page, '2-tela-vazia')

    // ================== 2. lançar, e nada lança sozinho
    await lancar(page, { nome: LUZ.nome, valor: LUZ.valor, vencimento: dia(10), descricao: LUZ.descricao })
    await lancar(page, { nome: ATRASADA.nome, valor: ATRASADA.valor, vencimento: dia(-3) })
    const comContas = await naTela(page)
    await shot(page, '3-contas-lancadas')
    relatorio.etapas.push({ etapa: 'lançar', apareceram: comContas.includes(LUZ.nome) && comContas.includes(ATRASADA.nome) })
    exigir(comContas.includes(LUZ.nome) && comContas.includes(ATRASADA.nome),
      'as contas lançadas não apareceram na lista')

    // ================== 3. vencida é a data contra hoje, não uma coluna
    relatorio.etapas.push({ etapa: 'vencida é derivada', acusou: /venceu há 3 dias/.test(comContas) })
    exigir(/venceu há 3 dias/.test(comContas),
      'a conta com vencimento no passado deveria aparecer como vencida, com quantos dias')
    exigir(/conta vencida|contas vencidas/.test(comContas),
      'o topo deveria resumir quantas contas estão vencidas')
    // E a ordem é por vencimento: quem entra aqui está decidindo o que pagar.
    exigir(comContas.indexOf(ATRASADA.nome) < comContas.indexOf(LUZ.nome),
      'a lista deveria vir ordenada por vencimento, com a mais antiga primeiro')

    // ================== 4. dinheiro em português
    relatorio.etapas.push({ etapa: 'dinheiro com vírgula', escreveu: /R\$\s?2\.500,00/.test(comContas) })
    exigir(/R\$\s?2\.500,00/.test(comContas),
      'o valor deveria ser escrito em português, com vírgula e separador de milhar')

    // ================== 5. baixa parcial deixa a conta aberta pelo saldo certo
    await linhaDe(page, ATRASADA.nome).getByRole('button', { name: 'Dar baixa' }).click()
    await esperar(page, /Registrar pagamento/, 'o painel de pagamento', 20000, 'dialog')
    await page.getByLabel('Valor pago').fill('1000')
    await page.getByLabel('Forma').fill('Pix')
    await shot(page, '4-baixa-parcial-preenchida')
    await page.getByRole('button', { name: 'Registrar pagamento' }).click()
    await page.waitForTimeout(2600)
    const depoisDaParcial = await noDialogo(page)
    await shot(page, '5-baixa-parcial-registrada')
    relatorio.etapas.push({ etapa: 'baixa parcial', saldo: /R\$\s?1\.500,00/.test(depoisDaParcial) })
    exigir(/R\$\s?1\.500,00/.test(depoisDaParcial),
      'depois de pagar 1.000 de 2.500, a conta deveria mostrar 1.500 de saldo')
    exigir(/Pagamento/.test(depoisDaParcial), 'o histórico deveria registrar o pagamento')

    // ================== 6. reverter devolve o saldo e deixa as duas coisas à vista
    page.once('dialog', (dialogo) => dialogo.accept('Paguei a conta errada'))
    await page.getByRole('button', { name: 'Desfazer' }).first().click()
    await page.waitForTimeout(2800)
    const depoisDeReverter = await noDialogo(page)
    await shot(page, '6-baixa-desfeita')
    relatorio.etapas.push({
      etapa: 'reverter',
      voltou: /R\$\s?2\.500,00/.test(depoisDeReverter),
      mostraAsDuas: /Desfeito/.test(depoisDeReverter),
    })
    exigir(/Desfeito/.test(depoisDeReverter),
      'o histórico deveria marcar a baixa como desfeita, não apagá-la')
    exigir(/Lançamento desfeito/.test(depoisDeReverter),
      'a reversão deveria aparecer como lançamento próprio')

    // ================== 7. o ajuste é digitado, e diz que não calcula nada
    await page.getByRole('button', { name: /Ajustar valor/ }).click()
    await page.waitForTimeout(800)
    await page.getByLabel('Valor do ajuste').fill('50')
    await page.getByLabel('Motivo do ajuste').fill('Multa combinada por telefone')
    const antesDoAjuste = await noDialogo(page)
    await shot(page, '7-ajuste-preenchido')
    relatorio.etapas.push({ etapa: 'ajuste', avisa: /não calcula juros nem desconto/.test(antesDoAjuste) })
    exigir(/não calcula juros nem desconto/.test(antesDoAjuste),
      'a tela deveria dizer que o sistema não calcula juros nem desconto')
    await page.getByRole('button', { name: 'Lançar ajuste' }).click()
    await page.waitForTimeout(2600)
    const depoisDoAjuste = await noDialogo(page)
    await shot(page, '8-ajuste-lancado')
    exigir(/R\$\s?2\.550,00/.test(depoisDoAjuste),
      'depois do acréscimo de 50, o saldo deveria ser 2.550')
    exigir(/Acréscimo/.test(depoisDoAjuste), 'o ajuste deveria aparecer no histórico')

    await page.keyboard.press('Escape').catch(() => null)
    await page.waitForTimeout(900)

    // ================== 8. a fronteira: receber mercadoria não gera dívida
    const antes = quantasContas(await naTela(page))
    await page.goto(appUrl + '/manage?area=MERCADORIAS&module=inventory', { waitUntil: 'domcontentloaded' })
    // O título aparece antes das linhas. Esperar por ele e perguntar logo em
    // seguida se existe botão "Receber" mede a tela meio carregada — e a
    // resposta "não existe" mandava a travessia pelo caminho errado.
    await esperar(page, /Estoque por unidade/, 'a lista de estoque')
    await page.getByRole('button', { name: /^Ações de / }).first().waitFor({ state: 'visible' })
    const botaoDireto = page.getByRole('button', { name: /^Receber$/ })
    if (await botaoDireto.count()) {
      await botaoDireto.first().click()
    } else {
      await page.getByRole('button', { name: /^Ações de / }).first().click()
      await page.waitForTimeout(700)
      await page.getByRole('menuitem', { name: 'Receber mercadoria' }).first().click()
    }
    await page.waitForTimeout(1200)
    await page.getByLabel(/Quantidade recebida/).fill('12')
    await page.getByRole('button', { name: 'Confirmar recebimento' }).click()
    await page.waitForTimeout(3200)
    await shot(page, '9-recebimento-feito')

    await page.goto(appUrl + '/manage?area=FINANCEIRO&module=payables', { waitUntil: 'domcontentloaded' })
    // O título aparece antes das linhas: esperar por ele leria a lista vazia e
    // acusaria o produto de ter apagado as contas.
    const depoisDoRecebimento = await esperar(
      page, new RegExp(ATRASADA.nome), 'a lista de contas de volta')
    await shot(page, '10-nenhuma-divida-nova')
    const nomesConhecidos = [LUZ.nome, ATRASADA.nome]
    const linhasDeConta = quantasContas(depoisDoRecebimento)
    relatorio.etapas.push({
      etapa: 'receber mercadoria não gera dívida',
      contasAntes: antes, contasDepois: linhasDeConta,
    })
    exigir(nomesConhecidos.every((nome) => depoisDoRecebimento.includes(nome)),
      'as contas lançadas manualmente sumiram depois do recebimento')
    exigir(linhasDeConta === antes,
      `o recebimento criou dívida sozinho: eram ${antes} contas em aberto e passaram a ser ${linhasDeConta}`)
    // E nada na tela promete o que a primeira entrega não faz.
    exigir(!/parcelar|parcelamento|juros automáticos|calcular juros/i.test(depoisDoRecebimento),
      'a tela promete parcelamento ou cálculo de juros, que estão fora da primeira entrega')
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux10-contas-a-pagar.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
