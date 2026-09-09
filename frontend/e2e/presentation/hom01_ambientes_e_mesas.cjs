/**
 * Homologação — Ambientes e Mesas, o destino que nunca tinha sido percorrido.
 *
 * A UX-05 registrou este card como não auditado, e a razão registrada era "o
 * acervo não contrata FOOD_SERVICE". Verificando de perto, a razão é outra e
 * mais precisa: `table_service` **estava** semeado como entitlement e mesmo
 * assim não chegava ao acesso efetivo, porque `capability_allowed_by_activity`
 * recusa atender mesa a quem não declarou a atividade — e o acervo não
 * declarava nenhuma. Faltava atividade, não capability.
 *
 * Esta travessia percorre a jornada inteira com a atividade declarada, e prova
 * também o que a permissão faz: a mesma tela, com a pessoa do caixa, mostra o
 * mapa e não oferece configuração.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'hom-mesas')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const marca = Date.now().toString().slice(-4)
const AMBIENTE = { codigo: `SALAO${marca}`, nome: `Salão principal ${marca}` }
const MESA = { codigo: `M${marca}`, nome: `Mesa ${marca}`, lugares: '4' }
const IMPEDIMENTO = 'Cadeira quebrada, aguardando manutenção'

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao(token, email, nome) {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'hom01',
    user: {
      id: JSON.parse(Buffer.from(token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: nome },
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

async function abrir(navegador, token, email, nome) {
  const contexto = await navegador.newContext({
    viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1, locale: 'pt-BR',
  })
  await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
    ['sb-127-auth-token', JSON.stringify(sessao(token, email, nome))])
  const page = await contexto.newPage()
  page.setDefaultTimeout(25000)
  return { contexto, page }
}

async function main() {
  const navegador = await chromium.launch()
  try {
    // ==================================================================
    // A gestora: a jornada inteira
    // ==================================================================
    const { page, contexto } = await abrir(
      navegador, fixture.manager_token, fixture.manager_email, 'Renata Nogueira')
    const shot = async (nome) => {
      await page.screenshot({ path: path.join(outDir, nome + '.png'), fullPage: false })
      relatorio.telas.push(nome)
    }

    // ---- 1. o card existe, e é isto que não existia antes
    await page.goto(appUrl + '/manage?area=ESTRUTURA', { waitUntil: 'domcontentloaded' })
    const noHub = await esperar(page, /Ambientes e mesas/i, 'o card de Ambientes e mesas')
    await shot('1-card-em-estrutura')
    relatorio.etapas.push({ etapa: 'o card aparece com a atividade declarada' })
    exigir(/Organize os espaços/i.test(noHub), 'o card deveria trazer a frase de tarefa do mapa')

    await page.getByRole('button', { name: /^Ambientes e mesas/ }).first().click()
    await esperar(page, /Ambientes, mesas e reservas/, 'a tela de estrutura do atendimento')
    await shot('2-tela-do-atendimento')

    // ---- 2. criar o ambiente
    await page.getByRole('button', { name: 'Ambientes' }).first().click()
    await page.waitForTimeout(800)
    await page.getByRole('button', { name: 'Novo ambiente' }).click()
    await page.waitForTimeout(700)
    await page.getByLabel('Código').fill(AMBIENTE.codigo)
    await page.getByLabel('Nome', { exact: true }).fill(AMBIENTE.nome)
    await page.getByRole('button', { name: 'Cadastrar ambiente' }).click()
    const comAmbiente = await esperar(page, new RegExp(AMBIENTE.nome), 'o ambiente cadastrado')
    await shot('3-ambiente-cadastrado')
    relatorio.etapas.push({ etapa: 'cadastrar ambiente', apareceu: true })
    exigir(/0 mesas/.test(comAmbiente), 'um ambiente novo deveria dizer que ainda não tem mesas')

    // ---- 3. criar a mesa dentro dele
    await page.getByRole('button', { name: 'Mesas' }).first().click()
    await page.waitForTimeout(800)
    await page.getByRole('button', { name: 'Nova mesa' }).click()
    await page.waitForTimeout(700)
    await page.getByLabel('Código').fill(MESA.codigo)
    await page.getByLabel('Nome visível').fill(MESA.nome)
    await page.getByLabel('Capacidade').fill(MESA.lugares)
    // O rótulo do `<label>` envolve o `<select>`, então o nome acessível é
    // "Ambiente" + o texto das opções: nem exato nem parcial resolve bem. O
    // diálogo tem um select só, e é ele.
    await page.locator('[role="dialog"] select').first().selectOption({ label: AMBIENTE.nome })
    await page.getByRole('button', { name: 'Adicionar ao mapa' }).click()
    const comMesa = await esperar(page, new RegExp(MESA.nome), 'a mesa cadastrada')
    await shot('4-mesa-no-mapa')
    relatorio.etapas.push({ etapa: 'cadastrar mesa', noAmbiente: comMesa.includes(AMBIENTE.nome) })
    exigir(comMesa.includes(AMBIENTE.nome), 'a mesa deveria mostrar em que ambiente está')
    exigir(/AVAILABLE/.test(comMesa), 'uma mesa nova deveria nascer disponível')

    // ---- 4. impedir e liberar, com motivo — a jornada que deixa rastro
    await page.getByRole('button', { name: /^Bloquear$/ }).first().click()
    await page.waitForTimeout(700)
    await page.getByLabel('Motivo').fill(IMPEDIMENTO)
    await page.getByRole('button', { name: 'Confirmar impedimento' }).click()
    const bloqueada = await esperar(page, /BLOCKED/, 'a mesa impedida')
    await shot('5-mesa-impedida')
    relatorio.etapas.push({ etapa: 'sinalizar impedimento', mostraMotivo: bloqueada.includes(IMPEDIMENTO) })
    exigir(bloqueada.includes(IMPEDIMENTO),
      'a mesa impedida deveria mostrar o motivo, não só o estado')

    await page.getByRole('button', { name: /^Liberar$/ }).first().click()
    await page.waitForTimeout(700)
    await page.getByLabel('Motivo').fill('Manutenção concluída')
    await page.getByRole('button', { name: 'Confirmar liberação' }).click()
    const liberada = await esperar(page, /AVAILABLE/, 'a mesa liberada')
    await shot('6-mesa-liberada')
    relatorio.etapas.push({ etapa: 'liberar', voltou: /AVAILABLE/.test(liberada) })
    exigir(!liberada.includes(IMPEDIMENTO), 'o motivo do impedimento deveria sair quando ele acaba')

    // ---- 5. a recusa: ambiente com mesa não se arquiva
    await page.getByRole('button', { name: 'Ambientes' }).first().click()
    const comContagem = await esperar(page, /1 mesas|1 mesa/, 'a contagem do ambiente')
    await shot('7-ambiente-com-mesa')
    const arquivar = page.getByRole('button', { name: 'Arquivar ambiente' }).first()
    const desabilitado = await arquivar.isDisabled()
    relatorio.etapas.push({ etapa: 'ambiente com mesa não se arquiva', recusou: desabilitado })
    exigir(desabilitado,
      'arquivar um ambiente que ainda tem mesa deveria ser recusado, não permitido')

    await contexto.close()

    // ==================================================================
    // Quem vê o mapa e não o configura
    //
    // Perfil de caixa não serve aqui: caixa não entra na Gestão, a tela recusa
    // com "terminal não autorizado". E nenhum perfil de sistema tem
    // `table.read` sem `table.manage`. A distinção real é por concessão — uma
    // gerente com `table.manage` negado no vínculo, que é como um lojista tira
    // uma permissão de alguém.
    // ==================================================================
    const { page: pageCaixa } = await abrir(
      navegador, fixture.limited_token, fixture.limited_email, 'Tiago Prado')
    await pageCaixa.goto(appUrl + '/manage?area=ESTRUTURA&module=tables',
                         { waitUntil: 'domcontentloaded' })
    // O título aparece antes do mapa carregar. Esperar por ele e ler em
    // seguida mede a tela vazia — e a acusação sai contra a permissão, que não
    // tem culpa nenhuma.
    const doCaixa = await esperar(pageCaixa, new RegExp(MESA.nome),
                                  'o mapa do salão para quem só pode ver')
    await pageCaixa.screenshot({ path: path.join(outDir, '8-ve-o-mapa-sem-configurar.png') })
    relatorio.telas.push('8-ve-o-mapa-sem-configurar')

    relatorio.etapas.push({
      etapa: 'permissão: vê o mapa, não configura',
      veOMapa: doCaixa.includes(MESA.nome),
    })
    exigir(doCaixa.includes(MESA.nome),
      'quem tem table.read deveria ver o mapa do salão')
    exigir(!/Novo ambiente/.test(doCaixa),
      'com table.manage negado, "Novo ambiente" não deveria ser oferecido')
    exigir(!/Nova mesa/.test(doCaixa),
      'com table.manage negado, "Nova mesa" não deveria ser oferecido')
    exigir(!/Arquivar/.test(doCaixa),
      'com table.manage negado, arquivar não deveria ser oferecido')
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom01-ambientes-e-mesas.json'),
                   JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
