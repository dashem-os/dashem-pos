/**
 * Regras de apresentação para itens e lotes de catálogo no Channel Hub (S13.2).
 *
 * Mantém coerência estrita entre o estado observado e o rótulo exibido:
 * - O estado agregado do lote (PARTIAL/FAILED) não comprova tentativa individual.
 * - Itens PENDING fora de PROCESSING usam o contador individual:
 *   zero tentativas é "Pendente de envio"; contador positivo é "Tentativa sem confirmação".
 */

export interface ItemPresentationInput {
  status: string
  attempt_count?: number | null
  error_code?: string | null
}

export interface ItemPresentationOutput {
  label: string
  toneClass: string
}

export function getItemPresentationStatus(
  item: ItemPresentationInput,
  batchStatus: string
): ItemPresentationOutput {
  if (item.status === 'SUCCEEDED') {
    return { label: 'Confirmado', toneClass: 'text-state-success font-bold' }
  }
  if (item.status === 'FAILED') {
    if (item.error_code === 'TIMEOUT' || item.error_code === 'NETWORK_FAILURE') {
      return { label: 'Resposta não confirmada', toneClass: 'text-state-warning font-bold' }
    }
    return { label: 'Rejeitado pelo canal', toneClass: 'text-state-danger font-bold' }
  }
  if (batchStatus === 'PROCESSING') {
    return { label: 'Em execução', toneClass: 'text-dashem-strong font-bold' }
  }
  if ((item.attempt_count ?? 0) > 0) {
    return { label: 'Tentativa sem confirmação', toneClass: 'text-state-warning font-bold' }
  }
  return { label: 'Pendente de envio', toneClass: 'text-dashem-muted' }
}
