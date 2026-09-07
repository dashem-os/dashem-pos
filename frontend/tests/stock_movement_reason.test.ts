import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import {
  DEFAULT_STOCK_REASONS, reasonForMovement,
} from '../src/domain/stockMovements.ts'

/**
 * Uma perda justificada como "Entrada de mercadoria" é um histórico que
 * contradiz o próprio movimento — e o histórico é o que alguém lê meses depois
 * para entender o que aconteceu com a mercadoria.
 */

test('o motivo sugerido acompanha a operação escolhida', () => {
  assert.equal(
    reasonForMovement(DEFAULT_STOCK_REASONS.PURCHASE, 'LOSS'),
    DEFAULT_STOCK_REASONS.LOSS,
  )
  assert.equal(
    reasonForMovement(DEFAULT_STOCK_REASONS.LOSS, 'ADJUSTMENT'),
    DEFAULT_STOCK_REASONS.ADJUSTMENT,
  )
  assert.equal(
    reasonForMovement(DEFAULT_STOCK_REASONS.ADJUSTMENT, 'RETURN'),
    DEFAULT_STOCK_REASONS.RETURN,
  )
})

test('o que a pessoa escreveu é dela e não é sobrescrito', () => {
  const escrito = 'Caixa amassada na descarga da terça'
  assert.equal(reasonForMovement(escrito, 'ADJUSTMENT'), escrito)
})

test('campo vazio recebe a sugestão da operação', () => {
  assert.equal(reasonForMovement('', 'LOSS'), DEFAULT_STOCK_REASONS.LOSS)
  assert.equal(reasonForMovement('   ', 'PURCHASE'), DEFAULT_STOCK_REASONS.PURCHASE)
})

test('cada operação tem a sua própria justificativa, sem repetir texto', () => {
  const textos = Object.values(DEFAULT_STOCK_REASONS)
  assert.equal(new Set(textos).size, textos.length)
  for (const texto of textos) assert.ok(texto.length > 3)
})

test('as duas telas de movimentação leem a mesma regra', () => {
  const root = join(import.meta.dirname, '..', 'src', 'components', 'management')
  for (const arquivo of ['CatalogManager.tsx', 'InventoryManager.tsx']) {
    const fonte = readFileSync(join(root, arquivo), 'utf8')
    assert.match(fonte, /reasonForMovement/, `${arquivo} não usa a regra compartilhada`)
    assert.doesNotMatch(
      fonte, /reason: ['"]Entrada de mercadoria['"]/i,
      `${arquivo} voltou a fixar o motivo de entrada`,
    )
  }
})
