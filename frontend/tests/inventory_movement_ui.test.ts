import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

/**
 * A tela não pode anunciar o que o servidor recusou.
 *
 * `adjustStock` capturava o erro, mostrava o aviso e devolvia normalmente. Quem
 * chamava seguia como se tivesse dado certo: o cadastro de produtos limpava os
 * campos e fechava o modal, e a tela de estoque ainda emitia mensagem de
 * sucesso por cima da mensagem de falha.
 *
 * Estas verificações leem o fonte. Elas provam que o padrão anterior não voltou
 * — não substituem exercitar a recusa pela interface, que é o gate de operação.
 */

const root = join(import.meta.dirname, '..', 'src')
const context = readFileSync(join(root, 'context', 'PosContext.tsx'), 'utf8')
const catalog = readFileSync(join(root, 'components', 'management', 'CatalogManager.tsx'), 'utf8')
const inventory = readFileSync(join(root, 'components', 'management', 'InventoryManager.tsx'), 'utf8')

test('a falha ao movimentar estoque chega a quem chamou', () => {
  assert.match(context, /throw err instanceof Error \? err : new Error\(msg\)/)
})

test('o cadastro de produtos não fecha o formulário sobre uma recusa', () => {
  // Recortado no handler: abrir o formulário também zera campos, e isso é
  // outra coisa — o que não pode acontecer é limpar depois de uma recusa.
  const handler = catalog.slice(catalog.indexOf('const handleAdjustStock'))
  const corpo = handler.slice(0, handler.indexOf('const handleQuickAccess'))
  assert.match(corpo, /try \{\s*await adjustStock\(/)
  assert.match(corpo, /\} catch \{\s*return\s*\}/)
  // Os campos só são limpos depois do catch, nunca antes dele.
  assert.ok(corpo.indexOf('} catch {') < corpo.indexOf("setAdjustQty('')"))
})

test('a tela de estoque só comemora depois de o servidor aceitar', () => {
  // O aviso de sucesso saiu daqui: quem o emite é `adjustStock`, e só depois de
  // a API responder. Duas mensagens para uma ação diziam a mesma coisa duas
  // vezes; o que esta tela não pode fazer é anunciar por conta própria.
  const submit = inventory.slice(inventory.indexOf('const submit = async'))
  const corpo = submit.slice(0, submit.indexOf('// -------'))
  assert.doesNotMatch(corpo, /showToast\('success'/)
})

test('a recusa do servidor fica no formulário, não só no aviso que some', () => {
  // O aviso flutuante dura poucos segundos. Quem digitou 999 e viu o aviso
  // passar não descobre mais por que nada foi registrado.
  const submit = inventory.slice(inventory.indexOf('const submit = async'))
  const corpo = submit.slice(0, submit.indexOf('// -------'))
  assert.match(corpo, /catch \(reason\) \{[\s\S]*setMovementError\(/)
  assert.match(corpo, /setMovementError\([\s\S]*?\)\s+setBusy\(false\)\s+return/)
  assert.match(inventory, /role="alert"[\s\S]*?\{movementError\}/)
})

test('a mensagem de sucesso fala a língua do lojista', () => {
  assert.doesNotMatch(inventory, /ledger/i)
  // A frase vive onde o aviso é emitido: no contexto, depois da resposta da API.
  assert.match(context, /histórico do estoque/)
  assert.doesNotMatch(context, /Estoque ajustado com sucesso/)
})

test('nenhuma tela inventa sinal negativo para representar saída', () => {
  // O sinal é do servidor: a tela informa magnitude e o tipo da operação.
  for (const source of [catalog, inventory]) {
    assert.doesNotMatch(source, /quantity:\s*-/)
    // O que se proíbe é enviar quantidade negativa, não subtrair dois números:
    // a folga sobre a referência é uma subtração legítima na tela.
    assert.doesNotMatch(source, /quantity:\s*-/)
    assert.doesNotMatch(source, /:\s*-\s*(parseFloat|Number)\(/)
  }
})

test('a movimentação viaja carimbada, e o carimbo é da intenção', () => {
  const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
  const contexto = context
  const estoque = inventory

  // O servidor sempre soube deduplicar por Idempotency-Key. Esta tela nunca
  // mandava uma, então dois cliques em "Receber" registravam duas entradas.
  assert.match(api, /'Idempotency-Key': idempotencyKey/)
  assert.match(contexto, /api\.adjustInventory\(hdrs, \{[\s\S]*?\}, idempotencyKey\)/)

  // E o carimbo nasce ao abrir o formulário, não a cada envio: uma chave por
  // tentativa faria o reenvio depois de um erro virar um segundo movimento,
  // que é exatamente o caso que a chave existe para impedir.
  assert.match(estoque, /setMovementKey\(crypto\.randomUUID\(\)\)/)
  // A chamada passou a levar também de quem veio a mercadoria, e por isso
  // ocupa mais de uma linha. O que esta regra guarda continua sendo o
  // carimbo: a chave da intenção viaja junto com o motivo.
  assert.match(estoque, /form\.reason,[\s\S]{0,20}?movementKey[,)]/)
  assert.doesNotMatch(estoque, /form\.reason,\s*crypto\.randomUUID\(\)\)/)
})

test('a cobrança viaja carimbada, e o carimbo é da intenção', () => {
  const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
  const dialogo = readFileSync(join(root, 'components', 'pos', 'PaymentDialog.tsx'), 'utf8')

  // Confirmar já era idempotente por estado. Criar não era — e é criar que
  // abre a segunda cobrança quando a confirmação estoura depois do envio.
  assert.match(api, /'Idempotency-Key': idempotencyKey/)
  assert.match(context, /api\.createPayment\([\s\S]{0,300}?idempotencyKey,/)

  // O carimbo da confirmação deriva da mesma intenção. Antes carregava
  // Date.now\(\), o que o tornava novo a cada tentativa: carimbo por tentativa
  // não protege reenvio nenhum.
  assert.match(context, /\$\{idempotencyKey\}-confirm/)
  assert.doesNotMatch(context, /pay-idemp-\$\{pay\.id\}-\$\{Date\.now\(\)\}/)

  // E a intenção não nasce de um efeito: efeito roda de novo quando o React
  // quer, e o carimbo trocava entre a tentativa que falhou e o reenvio. Ela é
  // derivada do que a define — método, valor e quantas parcelas já foram
  // confirmadas —, porque duas parcelas iguais na mesma venda são duas
  // intenções, e deduplicá-las perderia metade do dinheiro.
  assert.match(dialogo, /const assinaturaDaIntencao = `\$\{method\}:\$\{activeAmountToPay\.toFixed\(2\)\}:\$\{confirmedPayments\.length\}`/)
  assert.match(dialogo, /intencaoRef\.current = \{ assinatura: assinaturaDaIntencao, chave: crypto\.randomUUID\(\) \}/)
  assert.match(dialogo, /processPayment\(method, activeAmountToPay, tend, intencaoRef\.current\.chave\)/)
  assert.doesNotMatch(dialogo, /useEffect\([^)]*setIntencao/)
})

test('timeout não é recusa, e a ação principal é consultar', () => {
  const dialogo = readFileSync(join(root, 'components', 'pos', 'PaymentDialog.tsx'), 'utf8')
  const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')

  // Quando a resposta não volta, a cobrança pode ter sido confirmada do outro
  // lado. Anunciar erro empurraria o operador a cobrar de novo do que já foi
  // cobrado — que é a segunda cobrança por ambiguidade que o aceite proíbe.
  assert.match(context, /setPagamentoPendente\(\{[\s\S]{0,200}?situacao: 'DESCONHECIDO'/)
  assert.match(dialogo, /Pendente de confirmação/)
  assert.match(dialogo, /Verificar pagamento/)
  assert.match(dialogo, /não quer dizer que ela foi recusada/)

  // Consultar nunca cobra: ela só lê o que existe.
  assert.match(context, /const verificarPagamento = async \(\) => \{/)
  const consulta = context.slice(context.indexOf('const verificarPagamento'), context.indexOf('const issueFiscal'))
  assert.doesNotMatch(consulta, /createPayment|confirmPayment/)

  // E a consulta falha alto: devolver lista vazia faria "não consegui
  // perguntar" ficar indistinguível de "nada foi cobrado".
  assert.match(api, /export async function consultarPagamentosDaVenda/)
  const leitura = api.slice(api.indexOf('export async function consultarPagamentosDaVenda'))
  assert.match(leitura.slice(0, 600), /throw await apiError/)
})
