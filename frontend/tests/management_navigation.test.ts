import assert from 'node:assert/strict'
import test from 'node:test'

import type { ContribuicaoDeNavegacao } from '../src/domain/managementNavigation.ts'
import {
  acharArea, areaDoModulo, ehConteudoDaEntrada, enderecoDe,
  montarAreas, precisaNormalizar, resolverEstado,
} from '../src/domain/managementNavigation.ts'

/**
 * A UX-00 mediu seis atritos na navegação da Gestão. Quatro deles nascem da
 * mesma causa: o módulo aberto era estado do componente e a URL era só um
 * espelho. Estes testes fixam a decisão que os corrige — a URL é o estado — e
 * fixam também o que já funcionava e não pode regredir: link direto e atualizar.
 *
 * As áreas não são constantes deste arquivo nem do componente: vêm da malha,
 * como a palavra do nicho veio na 088. Os dados abaixo têm a forma que a
 * migração 090 grava.
 */

function contribuicao(
  chave: string, label: string, area: string, rotuloDaArea: string, ordemDaArea: number, ordem: number,
  extra: Record<string, unknown> = {},
): ContribuicaoDeNavegacao {
  return {
    surface: 'MANAGEMENT_NAV',
    contribution_key: chave,
    implementation_key: chave,
    label,
    sort_order: ordem,
    metadata_json: {
      area: { key: area, label: rotuloDaArea, order: ordemDaArea },
      description: `frase de ${chave}`,
      ...extra,
    },
  }
}

const MALHA: ContribuicaoDeNavegacao[] = [
  {
    surface: 'MANAGEMENT_NAV', contribution_key: 'overview', implementation_key: 'overview',
    label: 'Visão geral', sort_order: 10, metadata_json: { placement: 'ENTRY' },
  },
  contribuicao('sales', 'Vendas', 'OPERACAO', 'Operação', 1, 20),
  contribuicao('cash', 'Caixas', 'OPERACAO', 'Operação', 1, 30),
  contribuicao('inventory', 'Estoques', 'MERCADORIAS', 'Mercadorias', 2, 80),
  contribuicao('products', 'Produtos e preços', 'MERCADORIAS', 'Mercadorias', 2, 60),
  contribuicao('subscription', 'Plano e solicitações', 'ADMINISTRACAO', 'Administração', 7, 120),
]

test('a visão geral é conteúdo da entrada, não a oitava área', () => {
  const areas = montarAreas(MALHA)
  assert.deepEqual(areas.map((area) => area.chave), ['OPERACAO', 'MERCADORIAS', 'ADMINISTRACAO'])
  assert.ok(ehConteudoDaEntrada(MALHA[0]))
  assert.ok(!areas.some((area) => area.cards.some((card) => card.id === 'overview')))
})

test('as áreas saem na ordem declarada pela malha, e os cards na ordem do mapa', () => {
  const areas = montarAreas(MALHA)
  assert.deepEqual(areas.map((area) => area.ordem), [1, 2, 7])
  const mercadorias = acharArea(areas, 'MERCADORIAS')
  assert.deepEqual(mercadorias?.cards.map((card) => card.id), ['products', 'inventory'])
})

test('cada card carrega a frase de tarefa que a malha declara', () => {
  const areas = montarAreas(MALHA)
  const vendas = acharArea(areas, 'OPERACAO')?.cards[0]
  assert.equal(vendas?.descricao, 'frase de sales')
})

test('contribuição sem área declarada não vira card — não se inventa destino', () => {
  const semArea: ContribuicaoDeNavegacao = {
    surface: 'MANAGEMENT_NAV', contribution_key: 'orfa', implementation_key: 'orfa',
    label: 'Órfã', sort_order: 999, metadata_json: {},
  }
  const areas = montarAreas([...MALHA, semArea])
  assert.ok(!areas.some((area) => area.cards.some((card) => card.id === 'orfa')))
})

test('o endereço é o estado: entrada, área e módulo têm cada um o seu', () => {
  assert.equal(enderecoDe({ tipo: 'ENTRADA' }), '/manage')
  assert.equal(enderecoDe({ tipo: 'AREA', area: 'MERCADORIAS' }), '/manage?area=MERCADORIAS')
  assert.equal(
    enderecoDe({ tipo: 'MODULO', area: 'MERCADORIAS', modulo: 'inventory' }),
    '/manage?area=MERCADORIAS&module=inventory',
  )
})

test('link direto abre o módulo, e continua abrindo depois de atualizar', () => {
  const areas = montarAreas(MALHA)
  const estado = resolverEstado('?area=MERCADORIAS&module=inventory', areas)
  assert.deepEqual(estado, { tipo: 'MODULO', area: 'MERCADORIAS', modulo: 'inventory' })
  // Atualizar é resolver o mesmo endereço de novo: precisa dar o mesmo estado.
  assert.deepEqual(resolverEstado(enderecoDe(estado).replace('/manage', ''), areas), estado)
})

test('o link legado `?module=x` continua funcionando, deduzindo a área', () => {
  const areas = montarAreas(MALHA)
  const estado = resolverEstado('?module=devices'.replace('devices', 'inventory'), areas)
  assert.deepEqual(estado, { tipo: 'MODULO', area: 'MERCADORIAS', modulo: 'inventory' })
  assert.equal(areaDoModulo(areas, 'inventory')?.chave, 'MERCADORIAS')
})

test('o link legado é reescrito no lugar, para o voltar não cair em laço', () => {
  const areas = montarAreas(MALHA)
  const estado = resolverEstado('?module=inventory', areas)
  assert.ok(precisaNormalizar('?module=inventory', estado))
  assert.ok(!precisaNormalizar('?area=MERCADORIAS&module=inventory', estado))
  assert.ok(!precisaNormalizar('', { tipo: 'ENTRADA' }))
})

test('destino desconhecido não cai calado na visão geral', () => {
  const areas = montarAreas(MALHA)
  assert.deepEqual(resolverEstado('?module=fornecedores', areas), { tipo: 'INDISPONIVEL', pedido: 'fornecedores' })
  assert.deepEqual(resolverEstado('?area=NAO_EXISTE', areas), { tipo: 'INDISPONIVEL', pedido: 'NAO_EXISTE' })
})

test('destino não autorizado é indisponível, não tela em branco', () => {
  // O servidor só projeta o que a pessoa pode ver: um perfil restrito recebe
  // uma malha menor, e o que ficou de fora precisa dizer que ficou de fora.
  const restrita = MALHA.filter((item) => item.implementation_key !== 'subscription')
  const areas = montarAreas(restrita)
  assert.deepEqual(resolverEstado('?module=subscription', areas), { tipo: 'INDISPONIVEL', pedido: 'subscription' })
  assert.ok(!areas.some((area) => area.chave === 'ADMINISTRACAO'))
})

test('perfil restrito não ganha área vazia para completar sete itens', () => {
  const areas = montarAreas(MALHA.filter((item) => item.implementation_key === 'sales' || item.contribution_key === 'overview'))
  assert.equal(areas.length, 1)
  assert.deepEqual(areas[0].cards.map((card) => card.id), ['sales'])
})
