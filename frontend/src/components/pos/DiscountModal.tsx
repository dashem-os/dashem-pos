import React, { useState } from 'react'
import { Modal } from '../common/Modal'
import { usePos } from '../../context/PosContext'
import { Check, Percent, DollarSign, Delete } from 'lucide-react'

export const DiscountModal: React.FC = () => {
  const { isDiscountModalOpen, closeDiscountModal, currentSale, applyDiscount, actionLoading } = usePos()
  const [discountType, setDiscountType] = useState<'FIXED' | 'PERCENTAGE'>('FIXED')
  const [val, setVal] = useState<string>('')

  const grossTotal = Number(currentSale?.gross_total || 0)

  const handleDigit = (digit: string) => {
    if (digit === '.' && val.includes('.')) return
    if (val.length < 5) {
      setVal(val + digit)
    }
  }

  const handleBackspace = () => {
    setVal(val.slice(0, -1))
  }

  const handleQuickPercent = (pct: number) => {
    setDiscountType('PERCENTAGE')
    setVal(String(pct))
  }

  const handleQuickFixed = (amount: number) => {
    setDiscountType('FIXED')
    setVal(String(amount))
  }

  const calculatedDiscount = () => {
    const num = parseFloat(val || '0')
    if (isNaN(num) || num <= 0) return 0
    if (discountType === 'PERCENTAGE') {
      return (grossTotal * Math.min(100, num)) / 100
    }
    return Math.min(grossTotal, num)
  }

  const handleConfirm = async () => {
    const num = parseFloat(val)
    if (!isNaN(num) && num >= 0) {
      await applyDiscount(discountType, num)
      closeDiscountModal()
    }
  }

  return (
    <Modal
      isOpen={isDiscountModalOpen}
      onClose={closeDiscountModal}
      title="Aplicar Desconto na Venda"
      subtitle={`Subtotal Bruto: R$ ${grossTotal.toFixed(2)}`}
      maxWidth="sm"
    >
      <div className="flex flex-col space-y-3.5">
        {/* Toggle Discount Type */}
        <div className="grid grid-cols-2 gap-1.5 p-1 bg-slate-100 rounded-xl border border-slate-200">
          <button
            type="button"
            onClick={() => setDiscountType('FIXED')}
            className={`h-9 rounded-lg font-bold text-xs flex items-center justify-center space-x-1.5 transition-all ${
              discountType === 'FIXED' ? 'bg-white text-rose-600 shadow-xs' : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <DollarSign className="w-3.5 h-3.5" />
            <span>Valor em Reais (R$)</span>
          </button>

          <button
            type="button"
            onClick={() => setDiscountType('PERCENTAGE')}
            className={`h-9 rounded-lg font-bold text-xs flex items-center justify-center space-x-1.5 transition-all ${
              discountType === 'PERCENTAGE' ? 'bg-white text-rose-600 shadow-xs' : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <Percent className="w-3.5 h-3.5" />
            <span>Porcentagem (%)</span>
          </button>
        </div>

        {/* Display & Live Preview */}
        <div className="bg-slate-50 border-2 border-slate-200 rounded-2xl p-3 flex items-center justify-between">
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">Desconto Digitado</span>
            <span className="text-2xl font-black text-slate-900">
              {discountType === 'FIXED' ? `R$ ${val || '0.00'}` : `${val || '0'} %`}
            </span>
          </div>

          <div className="text-right">
            <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-600 block">Efeito no Total</span>
            <span className="text-lg font-black text-emerald-600">
              - R$ {calculatedDiscount().toFixed(2)}
            </span>
          </div>
        </div>

        {/* Quick Discount Buttons */}
        <div className="grid grid-cols-4 gap-1.5">
          {discountType === 'PERCENTAGE'
            ? [5, 10, 15, 20].map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => handleQuickPercent(p)}
                  className="h-8 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
                >
                  {p}%
                </button>
              ))
            : [5, 10, 20, 50].map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => handleQuickFixed(f)}
                  className="h-8 rounded-lg bg-white hover:bg-slate-100 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
                >
                  R$ {f}
                </button>
              ))}
        </div>

        {/* Numeric Touch Keypad */}
        <div className="grid grid-cols-3 gap-1.5">
          {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((num) => (
            <button
              key={num}
              type="button"
              onClick={() => handleDigit(num)}
              className="h-11 rounded-xl bg-white hover:bg-slate-50 text-slate-900 text-lg font-black transition-all border border-slate-200 active:scale-95 flex items-center justify-center shadow-xs"
            >
              {num}
            </button>
          ))}

          <button
            type="button"
            onClick={() => handleDigit('.')}
            className="h-11 rounded-xl bg-white hover:bg-slate-50 text-slate-900 text-lg font-black transition-all border border-slate-200 active:scale-95 flex items-center justify-center shadow-xs"
          >
            .
          </button>

          <button
            type="button"
            onClick={() => handleDigit('0')}
            className="h-11 rounded-xl bg-white hover:bg-slate-50 text-slate-900 text-lg font-black transition-all border border-slate-200 active:scale-95 flex items-center justify-center shadow-xs"
          >
            0
          </button>

          <button
            type="button"
            onClick={handleBackspace}
            className="h-11 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-500 text-sm font-bold transition-all border border-slate-200 active:scale-95 flex items-center justify-center"
          >
            <Delete className="w-4 h-4" />
          </button>
        </div>

        {/* Confirm Button */}
        <button
          type="button"
          onClick={handleConfirm}
          disabled={actionLoading || calculatedDiscount() > grossTotal}
          className="w-full h-13 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-black flex items-center justify-center space-x-2 transition-all shadow-md active:scale-[0.98] disabled:opacity-40"
        >
          <Check className="w-4 h-4" />
          <span>Confirmar Desconto</span>
        </button>
      </div>
    </Modal>
  )
}
