import React, { useState, useEffect } from 'react'
import { Modal } from '../common/Modal'
import { usePos } from '../../context/PosContext'
import { Delete, Check } from 'lucide-react'

export const QuantityModal: React.FC = () => {
  const { isQuantityModalOpen, closeQuantityModal, selectedItemForQuantity, updateItemQuantity, actionLoading } = usePos()
  const [val, setVal] = useState<string>('1')

  useEffect(() => {
    if (selectedItemForQuantity) {
      setVal(String(selectedItemForQuantity.quantity))
    }
  }, [selectedItemForQuantity])

  if (!selectedItemForQuantity) return null

  const handleDigit = (digit: string) => {
    if (val === '0' || val === '') {
      setVal(digit)
    } else if (val.length < 4) {
      setVal(val + digit)
    }
  }

  const handleBackspace = () => {
    if (val.length <= 1) {
      setVal('1')
    } else {
      setVal(val.slice(0, -1))
    }
  }

  const handleClear = () => {
    setVal('1')
  }

  const handleQuickAdd = (amount: number) => {
    const current = parseInt(val || '0', 10)
    setVal(String(Math.max(1, current + amount)))
  }

  const handleConfirm = async () => {
    const qty = parseInt(val, 10)
    if (qty > 0) {
      await updateItemQuantity(selectedItemForQuantity.id, qty)
      closeQuantityModal()
    }
  }

  return (
    <Modal
      isOpen={isQuantityModalOpen}
      onClose={closeQuantityModal}
      title="Alterar Quantidade"
      subtitle={selectedItemForQuantity.product_name}
      maxWidth="sm"
    >
      <div className="flex flex-col space-y-3.5">
        {/* Quantity Display */}
        <div className="bg-slate-50 border-2 border-slate-300 focus-within:border-rose-600 rounded-2xl p-3 text-center">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">Quantidade</span>
          <span className="text-3xl font-black text-slate-900">{val || '0'}</span>
        </div>

        {/* Quick Increment Buttons */}
        <div className="grid grid-cols-4 gap-1.5">
          {[+1, +2, +5, +10].map((inc) => (
            <button
              key={inc}
              type="button"
              onClick={() => handleQuickAdd(inc)}
              className="h-9 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
            >
              +{inc}
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
              className="h-12 rounded-xl bg-white hover:bg-slate-50 text-slate-900 text-xl font-black transition-all border border-slate-200 active:scale-95 flex items-center justify-center shadow-xs"
            >
              {num}
            </button>
          ))}

          <button
            type="button"
            onClick={handleClear}
            className="h-12 rounded-xl bg-slate-100 hover:bg-rose-50 text-rose-600 text-xs font-bold transition-all border border-slate-200 active:scale-95 flex items-center justify-center"
          >
            Limpar
          </button>

          <button
            type="button"
            onClick={() => handleDigit('0')}
            className="h-12 rounded-xl bg-white hover:bg-slate-50 text-slate-900 text-xl font-black transition-all border border-slate-200 active:scale-95 flex items-center justify-center shadow-xs"
          >
            0
          </button>

          <button
            type="button"
            onClick={handleBackspace}
            className="h-12 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-500 text-sm font-bold transition-all border border-slate-200 active:scale-95 flex items-center justify-center"
          >
            <Delete className="w-5 h-5" />
          </button>
        </div>

        {/* Confirm Button */}
        <button
          type="button"
          onClick={handleConfirm}
          disabled={actionLoading || parseInt(val || '0', 10) <= 0}
          className="w-full h-13 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-sm font-black flex items-center justify-center space-x-2 transition-all shadow-md active:scale-[0.98] disabled:opacity-40"
        >
          <Check className="w-4 h-4" />
          <span>Confirmar Quantidade</span>
        </button>
      </div>
    </Modal>
  )
}
