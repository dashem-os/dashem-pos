import React from 'react'
import { Tag, ArrowRight, Ban, Clock } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { formatCurrency } from '../../utils/format'

export const SaleTotals: React.FC = () => {
  const {
    currentSale,
    openPaymentModal,
    openDiscountModal,
    openCancelModal,
    actionLoading,
    cashSession,
    permissions
  } = usePos()

  const items = currentSale?.items || []
  const hasItems = items.length > 0
  const grossTotal = Number(currentSale?.gross_total || 0)
  const discountTotal = Number(currentSale?.discount_total || 0)
  const netTotal = Number(currentSale?.net_total || 0)
  const isAwaitingPayment = currentSale?.status === 'AWAITING_PAYMENT'
  const isCashOpen = cashSession?.status === 'OPEN'
  const canDiscount = permissions.includes('sale.discount')
  const canCancel = permissions.includes('sale.cancel')
  const canCheckout = permissions.includes('sale.checkout')

  return (
    <div className="bg-white border-t border-slate-200 pt-3 flex flex-col space-y-2.5 shrink-0 select-none">
      {/* Subtotal & Discount Breakdown */}
      <div className="space-y-1 text-xs">
        <div className="flex items-center justify-between text-slate-500">
          <span>Subtotal Bruto ({items.length} {items.length === 1 ? 'item' : 'itens'})</span>
          <span className="font-semibold text-slate-700">{formatCurrency(grossTotal)}</span>
        </div>

        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={openDiscountModal}
            disabled={!hasItems || !isCashOpen || actionLoading || !canDiscount}
            title={canDiscount ? 'Aplicar desconto' : 'Seu perfil não possui permissão para desconto'}
            className="flex items-center space-x-1 font-bold text-emerald-600 hover:text-emerald-700 disabled:opacity-40"
          >
            <Tag className="w-3 h-3" />
            <span>{discountTotal > 0 ? 'Editar Desconto' : 'Aplicar Desconto'}</span>
          </button>
          <span className="font-bold text-emerald-600">
            {discountTotal > 0 ? `- ${formatCurrency(discountTotal)}` : formatCurrency(0)}
          </span>
        </div>
      </div>

      {/* Main Net Total Highlight */}
      <div className="pt-2 border-t border-slate-100 flex items-baseline justify-between">
        <div>
          <span className="text-[11px] uppercase font-extrabold tracking-wider text-slate-400 block">
            Total a Pagar
          </span>
          {isAwaitingPayment && (
            <span className="text-[10px] font-bold text-amber-600 uppercase flex items-center space-x-1">
              <Clock className="w-3 h-3" />
              <span>Aguardando Pagamento</span>
            </span>
          )}
        </div>
        <div className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
          {formatCurrency(netTotal)}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="grid grid-cols-4 gap-2 pt-1">
        {/* Cancel Sale Button */}
        <button
          type="button"
          onClick={openCancelModal}
          disabled={!hasItems || !isCashOpen || actionLoading || !canCancel}
          className="col-span-1 h-13 rounded-xl bg-slate-100 hover:bg-rose-50 hover:text-rose-600 text-slate-500 border border-slate-200 flex flex-col items-center justify-center text-xs font-bold transition-all disabled:opacity-30 active:scale-95"
          title="Cancelar venda atual"
        >
          <Ban className="w-4 h-4 mb-0.5" />
          <span>Cancelar</span>
        </button>

        {/* Primary Checkout Button */}
        <button
          type="button"
          onClick={openPaymentModal}
          disabled={!hasItems || !isCashOpen || actionLoading || !canCheckout}
          className={`col-span-3 h-13 rounded-xl font-black text-sm sm:text-base flex items-center justify-center space-x-2 transition-all shadow-sm active:scale-[0.98] ${
            hasItems && isCashOpen && canCheckout
              ? isAwaitingPayment
                ? 'bg-amber-600 hover:bg-amber-500 text-white shadow-amber-600/30'
                : 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-600/30'
              : 'bg-slate-200 text-slate-400 cursor-not-allowed'
          }`}
        >
          <span>{isAwaitingPayment ? 'RETOMAR PAGAMENTO' : 'RECEBER / PAGAR'}</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
