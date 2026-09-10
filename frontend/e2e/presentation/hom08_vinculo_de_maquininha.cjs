/**
 * Homologação — vincular a maquininha ao caixa, pela tela.
 *
 * A hom02 percorreu **configuração de provedor e pareamento de bridge**, e o
 * cabeçalho dela chegou a dizer que percorria o vínculo de maquininha também.
 * Não percorria: isso foi corrigido, e o vínculo ficou como pendência separada.
 * É esta travessia.
 *
 * O que se cobra aqui é a cadeia inteira, do jeito que a lojista a monta:
 *
 * 1. sem provedor ativo e POS livre, a tela **explica** o que falta em vez de
 *    oferecer um botão que não funciona;
 * 2. a gestora vincula o POS ao caixa, escolhendo provedor, modo e terminal;
 * 3. o vínculo aparece na listagem com o que ele é;
 * 4. **pausar** exige motivo, e o balcão perde o TEF na hora;
 * 5. **reativar** devolve o TEF ao balcão.
 *
 * O passo 4 é o que dá sentido aos outros: um vínculo é uma rota de execução, e
 * pausá-lo tem de tirar a maquininha do caixa de verdade — não só mudar um
 * rótulo na Gestão.
 *
 * **Alcance.** Nenhum provedor real é contatado e não existe maquininha física:
 * o terminal de bridge é declarado online pelo heartbeat que o roteiro de
 * cenário envia, no papel do Dashem TEF Bridge. Vincular é configuração; a
 * transação real com provedor continua pendência separada.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5199'
const apiUrl = process.env.WALK_API_URL || 'http://127.0.0.1:8004'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'hom-vinculo')
const VIEWPORT = { width: 1660, height: 940 }

if (!fixturePath) throw new Error('WALK_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
if (fixture.payment_device_binding_id) {
  throw new Error('a fixture já tem vínculo: semeie com --sem-vinculo, senão não há o que criar pela tela')
}
if (!fixture.bridge_terminal || !fixture.terminal_token || !fixture.atendente) {
  throw new Error('fixture incompleta: rode seed_tef_awaiting_bridge.py --sem-vinculo')
}
fs.mkdirSync(outDir, { recursive: true })

const relatorio = {
  app: appUrl, gerado_em: new Date().toISOString(),
  alcance: {
    configuracao_pela_tela: 'percorrida — o vínculo é criado clicando',
    bridge: 'simulado — heartbeat enviado pelo roteiro de cenário',
    maquininha_fisica: 'NÃO existe',
    transacao_real_com_provedor: 'NÃO percorrida',
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
    expires_at: agora + 28800, refresh_token: 'hom08',
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

/** Os vínculos, como o servidor os descreve. */
async function vinculosNoServidor(page) {
  return page.evaluate(async ([api, tenant, store, token]) => {
    const resposta = await fetch(`${api}/api/v1/providers/device-bindings`, {
      headers: { 'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}` },
    })
    if (!resposta.ok) return { status: resposta.status, linhas: null }
    const corpo = await resposta.json()
    return {
      status: resposta.status,
      linhas: corpo.map((row) => ({
        id: row.id, situacao: row.status, modo: row.execution_mode,
        motivo: row.paused_reason, terminal: row.tef_bridge_terminal_id,
      })),
    }
  }, [apiUrl, fixture.tenant_id, fixture.store_id, fixture.manager_token])
}

/** Abre o salão numa aba própria, com o turno da atendente. */
async function abrirSalao(navegador) {
  const contexto = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
  await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
    ['sb-127-auth-token', JSON.stringify(sessaoDeGestao())])
  await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
    ['dashem.terminal_token', fixture.terminal_token])
  const page = await contexto.newPage()
  page.setDefaultTimeout(30000)
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
  return page
}

/** O balcão tem TEF disponível para cobrar? A resposta é a opção no seletor. */
async function balcaoTemTef(page) {
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)
  await esperaTexto(page, new RegExp(fixture.service_table.name), 30000)
  await page.getByRole('button', { name: new RegExp(fixture.service_table.name) }).first().click()
  await esperaTexto(page, /Fechar conta completa|Conta viva da mesa/i, 25000)
  const fechar = page.getByRole('button', { name: /Fechar conta completa/ })
  if (await fechar.count()) {
    await fechar.first().click()
    await esperaTexto(page, /Conta viva da mesa/i, 25000)
  }
  // Portão de carga: o vínculo e o terminal chegam depois da conta abrir.
  const limite = Date.now() + 20000
  const opcao = page.locator('option[value="TEF_CREDIT"]')
  while (Date.now() < limite && await opcao.count() === 0) await page.waitForTimeout(400)
  return { temOpcao: await opcao.count() > 0, texto: await naTela(page) }
}

async function run() {
  const navegador = await chromium.launch()
  try {
    const contextoGestao = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
    await contextoGestao.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessaoDeGestao())])
    const gestao = await contextoGestao.newPage()
    gestao.setDefaultTimeout(30000)

    // ---------------------------------------- 1. a tela, antes do vínculo
    await gestao.goto(`${appUrl}/manage?module=payment_providers`, { waitUntil: 'domcontentloaded' })
    const semVinculo = await esperaTexto(gestao, /Vínculos de maquininhas/i, 30000)
    await shot(gestao, 'sem-vinculo-a-tela-diz-o-que-falta')
    relatorio.etapas.push({
      etapa: 'a unidade ainda não tem maquininha vinculada',
      diz: /Nenhuma maquininha vinculada nesta unidade/i.test(semVinculo),
    })
    exigir(/Nenhuma maquininha vinculada nesta unidade/i.test(semVinculo),
      `a tela deveria dizer que não há vínculo: "${semVinculo.slice(0, 300)}"`)

    // ---------------------------------------- 2. vincular, clicando
    await gestao.getByRole('button', { name: /^Vincular maquininha$/ }).click()
    await gestao.waitForTimeout(1500)

    const caixa = gestao.getByLabel('Caixa')
    const pos = gestao.getByLabel('POS')
    const provedor = gestao.getByLabel('Provedor')
    const modo = gestao.getByLabel('Modo de execução')
    // Os seletores nascem vazios de propósito: quem escolhe é a pessoa. Pegar a
    // segunda opção de cada um é pegar a primeira real, depois do placeholder.
    const primeiraReal = async (locator) => {
      const valores = await locator.locator('option').evaluateAll(
        (opcoes) => opcoes.map((o) => o.value).filter(Boolean))
      return valores[0]
    }
    await caixa.selectOption(await primeiraReal(caixa))
    await gestao.waitForTimeout(600)
    await pos.selectOption(await primeiraReal(pos))
    await provedor.selectOption(await primeiraReal(provedor))
    await gestao.waitForTimeout(600)
    await modo.selectOption('TEF_BRIDGE')
    await gestao.waitForTimeout(800)

    const terminal = gestao.getByLabel('Terminal de bridge')
    const opcoesDeTerminal = await terminal.locator('option').evaluateAll(
      (opcoes) => opcoes.map((o) => o.textContent.trim()).filter(Boolean))
    relatorio.etapas.push({
      etapa: 'o diálogo só oferece terminal pareado com este caixa e provedor',
      terminais: opcoesDeTerminal,
    })
    if (!exigir(opcoesDeTerminal.length > 0,
      'nenhum terminal de bridge foi oferecido para o vínculo TEF')) {
      throw new Error('sem terminal no seletor, não há vínculo TEF a criar')
    }
    await terminal.selectOption(await primeiraReal(terminal))
    await shot(gestao, 'dialogo-de-vinculo-preenchido')

    await gestao.getByRole('button', { name: /^(Vincular|Salvar|Confirmar)/ }).last().click()
    const comVinculo = await esperaTexto(gestao, /TEF Bridge/i, 25000)
    await shot(gestao, 'vinculo-criado-e-listado')
    relatorio.etapas.push({
      etapa: 'a maquininha aparece vinculada ao caixa',
      listaModo: /TEF Bridge/i.test(comVinculo),
    })
    exigir(/TEF Bridge/i.test(comVinculo),
      `o vínculo deveria aparecer como TEF Bridge: "${comVinculo.slice(0, 300)}"`)

    const criados = await vinculosNoServidor(gestao)
    relatorio.servidor.depois_de_criar = criados
    exigir(criados.linhas && criados.linhas.length === 1
      && criados.linhas[0].situacao === 'ACTIVE'
      && criados.linhas[0].modo === 'TEF_BRIDGE'
      && Boolean(criados.linhas[0].terminal),
      `o servidor deveria ter um vínculo TEF ativo com terminal: ${JSON.stringify(criados)}`)

    // ---------------------------------------- 3. o balcão ganha o TEF
    const salao = await abrirSalao(navegador)
    const comTef = await balcaoTemTef(salao)
    await shot(salao, 'balcao-com-tef-disponivel')
    relatorio.etapas.push({ etapa: 'com o vínculo ativo, o balcão pode cobrar por TEF', tem: comTef.temOpcao })
    exigir(comTef.temOpcao,
      `com vínculo ativo, o balcão deveria oferecer cobrança por TEF: "${comTef.texto.slice(0, 300)}"`)

    // ---------------------------------------- 4. pausar exige motivo
    await gestao.getByRole('button', { name: /^Pausar$/ }).first().click()
    await gestao.waitForTimeout(1200)
    const motivo = gestao.getByLabel('Motivo')
    await motivo.fill('ok')
    const confirmar = gestao.getByRole('button', { name: /^(Pausar|Salvar|Confirmar)/ }).last()
    await confirmar.click()
    await gestao.waitForTimeout(1500)
    // O que se cobra é o **efeito**, não a frase: com motivo de dois caracteres a
    // pausa não acontece, o diálogo continua aberto e o vínculo segue ativo. Quem
    // barra aqui é a validação do próprio campo (`minLength`), antes de o
    // aplicativo dizer qualquer coisa — e a asserção anterior, escrita sobre a
    // mensagem do aplicativo, media a implementação em vez do resultado.
    const dialogoAberto = await motivo.count() > 0
    const aindaAtivo = await vinculosNoServidor(gestao)
    relatorio.etapas.push({
      etapa: 'pausar com motivo de dois caracteres não passa',
      dialogo_continua_aberto: dialogoAberto,
      situacao_no_servidor: aindaAtivo.linhas && aindaAtivo.linhas[0].situacao,
    })
    exigir(dialogoAberto,
      'o diálogo fechou com um motivo de dois caracteres')
    exigir(aindaAtivo.linhas && aindaAtivo.linhas[0].situacao === 'ACTIVE',
      `o vínculo foi pausado com motivo insuficiente: ${JSON.stringify(aindaAtivo)}`)

    const RAZAO = 'Maquininha recolhida para manutenção pela adquirente'
    await motivo.fill(RAZAO)
    await gestao.getByRole('button', { name: /^(Pausar|Salvar|Confirmar)/ }).last().click()
    const pausado = await esperaTexto(gestao, new RegExp(RAZAO), 25000)
    await shot(gestao, 'vinculo-pausado-com-motivo')
    relatorio.etapas.push({
      etapa: 'o vínculo fica pausado, e o motivo fica à vista',
      mostraMotivo: new RegExp(RAZAO).test(pausado),
    })
    exigir(new RegExp(RAZAO).test(pausado),
      `o motivo da pausa deveria ficar na listagem: "${pausado.slice(0, 300)}"`)

    const pausados = await vinculosNoServidor(gestao)
    relatorio.servidor.depois_de_pausar = pausados
    exigir(pausados.linhas && pausados.linhas[0].situacao === 'PAUSED',
      `o servidor deveria ter o vínculo pausado: ${JSON.stringify(pausados)}`)

    // ---------------------------------------- 5. e o balcão perde o TEF
    //
    // Esta é a etapa que dá sentido às outras. Pausar um vínculo é tirar uma
    // rota de execução do caixa; se o balcão continuasse oferecendo TEF, o
    // rótulo na Gestão não significaria nada.
    const semTef = await balcaoTemTef(salao)
    await shot(salao, 'balcao-sem-tef-com-o-vinculo-pausado')
    relatorio.etapas.push({
      etapa: 'com o vínculo pausado, o balcão não oferece mais TEF',
      tem: semTef.temOpcao,
    })
    exigir(!semTef.temOpcao,
      'com o vínculo pausado, o balcão continuou oferecendo cobrança por TEF')
    exigir(/TEF não configurado ou offline|meios locais permanecem disponíveis/i.test(semTef.texto),
      `o balcão deveria dizer que o TEF não está disponível: "${semTef.texto.slice(0, 300)}"`)

    // ---------------------------------------- 6. reativar devolve a rota
    await gestao.getByRole('button', { name: /^Reativar$/ }).first().click()
    await gestao.waitForTimeout(1200)
    await gestao.getByLabel('Motivo').fill('Maquininha devolvida e testada no caixa')
    await gestao.getByRole('button', { name: /^(Reativar|Salvar|Confirmar)/ }).last().click()
    await gestao.waitForTimeout(2500)
    const reativados = await vinculosNoServidor(gestao)
    relatorio.servidor.depois_de_reativar = reativados
    exigir(reativados.linhas && reativados.linhas[0].situacao === 'ACTIVE',
      `o servidor deveria ter o vínculo ativo de novo: ${JSON.stringify(reativados)}`)

    const deVolta = await balcaoTemTef(salao)
    await shot(salao, 'balcao-recupera-o-tef')
    relatorio.etapas.push({ etapa: 'reativado o vínculo, o balcão volta a ter TEF', tem: deVolta.temOpcao })
    exigir(deVolta.temOpcao,
      `reativado o vínculo, o balcão deveria voltar a oferecer TEF: "${deVolta.texto.slice(0, 300)}"`)
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom08-vinculo.json'),
                   JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  console.log(`servidor: ${JSON.stringify(relatorio.servidor)}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exitCode = 1
}

run().catch((erro) => { console.error('FALHOU:', erro.message); process.exitCode = 1 })
