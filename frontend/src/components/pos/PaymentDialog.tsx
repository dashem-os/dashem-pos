import React, { useState, useEffect } from 'react'
import { Modal } from '../common/Modal'
import { usePos } from '../../context/PosContext'
import { Banknote, QrCode, CreditCard, Check, Split, ArrowLeft } from 'lucide-react'
import { Payment } from '../../services/api'
import { formatCurrency } from '../../utils/format'

export const PaymentDialog: React.FC = () => {
  const {
    isPaymentModalOpen,
    closePaymentModal,
    currentSale,
    confirmedPayments,
    processPayment,
    actionLoading
  } = usePos()

  const [method, setMethod] = useState<Payment['method']>('CASH')
  const [tenderedInput, setTenderedInput] = useState<string>('')
  const [customAmountInput, setCustomAmountInput] = useState<string>('')
  const [isSplitMode, setIsSplitMode] = useState<boolean>(false)

  const netTotal = Number(currentSale?.net_total || 0)
  const totalPaid = confirmedPayments.reduce((acc, p) => acc + Number(p.amount), 0)
  const remainingBalance = Math.max(0, netTotal - totalPaid)

  const activeAmountToPay = isSplitMode && customAmountInput ? parseFloat(customAmountInput) || 0 : remainingBalance

  const tenderedAmount = parseFloat(tenderedInput || '0')
  const changeAmount = method === 'CASH' && tenderedAmount > activeAmountToPay ? tenderedAmount - activeAmountToPay : 0

  useEffect(() => {
    if (isPaymentModalOpen) {
      setTenderedInput(remainingBalance.toFixed(2))
      setCustomAmountInput(remainingBalance.toFixed(2))
      setIsSplitMode(false)
    }
  }, [isPaymentModalOpen, remainingBalance])

  const handleQuickTender = (amt: number) => {
    setTenderedInput(amt.toFixed(2))
  }

  const handleQuickAddTender = (amt: number) => {
    const current = parseFloat(tenderedInput || '0') || 0
    setTenderedInput((current + amt).toFixed(2))
  }

  const handleConfirmPayment = async () => {
    if (actionLoading || activeAmountToPay <= 0) return

    const tend = method === 'CASH' ? tenderedAmount : undefined
    const completed = await processPayment(method, activeAmountToPay, tend)

    if (completed) {
      closePaymentModal()
    } else {
      setCustomAmountInput('')
    }
  }

  return (
    <Modal
      isOpen={isPaymentModalOpen}
      onClose={closePaymentModal}
      title="Receber Pagamento"
      subtitle={`Venda #${currentSale?.id?.slice(0, 8)}`}
      maxWidth="md"
    >
      <div className="flex flex-col space-y-4">
        {/* Financial Summary Card */}
        <div className="grid grid-cols-3 gap-2 p-3 bg-slate-50 rounded-2xl border border-slate-200 text-center select-none">
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">Total da Venda</span>
            <span className="text-base sm:text-lg font-black text-slate-900">{formatCurrency(netTotal)}</span>
          </div>

          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-600 block">Já Pago</span>
            <span className="text-base sm:text-lg font-black text-emerald-600">{formatCurrency(totalPaid)}</span>
          </div>

          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-rose-600 block">Restante a Pagar</span>
            <span className="text-base sm:text-lg font-black text-rose-600">{formatCurrency(remainingBalance)}</span>
          </div>
        </div>

        {/* Payment Method Selector */}
        <div>
          <div className="flex items-center justify-between mb-1.5 px-0.5">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Forma de Pagamento
            </span>
            <button
              type="button"
              onClick={() => setIsSplitMode(!isSplitMode)}
              className="text-xs font-bold text-rose-600 hover:text-rose-700 flex items-center space-x-1"
            >
              <Split className="w-3 h-3" />
              <span>{isSplitMode ? 'Pagamento Total' : 'Pagamento Dividido (Split)'}</span>
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { id: 'CASH', label: 'Dinheiro', icon: Banknote, color: 'text-emerald-600' },
              { id: 'PIX', label: 'PIX', icon: QrCode, color: 'text-teal-600' },
              { id: 'DEBIT_CARD', label: 'Cartão Débito', icon: CreditCard, color: 'text-sky-600' },
              { id: 'CREDIT_CARD', label: 'Cartão Crédito', icon: CreditCard, color: 'text-purple-600' }
            ].map((pm) => {
              const Icon = pm.icon
              const isSelected = method === pm.id
              return (
                <button
                  key={pm.id}
                  type="button"
                  onClick={() => setMethod(pm.id as any)}
                  className={`h-16 p-2 rounded-xl flex flex-col items-center justify-center space-y-1 transition-all border text-center ${
                    isSelected
                      ? 'bg-rose-50 border-rose-600 text-rose-700 ring-2 ring-rose-500/20 shadow-xs'
                      : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <Icon className={`w-5 h-5 ${isSelected ? 'text-rose-600' : pm.color}`} />
                  <span className="text-xs font-bold">{pm.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Split Partial Amount Input */}
        {isSplitMode && (
          <div className="p-3 bg-amber-50 rounded-xl border border-amber-200 space-y-1.5">
            <span className="text-xs font-bold text-amber-900 block">Valor desta Parcela (R$)</span>
            <input
              type="number"
              step="0.01"
              max={remainingBalance}
              value={customAmountInput}
              onChange={(e) => setCustomAmountInput(e.target.value)}
              placeholder="Digite o valor parcial a pagar..."
              className="w-full h-11 px-3 rounded-lg bg-white border border-amber-300 text-slate-900 text-base font-bold outline-none focus:border-rose-600"
            />
          </div>
        )}

        {/* Cash Tendered & Change Section */}
        {method === 'CASH' && (
          <div className="p-3.5 bg-slate-50 rounded-2xl border border-slate-200 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-600 uppercase">
                Valor Recebido em Dinheiro (R$)
              </span>
              {changeAmount > 0 && (
                <span className="text-xs font-extrabold text-emerald-600">
                  Troco: {formatCurrency(changeAmount)}
                </span>
              )}
            </div>

            <div className="flex items-center space-x-2">
              <input
                type="number"
                step="0.01"
                value={tenderedInput}
                onChange={(e) => setTenderedInput(e.target.value)}
                className="flex-1 h-12 px-3 rounded-xl bg-white border-2 border-slate-300 focus:border-rose-600 text-slate-900 text-xl font-black outline-none"
              />

              {/* Large Change Display Badge */}
              <div className="px-4 h-12 rounded-xl bg-emerald-100 border border-emerald-300 flex flex-col justify-center text-right shrink-0">
                <span className="text-[9px] font-bold uppercase text-emerald-800">Troco</span>
                <span className="text-lg font-black text-emerald-700">{formatCurrency(changeAmount)}</span>
              </div>
            </div>

            {/* Quick Bill Increments */}
            <div className="grid grid-cols-6 gap-1 pt-0.5">
              <button
                type="button"
                onClick={() => handleQuickTender(activeAmountToPay)}
                className="h-8 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
              >
                Exato
              </button>
              <button
                type="button"
                onClick={() => handleQuickAddTender(10)}
                className="h-8 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
              >
                + R$ 10
              </button>
              <button
                type="button"
                onClick={() => handleQuickAddTender(20)}
                className="h-8 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
              >
                + R$ 20
              </button>
              <button
                type="button"
                onClick={() => handleQuickAddTender(50)}
                className="h-8 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
              >
                + R$ 50
              </button>
              <button
                type="button"
                onClick={() => handleQuickTender(100)}
                className="h-8 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
              >
                R$ 100
              </button>
              <button
                type="button"
                onClick={() => handleQuickTender(200)}
                className="h-8 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
              >
                R$ 200
              </button>
            </div>
          </div>
        )}

        {/* Existing Confirmed Payments List */}
        {confirmedPayments.length > 0 && (
          <div className="space-y-1 pt-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block px-1">
              Pagamentos já Confirmados
            </span>
            <div className="space-y-1 max-h-24 overflow-y-auto">
              {confirmedPayments.map((p, idx) => (
                <div
                  key={p.id || idx}
                  className="px-3 py-1.5 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-between text-xs"
                >
                  <span className="font-semibold text-slate-700">{idx + 1}. {p.method}</span>
                  <span className="font-bold text-emerald-600">{formatCurrency(Number(p.amount))}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex items-center space-x-2 pt-2">
          <button
            type="button"
            onClick={closePaymentModal}
            disabled={actionLoading}
            className="px-4 h-14 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs font-bold transition-colors border border-slate-200 flex items-center space-x-1 shrink-0"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Voltar</span>
          </button>

          <button
            type="button"
            onClick={handleConfirmPayment}
            disabled={actionLoading || activeAmountToPay <= 0 || (method === 'CASH' && tenderedAmount < activeAmountToPay)}
            className="flex-1 h-14 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-base font-black flex items-center justify-center space-x-2 transition-all shadow-md active:scale-[0.98] disabled:opacity-40"
          >
            <Check className="w-5 h-5" />
            <span>
              {actionLoading
                ? 'Processando...'
                : `CONFIRMAR RECEBIMENTO (${formatCurrency(activeAmountToPay)})`}
            </span>
          </button>
        </div>
      </div>
    </Modal>
  )
}
