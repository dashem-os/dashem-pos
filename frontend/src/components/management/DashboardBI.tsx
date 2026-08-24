import React, { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Banknote, Boxes, ChefHat, CircleDollarSign, Loader2, Monitor, Package, Receipt, ShoppingCart, TrendingUp, Users } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { fetchManagementOverview, ManagementOverview } from '../../services/api'
import { formatCurrency } from '../../utils/format'

export const DashboardBI: React.FC<{ onOpenModule?: (module: 'products' | 'tables' | 'devices' | 'team') => void }> = ({ onOpenModule }) => {
  const { tenant, store } = usePos()
  const [overview, setOverview] = useState<ManagementOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!tenant || !store) return
    setError(null)
    fetchManagementOverview({ 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id })
      .then(setOverview)
      .catch((reason) => setError(reason instanceof Error ? reason.message : 'Falha ao carregar indicadores.'))
  }, [tenant, store])

  const chart = useMemo(() => overview?.daily_revenue.slice(-14) ?? [], [overview])
  const maxRevenue = Math.max(1, ...chart.map((item) => item.revenue))

  if (error) return <State text={error} error />
  if (!overview) return <State text="Calculando indicadores persistidos..." />

  const primaryCards = [
    { label: 'Faturamento hoje', value: formatCurrency(overview.revenue_today), meta: `${overview.sales_today} vendas`, icon: CircleDollarSign, iconClass: 'bg-emerald-950/60 text-emerald-400' },
    { label: 'Faturamento 30 dias', value: formatCurrency(overview.revenue_30d), meta: `${overview.sales_30d} vendas`, icon: TrendingUp, iconClass: 'bg-sky-950/60 text-sky-400' },
    { label: 'Ticket médio', value: formatCurrency(overview.average_ticket_30d), meta: '30 dias', icon: Receipt, iconClass: 'bg-violet-950/60 text-violet-400' },
    { label: 'Vendas em aberto', value: String(overview.open_sales), meta: 'operações pendentes', icon: ShoppingCart, iconClass: 'bg-amber-950/60 text-amber-400' },
  ]

  const operations = [
    { label: 'Recebimentos (30d)', value: formatCurrency(overview.confirmed_receipts_30d), icon: Banknote },
    { label: 'Caixas abertos', value: String(overview.active_cash_sessions), icon: Banknote },
    { label: 'Produtos', value: String(overview.products), icon: Package },
    { label: 'Equipe ativa', value: String(overview.active_team_members), icon: Users },
  ]
  const shortcuts = [
    { module: 'products' as const, label: 'Cadastrar mercadorias', hint: 'Produtos, preços e acesso rápido', icon: Boxes },
    { module: 'tables' as const, label: 'Organizar atendimento', hint: 'Ambientes, mesas e reservas', icon: ChefHat },
    { module: 'devices' as const, label: 'Preparar terminais', hint: 'PDV, KDS e impressão', icon: Monitor },
    { module: 'team' as const, label: 'Montar a equipe', hint: 'Convites, funções e unidades', icon: Users },
  ]

  return <div className="space-y-6"><section className="rounded-3xl border border-dashem-border bg-gradient-to-br from-dashem-surface via-dashem-surface to-[#14253f] p-6 shadow-xl"><p className="text-[11px] font-extrabold uppercase tracking-[.18em] text-dashem-red">Resumo da unidade</p><div className="mt-2 flex flex-col justify-between gap-3 sm:flex-row sm:items-end"><div><h1 className="text-3xl font-black text-white">{store?.name}</h1><p className="mt-2 text-sm text-dashem-muted">{tenant?.name} · dados atualizados em {new Date(overview.generated_at).toLocaleString('pt-BR')}</p></div><span className="w-fit rounded-full border border-emerald-800/60 bg-emerald-950/40 px-3 py-1.5 text-xs font-black text-emerald-300">Operação persistida</span></div></section><section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{primaryCards.map(({ label, value, meta, icon: Icon, iconClass }) => <article key={label} className="rounded-2xl border border-dashem-border bg-dashem-surface p-5 shadow-sm"><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase tracking-wide text-dashem-muted">{label}</p><p className="mt-3 text-2xl font-black text-white">{value}</p><p className="mt-1 text-xs font-semibold text-dashem-muted">{meta}</p></div><div className={`flex h-10 w-10 items-center justify-center rounded-xl ${iconClass}`}><Icon className="h-5 w-5" /></div></div></article>)}</section><section className="grid gap-5 xl:grid-cols-[1.55fr_1fr]"><article className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><div className="flex items-center justify-between"><div><h3 className="font-black text-white">Faturamento diário</h3><p className="text-xs text-dashem-muted">Últimos 14 dias · valores persistidos</p></div><TrendingUp className="h-5 w-5 text-dashem-red" /></div><div className="mt-8 flex h-48 items-end gap-2">{chart.map((item) => <div key={item.date} className="group flex min-w-0 flex-1 flex-col items-center justify-end gap-2"><div title={`${new Date(`${item.date}T12:00:00`).toLocaleDateString('pt-BR')}: ${formatCurrency(item.revenue)} · ${item.sales} vendas`} className="w-full rounded-t-lg bg-gradient-to-t from-dashem-red to-rose-400 transition-opacity hover:opacity-80" style={{ height: `${Math.max(item.revenue > 0 ? 8 : 2, (item.revenue / maxRevenue) * 100)}%` }} /><span className="hidden text-[9px] text-dashem-muted 2xl:block">{item.date.slice(8)}</span></div>)}</div></article><article className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><div className="flex items-center gap-2"><AlertTriangle className="h-5 w-5 text-amber-400" /><h3 className="font-black text-white">Atenção agora</h3></div>{overview.alerts.length ? <ul className="mt-5 space-y-3">{overview.alerts.map((alert) => <li key={alert} className="rounded-xl border border-amber-800/40 bg-amber-950/30 p-3 text-sm font-semibold text-amber-200">{alert}</li>)}</ul> : <p className="mt-5 rounded-xl border border-emerald-800/40 bg-emerald-950/30 p-4 text-sm font-bold text-emerald-300">Nenhum alerta operacional ativo.</p>}<div className="mt-5 grid grid-cols-2 gap-2">{operations.map(({ label, value, icon: Icon }) => <div key={label} className="rounded-xl bg-dashem-bg p-3"><Icon className="h-4 w-4 text-slate-500" /><p className="mt-2 font-black text-white">{value}</p><p className="mt-1 text-[10px] font-bold text-dashem-muted">{label}</p></div>)}</div></article></section><section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><div><h2 className="font-black text-white">Preparar e administrar a operação</h2><p className="mt-1 text-sm text-dashem-muted">Acesse diretamente as tarefas mais frequentes da retaguarda.</p></div><div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{shortcuts.map(({ module, label, hint, icon: Icon }) => <button key={module} onClick={() => onOpenModule?.(module)} className="group rounded-2xl border border-dashem-border bg-dashem-bg p-4 text-left transition hover:-translate-y-0.5 hover:border-slate-600"><div className="flex items-center justify-between"><Icon className="h-5 w-5 text-dashem-red" /><ArrowRight className="h-4 w-4 text-slate-600 transition group-hover:translate-x-0.5 group-hover:text-white" /></div><p className="mt-4 text-sm font-black text-white">{label}</p><p className="mt-1 text-xs leading-5 text-dashem-muted">{hint}</p></button>)}</div></section></div>
}

function State({ text, error = false }: { text: string; error?: boolean }) {
  return <div className={`flex min-h-64 items-center justify-center rounded-3xl border border-dashem-border bg-dashem-surface text-sm font-bold ${error ? 'text-red-300' : 'text-dashem-muted'}`}>{!error && <Loader2 className="mr-3 h-5 w-5 animate-spin" />}{text}</div>
}
