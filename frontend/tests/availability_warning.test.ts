import assert from 'node:assert/strict'
import test from 'node:test'

import { LIMITE_CRITICO, avisoDeDisponibilidade } from '../src/domain/availabilityWarning.ts'

/**
 * A escada de avisos do PDV, com os números do próprio plano corretivo: nove
 * disponíveis, e o que o operador vê a cada pedido.
 *
 * O ADR-032 já entregou a recusa antes do pagamento. O que estes casos fixam é
 * o degrau anterior — descobrir que está no fim enquanto se monta a venda, e
 * não quando o cliente já está com o cartão na mão.
 */

test('com nove disponíveis, sete pedidos avisam que restarão dois', () => {
  const aviso = avisoDeDisponibilidade({ disponivel: 9, pedido: 7 })
  assert.equal(aviso.nivel, 'CRITICO')
  assert.equal(aviso.projetado, 2)
  assert.match(aviso.mensagem, /restarão 2 un/)
})

test('a última unidade é dita como última, não como crítica', () => {
  const aviso = avisoDeDisponibilidade({ disponivel: 9, pedido: 9 })
  assert.equal(aviso.nivel, 'ULTIMA')
  assert.equal(aviso.projetado, 0)
  assert.equal(aviso.mensagem, 'Última unidade disponível')
})

test('pedir mais do que existe bloqueia e diz quanto existe', () => {
  const aviso = avisoDeDisponibilidade({ disponivel: 9, pedido: 10 })
  assert.equal(aviso.nivel, 'BLOQUEIO')
  assert.equal(aviso.projetado, -1)
  assert.match(aviso.mensagem, /Indisponível\. Disponível: 9 un/)
})

test('folga confortável não diz nada — silêncio é informação', () => {
  const aviso = avisoDeDisponibilidade({ disponivel: 9, pedido: 1 })
  assert.equal(aviso.nivel, 'SILENCIO')
  assert.equal(aviso.mensagem, '')
  assert.equal(aviso.projetado, 8)
})

test('o limite do crítico é o do plano, e vale nos dois lados', () => {
  assert.equal(avisoDeDisponibilidade({ disponivel: 100, pedido: 100 - LIMITE_CRITICO }).nivel, 'CRITICO')
  assert.equal(avisoDeDisponibilidade({ disponivel: 100, pedido: 100 - LIMITE_CRITICO - 1 }).nivel, 'SILENCIO')
})

test('quem não controla estoque não tem disponível, e não é bloqueado', () => {
  // Taxa de entrega é serviço: inventar zero para ela impediria vender o que
  // não tem prateleira nenhuma.
  assert.equal(avisoDeDisponibilidade({ disponivel: null, pedido: 3 }).nivel, 'SILENCIO')
  assert.equal(avisoDeDisponibilidade({ disponivel: undefined, pedido: 3 }).nivel, 'SILENCIO')
})

test('quantidade fracionada não vira número inteiro mentiroso', () => {
  const aviso = avisoDeDisponibilidade({ disponivel: 2.5, pedido: 1, unidade: 'kg' })
  assert.equal(aviso.nivel, 'CRITICO')
  assert.match(aviso.mensagem, /restarão 1,5 kg/)
})

test('estoque zerado bloqueia qualquer pedido, e diz zero', () => {
  const aviso = avisoDeDisponibilidade({ disponivel: 0, pedido: 1, unidade: 'un' })
  assert.equal(aviso.nivel, 'BLOQUEIO')
  assert.match(aviso.mensagem, /Disponível: 0 un/)
})
