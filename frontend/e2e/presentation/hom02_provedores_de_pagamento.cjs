/**
 * Homologação — Provedores de pagamento, o segundo destino nunca percorrido.
 *
 * **A distinção que esta travessia existe para fazer.** Contratar `tef` no
 * acervo não comprova, sozinho, uma transação TEF. São três camadas
 * diferentes, e misturá-las é como um cadastro vira "integração pronta" num
 * relatório:
 *
 * 1. **configuração na tela** — cadastrar provedor e parear bridge. É o que
 *    esta travessia percorre de ponta a ponta. **Vincular maquininha não está
 *    aqui**: o vínculo de aparelho é pendência separada, e escrevê-lo nesta
 *    lista foi imprecisão minha — as etapas abaixo não o percorrem;
 * 2. **simulação** — o heartbeat do bridge é chamado por este roteiro, no
 *    papel do Dashem TEF Bridge. Prova que a tela reflete a conexão relatada;
 *    **não** prova que existe um bridge instalado nem que ele fala com alguém;
 * 3. **integração real** — comunicação com provedor e transação TEF de fato.
 *    **Não é percorrida aqui**, e nada nesta travessia deve ser lido como se
 *    fosse.
 *
 * A própria tela já diz a primeira parte disso, e a travessia confere que ela
 * continua dizendo: "Cadastro ativo não comprova conexão, homologação ou
 * aprovação de cobrança."
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5199'
const apiUrl = process.env.UX_API_URL || 'http://127.0.0.1:8004'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'hom-provedores')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const marca = Date.now().toString().slice(-4)
const PROVEDOR = { codigo: `HOMOLOG-${marca}`, credenciais: `cofre://homolog/${marca}`, limite: '45' }
const TERMINAL = { codigo: `BRIDGE-${marca}` }

const relatorio = {
  app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [],
  camadas: {
    configuracao_na_tela: 'percorrida',
    simulacao_de_bridge: 'percorrida — heartbeat enviado por este roteiro',
    integracao_real_com_provedor: 'NÃO percorrida',
  },
}
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'hom02',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Renata Nogueira' },
      created_at: new Date().toISOString(),
    },
  }
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
const noDialogo = (page) => page.evaluate(() => {
  const d = document.querySelector('[role="dialog"]')
  return d ? d.innerText : ''
})

async function main() {
  const navegador = await chromium.launch()
  let terminalId = null
  try {
    const contexto = await navegador.newContext({
      viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1, locale: 'pt-BR',
    })
    await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessao())])
    const page = await contexto.newPage()
    page.setDefaultTimeout(25000)
    const shot = async (nome) => {
      await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
      relatorio.telas.push(nome)
    }

    // ================== 1. o card existe em Financeiro
    await page.goto(appUrl + '/manage?area=FINANCEIRO', { waitUntil: 'domcontentloaded' })
    const noHub = await esperar(page, /Provedores de pagamento/i, 'o card de Provedores')
    await shot('1-card-em-financeiro')
    relatorio.etapas.push({ etapa: 'o card existe com tef habilitado por override de homologação' })
    exigir(/Configure como você recebe/i.test(noHub), 'o card deveria trazer a frase de tarefa do mapa')

    await page.getByRole('button', { name: /^Provedores de pagamento/ }).first().click()
    // Esta travessia **configura** provedor e bridge: rodar de novo sobre a
    // mesma semeadura encontra a tela já preenchida, e a falha sai parecendo
    // defeito do produto. Ela precisa de tenant novo.
    const naTelaInicial = await esperar(
      page, /Nenhum provedor configurado|Adapter/, 'a tela de provedores')
    if (!/Nenhum provedor configurado/.test(naTelaInicial)) {
      throw new Error(
        'Este tenant já tem provedor configurado, e a travessia precisa começar do zero. ' +
        'Semeie de novo com tests/support/seed_food_service_walkthrough.py.')
    }
    await shot('2-tela-sem-provedor')

    // A tela nasce dizendo o que ainda não existe, em vez de parecer pronta.
    relatorio.etapas.push({ etapa: 'a tela parte do nada configurado' })
    exigir(/A conexão TEF ainda não está disponível/.test(naTelaInicial),
      'sem bridge, a tela deveria dizer que a conexão TEF não está disponível')

    // ================== 2. camada 1 — configuração na tela
    await page.getByRole('button', { name: 'Configurar provedor' }).click()
    await page.waitForTimeout(700)
    await page.getByLabel('Código do provedor').fill(PROVEDOR.codigo)
    await page.getByLabel('Referência segura das credenciais').fill(PROVEDOR.credenciais)
    await page.getByLabel('Tempo limite em segundos').fill(PROVEDOR.limite)
    const noFormulario = await noDialogo(page)
    exigir(/Não cole senhas ou chaves de acesso/.test(noFormulario),
      'o formulário deveria avisar para não colar segredo no campo de referência')
    await page.getByRole('button', { name: 'Salvar' }).click()
    const comProvedor = await esperar(page, new RegExp(PROVEDOR.codigo), 'o provedor configurado')
    await shot('3-provedor-configurado')
    relatorio.etapas.push({ etapa: 'configurar provedor', apareceu: true })

    // **A frase que separa cadastro de integração.**
    exigir(/Cadastro ativo não comprova conexão, homologação ou aprovação de cobrança/.test(comProvedor),
      'a tela deveria dizer que cadastrar não é integrar')

    // ================== 3. parear o bridge — ainda configuração
    await page.getByRole('button', { name: 'Parear bridge' }).click()
    await page.waitForTimeout(700)
    const seletores = page.locator('[role="dialog"] select')
    await seletores.nth(0).selectOption({ index: 1 })
    await seletores.nth(1).selectOption({ index: 1 })
    await page.getByLabel('Código do terminal').fill(TERMINAL.codigo)
    await page.getByRole('button', { name: 'Gerar código de pareamento' }).click()
    await page.waitForTimeout(2600)
    const pareamento = await noDialogo(page)
    await shot('4-codigo-de-pareamento')
    relatorio.etapas.push({ etapa: 'parear bridge', gerouCodigo: /Código de pareamento/.test(pareamento) })
    exigir(/Código de pareamento/.test(pareamento),
      'o pareamento deveria devolver um código para configurar no bridge')
    exigir(/não será exibido na listagem/.test(pareamento),
      'a tela deveria avisar que o código não volta a aparecer')

    // O código só aparece **uma vez**. É com ele que o bridge se identifica, e
    // é por isso que a simulação precisa capturá-lo aqui.
    const codigoDePareamento = (pareamento.match(/Código de pareamento\s*\n?\s*(\S+)/) || [])[1]
    exigir(Boolean(codigoDePareamento), 'não consegui ler o código de pareamento da tela')

    await page.getByRole('button', { name: 'Concluir' }).click()
    const comTerminal = await esperar(page, new RegExp(TERMINAL.codigo), 'o terminal na listagem')
    await shot('5-bridge-pareado-sem-conexao')

    // Pareado **não** é conectado, e a tela precisa continuar dizendo isso.
    relatorio.etapas.push({ etapa: 'pareado não é conectado' })
    exigir(/Ainda não informada/.test(comTerminal),
      'sem heartbeat, a versão do bridge deveria aparecer como não informada')
    exigir(/A conexão é confirmada pelo heartbeat do bridge/.test(comTerminal),
      'a tela deveria dizer que quem confirma a conexão é o heartbeat')

    // ================== 4. camada 2 — SIMULAÇÃO do bridge
    // Daqui em diante quem fala é **este roteiro**, no papel do Dashem TEF
    // Bridge. Não há bridge instalado, e nada disto prova que exista.
    terminalId = await page.evaluate(async ([api, tenant, store, token, codigo]) => {
      const resposta = await fetch(`${api}/api/v1/providers/bridge/terminals`, {
        headers: {
          'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}`,
        },
      })
      if (!resposta.ok) return null
      const lista = await resposta.json()
      const alvo = (Array.isArray(lista) ? lista : []).find((t) => t.terminal_code === codigo)
      return alvo ? alvo.id : null
    }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token, TERMINAL.codigo])
    if (!exigir(Boolean(terminalId), 'não achei o terminal para simular o heartbeat')) {
      throw new Error('sem terminal, a camada de simulação não pode ser percorrida')
    }

    // O heartbeat sai de fora do navegador, como sairia de um bridge de
    // verdade: é uma máquina falando com a API, sem sessão de tela. Só que a
    // máquina, aqui, é este roteiro.
    const bater = (protocolo) => page.evaluate(
      async ([api, terminal, codigo, tenant, store, versaoDoProtocolo]) => {
        const resposta = await fetch(
          `${api}/api/v1/providers/bridge/terminals/${terminal}/heartbeat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              pairing_code: codigo, tenant_id: tenant, store_id: store,
              bridge_version: '0.0.0-simulado', protocol_version: versaoDoProtocolo,
            }),
          })
        return { status: resposta.status, corpo: (await resposta.text()).slice(0, 300) }
      },
      [apiUrl, terminalId, codigoDePareamento, fixture.tenant_id, fixture.store_id, protocolo])

    // ---- 4a. um bridge que fala **não** é um bridge que serve.
    // Protocolo errado de propósito: a chamada é aceita e o terminal é marcado
    // com falha. É a diferença entre "chegou mensagem" e "está funcionando" —
    // a confusão que faz cadastro virar "integração pronta" num relatório.
    const errado = await bater('0.9-incompativel')
    console.log(`  heartbeat com protocolo errado -> ${errado.status}`)
    exigir(errado.status === 200,
      `a chamada do bridge deveria ser aceita mesmo com protocolo errado, e voltou ${errado.status}`)

    await page.getByRole('button', { name: 'Atualizar' }).first().click()
    const comFalha = await esperar(page, /incompatível/, 'a falha de protocolo na tela')
    await shot('6-bridge-fala-e-nao-serve')
    relatorio.etapas.push({ etapa: 'protocolo incompatível é acusado na tela', acusou: true })
    exigir(/Com falha/.test(comFalha),
      'com protocolo incompatível o terminal deveria aparecer com falha, não conectado')
    exigir(/Último contato/.test(comFalha),
      'a tela deveria dizer quando foi o último contato, mesmo com falha')

    // ---- 4b. agora com o protocolo que o terminal espera
    const protocoloEsperado = (comFalha.match(/Protocolo\s+([\w.]+)/) || [])[1]
    exigir(Boolean(protocoloEsperado), 'não consegui ler o protocolo esperado na tela')
    const certo = await bater(protocoloEsperado)
    console.log(`  heartbeat com protocolo ${protocoloEsperado} -> ${certo.status}`)
    relatorio.etapas.push({
      etapa: 'simulação: heartbeat aceito com o protocolo certo',
      status: certo.status, protocolo: protocoloEsperado,
      observacao: 'não há bridge instalado; quem bateu foi este roteiro',
    })
    exigir(certo.status === 200,
      `o heartbeat com o protocolo certo deveria ser aceito, e voltou ${certo.status}`)

    // ================== 5. a tela reflete a conexão relatada
    await page.getByRole('button', { name: 'Atualizar' }).first().click()
    await page.waitForTimeout(2200)
    const comConexao = await naTela(page)
    await shot('7-conexao-relatada-pelo-bridge')
    relatorio.etapas.push({
      etapa: 'a tela mostra a conexão que o bridge relatou',
      versao: /0\.0\.0-simulado/.test(comConexao),
    })
    exigir(/0\.0\.0-simulado/.test(comConexao),
      'a tela deveria mostrar a versão que o bridge relatou')
    exigir(!/incompatível/.test(comConexao),
      'com o protocolo certo, a falha anterior deveria sair da tela')

    // ================== 6. o que continua sem prova
    // Nada aqui tocou um provedor. A tela não promete que tocou, e a travessia
    // confere que ela continua não prometendo.
    exigir(/Cadastro ativo não comprova conexão, homologação ou aprovação de cobrança/.test(comConexao),
      'mesmo com bridge conectado, a tela deveria manter a ressalva sobre cadastro')
    relatorio.etapas.push({
      etapa: 'integração real com provedor',
      percorrida: false,
      motivo: 'nenhuma transação TEF foi executada e nenhum provedor foi contatado',
    })
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom02-provedores.json'),
                   JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
