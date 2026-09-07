import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { countPreview } from '../src/domain/stockMovements.ts'

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

test('a ação de contar só aparece para quem tem a permissão de contar', () => {
  assert.match(inventory, /canCount = permissions\.includes\('inventory\.count'\)/)
  assert.match(inventory, /canCount \? <button/)
})
