/**
 * O motivo de uma movimentação vai para o histórico, ao lado do tipo.
 *
 * Enquanto o motivo não acompanhava o tipo, trocar para "Perda" e confirmar
 * gravava uma perda justificada como "Entrada de Mercadoria": livro correto no
 * saldo e contraditório na explicação — que é justamente o que alguém lê meses
 * depois para entender o que aconteceu com a mercadoria.
 *
 * Isto vive aqui, e não dentro de uma tela, porque duas superfícies movimentam
 * estoque hoje e a próxima não deve precisar redescobrir a regra.
 */

export type StockMovementType = 'PURCHASE' | 'LOSS' | 'RETURN' | 'ADJUSTMENT'

export const DEFAULT_STOCK_REASONS: Record<StockMovementType, string> = {
  PURCHASE: 'Entrada de mercadoria',
  LOSS: 'Perda, avaria ou vencimento',
  RETURN: 'Devolução de cliente',
  ADJUSTMENT: 'Diferença apurada em conferência',
}

/**
 * O motivo que a operação escolhida pede, preservando o que a pessoa escreveu.
 *
 * Só o texto que o próprio formulário sugeriu é substituído. Quem digitou a
 * própria justificativa não a perde ao corrigir o tipo do movimento.
 */
export function reasonForMovement(current: string, next: StockMovementType): string {
  const typed = current.trim()
  const suggested = Object.values(DEFAULT_STOCK_REASONS).includes(typed)
  return !typed || suggested ? DEFAULT_STOCK_REASONS[next] : current
}


/**
 * A frase que a pessoa lê antes de confirmar uma contagem.
 *
 * Ela não é autoridade: ao confirmar, o servidor verifica se o saldo mudou. Mas
 * é o que permite decidir sem fazer a conta de cabeça, e é onde a diferença fica
 * visível antes de virar movimento.
 */
export function countPreview(counted: number, current: number, unit = 'un'): string {
  const difference = counted - current
  const found = `Você contou ${counted} ${unit}. O sistema registra ${current} ${unit}.`
  if (difference === 0) return `${found} Confere — a conferência fica registrada sem movimentar estoque.`
  const sign = difference > 0 ? '+' : '−'
  return `${found} Diferença: ${sign}${Math.abs(difference)} ${unit}.`
}


/**
 * Mercadoria imprópria não volta ao saldo vendável.
 *
 * A condição é o que a pessoa observa; o destino é a consequência. Deixar as
 * duas soltas permitiria dizer "está boa" e mandar para o descarte, ou o
 * contrário — payload ambíguo que o servidor recusa. Aqui a escolha da condição
 * já leva o destino coerente, e o único caso com escolha real é a mercadoria
 * imprópria: quarentena enquanto se decide, ou descarte.
 */
export type ReturnCondition = 'RESALEABLE' | 'UNFIT'
export type ReturnDestination = 'SELLABLE_STOCK' | 'QUARANTINE' | 'DISCARD'

export const DESTINATIONS_FOR_CONDITION: Record<ReturnCondition, ReturnDestination[]> = {
  RESALEABLE: ['SELLABLE_STOCK'],
  UNFIT: ['QUARANTINE', 'DISCARD'],
}

export function defaultDestination(condition: ReturnCondition): ReturnDestination {
  return DESTINATIONS_FOR_CONDITION[condition][0]
}

/** A frase que diz o que vai acontecer com a mercadoria ao confirmar. */
export function returnEffect(condition: ReturnCondition, destination: ReturnDestination): string {
  if (destination === 'SELLABLE_STOCK') return 'A mercadoria volta ao saldo disponível para venda.'
  if (destination === 'QUARANTINE') return 'A mercadoria fica separada e não entra no saldo de venda.'
  return 'A mercadoria é descartada e não entra no saldo de venda.'
}
