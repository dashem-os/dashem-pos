import React from 'react'
import { Plus, Minus, Trash2, Edit3 } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { formatCurrency, formatQuantity } from '../../utils/format'
import { CartGroup, itemToDecrease, itemToIncrease } from '../../domain/cartGrouping'

interface CartItemProps {
  group: CartGroup
}

/**
 * Uma linha da venda: produto, quantidade e total.
 *
 * A conferência é uma das quatro coisas que o operador faz no caixa, e ela se
 * faz com três informações. Número de ordem, SKU e preço unitário saíram da
 * hierarquia principal: o SKU aparece pequeno, para desempatar homônimos, e o
 * preço unitário só quando há mais de uma unidade — com uma, o total já é ele.
 */
export const CartItem: React.FC<CartItemProps> = ({ group }) => {
  const { updateItemQuantity, removeItemFromCart, openQuantityModal, actionLoading, permissions } = usePos()
  const canEdit = permissions.includes('sale.item.update')

  const handleDecrease = () => {
    const alvo = itemToDecrease(group)
    if (Number(alvo.quantity) > 1) updateItemQuantity(alvo.id, Number(alvo.quantity) - 1)
    else removeItemFromCart(alvo.id)
  }

  const handleIncrease = () => {
    const alvo = itemToIncrease(group)
    updateItemQuantity(alvo.id, Number(alvo.quantity) + 1)
  }

  // Remover o grupo remove tudo o que ele representa: deixar linhas para trás
  // faria a mercadoria reaparecer com um total menor, sem explicação.
  const handleRemove = () => {
    for (const item of group.items) removeItemFromCart(item.id)
  }

  return (
    <div className="select-none rounded-xl border border-slate-200/80 bg-white p-3 transition-all hover:border-slate-300">
      {/*
        A coluna da venda é estreita. Nome em cima, com espaço para caber
        inteiro; controles embaixo, onde o dedo alcança sem apertar o vizinho.
      */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="line-clamp-2 text-sm font-bold leading-snug text-slate-900">{group.productName}</h4>
          <p className="mt-0.5 truncate text-[11px] text-slate-400">
            <span className="font-mono">{group.sku}</span>
            {group.quantity > 1 && <span className="ml-2">{formatCurrency(group.unitPrice)} cada</span>}
          </p>
        </div>
        <button
          onClick={handleRemove}
          disabled={actionLoading || !canEdit}
          aria-label={`Remover ${group.productName}`}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-300 transition-all hover:bg-rose-50 hover:text-rose-600 active:scale-95"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
      <div className="flex items-center gap-1 rounded-xl border border-slate-200 bg-slate-100 p-0.5">
        <button
          onClick={handleDecrease}
          disabled={actionLoading || !canEdit}
          aria-label={`Diminuir ${group.productName}`}
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-slate-700 shadow-xs transition-all hover:bg-slate-50 active:bg-slate-200 disabled:opacity-40"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => openQuantityModal(itemToIncrease(group))}
          disabled={!canEdit}
          title="Toque para digitar a quantidade"
          className="flex h-8 items-center justify-center gap-1 rounded-lg px-2.5 text-xs font-black text-slate-900 transition-all hover:bg-white"
        >
          <span>{formatQuantity(group.quantity)}</span>
          <Edit3 className="h-2.5 w-2.5 text-slate-400" />
        </button>
        <button
          onClick={handleIncrease}
          disabled={actionLoading || !canEdit}
          aria-label={`Aumentar ${group.productName}`}
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-slate-700 shadow-xs transition-all hover:bg-slate-50 active:bg-slate-200 disabled:opacity-40"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="text-right">
        {group.discountAmount > 0 && (
          <span className="block text-[11px] font-bold text-emerald-600">− {formatCurrency(group.discountAmount)}</span>
        )}
        <span className="text-base font-black text-slate-900">{formatCurrency(group.netTotal)}</span>
      </div>
      </div>
    </div>
  )
}
