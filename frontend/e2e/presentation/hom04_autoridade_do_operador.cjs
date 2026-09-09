/**
 * Homologação — conceder e retirar autoridade, com a sessão do operador aberta.
 *
 * A UX-13 provou a direção que **tira** autoridade, com sujeito real, e deixou
 * registrado que conceder e ver o operador agir sozinho não fora percorrido.
 * Esta travessia percorre as duas direções — e faz a pergunta que interessa:
 *
 * > uma permissão retirada continua utilizável por dados antigos da sessão?
 *
 * O PDV lê `permissions` **uma vez**, ao abrir a sessão operacional. Uma
 * concessão feita depois não chega àquela tela; uma **retirada** feita depois
 * também não. As duas direções erram, e elas não erram igual:
 *
 * * concessão que não chegou deixa a tela **mais restritiva** que a realidade —
 *   ela pede autorização que já não seria necessária. Incomoda;
 * * retirada que não chegou deixa a tela **mais permissiva** que a realidade —
 *   ela deixa agir sozinho quem já não pode. Aí quem precisa recusar é o
 *   servidor, e é isso que esta travessia mede.
 *
 * A operadora é CAIXA: depois da migração 089 ela não cancela venda sozinha.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5199'
const apiUrl = process.env.WALK_API_URL || 'http://127.0.0.1:8004'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'hom-autoridade')
const VIEWPORT = { width: 1660, height: 860 }

if (!fixturePath) throw new Error('WALK_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [], servidor: {} }
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
    expires_at: agora + 28800, refresh_token: 'hom04',
    user: {
      id: JSON.parse(Buffer.from(token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: nome },
      created_at: new Date().toISOString(),
    },
  }
}

const naTela = async (page) => (await page.locator('body').innerText()).replace(/\s+/g, ' ')

async function esperaTexto(page, expressao, limiteMs = 12000) {
  const fim = Date.now() + limiteMs
  let ultimo = ''
  while (Date.now() < fim) {
    ultimo = await naTela(page)
    if (expressao.test(ultimo)) return ultimo
    await page.waitForTimeout(300)
  }
  return ultimo
}

async function estacao(navegador, pessoa, etiqueta) {
  const contexto = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
  await contexto.addInitScript(([chave, valor]) => window.localStorage.setItem(chave, valor), [
    'dashem.terminal_token', pessoa.terminal_token,
  ])
  const page = await contexto.newPage()
  page.setDefaultTimeout(25000)
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

async function montarVenda(page) {
  const busca = page.getByPlaceholder(/Buscar produto ou escanear/i).first()
  await busca.click()
  await busca.fill('Coca')
  await page.waitForTimeout(900)
  await page.keyboard.press('Enter')
  // "Cancelar venda" só fica clicável com venda montada. Sem conferir aqui, a
  // falha aparece três passos depois, num clique que expira — e parece defeito
  // do botão em vez de carrinho vazio.
  const comItem = await esperaTexto(page, /1 item/, 12000)
  if (!/1 item/.test(comItem)) {
    throw new Error(`a venda não foi montada: "${comItem.slice(0, 200)}"`)
  }
}

/** A gestora concede ou retira, pela mesma rota que a tela de acessos usa. */
async function autoridade(page, sozinho) {
  return page.evaluate(async ([api, tenant, store, token, membership, valor]) => {
    const resposta = await fetch(`${api}/api/v1/team/${membership}/autoridade`, {
      method: 'PUT',
      headers: {
        'X-Tenant-ID': tenant, 'X-Store-ID': store,
        Authorization: `Bearer ${token}`, 'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        chave: 'sale.cancel', sozinho: valor,
        motivo: valor ? 'Homologação: operadora passa a cancelar sozinha'
                      : 'Homologação: autoridade retirada com a sessão aberta',
      }),
    })
    return { status: resposta.status, corpo: (await resposta.text()).slice(0, 200) }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager.token,
      fixture.operator_membership_id, sozinho])
}

/**
 * O que o **servidor** diz, não o que a tela mostra.
 *
 * "1 item no carrinho" é a tela da operadora, e a tela é justamente a parte
 * cuja palavra está em dúvida nesta travessia. Quem responde se o cancelamento
 * passou é a situação da venda no servidor, lida pela gestão.
 */
async function vendasNoServidor(page, situacao) {
  return page.evaluate(async ([api, tenant, store, token, status]) => {
    const resposta = await fetch(`${api}/api/v1/sales?status=${status}`, {
      headers: { 'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}` },
    })
    if (!resposta.ok) return { status: resposta.status, quantas: null }
    return { status: resposta.status, quantas: (await resposta.json()).length }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager.token, situacao])
}

/**
 * Fecha o que ficou aberto: são **dois** modais empilhados.
 *
 * "Cancelar venda" abre a confirmação ("Cancelar Venda Atual"), e o "Sim,
 * Cancelar" dela abre o pedido de autorização do supervisor. Fechar só o de
 * cima devolve o de baixo — que continua na frente e engole o clique seguinte,
 * deixando o botão embaixo inerte. A falha aparecia três passos depois, como
 * se o botão estivesse quebrado.
 */
async function fecharAutorizacao(page) {
  for (const rotulo of [/^Voltar$/, /Voltar à Venda/i]) {
    const botao = page.getByRole('button', { name: rotulo })
    if (await botao.count()) {
      await botao.first().click()
      await page.waitForTimeout(900)
    }
  }
}

async function tentarCancelar(page) {
  await page.getByRole('button', { name: /Cancelar venda/i }).first().click()
  await page.waitForTimeout(900)
  const confirmar = page.getByRole('button', { name: /Sim, Cancelar/i })
  if (await confirmar.count()) {
    await confirmar.first().click()
    await page.waitForTimeout(2500)
  }
  return naTela(page)
}

async function run() {
  const navegador = await chromium.launch()
  try {
    // A gestão entra num contexto próprio, só para carregar a sessão dela.
    const contextoGestao = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
    await contextoGestao.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(
        sessaoDeGestao(fixture.manager.token, fixture.manager.email, fixture.manager.name))])
    const gestao = await contextoGestao.newPage()
    await gestao.goto(`${appUrl}/manage?area=PESSOAS`, { waitUntil: 'domcontentloaded' })
    await gestao.waitForTimeout(4000)
    await shot(gestao, 'gestao-aberta')

    const operadora = await estacao(navegador, fixture.operator, 'operadora')
    await abrirCaixa(operadora)

    // ---------------------------------------- 1. sem autoridade, pede segunda pessoa
    await montarVenda(operadora)
    const pedeAutorizacao = await tentarCancelar(operadora)
    await shot(operadora, 'sem-autoridade-pede-supervisor')
    relatorio.etapas.push({ etapa: 'sem autoridade, cancelar pede a segunda pessoa' })
    exigir(/Autorização do supervisor/i.test(pedeAutorizacao),
      'sem a autoridade, a operadora não deveria cancelar sozinha')
    await fecharAutorizacao(operadora)

    // ---------------------------------------- 2. a gestora concede
    const concessao = await autoridade(gestao, true)
    relatorio.etapas.push({ etapa: 'a gestora concede a autoridade', status: concessao.status })
    exigir(concessao.status === 200,
      `conceder deveria dar certo, e voltou ${concessao.status}: ${concessao.corpo}`)

    // A sessão da operadora **continua aberta**. Ela leu as permissões ao
    // entrar, e a concessão é depois disso: a tela ainda vai pedir supervisor.
    const aindaPede = await tentarCancelar(operadora)
    await shot(operadora, 'concessao-nao-chega-a-sessao-aberta')
    relatorio.etapas.push({
      etapa: 'concessão não alcança a sessão já aberta',
      telaAindaPede: /Autorização do supervisor/i.test(aindaPede),
      observacao: 'erra para o lado seguro: pede autorização que já não seria necessária',
    })
    await fecharAutorizacao(operadora)

    // Reabrindo, a tela lê de novo — e aí ela cancela sozinha.
    await operadora.reload({ waitUntil: 'domcontentloaded' })
    await operadora.waitForTimeout(6000)
    const sozinhaAgora = await tentarCancelar(operadora)
    await shot(operadora, 'com-autoridade-cancela-sozinha')
    relatorio.etapas.push({
      etapa: 'relida a sessão, a operadora cancela sozinha',
      semDialogo: !/Autorização do supervisor/i.test(sozinhaAgora),
    })
    exigir(!/Autorização do supervisor/i.test(sozinhaAgora),
      'com a autoridade concedida, cancelar não deveria mais pedir supervisor')

    // ---------------------------------------- 3. a retirada, com a sessão aberta
    await montarVenda(operadora)

    const retirada = await autoridade(gestao, false)
    relatorio.etapas.push({ etapa: 'a gestora retira a autoridade', status: retirada.status })
    exigir(retirada.status === 200,
      `retirar deveria dar certo, e voltou ${retirada.status}: ${retirada.corpo}`)

    // **A pergunta desta travessia.** A tela da operadora ainda acha que pode:
    // ela vai mandar o cancelamento sem cabeçalho de supervisor. Quem tem de
    // recusar é o servidor.
    const depoisDaRetirada = await tentarCancelar(operadora)
    await shot(operadora, 'retirada-com-sessao-aberta')
    const recusou = /não tem autorização|Autorização do supervisor/i.test(depoisDaRetirada)
    relatorio.etapas.push({
      etapa: 'a frase da recusa, como o balcão a lê',
      texto: (depoisDaRetirada.match(/Você não tem autorização[^.]*\./) || ['—'])[0],
    })
    // A recusa é lida por quem está no balcão. Chave de permissão em inglês
    // não é recusa: é enigma.
    exigir(!/Missing permission/i.test(depoisDaRetirada),
      'a recusa não deveria mostrar chave de permissão em inglês para o operador')
    relatorio.etapas.push({
      etapa: 'retirada com a sessão aberta: a tela tenta, o servidor decide',
      telaMostrouRecusa: recusou,
    })

    // O que decide não é a tela: é o estado no servidor. São duas leituras
    // diferentes, e a segunda é a que vale.
    const carrinhoIntacto = /1 item/.test(depoisDaRetirada)
    // A venda montada e não paga é DRAFT; a cancelada é CANCELED (um L só).
    // Nome errado aqui volta 422, e `quantas` viria nulo — por isso o status da
    // resposta entra na acusação: leitura que não aconteceu não é prova de nada.
    const abertas = await vendasNoServidor(gestao, 'DRAFT')
    const canceladas = await vendasNoServidor(gestao, 'CANCELED')
    relatorio.servidor.venda_apos_retirada = {
      carrinho_na_tela: carrinhoIntacto ? '1 item' : 'vazio',
      abertas_no_servidor: abertas.quantas,
      canceladas_no_servidor: canceladas.quantas,
      leitura_do_servidor: `HTTP ${abertas.status}/${canceladas.status}`,
      recusa: (depoisDaRetirada.match(/Você não tem autorização[^.]*\./) || ['—'])[0],
    }
    exigir(carrinhoIntacto,
      'a venda foi cancelada por quem já não tinha autoridade: o carrinho esvaziou')
    exigir(recusou,
      `com a autoridade retirada, a tela precisa mostrar a recusa: "${depoisDaRetirada.slice(0, 160)}"`)
    // A venda da retirada continua aberta no servidor, e a única cancelada é a
    // que a operadora cancelou **quando tinha** a autoridade. Se a retirada
    // tivesse passado, este número seria 2 — e a tela não contaria isso.
    exigir(abertas.quantas === 1,
      `o servidor deveria ter 1 venda em aberto depois da recusa, e tem ${abertas.quantas} (HTTP ${abertas.status})`)
    exigir(canceladas.quantas === 1,
      `o servidor deveria ter 1 venda cancelada — a do período com autoridade — e tem ${canceladas.quantas} (HTTP ${canceladas.status})`)
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom04-autoridade.json'),
                   JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  console.log(`servidor: ${JSON.stringify(relatorio.servidor)}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exitCode = 1
}

run().catch((erro) => { console.error('FALHOU:', erro.message); process.exitCode = 1 })
