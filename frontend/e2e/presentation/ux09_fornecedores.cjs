/**
 * UX-09 — Fornecedores: o card que era destino ausente passa a existir.
 *
 * O inventário não achou nada: nem tabela, nem rota, nem tela. Então esta
 * travessia prova o domínio inteiro pelo caminho de quem usa — o card aparece
 * em Relacionamento, cadastra, acha, guarda contato — e prova também o que o
 * enunciado **proíbe**: não há pedido de compra prometido em lugar nenhum.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux09')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const marca = Date.now().toString().slice(-6)
// O documento também carrega a marca da rodada. Sem isso a segunda execução
// esbarra no cadastro da primeira — e a recusa por documento repetido, que é
// comportamento correto, aparecia como falha da travessia.
const FORNECEDOR = {
  nome: `Distribuidora Aurora ${marca}`,
  documento: `${marca.slice(0, 2)}.${marca.slice(2, 5)}.${marca.slice(5)}12/0001-90`,
}
const CONTATO = { nome: 'Cláudia Ramos', funcao: 'Vendedora', telefone: '11999990000' }
// O CNPJ alfanumérico está em operação desde julho de 2026: as doze primeiras
// posições podem ser letras, e só os dois verificadores são numéricos.
const ALFANUMERICO = {
  nome: `Fornecedora Alfanumérica ${marca}`,
  documento: `${marca.slice(0, 2)}.ABC.${marca.slice(2, 5)}/01DE-35`,
}

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), etapas: [], telas: [] }
const falhas = []
const exigir = (condicao, oQue) => { if (!condicao) falhas.push(oQue); return !!condicao }

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux09-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

/**
 * Portão de carga. Esperar no relógio fotografa a tela ainda vazia e conta a
 * foto como evidência — quinze fotos do mesmo carregamento já contaram como
 * quinze capturas aqui. Isto espera o conteúdo e, se ele não vier, falha
 * dizendo o que **estava** na tela.
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

    // ================== 1. o card deixou de ser destino ausente
    await page.goto(appUrl + '/manage?area=RELACIONAMENTO', { waitUntil: 'domcontentloaded' })
    const noHub = await esperar(page, /Fornecedores/i, 'o card de Fornecedores')
    await shot(page, '1-card-em-relacionamento')
    relatorio.etapas.push({ etapa: 'o card existe em Relacionamento', descricao: /Organize quem fornece/i.test(noHub) })
    exigir(/Organize quem fornece/i.test(noHub), 'o card deveria trazer a frase de tarefa do mapa')

    // ================== 2. cadastrar
    await page.getByRole('button', { name: /^Fornecedores/ }).first().click()
    await esperar(page, /Cadastrar fornecedor/, 'a tela de Fornecedores')
    await shot(page, '2-tela-vazia')
    await page.getByRole('button', { name: 'Cadastrar fornecedor' }).first().click()
    await page.waitForTimeout(900)
    await page.getByLabel('Nome', { exact: true }).fill(FORNECEDOR.nome)
    await page.getByLabel('CNPJ ou CPF').fill(FORNECEDOR.documento)
    await page.getByRole('button', { name: 'Cadastrar fornecedor' }).last().click()
    const depoisDeCadastrar = await esperar(page, new RegExp(FORNECEDOR.nome), 'o fornecedor recém-cadastrado')
    relatorio.etapas.push({ etapa: 'cadastrar', apareceu: depoisDeCadastrar.includes(FORNECEDOR.nome) })
    exigir(depoisDeCadastrar.includes(FORNECEDOR.nome), 'o fornecedor cadastrado não apareceu na lista')
    exigir(/Nenhum ainda/.test(depoisDeCadastrar),
      'um fornecedor novo deveria dizer que ainda não teve recebimento')
    await shot(page, '3-fornecedor-cadastrado')

    // ================== 3. localizar pelo documento com máscara
    // Buscar pelo documento com máscara: quem digita o CNPJ digita os pontos.
    await page.getByPlaceholder(/Buscar por nome ou documento/).fill(FORNECEDOR.documento.slice(0, 10))
    await page.waitForTimeout(2200)
    const achado = await page.evaluate(() => (document.querySelector('main')?.innerText || ''))
    relatorio.etapas.push({ etapa: 'localizar pelo documento', achou: achado.includes(FORNECEDOR.nome) })
    exigir(achado.includes(FORNECEDOR.nome), 'buscar pelo documento com máscara deveria achar o cadastro')

    // ================== 4. contatos
    await page.getByRole('button', { name: 'Contatos' }).first().click()
    await page.waitForTimeout(1000)
    await page.getByLabel('Nome do contato').fill(CONTATO.nome)
    await page.getByLabel('Função').fill(CONTATO.funcao)
    await page.getByLabel('Telefone').fill(CONTATO.telefone)
    await page.getByLabel(/Este é o contato principal/).check()
    await page.getByRole('button', { name: 'Adicionar contato' }).click()
    await page.waitForTimeout(2600)
    const comContato = await page.evaluate(() => {
      const dialogo = document.querySelector('[role="dialog"]') || document.body
      return (dialogo.innerText || '')
    })
    await shot(page, '4-contatos')
    relatorio.etapas.push({ etapa: 'contatos', guardou: comContato.includes(CONTATO.nome) })
    exigir(comContato.includes(CONTATO.nome), 'o contato não foi guardado')
    exigir(comContato.includes(CONTATO.funcao), 'a função do contato deveria aparecer')

    // ================== 5. o que o enunciado proíbe
    await page.keyboard.press('Escape').catch(() => null)
    await page.waitForTimeout(800)
    const naTela = await page.evaluate(() => (document.querySelector('main')?.innerText || ''))
    relatorio.etapas.push({ etapa: 'nada promete pedido de compra' })
    exigir(!/pedido de compra|ordem de compra|aprovar compra/i.test(naTela),
      'a tela promete pedido de compra, que o enunciado proíbe entregar')
    await shot(page, '5-lista-final')

    // ================== 6. o CNPJ alfanumérico chega inteiro
    // Guardar só dígitos apagava letras de um documento válido e gravava outro
    // no lugar. O alfanumérico está em operação desde julho de 2026.
    await page.getByRole('button', { name: 'Cadastrar fornecedor' }).first().click()
    await page.waitForTimeout(900)
    await page.getByLabel('Nome', { exact: true }).fill(ALFANUMERICO.nome)
    await page.getByLabel('CNPJ ou CPF').fill(ALFANUMERICO.documento)
    await page.getByRole('button', { name: 'Cadastrar fornecedor' }).last().click()
    await page.waitForTimeout(3000)
    await page.getByPlaceholder(/Buscar por nome ou documento/).fill(ALFANUMERICO.nome)
    await page.waitForTimeout(2200)
    const comLetras = await page.evaluate(() => (document.querySelector('main')?.innerText || ''))
    await shot(page, '6-cnpj-alfanumerico')
    relatorio.etapas.push({ etapa: 'CNPJ alfanumérico', naTela: comLetras.includes(ALFANUMERICO.documento) })
    exigir(comLetras.includes(ALFANUMERICO.documento),
      `o CNPJ alfanumérico deveria voltar inteiro e com máscara: ${ALFANUMERICO.documento}`)

    // ================== 7. apagar o documento apaga mesmo
    // A tela mandava `undefined`, que some do JSON: o lojista apagava o CNPJ
    // errado, salvava, e ele voltava.
    await page.getByRole('button', { name: 'Editar' }).first().click()
    await page.waitForTimeout(1000)
    await page.getByLabel('CNPJ ou CPF').fill('')
    await page.getByRole('button', { name: /Salvar|Cadastrar fornecedor/ }).last().click()
    await page.waitForTimeout(3000)
    const semDocumento = await page.evaluate(() => (document.querySelector('main')?.innerText || ''))
    await shot(page, '7-documento-apagado')
    const aindaLa = semDocumento.includes(ALFANUMERICO.documento)
    relatorio.etapas.push({ etapa: 'apagar o documento', apagou: !aindaLa })
    exigir(!aindaLa, 'o documento apagado voltou: a tela não mandou a intenção de apagar')

    // ================== 8. o documento de outro é recusado com nome e motivo
    await page.getByRole('button', { name: 'Editar' }).first().click()
    await page.waitForTimeout(1000)
    await page.getByLabel('CNPJ ou CPF').fill(FORNECEDOR.documento)
    await page.getByRole('button', { name: /Salvar|Cadastrar fornecedor/ }).last().click()
    await page.waitForTimeout(2600)
    const recusa = await page.evaluate(() => {
      const dialogo = document.querySelector('[role="dialog"]') || document.body
      return (dialogo.innerText || '')
    })
    await shot(page, '8-documento-de-outro-recusado')
    relatorio.etapas.push({ etapa: 'documento de outro', recusou: /já existe um fornecedor/i.test(recusa) })
    exigir(/já existe um fornecedor/i.test(recusa),
      'editar para o documento de outro deveria ser recusado com explicação')
    exigir(recusa.includes(FORNECEDOR.nome),
      'a recusa deveria dizer de quem é o documento, não só que houve conflito')
    await page.keyboard.press('Escape').catch(() => null)
    await page.waitForTimeout(800)

    // ================== 9. o recebimento diz de quem veio
    // Este é o vínculo que a UX-09 promete. A coluna existia no banco e
    // nenhuma tela a preenchia, então "de quem veio esta mercadoria?"
    // continuava sem resposta no histórico.
    await page.goto(appUrl + '/manage?area=MERCADORIAS&module=inventory', { waitUntil: 'domcontentloaded' })
    await esperar(page, /Estoque por unidade/, 'a lista de estoque')
    await shot(page, '9-estoques')
    // Receber é botão de linha só para o que está em falta ou abaixo do
    // mínimo; para o resto ele vive no menu da linha. Os dois caminhos levam
    // ao mesmo formulário, e a travessia usa o que a tela estiver oferecendo.
    const botaoDireto = page.getByRole('button', { name: /^Receber$/ })
    if (await botaoDireto.count()) {
      await botaoDireto.first().click()
    } else {
      await page.getByRole('button', { name: /^Ações de / }).first().click()
      await page.waitForTimeout(700)
      await page.getByRole('menuitem', { name: 'Receber mercadoria' }).first().click()
    }
    await page.waitForTimeout(1400)

    const rotulo = page.getByText('De quem veio', { exact: true })
    const temSeletor = await rotulo.count()
    relatorio.etapas.push({ etapa: 'seletor no recebimento', existe: temSeletor > 0 })
    if (!exigir(temSeletor > 0, 'o recebimento não oferece informar de quem veio a mercadoria')) {
      await shot(page, '10-recebimento-sem-seletor')
    } else {
      const seletor = page.locator('select').first()
      await seletor.selectOption({ label: FORNECEDOR.nome })
      await page.getByLabel(/Quantidade recebida/).fill('24')
      await shot(page, '10-recebimento-com-fornecedor')
      await page.getByRole('button', { name: 'Confirmar recebimento' }).click()
      await page.waitForTimeout(3600)

      // O histórico relê o vínculo: guardar sem mostrar é o mesmo que não guardar.
      // A troca de aba é verificada, não presumida: clicar e fotografar sem
      // conferir rendeu uma captura da aba antiga contada como evidência.
      let historico = ''
      for (let tentativa = 0; tentativa < 3; tentativa += 1) {
        await page.getByRole('tab', { name: 'Movimentações', exact: true }).click()
        try {
          historico = await esperar(page, /Movimentações recentes/, 'o histórico do estoque', 6000)
          break
        } catch (semAba) {
          if (tentativa === 2) throw semAba
          await page.waitForTimeout(1200)
        }
      }
      await shot(page, '11-historico-de-quem-veio')
      relatorio.etapas.push({ etapa: 'histórico nomeia o fornecedor', achou: historico.includes(FORNECEDOR.nome) })
      exigir(historico.includes(FORNECEDOR.nome),
        'o histórico do estoque não diz de quem veio a entrada registrada')

      // E o cadastro do fornecedor deixa de dizer "Nenhum ainda".
      await page.goto(appUrl + '/manage?area=RELACIONAMENTO&module=suppliers', { waitUntil: 'domcontentloaded' })
      await esperar(page, /Buscar por nome ou documento|Cadastrar fornecedor/, 'a tela de Fornecedores de volta')
      await page.getByPlaceholder(/Buscar por nome ou documento/).fill(FORNECEDOR.nome)
      await page.waitForTimeout(2400)
      const contagem = await page.evaluate(() => (document.querySelector('main')?.innerText || ''))
      await shot(page, '12-fornecedor-com-recebimento')
      relatorio.etapas.push({ etapa: 'o fornecedor conta o recebimento', deixouDeSerZero: !/Nenhum ainda/.test(contagem) })
      exigir(!/Nenhum ainda/.test(contagem),
        'o fornecedor que recebeu uma entrada ainda diz que nunca teve recebimento')
    }
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'ux09-fornecedores.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
