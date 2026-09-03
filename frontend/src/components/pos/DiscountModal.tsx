import React, { useState } from 'react'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { NumericKeypad } from '../common/NumericKeypad'
import { usePos } from '../../context/PosContext'
import { Check, Percent, DollarSign } from 'lucide-react'

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
                <Button key={p} variant="secondary" onClick={() => handleQuickPercent(p)}>{p}%</Button>
              ))
            : [5, 10, 20, 50].map((f) => (
                <Button key={f} variant="secondary" onClick={() => handleQuickFixed(f)}>R$ {f}</Button>
              ))}
        </div>

        <NumericKeypad onDigit={handleDigit} onBackspace={handleBackspace} leadingKey="decimal" />

        <Button
          size="lg"
          block
          icon={Check}
          onClick={handleConfirm}
          loading={actionLoading}
          disabled={calculatedDiscount() > grossTotal}
          className="bg-emerald-600 text-white hover:bg-emerald-700"
        >
          Confirmar Desconto
        </Button>
      </div>
    </Modal>
  )
}
