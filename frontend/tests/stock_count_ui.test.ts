import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import {
  DESTINATIONS_FOR_CONDITION, countPreview, defaultDestination, returnEffect,
} from '../src/domain/stockMovements.ts'

/**
 * Contar estoque informa o total encontrado; o servidor calcula a diferença.
 *
 * A prévia é o que permite decidir sem fazer a conta de cabeça. Ela não é
 * autoridade — ao confirmar, o servidor verifica se o saldo mudou — mas precisa
 * dizer a mesma coisa que vai acontecer.
 */

test('a prévia mostra o que foi contado, o que havia e a diferença', () => {
  assert.equal(
    countPreview(10, 12),
    'Você contou 10 un. O sistema registra 12 un. Diferença: −2 un.',
  )
  assert.equal(
    countPreview(15, 12),
    'Você contou 15 un. O sistema registra 12 un. Diferença: +3 un.',
  )
})

test('contar zero é uma contagem, e a prévia diz o que vai sair', () => {
  assert.equal(
    countPreview(0, 4),
    'Você contou 0 un. O sistema registra 4 un. Diferença: −4 un.',
  )
})

test('contagem que bate não promete movimento nenhum', () => {
  const frase = countPreview(9, 9)
  assert.match(frase, /Confere/)
  assert.match(frase, /sem movimentar estoque/)
  assert.doesNotMatch(frase, /Diferença/)
})

test('a prévia respeita a unidade da mercadoria', () => {
  assert.match(countPreview(2.5, 3, 'kg'), /Você contou 2\.5 kg/)
})

const inventory = readFileSync(
  join(import.meta.dirname, '..', 'src', 'components', 'management', 'InventoryManager.tsx'),
  'utf8',
)

test('a tela manda a versão que a pessoa tinha à vista', () => {
  assert.match(inventory, /expected_version: countBase\?\.version \?\? 0/)
})

test('o conflito preserva o que foi digitado e pede nova conferência', () => {
  // Nada de setCounted('') no caminho do 409: o número contado permanece.
  const conflito = inventory.slice(inventory.indexOf('reason.status === 409'))
  const ateOFim = conflito.slice(0, conflito.indexOf('} finally'))
  assert.doesNotMatch(ateOFim, /setCounted\(''\)/)
  assert.doesNotMatch(ateOFim, /setCounting\(null\)/)
  assert.match(ateOFim, /setCountConflict\(reason\.message\)/)
  assert.match(ateOFim, /fetchInventoryBalance/)
  // E não reenvia sozinho com a versão nova: quem confirma é a pessoa.
  assert.doesNotMatch(ateOFim, /countStock\(/)
})

test('depois do conflito, confirmar exige um ato deliberado', () => {
  // Reler o saldo não pode transformar a contagem antiga em confirmação válida:
  // sem isto, um clique mandaria o número contado antes da movimentação contra
  // a versão recém-lida, que é a aceitação silenciosa que a versão impede.
  assert.match(inventory, /const \[recounted, setRecounted\] = useState\(false\)/)
  assert.match(inventory, /setRecounted\(false\)\s+setCountBase/)
  assert.match(inventory, /disabled=\{busy \|\| counted === '' \|\| \(Boolean\(countConflict\) && !recounted\)\}/)
  assert.match(inventory, /Voltei à prateleira/)
})

test('a ação de contar só aparece para quem tem a permissão de contar', () => {
  assert.match(inventory, /canCount = permissions\.includes\('inventory\.count'\)/)
  assert.match(inventory, /canCount \? <button/)
})


/**
 * Devolver mercadoria: a condição é o que a pessoa observa, o destino é a
 * consequência. Mercadoria imprópria não volta ao saldo vendável.
 */

const sales = readFileSync(
  join(import.meta.dirname, '..', 'src', 'components', 'management', 'SalesHistory.tsx'),
  'utf8',
)

test('mercadoria em condição de venda só tem um destino', () => {
  assert.deepEqual(DESTINATIONS_FOR_CONDITION.RESALEABLE, ['SELLABLE_STOCK'])
  assert.equal(defaultDestination('RESALEABLE'), 'SELLABLE_STOCK')
})

test('mercadoria imprópria nunca oferece o saldo vendável como destino', () => {
  assert.ok(!DESTINATIONS_FOR_CONDITION.UNFIT.includes('SELLABLE_STOCK'))
  assert.deepEqual(DESTINATIONS_FOR_CONDITION.UNFIT, ['QUARANTINE', 'DISCARD'])
})

test('a tela diz o que vai acontecer com a mercadoria', () => {
  assert.match(returnEffect('RESALEABLE', 'SELLABLE_STOCK'), /volta ao saldo disponível/)
  assert.match(returnEffect('UNFIT', 'QUARANTINE'), /não entra no saldo de venda/)
  assert.match(returnEffect('UNFIT', 'DISCARD'), /não entra no saldo de venda/)
})

test('trocar a condição leva junto um destino coerente', () => {
  assert.match(sales, /destination: defaultDestination\(condition\)/)
})

test('a devolução parte do item da venda, não do produto solto', () => {
  assert.match(sales, /sale_item_id: returning\.saleItemId/)
})

test('a recusa do servidor fica na tela com o formulário aberto', () => {
  const handler = sales.slice(sales.indexOf('const submitReturn'))
  const corpo = handler.slice(0, handler.indexOf('finally'))
  assert.ok(corpo.indexOf('catch') < corpo.indexOf("showToast('error'"))
  // Nada de fechar o formulário no catch: a recusa explica o limite.
  const doCatch = corpo.slice(corpo.indexOf('catch'))
  assert.doesNotMatch(doCatch, /setReturning\(null\)/)
})
