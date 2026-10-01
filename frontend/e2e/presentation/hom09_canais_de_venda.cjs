/**
 * Homologação — Canais de venda, o gate final do S10.1, com gente autenticada.
 *
 * A bancada `e2e/channel-inbox.spec.mjs` abre o componente com as permissões
 * interceptadas no navegador. Esta travessia é a outra coisa: a gestora entra
 * pela Gestão com sessão de verdade, contra a API com `AUTH_MODE=test`, e cada
 * permissão vem da concessão do vínculo dela — inclusive a que foi negada à
 * segunda pessoa.
 *
 * **Três camadas, ditas antes para ninguém misturar:**
 *
 * 1. **tela percorrida pela gestora** — abrir o card, ver os pedidos do canal,
 *    vincular o código que faltava, retomar a quarentena, retomar a revisão,
 *    reenviar o aviso não entregue, ver os prazos e o formulário de conexão;
 * 2. **simulação** — o canal é este roteiro: ele assina e envia os eventos pelo
 *    ingresso do conector de referência e pede os avisos pela rota que existe.
 *    A cozinha também é este roteiro, pelas rotas de produção do produto;
 * 3. **integração real com canal** — **não é percorrida**. Nenhum iFood, 99Food
 *    ou canal real foi contatado, e nada aqui deve ser lido como se fosse.
 *
 * Fora desta travessia, e por quê: registro com prazo **vencido** (exigiria
 * mexer no relógio pelo banco; a bancada e `test_channel_screen_facts.py` o
 * cobrem); o que fazer com cancelamento em preparo além de mandar para uma pessoa
 * (D2); quais transições geram aviso (D8); leitura de contato, hold, extensão e
 * limpeza (D7 sem concessão, e sem rota).
 */
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5199'
const apiUrl = process.env.UX_API_URL || 'http://127.0.0.1:8004'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'hom-canais')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
if (!fixture.channel) throw new Error('A fixture não tem canal. Semeie com tests/support/seed_channel_hub_walkthrough.py.')
fs.mkdirSync(outDir, { recursive: true })

const marca = Date.now().toString().slice(-5)
const PEDIDO = { chope: `pedido-chope-${marca}`, bolinho: `pedido-bolinho-${marca}`, cozinha: `pedido-cozinha-${marca}` }
const PESSOA = { name: 'Pessoa Marcadora Canal', phone: '5511988887777', address: { street: 'Rua Marcadora Canal 42' } }
const MARCADORES = [PESSOA.name, PESSOA.phone, PESSOA.address.street]
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

const relatorio = {
  app: appUrl, api: apiUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [],
  camadas: {
    tela_percorrida_pela_gestora: 'percorrida, com sessão autenticada (JWT de teste em banco isolado) e permissões da concessão',
    canal: 'SIMULADO — eventos assinados e pedidos de aviso enviados por este roteiro',
    cozinha: 'SIMULADA — despacho e aceite pelas rotas de produção, por este roteiro',
    integracao_real_com_canal: 'NÃO percorrida',
    d1_r11_valores_externos: 'DELIMITADA — o roteiro envia valores externos (preço 18,50, entrega 7,00, total 44,00) e a API verifica preço unitário e quantidade no pedido; as garantias contratuais de catálogo, snapshots, total e origem financeira são demonstradas pelos testes backend de R11',
  },
  limites_declarados: {
    autenticacao: 'JWT assinado localmente com AUTH_TEST_SECRET contra API em AUTH_MODE=test e concessões no PostgreSQL isolado; não comprova login interativo nem disponibilidade do Supabase Auth de produção',
    responsividade_e_layout: 'as 4 larguras (1366, 1024, 768, 390 px) aferem ausência de quebras de palavras ao meio (palavrasPartidas); não atestam ausência universal de defeitos de layout sem outras verificações',
    navegador: 'o navegador percorre a interface gerencial de visualização, vínculo, retomada, reenvio e diagnóstico; não percorre diretamente cobrança no PDV nem mutações financeiras',
  },
  fora_desta_travessia: [
    'prazo vencido aguardando limpeza (coberto na bancada e em test_channel_screen_facts.py)',
    'regra de cancelamento em preparo além da revisão por pessoa (D2)',
    'quais transições geram aviso (D8)', 'contato, hold, extensão e limpeza (D7, sem rota)',
  ],
}
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao(token, email, nome) {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: token, token_type: 'bearer', expires_in: 28800, expires_at: agora + 28800,
    refresh_token: 'hom09',
    user: {
      id: JSON.parse(Buffer.from(token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: nome },
      created_at: new Date().toISOString(),
    },
  }
}

const cabecalhos = (token) => ({
  Authorization: `Bearer ${token}`, 'X-Tenant-ID': fixture.tenant_id, 'X-Store-ID': fixture.store_id,
})

async function api(token, metodo, caminho, corpo, { chave = false } = {}) {
  const headers = { ...cabecalhos(token), 'Content-Type': 'application/json' }
  if (chave) headers['Idempotency-Key'] = `hom09-${crypto.randomUUID()}`
  const resposta = await fetch(apiUrl + caminho, { method: metodo, headers, body: corpo === undefined ? undefined : JSON.stringify(corpo) })
  const texto = await resposta.text()
  let json = null
  try { json = JSON.parse(texto) } catch { /* corpo não JSON */ }
  return { status: resposta.status, json, texto }
}

/** O canal: corpo assinado sobre os bytes enviados, como o conector de referência exige. */
async function canalEnvia(...eventos) {
  const corpo = Buffer.from(JSON.stringify({ events: eventos }), 'utf8')
  const assinatura = 'sha256=' + crypto.createHmac('sha256', Buffer.from(fixture.channel.ingress_key_hex, 'hex')).update(corpo).digest('hex')
  const resposta = await fetch(apiUrl + '/api/v1/channels/ingress/CONTRACT_TEST', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dashem-Reference-Signature': assinatura }, body: corpo,
  })
  const json = await resposta.json()
  if (resposta.status !== 200) throw new Error(`ingresso respondeu ${resposta.status}: ${JSON.stringify(json).slice(0, 200)}`)
  return json.events.map((item) => item.outcome)
}

const evento = (tipo, pedido, sequencia, codigo, unitPrice = '18.50') => {
  const e = { id: `hom09-${crypto.randomUUID()}`, merchant_id: fixture.channel.merchant_external_id, type: tipo, order_id: pedido, sequence: sequencia, customer: PESSOA }
  if (codigo) {
    const qty = 2
    const linesTotal = (Number(unitPrice) * qty).toFixed(2)
    const delivery = '7.00'
    const total = (Number(linesTotal) + Number(delivery)).toFixed(2)
    e.order = {
      fulfillment: 'DELIVERY',
      payment: { status: 'PAID_ONLINE' },
      delivery_fee: delivery,
      discount: '0.00',
      subsidy: '0.00',
      total: total,
      lines: [{ id: 'l1', item_code: codigo, quantity: String(qty), unit_price: unitPrice }],
    }
  }
  return e
}

async function assentado(eventoId, limite = 30000) {
  const inicio = Date.now()
  while (Date.now() - inicio < limite) {
    const caixa = await api(fixture.manager_token, 'GET', '/api/v1/channels/inbox')
    const linha = (caixa.json || []).find((item) => item.provider_event_id === eventoId)
    if (linha && !['RECEIVED', 'PROCESSING'].includes(linha.status)) return linha
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`o evento ${eventoId} não saiu da fila em ${limite}ms`)
}

async function avisoAssentado(tipo, limite = 30000) {
  const inicio = Date.now()
  while (Date.now() - inicio < limite) {
    const avisos = await api(fixture.manager_token, 'GET', '/api/v1/channels/outbound')
    const aviso = (avisos.json || []).find((item) => item.message_type === tipo)
    if (aviso && !['PENDING', 'SENDING'].includes(aviso.status)) return aviso
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`o aviso ${tipo} não saiu da fila em ${limite}ms`)
}

const esperar = async (page, padrao, oQue, limite = 25000) => {
  const inicio = Date.now()
  let visto = ''
  while (Date.now() - inicio < limite) {
    visto = await page.evaluate(() => (document.querySelector('main')?.innerText || ''))
    if (padrao.test(visto)) return visto
    await page.waitForTimeout(400)
  }
  throw new Error(`${oQue} não apareceu em ${limite}ms. Na tela: ${visto.slice(0, 300)}`)
}
const naTela = (page) => page.evaluate(() => (document.querySelector('main')?.innerText || ''))

/** Palavra partida no meio: folha de texto com mais linhas do que palavras longas. */
const palavrasPartidas = (page) => page.evaluate(() => {
  const achadas = []
  for (const el of document.querySelectorAll('main span, main p, main td, main button, main li, main h2')) {
    if (el.children.length || !el.getClientRects().length) continue
    const palavras = (el.textContent || '').trim().split(/\s+/).filter((w) => w.length > 3)
    if (!palavras.length) continue
    const range = document.createRange()
    range.selectNodeContents(el)
    const linhas = new Set([...range.getClientRects()].map((r) => Math.round(r.top)))
    if (linhas.size > palavras.length) achadas.push((el.textContent || '').trim().slice(0, 40))
  }
  return achadas
})

async function abrirCanais(page) {
  await page.goto(appUrl + '/manage?area=OPERACAO', { waitUntil: 'domcontentloaded' })
  await esperar(page, /Canais de venda/, 'o card de Canais de venda')
  await page.getByRole('button', { name: /^Canais de venda/ }).first().click()
  return esperar(page, /Pedidos recebidos dos canais[\s\S]*Aguardando|Pedidos recebidos dos canais[\s\S]*Aplicado ao pedido/, 'a caixa de entrada com eventos')
}

async function main() {
  // ================== 0. o canal e a cozinha, simulados por este roteiro
  const chope = evento('ORDER_PLACED', PEDIDO.chope, 1, fixture.channel.mapped_code, '18.50')
  const bolinho = evento('ORDER_PLACED', PEDIDO.bolinho, 1, fixture.channel.unmapped_code, '65.00')
  const cozinha = evento('ORDER_PLACED', PEDIDO.cozinha, 1, fixture.channel.mapped_code, '18.50')
  const recebidos = await canalEnvia(chope, bolinho, cozinha)
  exigir(recebidos.every((r) => r === 'RECEIVED'), `o ingresso deveria receber os três: ${recebidos.join(', ')}`)
  const linhaChope = await assentado(chope.id)
  const linhaBolinho = await assentado(bolinho.id)
  const linhaCozinha = await assentado(cozinha.id)
  relatorio.etapas.push({ etapa: 'simulação: o canal enviou três pedidos', estados: [linhaChope.status, linhaBolinho.status, linhaCozinha.status] })
  exigir(linhaChope.status === 'APPLIED', `pedido com código vinculado deveria aplicar, ficou ${linhaChope.status}`)
  exigir(linhaBolinho.status === 'QUARANTINED' && linhaBolinho.quarantine_code === 'ITEM_NOT_MAPPED',
    `pedido sem código deveria ir para quarentena por item não vinculado, ficou ${linhaBolinho.status} ${linhaBolinho.quarantine_code}`)

  // D1/R11: verificação delimitada pela API
  const pedidoChopeApi = await api(fixture.manager_token, 'GET', `/api/v1/orders/${linhaChope.order_id}`)
  exigir(pedidoChopeApi.status === 200, `o pedido criado deveria ser consultável: ${pedidoChopeApi.status}`)
  const itemChope = pedidoChopeApi.json?.items?.[0]
  exigir(itemChope && Number(itemChope.unit_price) === 18.5,
    `D1/R11: o item do pedido deveria guardar o preço declarado pelo canal (18.50), guardou ${itemChope?.unit_price}`)
  exigir(itemChope && Number(itemChope.quantity) === 2,
    `D1/R11: o item do pedido deveria ter quantidade 2, guardou ${itemChope?.quantity}`)
  relatorio.etapas.push({
    etapa: 'D1/R11: verificação do pedido na API (valores enviados vs verificados vs testes backend)',
    valores_enviados_pelo_roteiro: {
      item_code: fixture.channel.mapped_code,
      unit_price: '18.50',
      quantity: 2,
      delivery_fee: '7.00',
      declared_total: '44.00',
      payment_status: 'PAID_ONLINE',
    },
    valores_verificados_pela_api: {
      order_id: linhaChope.order_id,
      item_unit_price: itemChope?.unit_price,
      item_quantity: itemChope?.quantity,
    },
    garantias_demonstradas_pelos_testes_backend_r11: {
      catalogo_preservado: 'test_channel_inbox.py:533 (ProductPrice inalterado)',
      diferencas_registradas: 'test_channel_inbox.py:533 (difference_amount em ExternalOrderMapping e linhas)',
      total_com_entrega_e_subsidio: 'test_channel_inbox.py:767 e :1163 (_order_amount com delivery_fee e sem duplicar subsídio)',
      bloqueio_cobranca_local: 'test_channel_inbox.py:767 (409 ORDER_PAID_IN_MARKETPLACE e ORDER_PAYMENT_ORIGIN_UNKNOWN)',
      concorrencia_sem_deadlocks: 'test_r11_concurrency_matrix.py (7 testes com ordem canônica de locks)',
    },
  })

  const despacho = await api(fixture.manager_token, 'POST', `/api/v1/production/orders/${linhaCozinha.order_id}/dispatch`, {}, { chave: true })
  exigir(despacho.status === 200 && despacho.json.length > 0, `a cozinha deveria receber o pedido, e o despacho voltou ${despacho.status}`)
  const ticket = despacho.json?.[0]?.ticket
  const aceite = ticket && await api(fixture.manager_token, 'POST', `/api/v1/production/tickets/${ticket.id}/transition`,
    { target: 'ACCEPTED', expected_version: ticket.version, device_id: 'hom09-cozinha' }, { chave: true })
  exigir(aceite && aceite.status === 200, `a cozinha deveria aceitar o ticket, e voltou ${aceite && aceite.status}`)
  const cancelamento = evento('ORDER_CANCELLED', PEDIDO.cozinha, 2)
  await canalEnvia(cancelamento)
  const linhaCancelamento = await assentado(cancelamento.id)
  relatorio.etapas.push({ etapa: 'simulação: a cozinha aceitou e o canal cancelou', estado: linhaCancelamento.status, codigo: linhaCancelamento.quarantine_code })
  exigir(linhaCancelamento.status === 'NEEDS_REVIEW', `cancelamento com item em preparo deveria ir para uma pessoa, ficou ${linhaCancelamento.status}`)

  const aceito = await api(fixture.manager_token, 'POST', `/api/v1/channels/orders/${linhaChope.order_id}/outbound`,
    { message_type: 'ORDER_ACCEPTED', payload: { status: 'ACCEPTED' } }, { chave: true })
  const inexistente = await api(fixture.manager_token, 'POST', `/api/v1/channels/orders/${linhaChope.order_id}/outbound`,
    { message_type: 'ORDER_TELEPORTED', payload: { status: 'TELEPORTED' } }, { chave: true })
  exigir(aceito.status === 200 && inexistente.status === 200, `os avisos deveriam entrar na fila: ${aceito.status} ${inexistente.status}`)
  const avisoEntregue = await avisoAssentado('ORDER_ACCEPTED')
  const avisoMorto = await avisoAssentado('ORDER_TELEPORTED')
  relatorio.etapas.push({ etapa: 'simulação: dois avisos pedidos pela rota explícita', estados: [avisoEntregue.status, avisoMorto.status] })
  exigir(avisoEntregue.status === 'DELIVERED', `aviso aceito pelo canal deveria ser entregue, ficou ${avisoEntregue.status}`)
  exigir(avisoMorto.status === 'DEAD_LETTER', `aviso que o canal não conhece deveria ficar não entregue, ficou ${avisoMorto.status}`)

  const navegador = await chromium.launch()
  try {
    // ================== 1. a gestora, autenticada
    const gestora = await navegador.newContext({ viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1, locale: 'pt-BR' })
    await gestora.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessao(fixture.manager_token, fixture.manager_email, 'Renata Nogueira'))])
    const page = await gestora.newPage()
    page.setDefaultTimeout(25000)
    const erros = []
    page.on('pageerror', (e) => erros.push(String(e)))
    const shot = async (nome, fullPage = false) => {
      await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage })
      relatorio.telas.push(nome)
    }

    let tela = await abrirCanais(page)
    await esperar(page, /Precisa de uma pessoa/, 'o evento em revisão')
    tela = await naTela(page)
    await shot('1-canais-de-venda', true)
    for (const rotulo of ['Aplicado ao pedido', 'Em quarentena', 'Precisa de uma pessoa', 'Aberto no PDV', 'Nenhum pedido criado',
      'Canal de teste', 'Receber pedidos', 'Avisar o canal', 'Entregue ao canal', 'Não entregue', 'Prazos dos dados dos canais']) {
      exigir(tela.includes(rotulo), `a tela deveria mostrar "${rotulo}"`)
    }
    exigir(!UUID.test(tela), `nenhum UUID deveria aparecer na tela: ${(tela.match(UUID) || [])[0]}`)
    for (const marcador of MARCADORES) exigir(!tela.includes(marcador), `dado pessoal na tela: ${marcador}`)
    exigir(!/\b(RECEIVED|QUARANTINED|NEEDS_REVIEW|APPLIED|DEAD_LETTER|DELIVERED)\b/.test(tela), 'código cru de estado na tela')
    relatorio.etapas.push({ etapa: 'a gestora vê os pedidos do canal, as conexões, os avisos e os prazos' })

    // ================== 2. vincular o código que faltava, na tela
    await page.getByRole('button', { name: 'Vincular código' }).click()
    const dialogo = page.locator('[role="dialog"]')
    await dialogo.getByPlaceholder('Buscar nome ou SKU (2 caracteres)').fill('Bolinho')
    await dialogo.getByRole('button', { name: new RegExp(fixture.channel.unmapped_product_name) }).click()
    await dialogo.getByPlaceholder('Ex.: 8842-XYZ').fill(fixture.channel.unmapped_code)
    await shot('2-vincular-codigo')
    await dialogo.getByRole('button', { name: 'Vincular' }).click()
    await page.getByText('Código do canal vinculado ao produto.').waitFor()
    relatorio.etapas.push({ etapa: 'a gestora vinculou o código do bolinho na tela' })

    // ================== 3. retomar a quarentena
    const linhaDaQuarentena = page.locator('tr', { hasText: PEDIDO.bolinho })
    await linhaDaQuarentena.getByRole('button', { name: 'Retomar' }).click()
    await page.getByText('Evento aplicado ao pedido.').waitFor()
    await page.locator('tr', { hasText: PEDIDO.bolinho }).filter({ hasText: 'Aplicado ao pedido' }).waitFor()
    await shot('3-quarentena-retomada')
    const retomado = await api(fixture.manager_token, 'GET', '/api/v1/channels/inbox')
    const bolinhoDepois = retomado.json.find((item) => item.provider_event_id === bolinho.id)
    relatorio.etapas.push({ etapa: 'a gestora retomou a quarentena e o pedido nasceu', estado: bolinhoDepois.status, pedido: bolinhoDepois.order_status })
    exigir(bolinhoDepois.status === 'APPLIED' && bolinhoDepois.order_status === 'OPEN', `retomar deveria aplicar e abrir o pedido: ${bolinhoDepois.status} ${bolinhoDepois.order_status}`)
    exigir(bolinhoDepois.retention_until === linhaBolinho.retention_until, 'retomar não pode mudar o prazo do evento que passou por quarentena')

    // ================== 4. retomar a revisão: continua com uma pessoa (D2 sem decisão)
    const linhaDaRevisao = page.locator('tr', { hasText: PEDIDO.cozinha }).filter({ hasText: 'Precisa de uma pessoa' })
    await linhaDaRevisao.getByRole('button', { name: 'Retomar' }).click()
    await page.getByText('O evento continua: Precisa de uma pessoa.').waitFor()
    await shot('4-revisao-continua-com-uma-pessoa')
    const pedidoDaCozinha = (await api(fixture.manager_token, 'GET', '/api/v1/channels/inbox')).json.find((item) => item.provider_event_id === cozinha.id)
    relatorio.etapas.push({ etapa: 'retomar a revisão não cancela a produção sozinho', pedido: pedidoDaCozinha.order_status })
    exigir(pedidoDaCozinha.order_status === 'OPEN', `o pedido com item em preparo não pode ser cancelado sozinho: ${pedidoDaCozinha.order_status}`)

    // ================== 5. reenviar o aviso não entregue
    const avisos = page.locator('section', { has: page.getByRole('heading', { name: 'Avisos ao canal' }) }).last()
    exigir(await avisos.getByRole('button', { name: 'Reenviar' }).count() === 1, 'Reenviar deveria existir só no aviso não entregue')
    await avisos.getByRole('button', { name: 'Reenviar' }).click()
    await page.getByText('O aviso segue: Não entregue.').waitFor()
    await avisos.screenshot({ path: path.join(outDir, '5-aviso-reenviado.png') })
    relatorio.telas.push('5-aviso-reenviado')
    const depoisDoReenvio = (await api(fixture.manager_token, 'GET', '/api/v1/channels/outbound')).json.find((item) => item.message_type === 'ORDER_TELEPORTED')
    relatorio.etapas.push({ etapa: 'a gestora reenviou o aviso; o canal recusou de novo, e a tela diz', estado: depoisDoReenvio.status, codigo: depoisDoReenvio.last_error_code })
    exigir(depoisDoReenvio.status === 'DEAD_LETTER' && depoisDoReenvio.last_error_code === 'NOTICE_TYPE_NOT_SUPPORTED',
      `o reenvio de um aviso que o canal não conhece continua não entregue: ${depoisDoReenvio.status} ${depoisDoReenvio.last_error_code}`)

    // ================== 6. prazos: contagem, e a limpeza que não existe
    await page.getByRole('button', { name: 'Atualizar' }).first().click()
    await page.reload({ waitUntil: 'domcontentloaded' })
    tela = await abrirCanais(page)
    const prazos = page.locator('section', { has: page.getByRole('heading', { name: 'Prazos dos dados dos canais' }) }).last()
    await prazos.getByText('Nenhuma limpeza foi executada').waitFor()
    const textoDosPrazos = await prazos.innerText()
    await prazos.screenshot({ path: path.join(outDir, '6-prazos.png') })
    relatorio.telas.push('6-prazos')
    relatorio.etapas.push({ etapa: 'os prazos aparecem como contagem', texto: textoDosPrazos.replace(/\s+/g, ' ').slice(0, 400) })
    exigir(/Pedidos aguardando o fim\s+3\b/i.test(textoDosPrazos), 'três pedidos abertos deveriam aguardar o fim')
    exigir(/Nenhum registro com prazo vencido/.test(textoDosPrazos), 'sem vencidos, a tela deveria dizer isso')
    exigir(/a limpeza ainda não existe/.test(textoDosPrazos), 'a tela deveria dizer que a limpeza ainda não existe')
    exigir(!/eliminad|foram removidos|foi removido|apagad/i.test(await naTela(page)), 'a tela não pode afirmar remoção')

    // ================== 7. o formulário de conexão não pede credencial
    await page.getByRole('button', { name: 'Nova conexão' }).click()
    const formulario = page.locator('form', { has: page.getByRole('heading', { name: 'Nova conexão' }) })
    await formulario.waitFor()
    const campos = await formulario.locator('input').count()
    const textoDoFormulario = await formulario.innerText()
    await formulario.screenshot({ path: path.join(outDir, '7-nova-conexao.png') })
    relatorio.telas.push('7-nova-conexao')
    relatorio.etapas.push({ etapa: 'o formulário pede só a loja no canal e o nome', campos })
    exigir(campos === 2, `o formulário deveria ter dois campos de texto, tem ${campos}`)
    exigir(!/secret:\/\/|Referência segura/.test(textoDoFormulario), 'o formulário não pode pedir credencial')
    await formulario.getByRole('button', { name: '×' }).click()

    // ================== 8. palavra partida em quatro larguras
    for (const largura of [1366, 1024, 768, 390]) {
      await page.setViewportSize({ width: largura, height: 900 })
      await page.waitForTimeout(600)
      const partidas = await palavrasPartidas(page)
      relatorio.etapas.push({ etapa: `palavra partida em ${largura}px`, partidas })
      exigir(partidas.length === 0, `palavra partida em ${largura}px: ${partidas.join(' | ')}`)
    }
    await shot('8-canais-390', true)
    await page.setViewportSize({ width: 1366, height: 900 })

    // ================== 9. o diagnóstico também diz
    await page.goto(appUrl + '/manage?area=ADMINISTRACAO', { waitUntil: 'domcontentloaded' })
    await esperar(page, /Diagnóstico e suporte/, 'o card de Diagnóstico e suporte')
    await page.getByRole('button', { name: /^Diagnóstico e suporte/ }).first().click()
    const diagnostico = await esperar(page, /Prazos dos dados dos canais/, 'a verificação de prazos no diagnóstico')
    await shot('9-diagnostico')
    relatorio.etapas.push({ etapa: 'o diagnóstico mostra os prazos dos canais' })
    exigir(/Nenhum registro de canal com prazo vencido/.test(diagnostico), 'o diagnóstico deveria dizer que não há vencidos')
    exigir(/ainda não existe/.test(diagnostico), 'o diagnóstico deveria dizer que a limpeza ainda não existe')
    exigir(erros.length === 0, `erro de página: ${erros.join(' | ')}`)

    // ================== 10. a leitora vê e não mexe — pela concessão, não pela tela
    const leitora = await navegador.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, locale: 'pt-BR' })
    await leitora.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessao(fixture.limited_token, fixture.limited_email, 'Tiago Prado'))])
    const outra = await leitora.newPage()
    outra.setDefaultTimeout(25000)
    const telaDaLeitora = await abrirCanais(outra)
    await outra.screenshot({ path: path.join(outDir, '10-leitora-390.png'), fullPage: true })
    relatorio.telas.push('10-leitora-390')
    const botoes = {}
    for (const nome of ['Retomar', 'Reenviar', 'Nova conexão', 'Vincular código', 'Validar com o canal']) {
      botoes[nome] = await outra.getByRole('button', { name: nome }).count()
      exigir(botoes[nome] === 0, `a leitora não deveria ver "${nome}"`)
    }
    exigir(!UUID.test(telaDaLeitora), 'nenhum UUID na tela da leitora')
    const revisao = (await api(fixture.limited_token, 'GET', '/api/v1/channels/inbox')).json.find((item) => item.provider_event_id === cancelamento.id)
    const tentativas = {
      retomar: (await api(fixture.limited_token, 'POST', `/api/v1/channels/inbox/${revisao.id}/resume`, {})).status,
      reenviar: (await api(fixture.limited_token, 'POST', `/api/v1/channels/outbound/${depoisDoReenvio.id}/resend`, {})).status,
      conectar: (await api(fixture.limited_token, 'POST', '/api/v1/channels/connections', {
        store_id: fixture.store_id, provider_code: 'IFOOD', merchant_external_id: `leitora-${marca}`, channel_name: 'Tentativa',
      }, { chave: true })).status,
    }
    relatorio.etapas.push({ etapa: 'a leitora não vê as ações e a API recusa a ela as mesmas ações', botoes, tentativas })
    for (const [acao, status] of Object.entries(tentativas)) exigir(status === 403, `a API deveria recusar "${acao}" à leitora, e respondeu ${status}`)
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom09-canais.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
