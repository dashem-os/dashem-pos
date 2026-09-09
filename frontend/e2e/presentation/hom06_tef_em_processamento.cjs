/**
 * Homologação — a cobrança TEF que saiu e não voltou.
 *
 * A UX-08 registrou isto como **o maior risco aberto**: *"estado pendente de
 * confirmação sem representação visual. Quem reenvia hoje acerta pelo carimbo,
 * não porque a tela explicou."* A regra do dono, na UX-07, é a que se cobra
 * aqui:
 *
 * > não tratar timeout como recusa, nem oferecer nova cobrança ou cancelamento
 * > sem resolver o estado anterior.
 *
 * **As três camadas, outra vez, porque misturá-las é o erro que interessa
 * evitar.** Esta travessia percorre a primeira e a segunda; a terceira **não**:
 *
 * 1. **configuração** — provedor, bridge e vínculo de maquininha, montados pelas
 *    rotas do produto em `seed_tef_awaiting_bridge.py`;
 * 2. **simulação** — o heartbeat do bridge sai daquele mesmo roteiro, no papel
 *    do Dashem TEF Bridge. Não há bridge instalado;
 * 3. **integração real com provedor** — **não percorrida**. O adaptador é o
 *    `BridgeQueuedAdapter`: ele enfileira a cobrança e devolve PROCESSING, e a
 *    consulta devolve UNKNOWN. Nenhum provedor foi contatado, nenhum cartão foi
 *    passado, nenhum dinheiro se moveu.
 *
 * O que a camada 3 não ter sido percorrida **não** impede: o estado "em
 * processamento" é exatamente o estado de uma cobrança sem resposta, e é dele
 * que a tela precisava saber falar.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5199'
const apiUrl = process.env.WALK_API_URL || 'http://127.0.0.1:8004'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'hom-tef')
const VIEWPORT = { width: 1660, height: 940 }

if (!fixturePath) throw new Error('WALK_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
if (!fixture.atendente) {
  throw new Error('fixture sem atendente: o salão pede código e PIN para assumir a operação')
}
if (!fixture.terminal_token) {
  throw new Error('fixture sem terminal autorizado: o salão não abre sem ponto de operação')
}
if (!fixture.payment_device_binding_id || !fixture.table_session_id) {
  throw new Error('fixture sem vínculo ou sessão: rode seed_tef_awaiting_bridge.py antes')
}
fs.mkdirSync(outDir, { recursive: true })

const relatorio = {
  app: appUrl, gerado_em: new Date().toISOString(),
  camadas: {
    configuracao: 'percorrida — provedor, bridge e vínculo pelas rotas do produto',
    simulacao_de_bridge: 'percorrida — heartbeat enviado pelo roteiro de cenário',
    integracao_real_com_provedor: 'NÃO percorrida — BridgeQueuedAdapter, nenhum provedor contatado',
  },
  mesa: fixture.service_table, etapas: [], telas: [], servidor: {},
}
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

let contador = 0
async function shot(page, nome) {
  contador += 1
  const arquivo = `${String(contador).padStart(2, '0')}-${nome}`
  await page.screenshot({ path: path.join(outDir, `${arquivo}.png`), fullPage: false })
  relatorio.telas.push(arquivo)
}

function sessaoDeGestao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'hom06',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Gestora da homologação' },
      created_at: new Date().toISOString(),
    },
  }
}

const naTela = async (page) => (await page.locator('body').innerText()).replace(/\s+/g, ' ')

async function esperaTexto(page, expressao, limiteMs = 25000) {
  const fim = Date.now() + limiteMs
  let ultimo = ''
  while (Date.now() < fim) {
    ultimo = await naTela(page)
    if (expressao.test(ultimo)) return ultimo
    await page.waitForTimeout(300)
  }
  return ultimo
}

/** O que o servidor responde a quem tenta soltar a parcela na mão. */
async function tentarSoltarPelaApi(page, intentId) {
  return page.evaluate(async ([api, tenant, store, token, parcela, ator]) => {
    const resposta = await fetch(`${api}/api/v1/negotiations/intents/${parcela}/cancel`, {
      method: 'POST',
      headers: {
        'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json', 'Idempotency-Key': `hom06-${Date.now()}`,
      },
      body: JSON.stringify({ actor_id: ator, reason: 'Homologação: tentativa de soltar à mão' }),
    })
    return { status: resposta.status, corpo: (await resposta.text()).slice(0, 400) }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token, intentId, fixture.gestora_id])
}

/** A parcela, como o servidor a descreve. */
async function parcelaNoServidor(page, negotiationId) {
  return page.evaluate(async ([api, tenant, store, token, conta]) => {
    const resposta = await fetch(`${api}/api/v1/negotiations/${conta}`, {
      headers: { 'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}` },
    })
    if (!resposta.ok) return { status: resposta.status }
    const corpo = await resposta.json()
    const aberta = corpo.intents[corpo.intents.length - 1]
    return {
      status: resposta.status, parcela: aberta && {
        situacao: aberta.status, aguardando: aberta.awaiting_provider,
        pode_cancelar: aberta.can_cancel, pode_consultar: aberta.can_query_provider,
      },
      em_processamento: corpo.processing_amount, confirmado: corpo.confirmed_amount,
      falta: corpo.remaining_amount,
    }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token, negotiationId])
}

async function run() {
  const navegador = await chromium.launch()
  try {
    const contexto = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
    await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessaoDeGestao())])
    // O salão é ponto de operação: sem terminal autorizado, `/tables` só mostra
    // "Ative este ponto de operação". O token vem do cenário, que autorizou o
    // aparelho pela rota do produto.
    await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['dashem.terminal_token', fixture.terminal_token])
    const page = await contexto.newPage()
    page.setDefaultTimeout(30000)

    // ---------------------------------------- 1. o salão, com a mesa ocupada
    //
    // Duas portas, e são diferentes: a Gestão entra por e-mail, o salão exige
    // que alguém **assuma a operação** com código e PIN num terminal
    // autorizado. Quem atende aqui é a Bruna, com perfil de caixa — que é o
    // perfil que carrega `provider.execute`.
    await page.goto(`${appUrl}/tables`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3500)
    const pedePin = page.locator('input[name="operational-identity"]')
    if (await pedePin.count()) {
      await pedePin.fill(fixture.atendente.employee_code)
      await page.locator('input[name="operational-pin"]').fill(fixture.atendente.pin)
      await page.keyboard.press('Enter')
      await page.waitForTimeout(5000)
      relatorio.etapas.push({
        etapa: 'a atendente assume a operação do salão',
        pessoa: fixture.atendente.name, perfil: fixture.atendente.role,
      })
    }
    // Caixa fechado é a primeira tela de quem assume o turno, e o salão fica
    // atrás dela: sem sessão de caixa não se recebe nada.
    const abrirCaixa = page.getByRole('button', { name: /ABRIR CAIXA E INICIAR VENDAS/i })
    if (await abrirCaixa.count()) {
      const fundo = page.locator('input[inputmode="numeric"]').last()
      await fundo.click()
      await fundo.type('20000')
      await abrirCaixa.first().click()
      await page.waitForTimeout(4000)
      relatorio.etapas.push({ etapa: 'a atendente abre o caixa do salão' })
    }

    // O salão é o destino "Mesas" do cabeçalho.
    const irParaMesas = page.getByRole('button', { name: /^Mesas$/ })
    if (await irParaMesas.count()) {
      await irParaMesas.first().click()
      await page.waitForTimeout(4000)
    }

    const comMesa = await esperaTexto(page, new RegExp(fixture.service_table.name), 30000)
    await shot(page, 'salao-com-a-mesa-ocupada')
    if (!exigir(new RegExp(fixture.service_table.name).test(comMesa),
      `a mesa "${fixture.service_table.name}" não apareceu no salão: "${comMesa.slice(0, 200)}"`)) {
      throw new Error('sem a mesa na tela, o resto da travessia não tem onde acontecer')
    }

    await page.getByRole('button', { name: new RegExp(fixture.service_table.name) }).first().click()
    const comConta = await esperaTexto(page, /Fechar conta completa/, 25000)
    relatorio.etapas.push({ etapa: 'a mesa abre com o consumo lançado' })
    exigir(/Fechar conta completa/.test(comConta),
      'a sessão da mesa não ofereceu fechar a conta')

    // ---------------------------------------- 2. a conta, e o TEF disponível
    await page.getByRole('button', { name: /Fechar conta completa/ }).click()

    // **Portão de carga.** A conta abre antes de o terminal e o vínculo TEF
    // chegarem: por um instante a tela diz "TEF não configurado ou offline", e
    // fotografar aí registra um estado que já passou. O que diz que a carga
    // terminou é a opção de TEF existir no seletor.
    const opcaoTef = page.locator('option[value="TEF_CREDIT"]')
    const limite = Date.now() + 25000
    while (Date.now() < limite && await opcaoTef.count() === 0) {
      await page.waitForTimeout(300)
    }
    const naConta = await naTela(page)
    await shot(page, 'conta-aberta-com-tef-online')
    const online = /TEF online/.test(naConta)
    relatorio.etapas.push({ etapa: 'a conta abre e a tela declara o estado do TEF', online })
    exigir(online,
      `a tela deveria declarar o TEF online — o bridge bateu heartbeat: "${naConta.slice(0, 240)}"`)

    // ---------------------------------------- 3. cobrar pelo TEF
    const meio = page.getByLabel('Meio de pagamento')
    await meio.selectOption('TEF_CREDIT')
    const valor = page.getByLabel('Valor da parcela')
    await valor.fill('18.00')
    await page.getByRole('button', { name: /Registrar parcela no meio selecionado/ }).click()

    // A cobrança sai e não volta. É este o estado que a homologação apontou
    // como sem representação na tela.
    const esperando = await esperaTexto(page, /Aguardando conciliação/i, 30000)
    await shot(page, 'a-cobranca-saiu-e-nao-voltou')
    const frase = (esperando.match(/Aguardando conciliação[^·]*·[^.]*\./) || ['—'])[0]
    relatorio.etapas.push({ etapa: 'a cobrança sai e o provider não responde', frase })
    exigir(/Aguardando conciliação/i.test(esperando),
      `a tela precisa dizer que está aguardando o provider: "${esperando.slice(0, 300)}"`)
    // Timeout não é recusa: a palavra "falhou" não pode aparecer para esta parcela.
    exigir(!/· falhou|· cancelado/i.test(esperando),
      `a parcela sem resposta não pode ser lida como recusada: "${esperando.slice(0, 300)}"`)

    // ---------------------------------------- 4. o que a tela oferece, e o que não
    const temConsultar = await page.getByRole('button', { name: /Consultar pagamento/ }).count()
    const temCancelar = await page.getByRole('button', { name: /Cancelar reserva/ }).count()
    relatorio.etapas.push({
      etapa: 'as duas ações não são simétricas, e a tela não as oferece juntas',
      consultar_pagamento: temConsultar > 0, cancelar_reserva: temCancelar > 0,
    })
    exigir(temConsultar > 0,
      'com a cobrança sem resposta, "Consultar pagamento" é a saída honesta e precisa estar na tela')
    // **A regra do dono.** Oferecer cancelar aqui é oferecer soltar a conta com
    // um cartão possivelmente aprovado do outro lado.
    exigir(temCancelar === 0,
      'a tela ofereceu "Cancelar reserva" para uma parcela cuja cobrança não teve resposta')

    // ---------------------------------------- 4b. e nova cobrança, também não
    //
    // A outra metade da regra do dono. O servidor já recusava a segunda
    // cobrança — com "Parcela excede o saldo reservável de 0.0000", que ninguém
    // no balcão entende — mas a tela dizia "Falta R$ 18,00", propunha esse valor
    // e deixava o botão aceso. Descobrir pela recusa não é ser avisado.
    const propoe = await page.getByLabel('Valor da parcela').inputValue()
    const botaoCobrar = page.getByRole('button', { name: /Registrar parcela no meio selecionado/ })
    const cobrarLigado = await botaoCobrar.isEnabled()
    const naTelaAgora = await naTela(page)
    const avisa = /Não há valor para cobrar agora/i.test(naTelaAgora)
    const mostraEmProcessamento = /Em processamento/i.test(naTelaAgora)
    await shot(page, 'nova-cobranca-nao-e-oferecida')
    relatorio.etapas.push({
      etapa: 'com a cobrança em voo, a tela não propõe outra',
      valor_proposto: propoe, botao_ligado: cobrarLigado,
      avisa: avisa, mostra_em_processamento: mostraEmProcessamento,
    })
    exigir(Number(propoe) === 0,
      `a tela propôs cobrar ${propoe} enquanto a cobrança anterior não teve resposta`)
    exigir(!cobrarLigado,
      'o botão de cobrar continuou aceso com a cobrança anterior sem resposta')
    exigir(avisa,
      `a tela precisa dizer por que não dá para cobrar agora: "${naTelaAgora.slice(0, 300)}"`)
    exigir(mostraEmProcessamento,
      '"Falta R$ 18,00" sozinho engana: a conta precisa mostrar quanto está em processamento')

    // ---------------------------------------- 5. consultar não solta nada
    const conta = await page.evaluate(() => {
      const marca = window.location.pathname
      return marca
    })
    await page.getByRole('button', { name: /Consultar pagamento/ }).first().click()
    await page.waitForTimeout(3000)
    const depoisDaConsulta = await naTela(page)
    await shot(page, 'consultar-nao-solta-a-conta')
    relatorio.etapas.push({
      etapa: 'consultar o provider não resolve sozinho, e não libera',
      continua_aguardando: /Aguardando conciliação/i.test(depoisDaConsulta),
      pagina: conta,
    })
    exigir(/Aguardando conciliação/i.test(depoisDaConsulta),
      'depois de consultar, sem resposta do provider, a parcela precisa continuar aguardando')

    // ---------------------------------------- 6. o servidor, e a tentativa de soltar à mão
    // A conta da sessão não vem no projetado da mesa. Abri-la de novo devolve a
    // mesma: `open_negotiation` procura a negociação ativa pelo escopo antes de
    // criar outra — é o que a própria tela faz ao reabrir a conta.
    const negociacaoId = await page.evaluate(async ([api, tenant, store, token, sessao, loja, ator]) => {
      const resposta = await fetch(`${api}/api/v1/negotiations`, {
        method: 'POST',
        headers: {
          'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json', 'Idempotency-Key': `hom06-conta-${Date.now()}`,
        },
        body: JSON.stringify({ store_id: loja, table_session_id: sessao, order_ids: [], actor_id: ator }),
      })
      if (!resposta.ok) return null
      return (await resposta.json()).id || null
    }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token,
        fixture.table_session_id, fixture.store_id, fixture.gestora_id])
    relatorio.servidor.negotiation_id = negociacaoId

    if (negociacaoId) {
      const noServidor = await parcelaNoServidor(page, negociacaoId)
      relatorio.servidor.parcela = noServidor
      exigir(noServidor.parcela && noServidor.parcela.situacao === 'PROCESSING',
        `o servidor deveria ter a parcela em PROCESSING: ${JSON.stringify(noServidor)}`)
      exigir(noServidor.parcela && noServidor.parcela.pode_cancelar === false,
        'o servidor não pode considerar cancelável uma parcela com cobrança sem resposta')

      const soltar = await tentarSoltarPelaApi(page, await page.evaluate(async ([api, tenant, store, token, conta]) => {
        const r = await fetch(`${api}/api/v1/negotiations/${conta}`, {
          headers: { 'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}` },
        })
        const corpo = await r.json()
        return corpo.intents[corpo.intents.length - 1].id
      }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token, negociacaoId]))
      relatorio.servidor.tentativa_de_soltar = soltar
      relatorio.etapas.push({
        etapa: 'soltar a parcela por fora da tela também é recusado',
        status: soltar.status,
      })
      // A tela não oferece — e quem tentar pela API leva a mesma recusa, com o
      // caminho certo nomeado. Proteção com caminho alternativo não é proteção.
      exigir(soltar.status === 409,
        `a API deveria recusar o cancelamento com 409, e devolveu ${soltar.status}: ${soltar.corpo}`)
      exigir(/EXTERNAL_CHARGE_IN_FLIGHT/.test(soltar.corpo),
        `a recusa deveria nomear a cobrança em voo: ${soltar.corpo}`)
      exigir(/Consulte o pagamento/i.test(soltar.corpo),
        `a recusa deveria apontar o caminho certo: ${soltar.corpo}`)
    } else {
      exigir(false, 'não achei a conta da sessão para conferir a parcela no servidor')
    }
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom06-tef.json'),
                   JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  console.log(`servidor: ${JSON.stringify(relatorio.servidor)}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exitCode = 1
}

run().catch((erro) => { console.error('FALHOU:', erro.message); process.exitCode = 1 })
