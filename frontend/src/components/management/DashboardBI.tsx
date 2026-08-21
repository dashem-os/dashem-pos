import React from 'react'
import {
  TrendingUp,
  DollarSign,
  ShoppingCart,
  Package,
  AlertTriangle,
  ArrowUpRight,
  Clock,
  CheckCircle2,
  Receipt
} from 'lucide-react'
import { usePos } from '../../context/PosContext'

export const DashboardBI: React.FC = () => {
  const { salesHistory, products, balances, cashSession, switchView } = usePos()

  // Compute Real Metrics
  const completedSales = salesHistory.filter((s) => s.status === 'COMPLETED' || s.status === 'PAID')
  const totalRevenue = completedSales.reduce((acc, s) => acc + Number(s.net_total), 0)
  const salesCount = completedSales.length
  const averageTicket = salesCount > 0 ? totalRevenue / salesCount : 0

  const lowStockProducts = products.filter((p) => p.item_type === 'PRODUCT' && (balances[p.id] || 0) <= 5)

  return (
    <div className="space-y-6">
      {/* Top Welcome Banner & CTA */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-3xl bg-gradient-to-r from-dashem-surface to-dashem-surface-elevated border border-dashem-border shadow-xl">
        <div>
          <span className="text-[11px] font-extrabold uppercase tracking-wider text-dashem-red block mb-1">
            Painel Executivo & Business Intelligence
          </span>
          <h2 className="text-2xl font-black text-white tracking-tight">Indicadores Gerais de Operação</h2>
          <p className="text-xs text-dashem-muted font-medium mt-1">
            Métricas calculadas em tempo real a partir das transações reais do backend.
          </p>
        </div>

        <button
          onClick={() => switchView('pdv')}
          className="h-12 px-6 rounded-2xl bg-dashem-red hover:bg-dashem-red-light text-white text-xs font-black flex items-center justify-center space-x-2 transition-all shadow-lg shadow-dashem-red/30 active:scale-95 shrink-0"
        >
          <ShoppingCart className="w-4 h-4" />
          <span>Ir para o Modo Caixa / PDV</span>
        </button>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Revenue KPI */}
        <div className="p-5 rounded-2xl bg-dashem-surface border border-dashem-border flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-dashem-muted uppercase">Faturamento Real</span>
            <div className="w-9 h-9 rounded-xl bg-emerald-950/60 border border-emerald-800/40 text-emerald-400 flex items-center justify-center">
              <DollarSign className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-black text-white">R$ {totalRevenue.toFixed(2)}</div>
            <span className="text-[11px] font-semibold text-emerald-400 mt-1 flex items-center">
              <ArrowUpRight className="w-3.5 h-3.5 mr-0.5" />
              {salesCount} vendas concluídas
            </span>
          </div>
        </div>

        {/* Average Ticket KPI */}
        <div className="p-5 rounded-2xl bg-dashem-surface border border-dashem-border flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-dashem-muted uppercase">Ticket Médio</span>
            <div className="w-9 h-9 rounded-xl bg-sky-950/60 border border-sky-800/40 text-sky-400 flex items-center justify-center">
              <TrendingUp className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-black text-white">R$ {averageTicket.toFixed(2)}</div>
            <span className="text-[11px] font-medium text-dashem-muted mt-1 block">
              Média por transação consumada
            </span>
          </div>
        </div>

        {/* Cash Status KPI */}
        <div className="p-5 rounded-2xl bg-dashem-surface border border-dashem-border flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-dashem-muted uppercase">Saldo de Abertura</span>
            <div className="w-9 h-9 rounded-xl bg-amber-950/60 border border-amber-800/40 text-amber-400 flex items-center justify-center">
              <Receipt className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-black text-white">
              R$ {Number(cashSession?.opening_balance || 0).toFixed(2)}
            </div>
            <span className={`text-[11px] font-bold mt-1 block ${cashSession?.status === 'OPEN' ? 'text-emerald-400' : 'text-rose-400'}`}>
              {cashSession?.status === 'OPEN' ? '● Caixa Aberto no Terminal' : '○ Caixa Fechado'}
            </span>
          </div>
        </div>

        {/* Inventory KPI */}
        <div className="p-5 rounded-2xl bg-dashem-surface border border-dashem-border flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-dashem-muted uppercase">Catálogo & Estoque</span>
            <div className="w-9 h-9 rounded-xl bg-purple-950/60 border border-purple-800/40 text-purple-400 flex items-center justify-center">
              <Package className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-black text-white">{products.length} itens</div>
            <span className="text-[11px] font-medium text-amber-400 mt-1 block">
              {lowStockProducts.length} itens com estoque baixo
            </span>
          </div>
        </div>
      </div>

      {/* Two Column Section: Recent Transactions & Low Stock Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Transactions List */}
        <div className="p-6 rounded-3xl bg-dashem-surface border border-dashem-border shadow-sm flex flex-col space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-extrabold text-white flex items-center space-x-2">
              <Clock className="w-4 h-4 text-dashem-red" />
              <span>Últimas Transações</span>
            </h3>
            <span className="text-xs font-semibold text-dashem-muted">{salesHistory.length} registros</span>
          </div>

          {salesHistory.length === 0 ? (
            <div className="h-44 flex flex-col items-center justify-center border border-dashed border-dashem-border rounded-2xl text-center p-4 text-dashem-muted">
              <Receipt className="w-8 h-8 mb-2 opacity-40" />
              <p className="text-sm font-semibold text-white">Nenhuma transação registrada ainda</p>
              <p className="text-xs text-dashem-muted mt-0.5">Realize uma venda no PDV para alimentar os indicadores.</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {salesHistory.slice(0, 6).map((sale) => (
                <div
                  key={sale.id}
                  className="px-4 py-3 rounded-2xl bg-dashem-surface-elevated/60 border border-dashem-border flex items-center justify-between text-xs"
                >
                  <div>
                    <span className="font-bold text-white block">Venda #{sale.id.slice(0, 8)}</span>
                    <span className="text-[11px] text-dashem-muted">
                      {new Date(sale.created_at).toLocaleTimeString()} • {sale.items.length} itens
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="font-black text-white text-sm block">
                      R$ {Number(sale.net_total).toFixed(2)}
                    </span>
                    <span
                      className={`text-[10px] font-bold uppercase ${
                        sale.status === 'COMPLETED'
                          ? 'text-emerald-400'
                          : sale.status === 'CANCELED'
                          ? 'text-rose-400'
                          : 'text-amber-400'
                      }`}
                    >
                      {sale.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Low Stock Alerts */}
        <div className="p-6 rounded-3xl bg-dashem-surface border border-dashem-border shadow-sm flex flex-col space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-extrabold text-white flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <span>Atenção de Estoque</span>
            </h3>
            <span className="text-xs font-semibold text-dashem-muted">{lowStockProducts.length} itens</span>
          </div>

          {lowStockProducts.length === 0 ? (
            <div className="h-44 flex flex-col items-center justify-center border border-dashed border-dashem-border rounded-2xl text-center p-4 text-dashem-muted">
              <CheckCircle2 className="w-8 h-8 text-emerald-400 mb-2" />
              <p className="text-sm font-semibold text-white">Todos os produtos com estoque saudável</p>
              <p className="text-xs text-dashem-muted mt-0.5">Nenhum produto abaixo de 5 unidades.</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {lowStockProducts.map((prod) => {
                const stock = balances[prod.id] || 0
                return (
                  <div
                    key={prod.id}
                    className="px-4 py-3 rounded-2xl bg-dashem-surface-elevated/60 border border-dashem-border flex items-center justify-between text-xs"
                  >
                    <div>
                      <span className="font-bold text-white block">{prod.name}</span>
                      <span className="text-[11px] text-dashem-muted">SKU: {prod.sku}</span>
                    </div>
                    <div className="text-right">
                      <span
                        className={`text-xs font-extrabold px-2.5 py-1 rounded-lg ${
                          stock === 0
                            ? 'bg-rose-950/80 text-rose-300 border border-rose-800/50'
                            : 'bg-amber-950/80 text-amber-300 border border-amber-800/50'
                        }`}
                      >
                        {stock === 0 ? 'Sem Estoque' : `${stock} un restantes`}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
