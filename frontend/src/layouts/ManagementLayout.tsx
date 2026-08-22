import React, { useState } from 'react'
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
  AlertCircle,
  Menu,
  X
} from 'lucide-react'
import { usePos } from '../context/PosContext'
import { useAuth } from '../context/AuthContext'
import { DashboardBI } from '../components/management/DashboardBI'
import { SalesHistory } from '../components/management/SalesHistory'
import { CatalogManager } from '../components/management/CatalogManager'
import { CashManager } from '../components/management/CashManager'
import { Diagnostics } from '../components/management/Diagnostics'

export const ManagementLayout: React.FC = () => {
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false)
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

  const navigation = [
    { id: 'dashboard', label: 'Painel Geral (BI)', icon: Home },
    { id: 'sales', label: 'Vendas & Histórico', icon: FileText },
    { id: 'catalog', label: 'Catálogo & Estoque', icon: Package },
    { id: 'cash', label: 'Caixa & Tesouraria', icon: Banknote },
    { id: 'diagnostics', label: 'Diagnóstico & API', icon: Activity },
  ] as const

  const navigationButtons = navigation.map(item => {
    const Icon = item.icon
    const active = activeBiTab === item.id
    return (
      <button
        key={item.id}
        onClick={() => {
          setActiveBiTab(item.id)
          setMobileNavigationOpen(false)
        }}
        className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-xs font-extrabold transition-all ${
          active
            ? 'bg-dashem-surface-elevated text-white shadow-md border-l-4 border-dashem-red'
            : 'text-dashem-muted hover:text-white hover:bg-dashem-surface-elevated/60'
        }`}
      >
        <Icon className={`w-4 h-4 ${active ? 'text-dashem-red' : ''}`} />
        <span>{item.label}</span>
      </button>
    )
  })

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
          <nav className="space-y-1.5">{navigationButtons}</nav>
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

      {mobileNavigationOpen && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="Navegação da gestão">
          <button className="absolute inset-0 bg-slate-950/75 backdrop-blur-sm" aria-label="Fechar navegação" onClick={() => setMobileNavigationOpen(false)} />
          <aside className="relative flex h-full w-[min(86vw,20rem)] flex-col bg-dashem-surface p-5 shadow-2xl">
            <div className="mb-7 flex items-center justify-between">
              <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-dashem-red text-xl font-black">D</div><div><p className="font-black">DASHEM <span className="text-dashem-red">GESTÃO</span></p><p className="text-[10px] font-bold uppercase tracking-wider text-dashem-muted">Admin do tenant</p></div></div>
              <button className="flex h-11 w-11 items-center justify-center rounded-xl border border-dashem-border text-dashem-muted" onClick={() => setMobileNavigationOpen(false)} aria-label="Fechar menu"><X className="h-5 w-5" /></button>
            </div>
            <nav className="space-y-1.5">{navigationButtons}</nav>
            <div className="mt-auto space-y-3 border-t border-dashem-border pt-5">
              <button onClick={() => switchView('pdv')} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-dashem-red text-sm font-black"><ShoppingCart className="h-4 w-4" />Abrir PDV / Caixa</button>
              <button onClick={signOut} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-dashem-border text-sm font-black text-dashem-muted"><LogOut className="h-4 w-4" />Encerrar sessão</button>
            </div>
          </aside>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MAIN MANAGEMENT CONTENT AREA                                              */}
      {/* ========================================================================= */}
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {/* Management Top Header */}
        <header className="h-16 px-3 sm:px-6 bg-dashem-surface border-b border-dashem-border flex items-center justify-between sticky top-0 z-20 shadow-sm">
          <div className="flex items-center space-x-3">
            <button onClick={() => setMobileNavigationOpen(true)} className="flex h-11 w-11 items-center justify-center rounded-xl border border-dashem-border text-white md:hidden" aria-label="Abrir menu de gestão"><Menu className="h-5 w-5" /></button>
            <div className="flex items-center space-x-2 text-xs font-bold text-dashem-muted">
              <StoreIcon className="w-4 h-4 text-dashem-red" />
              <span className="text-white">{store?.name || 'Loja Principal'}</span>
              <span className="hidden sm:inline">•</span>
              <span className="hidden sm:inline">{register?.name || 'Terminal 01'}</span>
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
              title="Ir para o PDV"
              aria-label="Ir para o PDV"
              className="h-9 px-4 rounded-xl bg-dashem-red hover:bg-dashem-red-light text-white text-xs font-black flex items-center space-x-1.5 transition-all shadow-md active:scale-95"
            >
              <ShoppingCart className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Ir para o PDV</span>
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
        <main className="flex-1 p-3 sm:p-6 max-w-7xl w-full mx-auto">{renderActiveTab()}</main>
      </div>
    </div>
  )
}
