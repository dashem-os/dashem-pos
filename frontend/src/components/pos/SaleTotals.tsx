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
  // Sete unidades da mesma bebida são sete itens vendidos, não uma linha.
  const unidades = items.reduce((total, item) => total + Number(item.quantity), 0)
  const grossTotal = Number(currentSale?.gross_total || 0)
  const discountTotal = Number(currentSale?.discount_total || 0)
  const netTotal = Number(currentSale?.net_total || 0)
  const isAwaitingPayment = currentSale?.status === 'AWAITING_PAYMENT'
  const isCashOpen = cashSession?.status === 'OPEN'
  // O botão não some nem apaga por falta de permissão: a ação existe na loja,
  // e quem não pode sozinho chama quem pode. Apagar o botão empurrava o
  // supervisor a operar no caixa alheio, que é pior do que pedir autorização.
  const canDiscount = permissions.includes('sale.discount')
  const canCancel = permissions.includes('sale.cancel')
  const canCheckout = permissions.includes('sale.checkout')

  return (
    <div className="bg-white border-t border-slate-200 pt-3 flex flex-col space-y-2.5 shrink-0 select-none">
      {/*
        Quantidade, total e a ação. Subtotal bruto e "desconto R$ 0,00" eram duas
        linhas para dizer que nada aconteceu: o desconto vira um link discreto, e
        o valor descontado só aparece quando existe (ADR-034).
      */}
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-500">{unidades} {unidades === 1 ? 'item' : 'itens'}</span>
        {discountTotal > 0 && (
          <span className="font-bold text-emerald-600">− {formatCurrency(discountTotal)} de desconto</span>
        )}
      </div>

      <div className="flex items-baseline justify-between border-t border-slate-100 pt-2">
        <div>
          <span className="block text-[11px] font-extrabold uppercase tracking-wider text-slate-400">
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

      {/*
        Uma ação dominante, com o valor dentro dela: "Receber R$ 134,00" é a
        frase que o operador diz em voz alta. Cancelar e descontar existem, e
        ficam abaixo, sem disputar tamanho com ela.
      */}
      <button
        type="button"
        onClick={openPaymentModal}
        disabled={!hasItems || !isCashOpen || actionLoading || !canCheckout}
        className={`flex h-14 w-full items-center justify-center gap-2 rounded-xl text-base font-black shadow-sm transition-all active:scale-[0.98] ${
          hasItems && isCashOpen && canCheckout
            ? isAwaitingPayment
              ? 'bg-amber-600 text-white shadow-amber-600/30 hover:bg-amber-500'
              : 'bg-rose-600 text-white shadow-rose-600/30 hover:bg-rose-500'
            : 'cursor-not-allowed bg-slate-200 text-slate-400'
        }`}
      >
        <span>
          {isAwaitingPayment ? 'Retomar pagamento' : 'Receber'}
          {hasItems && ` ${formatCurrency(netTotal)}`}
        </span>
        <ArrowRight className="h-4 w-4" />
      </button>

      <div className="flex items-center justify-between text-xs">
        <button
          type="button"
          onClick={openDiscountModal}
          disabled={!hasItems || !isCashOpen || actionLoading}
          title={canDiscount ? 'Aplicar desconto' : 'Precisa de autorização do supervisor'}
          className="flex items-center gap-1 font-bold text-emerald-700 disabled:opacity-30"
        >
          <Tag className="h-3 w-3" />
          <span>{discountTotal > 0 ? 'Editar desconto' : 'Aplicar desconto'}</span>
        </button>
        <button
          type="button"
          onClick={openCancelModal}
          disabled={!hasItems || !isCashOpen || actionLoading}
          title={canCancel ? 'Cancelar venda' : 'Precisa de autorização do supervisor'}
          className="flex items-center gap-1 font-bold text-slate-500 hover:text-rose-600 disabled:opacity-30"
        >
          <Ban className="h-3 w-3" />
          <span>Cancelar venda</span>
        </button>
      </div>
    </div>
  )
}
