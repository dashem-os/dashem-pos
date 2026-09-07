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
  assert.match(catalog, /try \{\s*await adjustStock\(/)
  assert.match(catalog, /\} catch \{\s*return\s*\}/)
  // Os campos só são limpos depois do catch, nunca antes dele.
  assert.ok(catalog.indexOf('} catch {') < catalog.indexOf("setAdjustQty('')"))
})

test('a tela de estoque só comemora depois de o servidor aceitar', () => {
  assert.ok(inventory.indexOf('await adjustStock(') < inventory.indexOf("showToast('success'"))
  assert.match(inventory, /\} catch \{/)
})

test('a mensagem de sucesso fala a língua do lojista', () => {
  assert.doesNotMatch(inventory, /ledger/i)
  assert.match(inventory, /histórico do estoque/)
})

test('nenhuma tela inventa sinal negativo para representar saída', () => {
  // O sinal é do servidor: a tela informa magnitude e o tipo da operação.
  for (const source of [catalog, inventory]) {
    assert.doesNotMatch(source, /quantity:\s*-/)
    assert.doesNotMatch(source, /-\s*(parseFloat|Number)\(/)
  }
})
