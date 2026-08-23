import React from 'react'
import { Plus, Minus, Trash2, Edit3 } from 'lucide-react'
import { SaleItem } from '../../services/api'
import { usePos } from '../../context/PosContext'
import { formatCurrency, formatQuantity } from '../../utils/format'

interface CartItemProps {
  item: SaleItem
  index: number
}

export const CartItem: React.FC<CartItemProps> = ({ item, index }) => {
  const { updateItemQuantity, removeItemFromCart, openQuantityModal, actionLoading, permissions } = usePos()
  const canEdit = permissions.includes('sale.item.update')

  const handleDecrease = () => {
    if (item.quantity > 1) {
      updateItemQuantity(item.id, item.quantity - 1)
    } else {
      removeItemFromCart(item.id)
    }
  }

  const handleIncrease = () => {
    updateItemQuantity(item.id, item.quantity + 1)
  }

  const unitPrice = Number(item.unit_price) || 0
  const grossTotal = Number(item.gross_total) || unitPrice * item.quantity
  const discountAmount = Number(item.discount_amount) || 0
  const netTotal = Number(item.net_total) || grossTotal - discountAmount

  return (
    <div className="p-3 rounded-xl bg-white border border-slate-200/80 hover:border-slate-300 transition-all flex flex-col space-y-2 select-none">
      {/* Top Row: Title, SKU, Unit Price, Trash */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start space-x-2 flex-1 min-w-0">
          <span className="w-5 h-5 rounded-md bg-slate-100 text-slate-500 text-[11px] font-bold flex items-center justify-center shrink-0 mt-0.5">
            {index + 1}
          </span>
          <div className="min-w-0 flex-1">
            <h4 className="text-xs sm:text-sm font-bold text-slate-900 leading-snug line-clamp-2">
              {item.product_name}
            </h4>
            <div className="text-[11px] text-slate-400 font-mono flex items-center space-x-2 mt-0.5">
              <span>{item.sku}</span>
              <span>•</span>
              <span className="text-slate-600 font-semibold">{formatCurrency(unitPrice)} / un</span>
            </div>
          </div>
        </div>

        {/* Remove Button */}
        <button
          onClick={() => removeItemFromCart(item.id)}
          disabled={actionLoading || !canEdit}
          aria-label="Remover item"
          className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-rose-600 hover:bg-rose-50 active:scale-95 transition-all shrink-0"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Bottom Row: Touch Quantity Stepper & Line Subtotal */}
      <div className="flex items-center justify-between pt-1.5 border-t border-slate-100">
        {/* Quantity Controls (Touch Targets >= 44x44px) */}
        <div className="flex items-center space-x-1 bg-slate-100 p-0.5 rounded-xl border border-slate-200">
          <button
            onClick={handleDecrease}
            disabled={actionLoading || !canEdit}
            className="w-8 h-8 rounded-lg bg-white hover:bg-slate-50 active:bg-slate-200 text-slate-700 flex items-center justify-center text-sm font-bold transition-all disabled:opacity-40 shadow-xs"
          >
            <Minus className="w-3.5 h-3.5" />
          </button>

          <button
            onClick={() => openQuantityModal(item)}
            disabled={!canEdit}
            className="px-2.5 h-8 hover:bg-white rounded-lg text-center font-black text-xs text-slate-900 flex items-center justify-center space-x-1 transition-all"
            title="Toque para digitar quantidade"
          >
            <span>{formatQuantity(item.quantity)}</span>
            <Edit3 className="w-2.5 h-2.5 text-slate-400 ml-0.5" />
          </button>

          <button
            onClick={handleIncrease}
            disabled={actionLoading || !canEdit}
            className="w-8 h-8 rounded-lg bg-white hover:bg-slate-50 active:bg-slate-200 text-slate-700 flex items-center justify-center text-sm font-bold transition-all disabled:opacity-40 shadow-xs"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Line Total Calculation */}
        <div className="text-right">
          {discountAmount > 0 && (
            <span className="text-[10px] text-emerald-600 font-bold block">
              - {formatCurrency(discountAmount)} desc.
            </span>
          )}
          <span className="text-sm sm:text-base font-black text-slate-900">
            {formatCurrency(netTotal)}
          </span>
        </div>
      </div>
    </div>
  )
}
