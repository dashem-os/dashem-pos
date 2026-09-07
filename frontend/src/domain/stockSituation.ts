/**
 * A situação de uma mercadoria, decidida em um lugar só.
 *
 * A lista, o resumo do topo e — quando existir — o cartão do PDV precisam dizer
 * a mesma coisa sobre o mesmo item. Enquanto cada tela aplicava a sua própria
 * comparação, o topo somava "sem estoque" com "abaixo do mínimo" e contava duas
 * vezes o item que era as duas coisas, enquanto o item em atenção não entrava
 * em conta nenhuma.
 *
 * Empatar com a referência não é estar bem: até existir ponto de reposição
 * calculado, a faixa de 25% acima dela é atenção, e a folga é dita em unidade
 * (ADR-033).
 */
export type StockSituation = 'SEM_ESTOQUE' | 'REPOR' | 'ATENCAO' | 'SEM_REFERENCIA' | 'SAUDAVEL'

export const FAIXA_DE_ATENCAO = 0.25

export interface SituationInput {
  quantity: number | string
  minimum_stock: number | string
  has_minimum: boolean
  is_out_of_stock: boolean
  is_low_stock: boolean
}

export function stockSituation(item: SituationInput): StockSituation {
  if (item.is_out_of_stock) return 'SEM_ESTOQUE'
  if (item.is_low_stock) return 'REPOR'
  if (!item.has_minimum) return 'SEM_REFERENCIA'
  const minimo = Number(item.minimum_stock)
  const folga = Number(item.quantity) - minimo
  if (minimo > 0 && folga / minimo <= FAIXA_DE_ATENCAO) return 'ATENCAO'
  return 'SAUDAVEL'
}

/** Quantas mercadorias exigem ação — cada uma contada uma vez. */
export function requiringAction(items: readonly SituationInput[]): number {
  return items.filter((item) => {
    const situacao = stockSituation(item)
    return situacao === 'SEM_ESTOQUE' || situacao === 'REPOR' || situacao === 'ATENCAO'
  }).length
}
