/**
 * Homologação — duas estações disputando a **última unidade**.
 *
 * Uma Coca-Cola na prateleira, dois caixas abertos lado a lado. As duas
 * operadoras a querem. É o caso em que overselling nasce: se as duas venderem,
 * o lojista prometeu mercadoria que não tem e vai descobrir no balcão, na
 * frente do cliente.
 *
 * O que esta travessia mede, nas **duas telas**:
 *
 * * a primeira estação prende a unidade ao pôr no carrinho;
 * * a segunda é recusada, e a recusa nomeia a mercadoria e diz o porquê;
 * * a primeira fecha a venda;
 * * a segunda continua recusada — agora por outro motivo: não está prometida,
 *   está vendida.
 *
 * E confere no servidor o que as telas disseram: quantas vendas existem, o que
 * ficou reservado e qual é o saldo. Saldo negativo aqui é o defeito que o
 * cenário existe para não deixar passar.
 *
 * **O que este roteiro NÃO faz.** Ele é sequencial: espera a estação 1 pôr a
 * unidade no carrinho antes de mandar a estação 2 tentar. Prova que uma reserva
 * já concluída impede a segunda inclusão — não prova que duas inclusões
 * **simultâneas** disputando a mesma unidade se resolvem no banco. Essa é outra
 * prova, e ela precisa construir a corrida em vez de torcer pelo escalonador.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.WALK_APP_URL || 'http://127.0.0.1:5199'
const apiUrl = process.env.WALK_API_URL || 'http://127.0.0.1:8004'
const fixturePath = process.env.WALK_FIXTURE
const outDir = process.env.WALK_OUT || path.resolve('artifacts', 'hom-ultima-unidade')
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

async function estacao(navegador, pessoa, etiqueta) {
  const contexto = await navegador.newContext({ viewport: VIEWPORT, locale: 'pt-BR' })
  // O terminal foi autorizado pela gestora na abertura da loja; é isso que o
  // equipamento guarda. Quem entra depois é a pessoa, com código e PIN.
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

async function abrirCaixa(page, etiqueta) {
  const abrir = page.getByRole('button', { name: /ABRIR CAIXA/i })
  if (await abrir.count() === 0) return
  const fundo = page.locator('input[inputmode="numeric"]').last()
  await fundo.click()
  await fundo.type('20000')
  await abrir.first().click()
  await page.waitForTimeout(3000)
  console.log(`  [${etiqueta}] caixa aberto`)
}

async function adicionar(page, termo) {
  const busca = page.getByPlaceholder(/Buscar produto ou escanear/i).first()
  await busca.click()
  await busca.fill(termo)
  await page.waitForTimeout(900)
  await page.keyboard.press('Enter')
  await page.waitForTimeout(1400)
}

const naTela = async (page) => (await page.locator('body').innerText()).replace(/\s+/g, ' ')

async function esperaTexto(page, expressao, limiteMs = 10000) {
  const fim = Date.now() + limiteMs
  let ultimo = ''
  while (Date.now() < fim) {
    ultimo = await naTela(page)
    if (expressao.test(ultimo)) return ultimo
    await page.waitForTimeout(300)
  }
  return ultimo
}

/** O servidor, perguntado direto. A tela conta uma história; aqui se confere. */
async function noServidor(page, caminho) {
  return page.evaluate(async ([api, rota, tenant, store, token]) => {
    const resposta = await fetch(`${api}${rota}`, {
      headers: { 'X-Tenant-ID': tenant, 'X-Store-ID': store, Authorization: `Bearer ${token}` },
    })
    return { status: resposta.status, corpo: await resposta.json().catch(() => null) }
  }, [apiUrl, caminho, fixture.tenant_id, fixture.store_id, fixture.supervisor.token])
}

async function run() {
  const navegador = await chromium.launch()
  try {
    const produtoId = fixture.disputado.product_id
    exigir(fixture.disputado.saldo === '1',
      `esta travessia precisa de uma unidade na prateleira, e a semeadura trouxe ${fixture.disputado.saldo}`)

    const primeira = await estacao(navegador, fixture.operator, 'estação 1')
    const segunda = await estacao(navegador, fixture.supervisor, 'estação 2')
    await abrirCaixa(primeira, 'estação 1')
    await abrirCaixa(segunda, 'estação 2')

    // ---------------------------------------- 1. a primeira prende a unidade
    await adicionar(primeira, 'Coca')
    const comItem = await esperaTexto(primeira, /1 item/)
    await shot(primeira, 'estacao-1-com-a-ultima-unidade')
    relatorio.etapas.push({ etapa: 'a primeira estação põe a última unidade no carrinho' })
    exigir(/1 item/.test(comItem),
      `a primeira estação deveria ter 1 item no carrinho: "${comItem.slice(0, 120)}"`)

    // ---------------------------------------- 2. a segunda é recusada
    await adicionar(segunda, 'Coca')
    const recusa = await esperaTexto(segunda, /vendas abertas|Não há|Só há/)
    await shot(segunda, 'estacao-2-recusada-por-venda-aberta')
    relatorio.etapas.push({
      etapa: 'a segunda estação é recusada enquanto a unidade está prometida',
      mensagem: (recusa.match(/(Não há|Só há)[^.]*\./) || ['sem mensagem'])[0],
    })
    exigir(/vendas abertas/.test(recusa),
      'a recusa deveria explicar que a unidade está prometida a uma venda aberta')
    exigir(/Coca-Cola Lata/.test(recusa),
      'a recusa deveria nomear a mercadoria, não falar de "item" em geral')
    exigir(!/1 item/.test(recusa),
      'a segunda estação não deveria ter conseguido pôr a unidade no carrinho')

    // A recusa é a prova de que esta tela estava atrasada, então ela precisa
    // reler. Sem isso, o aviso dizia "nada disponível agora" e o cartão ao lado
    // continuava anunciando "Última unidade" — um convite a clicar de novo.
    const releu = await esperaTexto(segunda, /Sem estoque/, 8000)
    await shot(segunda, 'estacao-2-grade-relida')
    relatorio.etapas.push({
      etapa: 'a recusa relê a prateleira, e o cartão para de convidar',
      cartao: /Sem estoque/.test(releu) ? 'Sem estoque' : 'não releu',
    })
    exigir(!/Última unidade/.test(releu),
      'depois da recusa, o cartão não deveria continuar anunciando "Última unidade"')
    exigir(/Sem estoque/.test(releu),
      'depois da recusa, o cartão deveria dizer que não há estoque disponível')

    // ---------------------------------------- 3. o servidor, no meio da disputa
    const durante = await noServidor(primeira, `/api/v1/inventory/holdings?store_id=${fixture.store_id}`)
    const saldoDurante = (durante.corpo || []).find((b) => b.product_id === produtoId)
    relatorio.servidor.durante_a_disputa = saldoDurante
      ? { fisico: saldoDurante.quantity, reservado: saldoDurante.reserved, disponivel: saldoDurante.available }
      : { erro: 'saldo não encontrado', status: durante.status }
    if (saldoDurante) {
      exigir(Number(saldoDurante.available) === 0,
        `com a unidade prometida, o disponível deveria ser 0 e é ${saldoDurante.available}`)
      exigir(Number(saldoDurante.quantity) === 1,
        `o físico ainda não saiu da prateleira e deveria ser 1, e é ${saldoDurante.quantity}`)
    }

    // ---------------------------------------- 4. a primeira fecha a venda
    await primeira.getByRole('button', { name: /^Receber/ }).first().click()
    await primeira.waitForTimeout(1400)
    await shot(primeira, 'estacao-1-pagamento')
    await primeira.getByRole('button', { name: /Confirmar|Finalizar|Receber/i }).last().click()
    // Medir a afirmação, não a ausência: "1 item" some do carrinho e continua
    // aparecendo no comprovante da venda recém-fechada. Quem responde se ela
    // fechou é a própria tela, dizendo que fechou.
    const fechada = await esperaTexto(primeira, /conclu[íi]da|finalizada com sucesso/i, 12000)
    await shot(primeira, 'estacao-1-venda-fechada')
    relatorio.etapas.push({
      etapa: 'a primeira estação fecha a venda',
      confirmou: /conclu[íi]da/i.test(fechada),
    })
    exigir(/conclu[íi]da|finalizada com sucesso/i.test(fechada),
      `a tela deveria confirmar a venda concluída: "${fechada.slice(0, 140)}"`)

    // ---------------------------------------- 5. a segunda continua recusada
    await adicionar(segunda, 'Coca')
    const depois = await esperaTexto(segunda, /Não há|Só há|indisponível|sem estoque/i)
    await shot(segunda, 'estacao-2-recusada-apos-a-venda')
    relatorio.etapas.push({
      etapa: 'depois da venda, a segunda continua recusada — e por outro motivo',
      mensagem: (depois.match(/(Não há|Só há)[^.]*\./) || ['sem mensagem'])[0],
    })
    // Aqui a ausência **é** a medida certa: a segunda estação não fechou venda
    // nenhuma, então nada na tela dela pode dizer que concluiu.
    exigir(!/conclu[íi]da|finalizada com sucesso/i.test(depois),
      'a segunda estação não deveria ter concluído venda do que já foi vendido')

    // ---------------------------------------- 6. o servidor, ao fim
    const balancos = await noServidor(primeira, `/api/v1/inventory/holdings?store_id=${fixture.store_id}`)
    const saldoFinal = (balancos.corpo || []).find((b) => b.product_id === produtoId)
    relatorio.servidor.ao_fim = saldoFinal
      ? { fisico: saldoFinal.quantity, reservado: saldoFinal.reserved, disponivel: saldoFinal.available }
      : { erro: 'saldo não encontrado', status: balancos.status }
    exigir(Boolean(saldoFinal), 'não consegui ler o saldo final no servidor')
    if (saldoFinal) {
      // **O defeito que este cenário existe para não deixar passar.**
      exigir(Number(saldoFinal.quantity) >= 0,
        `saldo físico negativo: a loja vendeu o que não tinha (${saldoFinal.quantity})`)
      exigir(Number(saldoFinal.quantity) === 0,
        `uma unidade havia e uma foi vendida: o físico deveria ser 0 e é ${saldoFinal.quantity}`)
      exigir(Number(saldoFinal.available) === 0,
        `o disponível deveria ser 0 e é ${saldoFinal.available}`)
    }

    const vendas = await noServidor(primeira, `/api/v1/sales?store_id=${fixture.store_id}`)
    const listaDeVendas = Array.isArray(vendas.corpo) ? vendas.corpo : (vendas.corpo?.items || [])
    const doProduto = listaDeVendas.filter((venda) =>
      (venda.items || []).some((item) => item.product_id === produtoId))
    const pagas = doProduto.filter((venda) => /COMPLETED|PAID|CLOSED/i.test(venda.status || ''))
    relatorio.servidor.vendas = {
      status: vendas.status,
      com_o_produto: doProduto.length,
      fechadas: pagas.length,
      situacoes: doProduto.map((v) => v.status),
    }
    exigir(pagas.length === 1,
      `só uma venda podia levar a última unidade, e ${pagas.length} foram fechadas`)

    // O que ficou reservado se lê no próprio saldo: `reserved` é a soma das
    // reservas ativas. Não há rota de listagem de reservas, e inventar uma para
    // a travessia provaria uma leitura que o produto não oferece.
    relatorio.servidor.reservado_ao_fim = saldoFinal ? saldoFinal.reserved : null
    if (saldoFinal) {
      exigir(Number(saldoFinal.reserved) === 0,
        `depois da venda fechada não deveria sobrar reserva, e sobrou ${saldoFinal.reserved}`)
    }
  } finally {
    await navegador.close()
  }

  relatorio.falhas = falhas
  fs.writeFileSync(path.join(outDir, 'hom03-ultima-unidade.json'),
                   JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`etapas: ${relatorio.etapas.length} · telas: ${relatorio.telas.length} · falhas: ${falhas.length}`)
  console.log(`servidor: ${JSON.stringify(relatorio.servidor)}`)
  falhas.forEach((f) => console.error('  REPROVOU: ' + f))
  if (falhas.length) process.exitCode = 1
}

run().catch((erro) => { console.error('FALHOU:', erro.message); process.exitCode = 1 })
