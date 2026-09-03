import React, { useState } from 'react'
import {
  Store as StoreIcon,
  ShoppingBag,
  CheckCircle2,
  AlertCircle,
  Lock,
  Unlock,
  ChevronUp,
  LogOut,
  X,
  Wifi,
  WifiOff,
  UtensilsCrossed,
  LayoutDashboard,
} from 'lucide-react'
import { usePos } from '../context/PosContext'
import { useAuth } from '../context/AuthContext'
import { ProductSearch } from '../components/pos/ProductSearch'
import { QuickProductGrid } from '../components/pos/QuickProductGrid'
import { Cart } from '../components/pos/Cart'
import { SaleTotals } from '../components/pos/SaleTotals'
import { PaymentDialog } from '../components/pos/PaymentDialog'
import { QuantityModal } from '../components/pos/QuantityModal'
import { DiscountModal } from '../components/pos/DiscountModal'
import { FiscalStatusModal } from '../components/pos/FiscalStatusModal'
import { CancelModal } from '../components/pos/CancelModal'
import { formatCurrency, formatQuantity, maskCurrencyInput, parseCurrencyInput } from '../utils/format'
import { Modal } from '../components/common/Modal'
import { navigateTo } from '../utils/navigation'
import { canNavigateToManagement, operationalRoleLabel } from '../domain/operationalRules'
import type { BusinessNiche } from '../services/api'
import { NICHE_LABELS } from '../utils/nicheTheme'

export const PosLayout: React.FC = () => {
  const { session, signOut } = useAuth()
  const {
    accessMode,
    store,
    register,
    operatorName,
    operatorRole,
    cashSession,
    currentSale,
    connectionState,
    operationMode,
    setOperationMode,
    openCash,
    closeCash,
    actionLoading,
    openPaymentModal,
    permissions,
    activities,
    capabilities,
    activeActivity,
    setActiveActivity,
  } = usePos()

  const [openingBalanceInput, setOpeningBalanceInput] = useState('')
  const [isMobileCartOpen, setIsMobileCartOpen] = useState(false)
  const [isCloseCashOpen, setIsCloseCashOpen] = useState(false)
  const [closingBalanceInput, setClosingBalanceInput] = useState('')

  const isCashOpen = cashSession?.status === 'OPEN'
  const items = currentSale?.items || []
  const netTotal = Number(currentSale?.net_total || 0)
  const managementAvailable = canNavigateToManagement(Boolean(session), permissions, accessMode)
  const canReadCash = permissions.includes('cash.read')
  const managementValidation = accessMode === 'MANAGEMENT'
  // Opening and closing a shift require an operational session. Offering the
  // control to a management identity would be offering a refusal.
  const canOpenCash = permissions.includes('cash.open') && !managementValidation
  const canCloseCash = permissions.includes('cash.close') && !managementValidation
  const roleLabel = operationalRoleLabel(operatorRole)

  const handleOpenCash = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canOpenCash) return
    const val = parseCurrencyInput(openingBalanceInput)
    if (val >= 0) {
      await openCash(val)
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 flex flex-col font-sans selection:bg-brand selection:text-brand-contrast pb-20 lg:pb-0">
      {/* ========================================================================= */}
      {/* COMPACT OPERATIONAL HEADER (56px)                                         */}
      {/* ========================================================================= */}
      <header className="h-14 gap-2 px-3 sm:px-6 bg-white border-b border-slate-200 flex items-center justify-between shrink-0 z-30 select-none shadow-xs">
        {/* Brand & Instance Identification */}
        <div className="flex min-w-0 items-center space-x-3">
          <div className="w-8 h-8 rounded-xl bg-brand flex items-center justify-center font-black text-brand-contrast text-base shadow-sm">
            D
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-black text-sm sm:text-base leading-none tracking-tight text-slate-900">
                DASHEM <span className="text-brand-ink">PDV</span>
              </span>
              <span className="hidden sm:inline-block text-xs font-bold px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200">
                Frente de Caixa
              </span>
            </div>
            <div className="flex items-center space-x-2 truncate text-xs text-slate-400 font-medium mt-0.5">
              <span className="flex items-center space-x-1 truncate text-slate-600">
                <StoreIcon className="w-3 h-3 text-brand-ink shrink-0" />
                <span className="truncate">{store?.name || 'Unidade não selecionada'}</span>
              </span>
              <span className="hidden sm:inline">•</span>
              <span className="hidden sm:inline text-slate-600">{register?.name || 'Terminal não selecionado'}</span>
              <span className="hidden md:inline">•</span>
              <span className="hidden md:inline max-w-[240px] truncate text-slate-500">
                {operatorName || 'Colaborador'}{roleLabel ? ` · ${roleLabel}` : ''}
              </span>
            </div>
          </div>
        </div>

        {/* Right Status Pill & Navigation */}
        <div className="flex shrink-0 items-center gap-2">
          <div className={`hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-bold border ${
            connectionState === 'ONLINE' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-800 border-amber-200'
          }`}>
            {connectionState === 'ONLINE' ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
            <span>{connectionState === 'ONLINE' ? 'API acessível' : connectionState === 'OFFLINE' ? 'Sem rede' : 'API instável'}</span>
          </div>
          {/* Cash Status Pill */}
          <div
            className={`flex items-center space-x-1.5 px-3 py-1 rounded-xl text-xs font-bold border ${
              isCashOpen
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                : canReadCash ? 'bg-rose-50 text-rose-700 border-rose-200' : 'bg-amber-50 text-amber-800 border-amber-200'
            }`}
          >
            {isCashOpen ? (
              <>
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                <span>Caixa Aberto<span className="hidden sm:inline"> ({formatCurrency(Number(cashSession?.opening_balance || 0))})</span></span>
              </>
            ) : (
              <>
                <AlertCircle className="w-3.5 h-3.5 text-rose-600" />
                <span>{canReadCash ? 'Caixa Fechado' : 'Caixa indisponível'}</span>
              </>
            )}
          </div>

          {isCashOpen && canCloseCash && <button
            onClick={() => { setClosingBalanceInput(''); setIsCloseCashOpen(true) }}
            className="h-9 px-3.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold flex items-center space-x-1.5 transition-colors border border-slate-300 active:scale-95"
            title="Conferir e fechar o caixa"
          >
            <Lock className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Fechar caixa</span>
          </button>}

          {activities.includes('FOOD_SERVICE') && permissions.includes('table.read') && 'table_service' in capabilities && <button
            onClick={() => navigateTo(managementValidation ? '/manage?module=tables' : '/tables')}
            className="h-9 px-3.5 rounded-xl bg-orange-50 hover:bg-orange-100 text-orange-800 text-xs font-bold flex items-center space-x-1.5 transition-colors border border-orange-200 active:scale-95"
            title="Operar mesas e comandas"
          >
            <UtensilsCrossed className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">{managementValidation ? 'Configurar mesas' : 'Mesas'}</span>
          </button>}

          {managementAvailable && !managementValidation && <button
            onClick={() => navigateTo('/manage')}
            className="h-9 px-3.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold flex items-center space-x-1.5 transition-colors border border-slate-700 active:scale-95"
            title="Voltar para a Gestão"
          >
            <LayoutDashboard className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Gestão</span>
          </button>}

          <button
            onClick={signOut}
            title="Encerrar sessão"
            aria-label="Encerrar sessão"
            className="h-9 w-9 rounded-xl border border-slate-200 bg-white text-slate-500 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700 flex items-center justify-center transition-colors active:scale-95"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </header>

      {managementValidation && (
        <div role="status" className="flex flex-col justify-between gap-2 border-b border-sky-300 bg-sky-50 px-4 py-2.5 text-xs text-sky-950 sm:flex-row sm:items-center sm:px-6">
          <p><strong>Acesso gerencial.</strong> Você está validando o PDV com sua identidade administrativa; ações executadas são reais e auditadas.</p>
          <button onClick={() => navigateTo('/manage')} className="shrink-0 font-black text-sky-800 underline underline-offset-2">Voltar à Gestão</button>
        </div>
      )}

      {connectionState !== 'ONLINE' && (
        <div role="alert" className="px-4 py-2 bg-amber-100 border-b border-amber-300 text-amber-900 text-xs font-bold text-center">
          {connectionState === 'OFFLINE'
            ? 'Sem rede: novas operações estão bloqueadas. A venda já persistida permanece segura no servidor.'
            : 'Conexão com a API instável: aguarde a confirmação online antes de continuar.'}
        </div>
      )}

      {/* ========================================================================= */}
      {/* CASH CLOSED BLOCKING STATE                                                */}
      {/* ========================================================================= */}
      {!isCashOpen ? (
        <main className="flex-1 flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-white border border-slate-200 rounded-3xl p-8 shadow-xl text-center flex flex-col items-center space-y-4 animate-in fade-in zoom-in-95 duration-200">
            <div className="w-16 h-16 rounded-2xl bg-rose-50 border border-rose-200 text-rose-600 flex items-center justify-center shadow-xs">
              <Lock className="w-8 h-8" />
            </div>

            <div>
              <h2 className="text-xl font-black text-slate-900">Caixa Fechado</h2>
              <p className="text-xs text-slate-500 font-medium max-w-xs mt-1">
                {canOpenCash
                  ? 'Para iniciar as operações de venda na Frente de Caixa, informe o saldo inicial de troco.'
                  : managementValidation
                    ? 'O turno pertence a quem o assume. Você está conferindo a configuração com identidade administrativa; abrir e fechar o caixa exige código e PIN pessoal no terminal.'
                    : canReadCash
                      ? 'Seu perfil pode operar vendas depois que um Caixa ou Supervisor abrir este caixa.'
                      : 'Sua função atual não possui acesso a este caixa. Solicite a revisão do acesso na Gestão.'}
              </p>
            </div>

            {canOpenCash ? <form onSubmit={handleOpenCash} className="w-full space-y-3 pt-2">
              <div className="space-y-1 text-left">
                <label className="text-xs font-bold text-slate-700 block">
                  Fundo de Troco / Saldo Inicial (R$)
                </label>
                <div className="flex h-12 w-full items-center rounded-xl border-2 border-slate-300 bg-slate-50 px-4 focus-within:border-brand">
                  <span className="mr-2 text-lg font-black text-slate-400">R$</span>
                  <input
                    inputMode="numeric"
                    required
                    value={openingBalanceInput}
                    onChange={(e) => setOpeningBalanceInput(maskCurrencyInput(e.target.value))}
                    placeholder="0,00"
                    className="h-full min-w-0 flex-1 bg-transparent text-lg font-black text-slate-900 outline-none placeholder:text-slate-400"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={actionLoading || !openingBalanceInput}
                className="w-full min-h-12 rounded-xl bg-brand hover:bg-brand-strong text-brand-contrast font-black text-sm flex items-center justify-center space-x-2 transition-all shadow-md active:scale-95 disabled:opacity-40"
              >
                <Unlock className="w-4 h-4" />
                <span>ABRIR CAIXA E INICIAR VENDAS</span>
              </button>
            </form> : <div role="status" className="w-full rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-bold leading-5 text-amber-900">
              Identidade reconhecida: {operatorName || 'Colaborador'}{roleLabel ? ` · ${roleLabel}` : ''}. Nenhuma ação incompatível com essa função será exibida.
            </div>}
          </div>
        </main>
      ) : (
        /* ========================================================================= */
        /* CASH OPEN: MAIN OPERATIONAL WORKSPACE                                     */
        /* 2-Column on >= 1024px (lg:), Single Column with Fixed Bottom on < 1024px  */
        /* ========================================================================= */
        <main className="mx-auto flex w-full max-w-[1920px] flex-1 flex-col gap-4 overflow-hidden p-3 sm:gap-5 sm:p-5 lg:flex-row">
          {/* LEFT COLUMN: Search + Category Tabs + Touch Product Grid */}
          <div className="flex-1 flex flex-col space-y-3 overflow-y-auto min-w-0 pr-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-xl p-1.5" aria-label="Modo da operação">
                {(['COUNTER', 'TAKEAWAY'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setOperationMode(mode)}
                    disabled={Boolean(currentSale?.items.length)}
                    className={`min-h-11 px-3 rounded-lg text-xs font-bold flex items-center gap-1.5 disabled:cursor-not-allowed ${operationMode === mode ? 'bg-brand text-brand-contrast' : 'text-slate-600 hover:bg-slate-100'}`}
                  >
                    {mode === 'TAKEAWAY' && <UtensilsCrossed className="w-3.5 h-3.5" />}
                    <span>{mode === 'COUNTER' ? 'Balcão' : 'Retirada'}</span>
                  </button>
                ))}
              </div>

              {/* Only a tenant contracted for more than one business model has a
                  choice to make; a single-activity operation stays implicit. */}
              {activities.length > 1 && (
                <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-xl p-1.5" aria-label="Atividade em operação">
                  {activities.map((activity) => (
                    <button
                      key={activity}
                      type="button"
                      onClick={() => setActiveActivity(activity as BusinessNiche)}
                      disabled={Boolean(currentSale?.items.length)}
                      className={`min-h-11 px-3 rounded-lg text-xs font-bold disabled:cursor-not-allowed ${activeActivity === activity ? 'bg-brand text-brand-contrast' : 'text-slate-600 hover:bg-slate-100'}`}
                    >
                      {NICHE_LABELS[activity] || activity}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <ProductSearch />
            <QuickProductGrid />
          </div>

          {/* RIGHT COLUMN (DESKTOP >= 1024px): "Venda atual" + Items + Totals.
              Fluid width: a hard 380px squeezed the product grid between 1024 and 1150px. */}
          <div className="hidden lg:flex flex-col w-[clamp(20rem,30vw,27rem)] shrink-0 bg-white border border-slate-200 rounded-3xl p-4 overflow-hidden shadow-sm justify-between">
            <div className="flex items-center justify-between pb-2.5 border-b border-slate-100 shrink-0">
              <h2 className="text-sm font-black text-slate-900 flex items-center space-x-2">
                <ShoppingBag className="w-4 h-4 text-brand-ink" />
                <span>Venda Atual</span>
              </h2>
              <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200">
                {items.length} {items.length === 1 ? 'item' : 'itens'}
              </span>
            </div>

            {/* Scrollable Cart Items */}
            <Cart />

            {/* Fixed Totals & Receber Action Button */}
            <SaleTotals />
          </div>
        </main>
      )}

      {/* ========================================================================= */}
      {/* FIXED BOTTOM BAR (Active for viewports < 1024px, e.g. 846x870, Tablets)   */}
      {/* ========================================================================= */}
      {isCashOpen && (
        <div className="lg:hidden fixed bottom-0 left-0 right-0 p-3 bg-white border-t border-slate-200 shadow-2xl z-30 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setIsMobileCartOpen(true)}
            className="flex items-center space-x-3 text-left"
          >
            <div className="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center text-brand-ink relative border border-slate-200">
              <ShoppingBag className="w-6 h-6" />
              {items.length > 0 && (
                <span className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-brand text-brand-contrast text-xs font-black flex items-center justify-center shadow-xs">
                  {items.length}
                </span>
              )}
            </div>
            <div>
              <span className="text-[10px] font-bold uppercase text-slate-400 block">
                Venda ({items.length} {items.length === 1 ? 'item' : 'itens'})
              </span>
              <span className="text-lg font-black text-slate-900 leading-tight">
                {formatCurrency(netTotal)}
              </span>
            </div>
          </button>

          <div className="flex items-center space-x-2">
            <button
              type="button"
              onClick={() => setIsMobileCartOpen(true)}
              className="h-12 px-4 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
            >
              Ver Itens
            </button>

            <button
              type="button"
              onClick={() => {
                if (items.length > 0) {
                  openPaymentModal()
                } else {
                  setIsMobileCartOpen(true)
                }
              }}
              disabled={items.length === 0}
              className="h-12 px-5 rounded-xl bg-brand hover:bg-brand-strong disabled:opacity-40 text-brand-contrast font-black text-xs flex items-center space-x-1.5 shadow-md active:scale-95 transition-all"
            >
              <span>RECEBER</span>
              <ChevronUp className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Cart Drawer for Viewports < 1024px */}
      {isMobileCartOpen && (
        <div className="lg:hidden fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex flex-col justify-end animate-in fade-in">
          <div className="bg-white border-t border-slate-200 rounded-t-3xl p-4 max-h-[85vh] flex flex-col space-y-3 shadow-2xl animate-in slide-in-from-bottom duration-200">
            <div className="flex items-center justify-between pb-2 border-b border-slate-100">
              <h3 className="text-sm font-black text-slate-900 flex items-center space-x-2">
                <ShoppingBag className="w-4 h-4 text-brand-ink" />
                <span>Venda Atual ({items.length} itens)</span>
              </h3>
              <button
                type="button"
                onClick={() => setIsMobileCartOpen(false)}
                className="w-9 h-9 rounded-xl flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <Cart />
            <SaleTotals />
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* OPERATIONAL MODALS                                                        */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCloseCashOpen}
        onClose={() => setIsCloseCashOpen(false)}
        title="Fechar caixa"
        subtitle="Informe o valor contado na gaveta para encerrar o turno."
        maxWidth="sm"
      >
        <form
          onSubmit={async (event) => {
            event.preventDefault()
            await closeCash(parseCurrencyInput(closingBalanceInput))
            setIsCloseCashOpen(false)
          }}
          className="space-y-4"
        >
          <label className="block text-xs font-black uppercase tracking-wide text-slate-500">
            Valor contado na gaveta
            <div className="mt-2 flex h-12 w-full items-center rounded-xl border-2 border-slate-300 bg-slate-50 px-4 focus-within:border-brand">
              <span className="mr-2 text-lg font-black text-slate-400">R$</span>
              <input
                inputMode="numeric"
                required
                autoFocus
                value={closingBalanceInput}
                onChange={(event) => setClosingBalanceInput(maskCurrencyInput(event.target.value))}
                placeholder="0,00"
                className="h-full min-w-0 flex-1 bg-transparent text-lg font-black text-slate-900 outline-none placeholder:text-slate-400"
              />
            </div>
          </label>
          <p className="text-xs leading-5 text-slate-500">
            A diferença entre o contado e o esperado é registrada como fato, sem reescrever movimentos.
          </p>
          <button
            type="submit"
            disabled={actionLoading || !closingBalanceInput}
            className="w-full min-h-12 rounded-xl bg-slate-950 text-sm font-black text-white disabled:opacity-40"
          >
            {actionLoading ? 'Fechando...' : 'Conferir e fechar o caixa'}
          </button>
        </form>
      </Modal>

      <PaymentDialog />
      <QuantityModal />
      <DiscountModal />
      <FiscalStatusModal />
      <CancelModal />
    </div>
  )
}
