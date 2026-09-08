/**
 * O aviso de disponibilidade, antes de o item entrar na venda.
 *
 * O ADR-032 entregou a recusa: quem tenta vender o que não tem é barrado pelo
 * servidor antes do pagamento. O que faltava era o degrau anterior — a pessoa
 * no balcão descobrir que está no fim **enquanto** monta a venda, e não quando
 * o cliente já está com o cartão na mão.
 *
 * A conta é a do plano corretivo, etapa 3.1:
 *
 *     projetado = disponível − quantidade pedida
 *
 * e o que o operador vê depende só dela:
 *
 * | projetado | o que aparece                        |
 * |-----------|--------------------------------------|
 * | < 0       | bloqueia: "Indisponível. Disponível: N" |
 * | = 0       | "Última unidade disponível"          |
 * | ≤ 2       | "Crítico — restarão N un"            |
 * | > 2       | nada. Silêncio é informação          |
 *
 * **Isto não é uma segunda regra de estoque.** O `disponível` vem da projeção
 * do servidor, que é quem decide; aqui só se antecipa a resposta para a recusa
 * não chegar depois de uma ida e volta. Se a tela estiver desatualizada, o
 * servidor recusa do mesmo jeito — e é ele que vale.
 *
 * O limite de "crítico" é 2, o número que o próprio plano usa no exemplo de
 * nove disponíveis. É uma escolha de produto, e está aqui num lugar só para
 * poder ser mudada num lugar só.
 */

export const LIMITE_CRITICO = 2

export type NivelDeAviso = 'BLOQUEIO' | 'ULTIMA' | 'CRITICO' | 'SILENCIO'

export interface AvisoDeDisponibilidade {
  nivel: NivelDeAviso
  /** O que a tela mostra. Vazio quando o nível é silêncio. */
  mensagem: string
  projetado: number
}

export interface PedidoDeInclusao {
  /** O disponível que o servidor projetou: prateleira menos o já prometido. */
  disponivel: number | null | undefined
  /** Quantas unidades a pessoa está pedindo agora. */
  pedido: number
  /** A unidade da mercadoria, para o número não ficar sem grandeza. */
  unidade?: string
}

export function avisoDeDisponibilidade({
  disponivel, pedido, unidade = 'un',
}: PedidoDeInclusao): AvisoDeDisponibilidade {
  // Mercadoria que não controla estoque não tem disponível, e uma tela que
  // inventa zero para ela bloquearia a venda de um serviço.
  if (disponivel === null || disponivel === undefined || Number.isNaN(Number(disponivel))) {
    return { nivel: 'SILENCIO', mensagem: '', projetado: Number.NaN }
  }

  const atual = Number(disponivel)
  const projetado = atual - Number(pedido)

  if (projetado < 0) {
    return {
      nivel: 'BLOQUEIO',
      mensagem: `Indisponível. Disponível: ${formatar(atual)} ${unidade}`,
      projetado,
    }
  }
  if (projetado === 0) {
    return { nivel: 'ULTIMA', mensagem: 'Última unidade disponível', projetado }
  }
  if (projetado <= LIMITE_CRITICO) {
    return {
      nivel: 'CRITICO',
      mensagem: `Crítico — restarão ${formatar(projetado)} ${unidade}`,
      projetado,
    }
  }
  return { nivel: 'SILENCIO', mensagem: '', projetado }
}

/** Quantidade fracionada existe (quilo, litro); inteiro não vira "3,00". */
function formatar(valor: number): string {
  return Number.isInteger(valor) ? String(valor) : valor.toFixed(3).replace(/\.?0+$/, '').replace('.', ',')
}
