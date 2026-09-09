/**
 * Homologação — a resposta que chegou depois, e a tela que volta para ela.
 *
 * A hom06 percorreu a cobrança que sai e não volta. Falta o outro lado: o
 * provider **responde**, tarde, e ninguém estava olhando. As perguntas são três,
 * e todas são sobre dinheiro:
 *
 * 1. a resposta tardia fecha a parcela, e a tela retomada mostra isso?
 * 2. o provider repetindo a mesma resposta confirma duas vezes?
 * 3. uma resposta que contradiz a anterior anda para trás e solta saldo?
 *
 * **O que este roteiro é.** A resposta tardia é enviada por ele, no papel do
 * Dashem TEF Bridge, pela rota de callback do bridge. Não há bridge instalado e
 * nenhum provedor foi contatado — a camada de integração real continua não
 * percorrida, como na hom06.
 *
 * **O que ele não é.** A reconciliação pelo worker não se prova por tela: ela
 * roda sem ninguém olhando, e a janela que ela conserta é uma queda entre dois
 * commits. Essa prova é determinística e vive no backend, em
 * `test_s25_1_payment_recovery.py`. Aqui se prova o que a pessoa vê.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5199'
const apiUrl = process.env.WALK_API_URL || 'http://127.0.0.1:8004'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'hom-tardia')
const VIEWPORT = { width: 1660, height: 940 }

if (!fixturePath) throw new Error('WALK_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
for (const chave of ['terminal_token', 'atendente', 'bridge_terminal', 'payment_device_binding_id']) {
  if (!fixture[chave]) throw new Error(`fixture sem ${chave}: rode seed_tef_awaiting_bridge.py antes`)
}
fs.mkdirSync(outDir, { recursive: true })

const relatorio = {
  app: appUrl, gerado_em: new Date().toISOString(),
  camadas: {
    resposta_tardia: 'enviada por este roteiro, no papel do bridge',
    integracao_real_com_provedor: 'NÃO percorrida — nenhum provedor foi contatado',
    reconciliacao_pelo_worker: 'provada no backend, não por tela',
  },
  etapas: [], telas: [], servidor: {},
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

function sessaoDeGestao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'hom07',
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

/** A conta, como o servidor a descreve. */
async function contaNoServidor(page, negotiationId) {
  return page.evaluate(async ([api, tenant, store, token, conta]) => {
    const resposta = await fetch(`${api}/api/v1/negotiations/${conta}`, {
      headers: { 'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}` },
    })
    if (!resposta.ok) return { status: resposta.status }
    const corpo = await resposta.json()
    return {
      status: resposta.status,
      confirmado: corpo.confirmed_amount, em_processamento: corpo.processing_amount,
      falta: corpo.remaining_amount,
      parcelas: corpo.intents.map((row) => ({ id: row.id, situacao: row.status, valor: row.amount })),
      divergencias: (corpo.divergences || []).map((row) => row.kind),
    }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token, negotiationId])
}

/** A conta desta sessão, reaberta — `open_negotiation` devolve a ativa. */
async function contaDaSessao(page) {
  return page.evaluate(async ([api, tenant, store, token, sessao, loja, ator]) => {
    const resposta = await fetch(`${api}/api/v1/negotiations`, {
      method: 'POST',
      headers: {
        'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json', 'Idempotency-Key': `hom07-conta-${Date.now()}`,
      },
      body: JSON.stringify({ store_id: loja, table_session_id: sessao, order_ids: [], actor_id: ator }),
    })
    if (!resposta.ok) return null
    return (await resposta.json()).id || null
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token,
      fixture.table_session_id, fixture.store_id, fixture.gestora_id])
}

/** Tentar cancelar devolve 409 — e, no corpo dele, o id da transação do provider. */
async function idDaTransacao(page, intentId) {
  return page.evaluate(async ([api, tenant, store, token, parcela, ator]) => {
    const resposta = await fetch(`${api}/api/v1/negotiations/intents/${parcela}/cancel`, {
      method: 'POST',
      headers: {
        'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json', 'Idempotency-Key': `hom07-${Date.now()}`,
      },
      body: JSON.stringify({ actor_id: ator, reason: 'Homologação: descobrir a transação do provider' }),
    })
    const corpo = await resposta.json().catch(() => ({}))
    return { status: resposta.status, transacao: corpo?.detail?.provider_transaction_id || null }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token, intentId, fixture.gestora_id])
}

/** O bridge reportando um resultado, pela rota de callback dele. */
async function resultadoDoBridge(page, transacao, corpo) {
  return page.evaluate(async ([api, terminal, codigo, tenant, store, transacaoId, dados]) => {
    const resposta = await fetch(
      `${api}/api/v1/providers/bridge/terminals/${terminal}/transactions/${transacaoId}/result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pairing_code: codigo, tenant_id: tenant, store_id: store, ...dados,
        }),
      })
    return { status: resposta.status, corpo: (await resposta.text()).slice(0, 200) }
  }, [apiUrl, fixture.bridge_terminal.id, fixture.bridge_terminal.pairing_code,
      fixture.tenant_id, fixture.store_id, transacao, corpo])
}

async function abrirAConta(page) {
  await page.getByRole('button', { name: new RegExp(fixture.service_table.name) }).first().click()
  await esperaTexto(page, /Fechar conta completa|Conta viva da mesa/i, 25000)
  const fechar = page.getByRole('button', { name: /Fechar conta completa/ })
  if (await fechar.count()) {
    await fechar.first().click()
    await esperaTexto(page, /Conta viva da mesa/i, 25000)
  }
  await page.waitForTimeout(2000)
}

async function run() {
  const navegador = await chromium.launch()
  try {
    const contexto = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
    await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessaoDeGestao())])
    await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['dashem.terminal_token', fixture.terminal_token])
    const page = await contexto.newPage()
    page.setDefaultTimeout(30000)

    // ---------------------------------------- 1. o salão e a cobrança que sai
    await page.goto(`${appUrl}/tables`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3500)
    const pedePin = page.locator('input[name="operational-identity"]')
    if (await pedePin.count()) {
      await pedePin.fill(fixture.atendente.employee_code)
      await page.locator('input[name="operational-pin"]').fill(fixture.atendente.pin)
      await page.keyboard.press('Enter')
      await page.waitForTimeout(5000)
    }
    const abrirCaixa = page.getByRole('button', { name: /ABRIR CAIXA E INICIAR VENDAS/i })
    if (await abrirCaixa.count()) {
      const fundo = page.locator('input[inputmode="numeric"]').last()
      await fundo.click()
      await fundo.type('20000')
      await abrirCaixa.first().click()
      await page.waitForTimeout(4000)
    }
    const irParaMesas = page.getByRole('button', { name: /^Mesas$/ })
    if (await irParaMesas.count()) {
      await irParaMesas.first().click()
      await page.waitForTimeout(4000)
    }
    await esperaTexto(page, new RegExp(fixture.service_table.name), 30000)
    await abrirAConta(page)

    const negociacao = await contaDaSessao(page)
    relatorio.servidor.negotiation_id = negociacao
    if (!exigir(Boolean(negociacao), 'não achei a conta desta sessão')) {
      throw new Error('sem a conta, a travessia não tem o que acompanhar')
    }

    const opcaoTef = page.locator('option[value="TEF_CREDIT"]')
    const limite = Date.now() + 25000
    while (Date.now() < limite && await opcaoTef.count() === 0) await page.waitForTimeout(300)
    await page.getByLabel('Meio de pagamento').selectOption('TEF_CREDIT')
    await page.getByLabel('Valor da parcela').fill('18.00')
    await page.getByRole('button', { name: /Registrar parcela no meio selecionado/ }).click()
    await esperaTexto(page, /Aguardando conciliação/i, 30000)
    await shot(page, 'a-cobranca-em-voo')
    relatorio.etapas.push({ etapa: 'a cobrança de R$ 18,00 sai e fica sem resposta' })

    const antes = await contaNoServidor(page, negociacao)
    const parcela = antes.parcelas[antes.parcelas.length - 1]
    exigir(parcela && parcela.situacao === 'PROCESSING',
      `a parcela deveria estar em PROCESSING: ${JSON.stringify(antes)}`)

    // O id da transação vem da recusa de cancelamento — que é, ela própria, a
    // prova de que a parcela não se solta na mão.
    const recusa = await idDaTransacao(page, parcela.id)
    relatorio.servidor.recusa_de_cancelamento = recusa.status
    if (!exigir(recusa.status === 409 && recusa.transacao,
      `esperava 409 com o id da transação, e veio ${recusa.status}`)) {
      throw new Error('sem o id da transação, o bridge não tem o que responder')
    }
    const transacao = recusa.transacao

    // ---------------------------------------- 2. a resposta tardia
    const tardia = await resultadoDoBridge(page, transacao, {
      status: 'CONFIRMED', nsu: 'NSU-TARDIA', authorization_code: 'OK',
      acquirer: 'HOMOLOG', card_brand: 'SIMULADO',
    })
    relatorio.servidor.resposta_tardia = tardia
    exigir(tardia.status === 200,
      `o bridge deveria conseguir reportar o resultado, e veio ${tardia.status}: ${tardia.corpo}`)

    // **A tela aberta não sabe.** Ela não é avisada, e continua mostrando o que
    // leu. Isso não é defeito de segurança — é o que a retomada resolve.
    const aindaNaTela = await naTela(page)
    relatorio.etapas.push({
      etapa: 'a tela aberta não é avisada da resposta tardia',
      ainda_aguardando: /Aguardando conciliação/i.test(aindaNaTela),
    })

    // ---------------------------------------- 3. a retomada da tela
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(6000)
    await esperaTexto(page, new RegExp(fixture.service_table.name), 30000)
    await abrirAConta(page)
    const retomada = await esperaTexto(page, /Confirmado/i, 25000)
    await shot(page, 'retomada-mostra-a-confirmacao')
    // Três coisas ao mesmo tempo, e nenhuma sozinha bastaria: a parcela lida
    // como confirmada, a espera sumiu, e a métrica de processamento — que só
    // existe com cobrança em voo — não está mais lá.
    const parcelaConfirmada = /confirmado/i.test(retomada)
    const semEspera = !/Aguardando conciliação/i.test(retomada)
    const semProcessamento = !/Em processamento/i.test(retomada)
    relatorio.etapas.push({
      etapa: 'retomando a tela, a confirmação está lá',
      parcela_confirmada: parcelaConfirmada, sem_aguardando: semEspera,
      sem_metrica_de_processamento: semProcessamento,
    })
    exigir(parcelaConfirmada,
      `a tela retomada precisa ler a parcela como confirmada: "${retomada.slice(0, 300)}"`)
    exigir(semEspera,
      `a tela retomada não pode continuar dizendo que aguarda: "${retomada.slice(0, 300)}"`)
    exigir(semProcessamento,
      `sem cobrança em voo, a métrica "Em processamento" não deveria estar na tela: "${retomada.slice(0, 300)}"`)

    const depoisDaTardia = await contaNoServidor(page, negociacao)
    relatorio.servidor.depois_da_tardia = depoisDaTardia
    exigir(Number(depoisDaTardia.confirmado) === 18,
      `o confirmado deveria ser 18,00 e é ${depoisDaTardia.confirmado}`)
    exigir(Number(depoisDaTardia.em_processamento) === 0,
      `nada deveria continuar em processamento e há ${depoisDaTardia.em_processamento}`)
    exigir(Number(depoisDaTardia.falta) === 62,
      `deveriam faltar 62,00 e faltam ${depoisDaTardia.falta}`)

    // ---------------------------------------- 4. a resposta repetida
    const repetidas = []
    for (let i = 0; i < 2; i += 1) {
      repetidas.push(await resultadoDoBridge(page, transacao, {
        status: 'CONFIRMED', nsu: 'NSU-TARDIA', authorization_code: 'OK',
      }))
    }
    relatorio.servidor.repetidas = repetidas.map((item) => item.status)
    const depoisDeRepetir = await contaNoServidor(page, negociacao)
    relatorio.servidor.depois_de_repetir = depoisDeRepetir
    relatorio.etapas.push({
      etapa: 'o provider repete a mesma resposta duas vezes',
      confirmado: depoisDeRepetir.confirmado, parcelas: depoisDeRepetir.parcelas.length,
    })
    // **A pergunta que importa.** Repetir não pode virar dinheiro a mais.
    exigir(Number(depoisDeRepetir.confirmado) === 18,
      `repetir a resposta dobrou o confirmado: ${depoisDeRepetir.confirmado}`)
    exigir(depoisDeRepetir.parcelas.length === depoisDaTardia.parcelas.length,
      `repetir a resposta criou parcela: ${JSON.stringify(depoisDeRepetir.parcelas)}`)
    exigir(Number(depoisDeRepetir.falta) === 62,
      `repetir a resposta mexeu no que falta: ${depoisDeRepetir.falta}`)

    // ---------------------------------------- 5. a resposta que contradiz
    //
    // O adquirente muda de ideia depois de confirmar. Andar para trás aqui
    // reabriria uma cobrança fechada e, com ela, soltaria a linha da conta.
    const contradiz = await resultadoDoBridge(page, transacao, {
      status: 'FAILED', failure_code: 'TARDIO', failure_reason: 'Recusa chegou depois da confirmação',
    })
    relatorio.servidor.contradiz = contradiz
    const depoisDaContradicao = await contaNoServidor(page, negociacao)
    relatorio.servidor.depois_da_contradicao = depoisDaContradicao
    relatorio.etapas.push({
      etapa: 'uma recusa chega depois da confirmação',
      confirmado: depoisDaContradicao.confirmado,
      divergencias: depoisDaContradicao.divergencias,
    })
    exigir(Number(depoisDaContradicao.confirmado) === 18,
      `a recusa tardia soltou saldo confirmado: ${depoisDaContradicao.confirmado}`)
    exigir(Number(depoisDaContradicao.falta) === 62,
      `a recusa tardia mexeu no que falta: ${depoisDaContradicao.falta}`)
    exigir(depoisDaContradicao.divergencias.length > 0,
      'uma resposta que contradiz a anterior precisa ficar registrada como divergência')
    // A frase mais simples do que está em jogo: a parcela confirmada continua
    // confirmada. Duas defesas independentes garantem isto — a transação não
    // retrocede, e uma parcela já encerrada não é reaberta por resposta de
    // provider. Desligando a primeira, a segunda continua segurando o dinheiro;
    // o que muda é só como a divergência é classificada.
    const aindaConfirmada = depoisDaContradicao.parcelas
      .find((row) => row.id === parcela.id)
    exigir(aindaConfirmada && aindaConfirmada.situacao === 'CONFIRMED',
      `a parcela foi reaberta pela recusa tardia: ${JSON.stringify(aindaConfirmada)}`)

    // E a tela retomada mostra o registro, em vez de escondê-lo.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(6000)
    await esperaTexto(page, new RegExp(fixture.service_table.name), 30000)
    await abrirAConta(page)
    const comDivergencia = await esperaTexto(page, /Pendente de conciliação/i, 25000)
    await shot(page, 'a-contradicao-fica-registrada-na-tela')
    relatorio.etapas.push({
      etapa: 'a divergência aparece para quem opera, e nada foi liberado',
      mostra: /Pendente de conciliação/i.test(comDivergencia),
    })
    exigir(/Pendente de conciliação/i.test(comDivergencia),
      `a tela precisa mostrar a divergência: "${comDivergencia.slice(0, 300)}"`)
    exigir(/nada foi liberado nem cobrado/i.test(comDivergencia),
      'a tela precisa dizer que nada foi liberado por conta da divergência')
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom07-tardia.json'),
                   JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  console.log(`servidor: ${JSON.stringify(relatorio.servidor)}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exitCode = 1
}

run().catch((erro) => { console.error('FALHOU:', erro.message); process.exitCode = 1 })
