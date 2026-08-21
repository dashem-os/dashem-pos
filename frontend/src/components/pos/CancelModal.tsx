import React, { useState } from 'react'
import { Modal } from '../common/Modal'
import { usePos } from '../../context/PosContext'
import { AlertTriangle, Ban } from 'lucide-react'

export const CancelModal: React.FC = () => {
  const { isCancelModalOpen, closeCancelModal, cancelCurrentSale, actionLoading } = usePos()
  const [reason, setReason] = useState('Desistência do cliente')

  const handleConfirmCancel = async () => {
    await cancelCurrentSale(reason)
  }

  return (
    <Modal
      isOpen={isCancelModalOpen}
      onClose={closeCancelModal}
      title="Cancelar Venda Atual"
      maxWidth="sm"
    >
      <div className="flex flex-col space-y-4">
        <div className="flex items-center space-x-3 p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-800">
          <AlertTriangle className="w-5 h-5 shrink-0 text-rose-600" />
          <p className="text-xs font-semibold leading-relaxed">
            Esta ação cancelará a venda e descartará todos os itens registrados no carrinho.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-bold text-slate-700 block">Motivo do Cancelamento</label>
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-full h-11 px-3 rounded-xl bg-white border border-slate-200 text-slate-800 text-xs font-semibold outline-none focus:border-rose-600"
          >
            <option value="Desistência do cliente">Desistência do cliente</option>
            <option value="Forma de pagamento não aceita">Forma de pagamento não aceita</option>
            <option value="Erro no registro de itens">Erro no registro de itens</option>
            <option value="Outro motivo operacional">Outro motivo operacional</option>
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2 pt-2">
          <button
            type="button"
            onClick={closeCancelModal}
            disabled={actionLoading}
            className="h-11 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
          >
            Voltar à Venda
          </button>

          <button
            type="button"
            onClick={handleConfirmCancel}
            disabled={actionLoading}
            className="h-11 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-black flex items-center justify-center space-x-1.5 transition-all shadow-sm active:scale-95 disabled:opacity-40"
          >
            <Ban className="w-4 h-4" />
            <span>Sim, Cancelar</span>
          </button>
        </div>
      </div>
    </Modal>
  )
}
