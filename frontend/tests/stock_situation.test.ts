import assert from 'node:assert/strict'
import test from 'node:test'
import { requiringAction, stockSituation } from '../src/domain/stockSituation.ts'

const item = (quantity: number, minimum: number) => ({
  quantity,
  minimum_stock: minimum,
  has_minimum: minimum > 0,
  is_out_of_stock: quantity <= 0,
  is_low_stock: minimum > 0 && quantity <= minimum,
})

test('empatar com a referência não é estar saudável', () => {
  // O caso relatado: 15 unidades com referência 14 é folga de uma unidade.
  assert.equal(stockSituation(item(15, 14)), 'ATENCAO')
  assert.equal(stockSituation(item(14, 14)), 'REPOR')
  assert.equal(stockSituation(item(40, 10)), 'SAUDAVEL')
})

test('sem referência não se afirma saudável', () => {
  assert.equal(stockSituation(item(10, 0)), 'SEM_REFERENCIA')
})

test('sem estoque é sem estoque, mesmo sem referência', () => {
  assert.equal(stockSituation(item(0, 0)), 'SEM_ESTOQUE')
  assert.equal(stockSituation(item(0, 6)), 'SEM_ESTOQUE')
})

test('cada mercadoria exige ação uma vez', () => {
  // Quem está sem estoque também está abaixo da referência. Somar os dois
  // contadores dizia "3 produtos precisam de atenção" onde havia 3 — mas por
  // motivo errado: contava o mesmo item duas vezes e ignorava o em atenção.
  const acervo = [
    item(0, 6),   // sem estoque e abaixo da referência: um item
    item(10, 12), // repor
    item(15, 12), // atenção
    item(40, 10), // saudável
    item(9, 0),   // sem referência
  ]
  assert.equal(requiringAction(acervo), 3)
})
