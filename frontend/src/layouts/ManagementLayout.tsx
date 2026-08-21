import React from 'react'
import {
  Home,
  ShoppingCart,
  FileText,
  Package,
  Banknote,
  Activity,
  LogOut,
  Store as StoreIcon,
  CheckCircle2,
  AlertCircle
} from 'lucide-react'
import { usePos } from '../context/PosContext'
import { useAuth } from '../context/AuthContext'
import { DashboardBI } from '../components/management/DashboardBI'
import { SalesHistory } from '../components/management/SalesHistory'
import { CatalogManager } from '../components/management/CatalogManager'
import { CashManager } from '../components/management/CashManager'
import { Diagnostics } from '../components/management/Diagnostics'

export const ManagementLayout: React.FC = () => {
  const { signOut } = useAuth()
  const {
    activeBiTab,
    setActiveBiTab,
    switchView,
    store,
    register,
    cashSession
  } = usePos()

  const isCashOpen = cashSession?.status === 'OPEN'

  const renderActiveTab = () => {
    switch (activeBiTab) {
      case 'dashboard':
        return <DashboardBI />
      case 'sales':
        return <SalesHistory />
      case 'catalog':
        return <CatalogManager />
      case 'cash':
        return <CashManager />
      case 'diagnostics':
        return <Diagnostics />
      default:
        return <DashboardBI />
    }
  }

  return (
    <div className="min-h-screen bg-dashem-bg text-slate-100 flex flex-row font-sans selection:bg-dashem-red selection:text-white">
      {/* ========================================================================= */}
      {/* EXECUTIVE LEFT SIDEBAR NAVIGATION                                         */}
      {/* ========================================================================= */}
      <aside className="w-64 bg-dashem-surface border-r border-dashem-border flex flex-col justify-between p-5 sticky top-0 h-screen select-none shrink-0 hidden md:flex">
        <div className="space-y-6">
          {/* Dashem Brand Header */}
          <div className="flex items-center space-x-3 px-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-dashem-red to-dashem-red-light flex items-center justify-center font-black text-white text-xl shadow-lg shadow-dashem-red/40 ring-2 ring-dashem-red/30">
              D
            </div>
            <div>
              <h1 className="font-extrabold text-lg leading-none tracking-tight text-white flex items-center">
                DASHEM <span className="text-dashem-red ml-1">POS</span>
              </h1>
              <span className="text-[10px] font-bold uppercase tracking-wider text-dashem-muted">
                Gestão & BI v1.0
              </span>
            </div>
          </div>

          {/* Navigation Menu */}
          <nav className="space-y-1.5">
            <button
              onClick={() => setActiveBiTab('dashboard')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-extrabold transition-all ${
                activeBiTab === 'dashboard'
                  ? 'bg-dashem-surface-elevated text-white shadow-md border-l-4 border-dashem-red'
                  : 'text-dashem-muted hover:text-white hover:bg-dashem-surface-elevated/60'
              }`}
            >
              <Home className={`w-4 h-4 ${activeBiTab === 'dashboard' ? 'text-dashem-red' : ''}`} />
              <span>Painel Geral (BI)</span>
            </button>

            <button
              onClick={() => setActiveBiTab('sales')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-extrabold transition-all ${
                activeBiTab === 'sales'
                  ? 'bg-dashem-surface-elevated text-white shadow-md border-l-4 border-dashem-red'
                  : 'text-dashem-muted hover:text-white hover:bg-dashem-surface-elevated/60'
              }`}
            >
              <FileText className={`w-4 h-4 ${activeBiTab === 'sales' ? 'text-dashem-red' : ''}`} />
              <span>Vendas & Histórico</span>
            </button>

            <button
              onClick={() => setActiveBiTab('catalog')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-extrabold transition-all ${
                activeBiTab === 'catalog'
                  ? 'bg-dashem-surface-elevated text-white shadow-md border-l-4 border-dashem-red'
                  : 'text-dashem-muted hover:text-white hover:bg-dashem-surface-elevated/60'
              }`}
            >
              <Package className={`w-4 h-4 ${activeBiTab === 'catalog' ? 'text-dashem-red' : ''}`} />
              <span>Catálogo & Estoque</span>
            </button>

            <button
              onClick={() => setActiveBiTab('cash')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-extrabold transition-all ${
                activeBiTab === 'cash'
                  ? 'bg-dashem-surface-elevated text-white shadow-md border-l-4 border-dashem-red'
                  : 'text-dashem-muted hover:text-white hover:bg-dashem-surface-elevated/60'
              }`}
            >
              <Banknote className={`w-4 h-4 ${activeBiTab === 'cash' ? 'text-dashem-red' : ''}`} />
              <span>Caixa & Tesouraria</span>
            </button>

            <button
              onClick={() => setActiveBiTab('diagnostics')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-extrabold transition-all ${
                activeBiTab === 'diagnostics'
                  ? 'bg-dashem-surface-elevated text-white shadow-md border-l-4 border-dashem-red'
                  : 'text-dashem-muted hover:text-white hover:bg-dashem-surface-elevated/60'
              }`}
            >
              <Activity className={`w-4 h-4 ${activeBiTab === 'diagnostics' ? 'text-dashem-red' : ''}`} />
              <span>Diagnóstico & API</span>
            </button>
          </nav>
        </div>

        {/* Bottom Switch to POS Card */}
        <div className="p-4 rounded-2xl bg-dashem-surface-elevated/80 border border-dashem-border space-y-2.5 text-center">
          <span className="text-[10px] font-extrabold uppercase text-dashem-muted block">
            Frente de Caixa
          </span>
          <button
            onClick={() => switchView('pdv')}
            className="w-full h-11 rounded-xl bg-dashem-red hover:bg-dashem-red-light text-white text-xs font-black flex items-center justify-center space-x-2 transition-all shadow-md shadow-dashem-red/30 active:scale-95"
          >
            <ShoppingCart className="w-4 h-4" />
            <span>Abrir PDV / Caixa</span>
          </button>
        </div>
      </aside>

      {/* ========================================================================= */}
      {/* MAIN MANAGEMENT CONTENT AREA                                              */}
      {/* ========================================================================= */}
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {/* Management Top Header */}
        <header className="h-16 px-6 bg-dashem-surface border-b border-dashem-border flex items-center justify-between sticky top-0 z-20 shadow-sm">
          <div className="flex items-center space-x-3">
            <div className="flex items-center space-x-2 text-xs font-bold text-dashem-muted">
              <StoreIcon className="w-4 h-4 text-dashem-red" />
              <span className="text-white">{store?.name || 'Loja Principal'}</span>
              <span>•</span>
              <span>{register?.name || 'Terminal 01'}</span>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            {/* Cash Status Indicator */}
            <div
              className={`flex items-center space-x-1.5 px-3 py-1 rounded-lg border text-[11px] font-bold ${
                isCashOpen
                  ? 'bg-emerald-950/80 border-emerald-500/40 text-emerald-300'
                  : 'bg-rose-950/80 border-rose-500/40 text-rose-300'
              }`}
            >
              {isCashOpen ? (
                <>
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Caixa Aberto</span>
                </>
              ) : (
                <>
                  <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
                  <span>Caixa Fechado</span>
                </>
              )}
            </div>

            {/* Quick Button to PDV */}
            <button
              onClick={() => switchView('pdv')}
              className="h-9 px-4 rounded-xl bg-dashem-red hover:bg-dashem-red-light text-white text-xs font-black flex items-center space-x-1.5 transition-all shadow-md active:scale-95"
            >
              <ShoppingCart className="w-3.5 h-3.5" />
              <span>Ir para o PDV</span>
            </button>

            <button
              onClick={signOut}
              title="Encerrar sessão"
              aria-label="Encerrar sessão"
              className="h-9 px-3 rounded-xl border border-dashem-border bg-dashem-surface-elevated text-dashem-muted hover:border-rose-500/40 hover:text-white text-xs font-black flex items-center space-x-1.5 transition-all active:scale-95"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span className="hidden xl:inline">Sair</span>
            </button>
          </div>
        </header>

        {/* Active Tab Body */}
        <main className="flex-1 p-6 max-w-7xl w-full mx-auto">{renderActiveTab()}</main>
      </div>
    </div>
  )
}
