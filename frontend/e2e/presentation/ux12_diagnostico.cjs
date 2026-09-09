/**
 * UX-12 — Diagnóstico do sistema e acesso assistido, pela tela do lojista.
 *
 * A metade que importa aqui é a segunda. Até esta sprint, o acesso do suporte
 * era pedido pela plataforma e aprovado pela plataforma: o dono dos dados não
 * via, não aprovava e não revogava. Esta travessia percorre o caminho novo —
 * ele vê o pedido com escopo e prazo, autoriza, e corta — e confere na tela que
 * cortar teve efeito.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux12')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux12-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

/**
 * Portão de carga.
 *
 * Os rótulos de seção são maiúsculos **por CSS**, e `innerText` devolve o que
 * está desenhado: "ESPERANDO A SUA DECISÃO". Procurar a forma escrita reprova o
 * produto por um erro que é da medida — e esta é a segunda vez que isso me
 * pega. Toda comparação de texto de seção aqui é insensível a caixa.
 */
const esperar = async (page, padrao, oQue, limite = 20000) => {
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

const shot = async (page, nome) => {
  await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
  relatorio.telas.push(nome)
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

    // ================== 1. o card existe em Administração
    await page.goto(appUrl + '/manage?area=ADMINISTRACAO', { waitUntil: 'domcontentloaded' })
    const noHub = await esperar(page, /Diagnóstico e suporte/i, 'o card de Diagnóstico e suporte')
    await shot(page, '1-card-em-administracao')
    relatorio.etapas.push({ etapa: 'o card existe em Administração' })
    exigir(/Veja se está tudo funcionando/i.test(noHub),
      'o card deveria trazer a frase de tarefa do mapa')

    await page.getByRole('button', { name: /^Diagnóstico e suporte/ }).first().click()
    const naVerificacao = await esperar(page, /O que foi verificado/, 'o diagnóstico')
    await shot(page, '2-diagnostico')

    // ================== 2. responde a pergunta dele, na língua dele
    relatorio.etapas.push({ etapa: 'o diagnóstico responde', dizQueEsta: /Está tudo funcionando/.test(naVerificacao) })
    exigir(/Está tudo funcionando|ponto de atenção|Alguma coisa parou|Não foi possível verificar/.test(naVerificacao),
      'o topo deveria dizer, em uma frase, como o sistema está')
    exigir(/Conexão com o sistema/.test(naVerificacao), 'faltou a verificação da conexão')
    exigir(/Conexão com o banco/.test(naVerificacao), 'faltou a verificação do banco')
    exigir(/Fila de envios do servidor/.test(naVerificacao), 'faltou a verificação da fila')

    // Cada frase afirma só o que a sua medição comprova. Um `SELECT 1` não
    // prova gravação, e a fila do servidor não alcança aparelho desconectado.
    exigir(!/Leitura e gravação respondendo/.test(naVerificacao),
      'a tela afirma que gravação responde, e a medição foi só um SELECT')
    exigir(!/Tudo o que você registrou já foi enviado/.test(naVerificacao),
      'a tela promete que tudo foi enviado, e a medição só olhou a fila do servidor')

    // E nada de jargão: as palavras são nossas, não dele.
    for (const palavra of ['outbox', 'backlog', 'AAL2', 'payload', 'latency']) {
      exigir(!new RegExp(palavra, 'i').test(naVerificacao),
        `a tela do lojista fala "${palavra}"`)
    }

    // ================== 3. quem entra nos meus dados
    exigir(/Quem tem acesso aos seus dados/.test(naVerificacao),
      'a tela deveria dizer quem tem acesso aos dados')
    // O pedido é criado pelo suporte, fora desta tela — pelo roteiro
    // `seed_support_request.py`, que faz o que o suporte faria. Ele chega aqui
    // sozinho, e é isto que a sprint entrega: até agora, não chegava.
    const pedido = JSON.parse(fs.readFileSync(process.env.UX_PEDIDO, 'utf8'))
    // A travessia **consome** o pedido: ela autoriza e depois corta. Rodar de
    // novo sobre a mesma semeadura encontra um pedido já decidido, e a falha
    // sai parecendo defeito do produto. Melhor dizer o que houve.
    if (pedido.situacao !== 'PENDING') {
      throw new Error(
        `O pedido semeado está como ${pedido.situacao}, e esta travessia precisa de um ` +
        'pendente. Semeie de novo com tests/support/seed_support_request.py.')
    }
    const comPedido = await esperar(page, /esperando a sua decisão/i, 'o pedido do suporte')
    await shot(page, '3-pedido-esperando-decisao')
    relatorio.etapas.push({
      etapa: 'o pedido chega ao lojista',
      escopo: /operations/.test(comPedido),
      nomeia: new RegExp(pedido.solicitante).test(comPedido),
    })
    exigir(/operations/.test(comPedido), 'o pedido deveria dizer o que o suporte quer ver')
    // A autorização é nominal, e a tela promete dizer quem tem acesso aos
    // dados. Um pedido anônimo não responde isso.
    exigir(new RegExp(pedido.solicitante).test(comPedido),
      `o pedido deveria nomear quem está pedindo: ${pedido.solicitante}`)
    exigir(new RegExp(pedido.solicitante_email).test(comPedido),
      'o pedido deveria trazer o contato de quem pede')
    exigir(/só esta pessoa/i.test(comPedido),
      'a tela deveria dizer que autorizar libera uma pessoa só')
    exigir(new RegExp(pedido.motivo.slice(0, 20)).test(comPedido),
      'o pedido deveria dizer por que o suporte quer entrar')
    exigir(/até \d{2}\/\d{2}/.test(comPedido), 'o pedido deveria dizer até quando vale')

    // ================== 4. autorizar
    page.once('dialog', (dialogo) => dialogo.accept('Falei com o suporte por telefone'))
    await page.getByRole('button', { name: 'Autorizar' }).first().click()
    const autorizado = await esperar(page, /valendo agora/i, 'o acesso autorizado')
    await shot(page, '4-acesso-autorizado')
    relatorio.etapas.push({ etapa: 'autorizar', valendo: /valendo agora/i.test(autorizado) })
    exigir(!/esperando a sua decisão/i.test(autorizado),
      'depois de autorizar, o pedido não deveria continuar esperando decisão')

    // ================== 5. cortar, e ver que cortou
    page.once('dialog', (dialogo) => dialogo.accept('O atendimento terminou'))
    await page.getByRole('button', { name: 'Cortar acesso' }).first().click()
    await page.waitForTimeout(2800)
    const cortado = await naTela(page)
    await shot(page, '5-acesso-cortado')
    relatorio.etapas.push({ etapa: 'cortar', saiuDoValendo: !/valendo agora/i.test(cortado) })
    exigir(!/valendo agora/i.test(cortado),
      'depois de cortar, o acesso não deveria continuar valendo')
    exigir(/encerrados/i.test(cortado),
      'o acesso cortado deveria aparecer entre os encerrados, não sumir')
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux12-diagnostico.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
