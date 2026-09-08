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
  assert.match(estoque, /form\.reason, movementKey\)/)
  assert.doesNotMatch(estoque, /form\.reason, crypto\.randomUUID\(\)\)/)
})
