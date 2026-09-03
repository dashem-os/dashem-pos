import React, { useState, useEffect } from 'react'
import { Banknote, ArrowDownRight, ArrowUpRight, Lock, Unlock, Clock, FileSpreadsheet, CheckCircle2 } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'

export const CashManager: React.FC = () => {
  const { tenant, store, register, cashSession, openCash, closeCash, addCashMovement, actionLoading } = usePos()

  const [openingInput, setOpeningInput] = useState('100.00')
  const [closingInput, setClosingInput] = useState('')
  const [movementType, setMovementType] = useState<'BLEED' | 'REINFORCEMENT'>('REINFORCEMENT')
  const [movementAmount, setMovementAmount] = useState('')
  const [movementNotes, setMovementNotes] = useState('')
  const [movementsList, setMovementsList] = useState<api.CashMovement[]>([])

  const isCashOpen = cashSession?.status === 'OPEN'

  useEffect(() => {
    async function loadMovements() {
      if (tenant && store && cashSession) {
        const hdrs = { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
        const movs = await api.fetchCashMovements(hdrs, cashSession.id).catch(() => [])
        setMovementsList(movs)
      }
    }
    loadMovements()
  }, [tenant, store, cashSession])

  const handleOpen = async (e: React.FormEvent) => {
    e.preventDefault()
    const amt = parseFloat(openingInput)
    if (!isNaN(amt) && amt >= 0) {
      await openCash(amt)
    }
  }

  const handleClose = async (e: React.FormEvent) => {
    e.preventDefault()
    const amt = parseFloat(closingInput)
    if (!isNaN(amt) && amt >= 0) {
      await closeCash(amt)
      setClosingInput('')
    }
  }

  const handleMovement = async (e: React.FormEvent) => {
    e.preventDefault()
    const amt = parseFloat(movementAmount)
    if (!isNaN(amt) && amt > 0) {
      await addCashMovement(movementType, amt, movementNotes)
      setMovementAmount('')
      setMovementNotes('')

      if (tenant && store && cashSession) {
        const hdrs = { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
        const movs = await api.fetchCashMovements(hdrs, cashSession.id).catch(() => [])
        setMovementsList(movs)
      }
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-black text-dashem-strong tracking-tight flex items-center space-x-2">
          <Banknote className="w-5 h-5 text-dashem-red" />
          <span>Gestão de Caixa & Tesouraria</span>
        </h2>
        <p className="text-xs text-dashem-muted font-medium mt-0.5">
          Controle de sessões de caixa, sangrias, suprimentos e conferência de saldos.
        </p>
      </div>

      {/* Cash Session Status Banner */}
      <div className="p-6 rounded-3xl bg-dashem-surface border border-dashem-border flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
        <div className="flex items-center space-x-4">
          <div
            className={`w-12 h-12 rounded-2xl flex items-center justify-center font-bold ${
              isCashOpen
                ? 'bg-emerald-50 border border-emerald-500/40 text-emerald-700'
                : 'bg-rose-50 border border-rose-500/40 text-rose-700'
            }`}
          >
            {isCashOpen ? <Unlock className="w-6 h-6" /> : <Lock className="w-6 h-6" />}
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-lg font-black text-dashem-strong">
                {isCashOpen ? 'Caixa Aberto' : 'Caixa Fechado'}
              </span>
              <span className="text-xs font-bold text-dashem-muted">
                ({register?.name || 'Terminal 01'})
              </span>
            </div>
            <span className="text-xs text-dashem-muted font-medium block mt-0.5">
              {isCashOpen
                ? `Aberto em ${new Date(cashSession?.opened_at || '').toLocaleTimeString()} com saldo inicial de R$ ${Number(cashSession?.opening_balance || 0).toFixed(2)}`
                : 'Abra o caixa informando o valor de abertura para iniciar as operações do PDV.'}
            </span>
          </div>
        </div>
      </div>

      {/* Open / Close / Movement Forms Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Open or Close Box */}
        {isCashOpen ? (
          <div className="p-6 rounded-3xl bg-dashem-surface border border-dashem-border space-y-4 shadow-sm">
            <h3 className="text-sm font-black text-dashem-strong flex items-center space-x-2">
              <Lock className="w-4 h-4 text-rose-700" />
              <span>Fechamento de Caixa</span>
            </h3>
            <p className="text-xs text-dashem-muted">
              Informe o valor apurado na gaveta para encerrar o expediente e calcular divergências.
            </p>

            <form onSubmit={handleClose} className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs font-bold text-dashem-strong block">Valor Contado em Gaveta (R$)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={closingInput}
                  onChange={(e) => setClosingInput(e.target.value)}
                  placeholder="Ex: 540.00"
                  className="w-full h-12 px-4 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-base font-bold outline-none focus:border-dashem-red"
                />
              </div>

              <button
                type="submit"
                disabled={actionLoading || !closingInput}
                className="w-full h-12 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-black transition-all shadow-lg active:scale-95 disabled:opacity-40"
              >
                Encerrar e Fechar Caixa
              </button>
            </form>
          </div>
        ) : (
          <div className="p-6 rounded-3xl bg-dashem-surface border border-dashem-border space-y-4 shadow-sm">
            <h3 className="text-sm font-black text-dashem-strong flex items-center space-x-2">
              <Unlock className="w-4 h-4 text-emerald-700" />
              <span>Abertura de Caixa</span>
            </h3>
            <p className="text-xs text-dashem-muted">
              Informe o fundo de troco para iniciar a sessão de atendimento.
            </p>

            <form onSubmit={handleOpen} className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs font-bold text-dashem-strong block">Saldo Inicial / Fundo de Troco (R$)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={openingInput}
                  onChange={(e) => setOpeningInput(e.target.value)}
                  placeholder="100.00"
                  className="w-full h-12 px-4 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-base font-bold outline-none focus:border-dashem-red"
                />
              </div>

              <button
                type="submit"
                disabled={actionLoading || !openingInput}
                className="w-full h-12 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-black transition-all shadow-lg active:scale-95 disabled:opacity-40"
              >
                Confirmar Abertura de Caixa
              </button>
            </form>
          </div>
        )}

        {/* Cash Movements Form (Sangria / Suprimento) */}
        <div className="p-6 rounded-3xl bg-dashem-surface border border-dashem-border space-y-4 shadow-sm">
          <h3 className="text-sm font-black text-dashem-strong flex items-center space-x-2">
            <ArrowUpDown className="w-4 h-4 text-dashem-red" />
            <span>Movimentação Avulsa (Sangria / Suprimento)</span>
          </h3>
          <p className="text-xs text-dashem-muted">
            Registre retiradas para cofre (sangria) ou reforço de troco (suprimento).
          </p>

          <form onSubmit={handleMovement} className="space-y-3">
            <div className="grid grid-cols-2 gap-2 p-1 bg-dashem-surface-elevated rounded-xl border border-dashem-border">
              <button
                type="button"
                onClick={() => setMovementType('REINFORCEMENT')}
                className={`h-9 rounded-lg font-extrabold text-xs flex items-center justify-center space-x-1.5 transition-all ${
                  movementType === 'REINFORCEMENT' ? 'bg-emerald-600 text-white shadow-sm' : 'text-dashem-muted'
                }`}
              >
                <ArrowUpRight className="w-3.5 h-3.5" />
                <span>Suprimento</span>
              </button>

              <button
                type="button"
                onClick={() => setMovementType('BLEED')}
                className={`h-9 rounded-lg font-extrabold text-xs flex items-center justify-center space-x-1.5 transition-all ${
                  movementType === 'BLEED' ? 'bg-rose-600 text-white shadow-sm' : 'text-dashem-muted'
                }`}
              >
                <ArrowDownRight className="w-3.5 h-3.5" />
                <span>Sangria</span>
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-xs font-bold text-dashem-strong block">Valor (R$)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  disabled={!isCashOpen}
                  value={movementAmount}
                  onChange={(e) => setMovementAmount(e.target.value)}
                  placeholder="0.00"
                  className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-sm font-bold outline-none focus:border-dashem-red disabled:opacity-40"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-dashem-strong block">Motivo / Notas</label>
                <input
                  type="text"
                  disabled={!isCashOpen}
                  value={movementNotes}
                  onChange={(e) => setMovementNotes(e.target.value)}
                  placeholder="Ex: Reforço moedas"
                  className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold outline-none focus:border-dashem-red disabled:opacity-40"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={!isCashOpen || actionLoading || !movementAmount}
              className="w-full h-11 rounded-xl bg-dashem-surface-elevated hover:bg-dashem-border text-dashem-strong text-xs font-black transition-all border border-dashem-border active:scale-95 disabled:opacity-40"
            >
              Registrar Movimentação
            </button>
          </form>
        </div>
      </div>

      {/* Movements History Ledger Table */}
      <div className="p-6 rounded-3xl bg-dashem-surface border border-dashem-border space-y-3 shadow-sm">
        <h3 className="text-sm font-black text-dashem-strong flex items-center space-x-2">
          <Clock className="w-4 h-4 text-dashem-red" />
          <span>Extrato de Movimentações da Sessão Atual</span>
        </h3>

        {movementsList.length === 0 ? (
          <p className="text-xs text-dashem-muted italic py-4 text-center">
            Nenhuma movimentação registrada nesta sessão de caixa.
          </p>
        ) : (
          <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
            {movementsList.map((m) => {
              const isPositive = m.movement_type === 'OPENING' || m.movement_type === 'SALE_PAYMENT' || m.movement_type === 'REINFORCEMENT'
              return (
                <div
                  key={m.id}
                  className="px-4 py-3 rounded-2xl bg-dashem-surface-elevated/60 border border-dashem-border flex items-center justify-between text-xs"
                >
                  <div className="flex items-center space-x-3">
                    <div
                      className={`w-7 h-7 rounded-lg flex items-center justify-center font-bold ${
                        isPositive ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
                      }`}
                    >
                      {isPositive ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                    </div>
                    <div>
                      <span className="font-bold text-dashem-strong block">
                        {m.movement_type === 'OPENING'
                          ? 'Abertura de Caixa'
                          : m.movement_type === 'SALE_PAYMENT'
                          ? 'Recebimento de Venda'
                          : m.movement_type === 'BLEED'
                          ? 'Sangria de Caixa'
                          : 'Suprimento'}
                      </span>
                      {m.notes && <span className="text-[11px] text-dashem-muted">{m.notes}</span>}
                    </div>
                  </div>

                  <div className="text-right">
                    <span className={`text-sm font-black ${isPositive ? 'text-emerald-700' : 'text-rose-700'}`}>
                      {isPositive ? '+' : '-'} R$ {Number(m.amount).toFixed(2)}
                    </span>
                    <span className="text-[10px] text-dashem-muted block">
                      {new Date(m.created_at).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function ArrowUpDown(props: any) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m21 16-4 4-4-4" />
      <path d="M17 20V4" />
      <path d="m3 8 4-4 4 4" />
      <path d="M7 4v16" />
    </svg>
  )
}
