import React from 'react'
import { Modal } from '../common/Modal'
import { usePos } from '../../context/PosContext'
import { CheckCircle2, AlertTriangle, AlertCircle, Printer, PlusCircle, RefreshCw } from 'lucide-react'

export const FiscalStatusModal: React.FC = () => {
  const { isFiscalModalOpen, closeFiscalModal, fiscalDoc, startNewSale, issueFiscal, actionLoading } = usePos()

  if (!fiscalDoc) return null

  const handleStartNewSale = async () => {
    closeFiscalModal()
    await startNewSale()
  }

  const handleRetry = async () => {
    await issueFiscal()
  }

  const isAuthorized = fiscalDoc.status === 'AUTHORIZED' || fiscalDoc.status === 'NOT_REQUIRED'
  const isRejected = fiscalDoc.status === 'REJECTED'
  const isContingency = fiscalDoc.status === 'CONTINGENCY'

  return (
    <Modal
      isOpen={isFiscalModalOpen}
      onClose={closeFiscalModal}
      title="Emissão Fiscal (NFC-e)"
      subtitle={`Documento: ${fiscalDoc.document_type}`}
      maxWidth="md"
    >
      <div className="flex flex-col space-y-4 text-center">
        {/* AUTHORIZED / SUCCESS */}
        {isAuthorized && (
          <div className="flex flex-col items-center space-y-2 py-3">
            <div className="w-14 h-14 rounded-full bg-emerald-100 border-2 border-emerald-500 text-emerald-600 flex items-center justify-center shadow-xs">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <div>
              <h3 className="text-lg font-black text-slate-900">Venda Concluída com Sucesso!</h3>
              <p className="text-xs text-emerald-700 font-semibold mt-0.5">Cupom NFC-e autorizado pela SEFAZ.</p>
            </div>

            {fiscalDoc.access_key && (
              <div className="w-full p-3 rounded-xl bg-slate-50 border border-slate-200 text-left mt-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Chave de Acesso NFC-e
                </span>
                <span className="text-xs font-mono font-bold text-slate-800 break-all">{fiscalDoc.access_key}</span>
              </div>
            )}
          </div>
        )}

        {/* REJECTED / SEFAZ ERROR */}
        {isRejected && (
          <div className="flex flex-col items-center space-y-2 py-3">
            <div className="w-14 h-14 rounded-full bg-rose-100 border-2 border-rose-500 text-rose-600 flex items-center justify-center shadow-xs">
              <AlertCircle className="w-8 h-8" />
            </div>
            <div>
              <h3 className="text-lg font-black text-slate-900">Rejeição na Emissão Fiscal</h3>
              <p className="text-xs text-rose-700 font-semibold mt-0.5">
                O pagamento foi registrado, mas a SEFAZ rejeitou o documento.
              </p>
            </div>

            <div className="w-full p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-left space-y-1 mt-2">
              <div className="flex items-center space-x-1.5 text-rose-800 font-bold text-xs">
                <span>Código: [{fiscalDoc.rejection_code || 'Erro'}]</span>
              </div>
              <p className="text-xs text-rose-900 font-medium leading-relaxed">
                {fiscalDoc.rejection_reason || 'Rejeição de regras fiscais da SEFAZ.'}
              </p>
            </div>
          </div>
        )}

        {/* CONTINGENCY */}
        {isContingency && (
          <div className="flex flex-col items-center space-y-2 py-3">
            <div className="w-14 h-14 rounded-full bg-amber-100 border-2 border-amber-500 text-amber-600 flex items-center justify-center shadow-xs">
              <AlertTriangle className="w-8 h-8" />
            </div>
            <div>
              <h3 className="text-lg font-black text-slate-900">Emitido em Contingência Offline</h3>
              <p className="text-xs text-amber-800 font-semibold mt-0.5">
                Cupom gerado offline. Será transmitido automaticamente na retomada da conexão com a SEFAZ.
              </p>
            </div>

            {fiscalDoc.access_key && (
              <div className="w-full p-3 rounded-xl bg-slate-50 border border-slate-200 text-left mt-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  Chave em Contingência
                </span>
                <span className="text-xs font-mono font-bold text-slate-800 break-all">{fiscalDoc.access_key}</span>
              </div>
            )}
          </div>
        )}

        {/* Action Buttons */}
        <div className="space-y-2 pt-2 border-t border-slate-100">
          {isRejected ? (
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={handleRetry}
                disabled={actionLoading}
                className="flex-1 h-12 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-black flex items-center justify-center space-x-1.5 transition-all shadow-sm active:scale-95 disabled:opacity-40"
              >
                <RefreshCw className={`w-4 h-4 ${actionLoading ? 'animate-spin' : ''}`} />
                <span>Tentar Novamente</span>
              </button>

              <button
                type="button"
                onClick={handleStartNewSale}
                className="px-5 h-12 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition-all border border-slate-200"
              >
                Nova Venda
              </button>
            </div>
          ) : (
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={() => window.print()}
                className="h-12 px-5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold flex items-center justify-center space-x-1.5 transition-all border border-slate-200"
              >
                <Printer className="w-4 h-4 text-slate-500" />
                <span>Imprimir Cupom</span>
              </button>

              <button
                type="button"
                onClick={handleStartNewSale}
                className="flex-1 h-12 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-black flex items-center justify-center space-x-1.5 transition-all shadow-sm active:scale-95"
              >
                <PlusCircle className="w-4 h-4" />
                <span>Iniciar Nova Venda</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}
