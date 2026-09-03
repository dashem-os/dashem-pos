import React, { useState, useEffect } from 'react'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { NumericKeypad } from '../common/NumericKeypad'
import { usePos } from '../../context/PosContext'
import { Check } from 'lucide-react'

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
            <Button key={inc} variant="secondary" onClick={() => handleQuickAdd(inc)}>
              +{inc}
            </Button>
          ))}
        </div>

        <NumericKeypad
          onDigit={handleDigit}
          onBackspace={handleBackspace}
          onClear={handleClear}
          leadingKey="clear"
        />

        <Button
          size="lg"
          block
          icon={Check}
          onClick={handleConfirm}
          loading={actionLoading}
          disabled={parseInt(val || '0', 10) <= 0}
        >
          Confirmar Quantidade
        </Button>
      </div>
    </Modal>
  )
}
