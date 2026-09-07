import type { SaleItem } from '../services/api'

/**
 * Sete garrafas iguais são uma linha, não sete.
 *
 * O servidor guarda cada inclusão como uma linha de venda, e isso está certo:
 * cada uma tem preço, desconto e histórico próprios. Na tela do caixa, porém,
 * sete linhas idênticas obrigam a pessoa a somar com o olho para conferir a
 * venda — e conferir é uma das quatro coisas que ela faz ali.
 *
 * O agrupamento é por produto **e preço unitário**: o mesmo item vendido a
 * preços diferentes na mesma venda continua em linhas separadas, porque aí a
 * diferença é real e esconder seria mentir sobre o total.
 */
export interface CartGroup {
  key: string
  productId: string
  productName: string
  sku: string
  unitPrice: number
  quantity: number
  discountAmount: number
  netTotal: number
  /** As linhas que compõem o grupo, na ordem em que entraram na venda. */
  items: SaleItem[]
}

export function groupCartItems(items: readonly SaleItem[]): CartGroup[] {
  const grupos = new Map<string, CartGroup>()
  for (const item of items) {
    const unitPrice = Number(item.unit_price) || 0
    const key = `${item.product_id}:${unitPrice}`
    const bruto = Number(item.gross_total) || unitPrice * Number(item.quantity)
    const desconto = Number(item.discount_amount) || 0
    const liquido = Number(item.net_total) || bruto - desconto
    const atual = grupos.get(key)
    if (atual) {
      atual.quantity += Number(item.quantity)
      atual.discountAmount += desconto
      atual.netTotal += liquido
      atual.items.push(item)
      continue
    }
    grupos.set(key, {
      key,
      productId: item.product_id,
      productName: item.product_name,
      sku: item.sku,
      unitPrice,
      quantity: Number(item.quantity),
      discountAmount: desconto,
      netTotal: liquido,
      items: [item],
    })
  }
  return Array.from(grupos.values())
}

/**
 * Qual linha recebe o `−`.
 *
 * Diminuir um grupo tira uma unidade da **última** inclusão: é a mais recente,
 * a que a pessoa acabou de errar. Se aquela linha tem uma unidade só, ela sai
 * inteira; o grupo continua existindo enquanto sobrar qualquer outra.
 */
export function itemToDecrease(group: CartGroup): SaleItem {
  return group.items[group.items.length - 1]
}

/** Qual linha recebe o `+`: a primeira, para a venda não crescer em linhas. */
export function itemToIncrease(group: CartGroup): SaleItem {
  return group.items[0]
}
