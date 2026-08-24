import React, { useState } from 'react'
import { FileText, Search, ChevronDown, ChevronUp, CheckCircle2, Ban, Clock, Scale } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Sale } from '../../services/api'
import * as api from '../../services/api'

export const SalesHistory: React.FC = () => {
  const { salesHistory, tenant, store, operatorId, permissions, showToast } = usePos()
  const [filterStatus, setFilterStatus] = useState<string>('ALL')
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedSaleId, setExpandedSaleId] = useState<string | null>(null)
  const [reconciliations, setReconciliations] = useState<Record<string, api.FinancialReconciliation>>({})
  const [reconciling, setReconciling] = useState<string | null>(null)

  const reconcile = async (sale: Sale) => {
    if (!tenant || !store) return
    setReconciling(sale.id)
    try {
      const result = await api.reconcileSale({ 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }, sale.id, operatorId)
      setReconciliations((current) => ({ ...current, [sale.id]: result }))
      showToast(result.status === 'MATCHED' ? 'success' : 'info', result.status === 'MATCHED' ? 'Venda conciliada sem diferenças.' : `Diferença sinalizada: R$ ${Number(result.difference).toFixed(2)}`)
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Falha na conciliação') }
    finally { setReconciling(null) }
  }

  const filtered = salesHistory.filter((s) => {
    if (filterStatus !== 'ALL' && s.status !== filterStatus) return false
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      return s.id.toLowerCase().includes(q) || (s.notes && s.notes.toLowerCase().includes(q))
    }
    return true
  })

  const getStatusBadge = (status: Sale['status']) => {
    switch (status) {
      case 'COMPLETED':
        return (
          <span className="px-2.5 py-1 rounded-md bg-emerald-950/80 text-emerald-300 border border-emerald-800/50 font-bold text-[11px] flex items-center space-x-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
            <span>Concluída</span>
          </span>
        )
      case 'PAID':
        return (
          <span className="px-2.5 py-1 rounded-md bg-sky-950/80 text-sky-300 border border-sky-800/50 font-bold text-[11px] flex items-center space-x-1">
            <CheckCircle2 className="w-3 h-3 text-sky-400" />
            <span>Paga (NF Pendente)</span>
          </span>
        )
      case 'AWAITING_PAYMENT':
        return (
          <span className="px-2.5 py-1 rounded-md bg-amber-950/80 text-amber-300 border border-amber-800/50 font-bold text-[11px] flex items-center space-x-1">
            <Clock className="w-3 h-3 text-amber-400" />
            <span>Aguardando Pagamento</span>
          </span>
        )
      case 'CANCELED':
        return (
          <span className="px-2.5 py-1 rounded-md bg-rose-950/80 text-rose-300 border border-rose-800/50 font-bold text-[11px] flex items-center space-x-1">
            <Ban className="w-3 h-3 text-rose-400" />
            <span>Cancelada</span>
          </span>
        )
      default:
        return (
          <span className="px-2.5 py-1 rounded-md bg-slate-800 text-slate-300 font-bold text-[11px]">
            {status}
          </span>
        )
    }
  }

  return (
    <div className="space-y-6">
      {/* Header & Filter Row */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-black text-white tracking-tight flex items-center space-x-2">
            <FileText className="w-5 h-5 text-dashem-red" />
            <span>Histórico de Vendas & Transações</span>
          </h2>
          <p className="text-xs text-dashem-muted font-medium mt-0.5">
            Registro consolidado de todas as vendas emitidas nesta loja.
          </p>
        </div>

        {/* Filter Badges */}
        <div className="flex items-center space-x-1.5 p-1 bg-dashem-surface rounded-xl border border-dashem-border shrink-0 overflow-x-auto">
          {[
            { id: 'ALL', label: 'Todas' },
            { id: 'COMPLETED', label: 'Concluídas' },
            { id: 'AWAITING_PAYMENT', label: 'Em Aberto' },
            { id: 'CANCELED', label: 'Canceladas' }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilterStatus(tab.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                filterStatus === tab.id
                  ? 'bg-dashem-red text-white shadow-md'
                  : 'text-dashem-muted hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Search Input */}
      <div className="relative">
        <Search className="w-4 h-4 text-dashem-muted absolute left-4 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Buscar por ID da venda ou observação..."
          className="w-full h-11 pl-11 pr-4 rounded-xl bg-dashem-surface border border-dashem-border text-white text-xs font-medium focus:border-dashem-red outline-none"
        />
      </div>

      {/* Sales List Table */}
      {filtered.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-dashem-border rounded-3xl bg-dashem-surface text-dashem-muted">
          <FileText className="w-12 h-12 mx-auto mb-2 opacity-40" />
          <p className="text-base font-bold text-white">Nenhuma venda encontrada com este filtro</p>
          <p className="text-xs text-dashem-muted mt-1">Altere o filtro de status ou realize novas operações no PDV.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((sale) => {
            const isExpanded = expandedSaleId === sale.id
            return (
              <div
                key={sale.id}
                className="bg-dashem-surface border border-dashem-border rounded-2xl overflow-hidden transition-all shadow-sm"
              >
                {/* Header Row */}
                <div
                  onClick={() => setExpandedSaleId(isExpanded ? null : sale.id)}
                  className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 cursor-pointer hover:bg-dashem-surface-elevated/50 transition-colors"
                >
                  <div className="flex items-center space-x-3">
                    <div className="w-10 h-10 rounded-xl bg-dashem-surface-elevated flex items-center justify-center text-dashem-red font-bold text-xs shrink-0">
                      #{sale.id.slice(0, 4)}
                    </div>
                    <div>
                      <div className="flex items-center space-x-2">
                        <span className="font-mono text-xs font-bold text-white">{sale.id}</span>
                        {getStatusBadge(sale.status)}
                      </div>
                      <span className="text-[11px] text-dashem-muted block mt-0.5">
                        {new Date(sale.created_at).toLocaleString()} • {sale.items.length} itens registrados
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between sm:justify-end space-x-4">
                    <div className="text-left sm:text-right">
                      <span className="text-xs text-dashem-muted block">
                        Bruto: R$ {Number(sale.gross_total).toFixed(2)}{' '}
                        {Number(sale.discount_total) > 0 && `(Desc: R$ ${Number(sale.discount_total).toFixed(2)})`}
                      </span>
                      <span className="text-base font-black text-white">
                        R$ {Number(sale.net_total).toFixed(2)}
                      </span>
                    </div>
                    <div className="w-8 h-8 rounded-lg bg-dashem-surface-elevated flex items-center justify-center text-dashem-muted">
                      {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </div>
                  </div>
                </div>

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="p-4 bg-dashem-surface-elevated/40 border-t border-dashem-border space-y-3 animate-in fade-in">
                    <h4 className="text-xs font-extrabold uppercase tracking-wider text-dashem-muted">
                      Itens desta Venda ({sale.items.length})
                    </h4>
                    <div className="space-y-1.5 divide-y divide-dashem-border/40">
                      {sale.items.map((item, idx) => (
                        <div key={item.id || idx} className="pt-1.5 first:pt-0 flex items-center justify-between text-xs">
                          <div>
                            <span className="font-bold text-white">{item.product_name}</span>
                            <span className="text-[11px] text-dashem-muted ml-2">
                              {item.quantity}x R$ {Number(item.unit_price).toFixed(2)}
                            </span>
                          </div>
                          <div className="text-right">
                            {Number(item.discount_amount) > 0 && (
                              <span className="text-[10px] text-emerald-400 font-semibold block">
                                - R$ {Number(item.discount_amount).toFixed(2)} desc.
                              </span>
                            )}
                            <span className="font-bold text-white">R$ {Number(item.net_total).toFixed(2)}</span>
                          </div>
                        </div>
                      ))}
                    </div>

                    {sale.notes && (
                      <div className="pt-2 text-xs text-dashem-muted border-t border-dashem-border">
                        <span className="font-bold text-white">Observações:</span> {sale.notes}
                      </div>
                    )}
                    {permissions.includes('reconciliation.manage') && ['PAID', 'COMPLETED', 'PARTIALLY_REFUNDED', 'REFUNDED'].includes(sale.status) && (
                      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-dashem-border pt-3">
                        <div className="text-xs text-dashem-muted">
                          {reconciliations[sale.id] ? <span className={reconciliations[sale.id].status === 'MATCHED' ? 'font-bold text-emerald-400' : 'font-bold text-amber-400'}>{reconciliations[sale.id].status === 'MATCHED' ? 'Conferência sem diferenças' : `Diferença de R$ ${Number(reconciliations[sale.id].difference).toFixed(2)}`}</span> : 'Compare venda, pagamentos, crediário e documento fiscal sem alterar os fatos.'}
                        </div>
                        <button type="button" onClick={() => reconcile(sale)} disabled={reconciling === sale.id} className="flex h-9 items-center gap-2 rounded-xl border border-dashem-border px-3 text-xs font-black text-white hover:border-dashem-red disabled:opacity-40"><Scale className="h-4 w-4" />{reconciling === sale.id ? 'Conferindo...' : 'Conciliar venda'}</button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
