import React, { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Banknote, Boxes, ChefHat, CircleDollarSign, Database, Loader2, Monitor, Package, Receipt, RefreshCw, ShoppingCart, TrendingUp, Users, X } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { BiDrilldown, fetchBiDrilldown, fetchManagementOverview, fetchOperationalProductivity, ManagementOverview, OperationalProductivity, rebuildOperationalProductivity, refreshBiProjection } from '../../services/api'
import { formatCurrency } from '../../utils/format'
import { CommercialRequestsPanel } from './CommercialRequestsPanel'

export const DashboardBI: React.FC<{ onOpenModule?: (module: 'products' | 'tables' | 'devices' | 'team') => void }> = ({ onOpenModule }) => {
  const { tenant, store, operatorId, permissions, showToast } = usePos()
  const [overview, setOverview] = useState<ManagementOverview | null>(null)
  const [productivity, setProductivity] = useState<OperationalProductivity | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(30)
  const [refreshing, setRefreshing] = useState(false)
  const [drilldown, setDrilldown] = useState<BiDrilldown | null>(null)
  const headers = tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : null

  const load = () => {
    if (!headers) return Promise.resolve()
    setError(null)
    return Promise.all([
      fetchManagementOverview(headers, { days }),
      fetchOperationalProductivity(headers, days),
    ]).then(([management, operational]) => {
      setOverview(management)
      setProductivity(operational)
    })
      .catch((reason) => setError(reason instanceof Error ? reason.message : 'Falha ao carregar indicadores.'))
  }

  useEffect(() => { load() }, [tenant, store, days])

  const refresh = async () => {
    if (!headers) return
    setRefreshing(true)
    try {
      await refreshBiProjection(headers, operatorId)
      await rebuildOperationalProductivity(headers, operatorId)
      await load()
      showToast('success', 'Projeção gerencial atualizada a partir dos fatos.')
    } catch (reason) {
      showToast('error', reason instanceof Error ? reason.message : 'Falha ao atualizar BI.')
    } finally { setRefreshing(false) }
  }

  const openDay = async (competence: string) => {
    if (!headers) return
    try { setDrilldown(await fetchBiDrilldown(headers, 'net_revenue', competence)) }
    catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha no detalhamento.') }
  }

  const chart = useMemo(() => overview?.daily_revenue.slice(-14) ?? [], [overview])
  const maxRevenue = Math.max(1, ...chart.map((item) => item.revenue))
  if (error) return <State text={error} error />
  if (!overview || !productivity) return <State text="Carregando projeções gerenciais persistidas..." />

  const primaryCards = [
    { label: 'Faturamento hoje', value: formatCurrency(overview.revenue_today), meta: `${overview.sales_today} vendas`, icon: CircleDollarSign, color: 'text-emerald-400' },
    { label: `Faturamento ${days} dias`, value: formatCurrency(overview.revenue_30d), meta: `${overview.sales_30d} vendas`, icon: TrendingUp, color: 'text-sky-400' },
    { label: 'Ticket médio', value: formatCurrency(overview.average_ticket_30d), meta: `${days} dias`, icon: Receipt, color: 'text-violet-400' },
    { label: 'Vendas em aberto', value: String(overview.open_sales), meta: 'estado operacional atual', icon: ShoppingCart, color: 'text-amber-400' },
  ]
  const operations = [
    ['Recebimentos', formatCurrency(overview.confirmed_receipts_30d), Banknote],
    ['Estornos', formatCurrency(overview.refunds_30d), RefreshCw],
    ['Crediário emitido', formatCurrency(overview.receivables_issued_30d), Receipt],
    ['Crediário liquidado', formatCurrency(overview.receivables_settled_30d), CircleDollarSign],
    ['Mesas fechadas', String(overview.table_sessions_closed_30d), ChefHat],
    ['Produções concluídas', String(overview.production_tickets_30d), ChefHat],
    ['Transferências', String(overview.transfers_30d), ArrowRight],
    ['Rupturas / mínimo', String(overview.stockout_products), Boxes],
  ] as const
  const shortcuts = [
    ['products', 'Cadastrar mercadorias', 'Produtos, preços e acesso rápido', Boxes],
    ['tables', 'Organizar atendimento', 'Ambientes, mesas e reservas', ChefHat],
    ['devices', 'Preparar terminais', 'PDV, KDS e impressão', Monitor],
    ['team', 'Montar a equipe', 'Convites, funções e unidades', Users],
  ] as const

  return <div className="space-y-6">
    <section className="rounded-3xl border border-dashem-border bg-gradient-to-br from-dashem-surface to-[#14253f] p-6 shadow-xl">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div><p className="text-[11px] font-extrabold uppercase tracking-[.18em] text-dashem-red">Business Intelligence V1</p><h1 className="mt-2 text-3xl font-black text-white">{store?.name}</h1><p className="mt-2 text-sm text-dashem-muted">{tenant?.name} · projeção v{overview.projection_version} · {new Date(overview.generated_at).toLocaleString('pt-BR')}</p></div>
        <div className="flex flex-wrap items-center gap-2"><div className="flex rounded-xl border border-dashem-border bg-dashem-bg p-1">{[7, 30, 90].map((period) => <button key={period} onClick={() => setDays(period)} className={`rounded-lg px-3 py-2 text-xs font-black ${days === period ? 'bg-white text-slate-950' : 'text-dashem-muted'}`}>{period} dias</button>)}</div>{permissions.includes('bi.refresh') && <button onClick={refresh} disabled={refreshing} className="flex h-10 items-center gap-2 rounded-xl bg-dashem-red px-4 text-xs font-black disabled:opacity-40"><RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />Atualizar</button>}</div>
      </div>
      <div className={`mt-5 flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-bold ${overview.projection_lag_seconds > 300 ? 'border-amber-800 bg-amber-950/30 text-amber-300' : 'border-emerald-800 bg-emerald-950/30 text-emerald-300'}`}><Database className="h-4 w-4" />Atraso informado: {overview.projection_lag_seconds}s · fonte até {overview.source_watermark ? new Date(overview.source_watermark).toLocaleString('pt-BR') : 'sem watermark'}.</div>
    </section>

    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{primaryCards.map(({ label, value, meta, icon: Icon, color }) => <article key={label} className="rounded-2xl border border-dashem-border bg-dashem-surface p-5"><div className="flex justify-between"><div><p className="text-xs font-black uppercase tracking-wide text-dashem-muted">{label}</p><p className="mt-3 text-2xl font-black text-white">{value}</p><p className="mt-1 text-xs text-dashem-muted">{meta}</p></div><Icon className={`h-6 w-6 ${color}`} /></div></article>)}</section>

    <CommercialRequestsPanel />

    <section className="grid gap-5 xl:grid-cols-[1.45fr_1fr]">
      <article className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><div className="flex justify-between"><div><h3 className="font-black text-white">Faturamento diário</h3><p className="text-xs text-dashem-muted">Clique na competência para rastrear as vendas de origem.</p></div><TrendingUp className="h-5 w-5 text-dashem-red" /></div><div className="mt-8 flex h-48 items-end gap-2">{chart.map((item) => <button type="button" onClick={() => openDay(item.date)} key={item.date} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-2" title={`${item.date}: ${formatCurrency(item.revenue)} · ${item.sales} vendas`}><span className="w-full rounded-t-lg bg-gradient-to-t from-dashem-red to-rose-400 hover:opacity-80" style={{ height: `${Math.max(item.revenue > 0 ? 8 : 2, (item.revenue / maxRevenue) * 100)}%` }} /><span className="hidden text-[9px] text-dashem-muted 2xl:block">{item.date.slice(8)}</span></button>)}</div></article>
      <article className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><div className="flex items-center gap-2"><AlertTriangle className="h-5 w-5 text-amber-400" /><h3 className="font-black text-white">Operação e alertas</h3></div>{overview.alerts.length ? <ul className="mt-4 space-y-2">{overview.alerts.map((alert) => <li key={alert} className="rounded-xl border border-amber-800/40 bg-amber-950/30 p-3 text-xs font-semibold text-amber-200">{alert}</li>)}</ul> : <p className="mt-4 rounded-xl border border-emerald-800/40 bg-emerald-950/30 p-3 text-xs font-bold text-emerald-300">Nenhum alerta operacional ativo.</p>}<div className="mt-4 grid grid-cols-2 gap-2">{operations.map(([label, value, Icon]) => <div key={label} className="rounded-xl bg-dashem-bg p-3"><Icon className="h-4 w-4 text-slate-500" /><p className="mt-2 font-black text-white">{value}</p><p className="mt-1 text-[10px] font-bold text-dashem-muted">{label}</p></div>)}</div></article>
    </section>

    <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6">
      <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-end"><div><p className="text-[10px] font-black uppercase tracking-[.16em] text-dashem-red">Projeção operacional explícita</p><h3 className="mt-1 font-black text-white">Produtividade por operador e turno</h3><p className="mt-1 text-xs text-dashem-muted">Derivada exclusivamente da cadeia imutável de solicitação, autorização, execução e resultado do pagamento.</p></div><p className="text-[10px] font-bold text-dashem-muted">Fonte até {productivity.source_watermark ? new Date(productivity.source_watermark).toLocaleString('pt-BR') : 'sem eventos operacionais'}</p></div>
      {productivity.items.length === 0 ? <div className="mt-5 rounded-2xl border border-dashed border-dashem-border bg-dashem-bg p-8 text-center text-xs font-bold text-dashem-muted">Nenhum pagamento executado por uma sessão PIN neste período.</div> : <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[760px] text-left text-xs"><thead className="text-[10px] font-black uppercase tracking-wide text-dashem-muted"><tr><th className="pb-3">Operador</th><th className="pb-3">Turnos</th><th className="pb-3">Solicitados</th><th className="pb-3">Executados</th><th className="pb-3">Confirmados</th><th className="pb-3">Falhas</th><th className="pb-3">Conversão</th><th className="pb-3 text-right">Valor confirmado</th></tr></thead><tbody className="divide-y divide-dashem-border">{productivity.items.map((item) => <tr key={item.operator_id}><td className="py-4 font-black text-white">{item.operator_name}</td><td className="py-4 text-dashem-muted">{item.shift_count}</td><td className="py-4 text-dashem-muted">{item.requested_count}</td><td className="py-4 text-dashem-muted">{item.executed_count}</td><td className="py-4 text-emerald-300">{item.confirmed_count}</td><td className="py-4 text-rose-300">{item.failed_count}</td><td className="py-4 font-black text-white">{(item.confirmation_rate * 100).toFixed(1)}%</td><td className="py-4 text-right font-black text-white">{formatCurrency(item.confirmed_amount)}</td></tr>)}</tbody></table></div>}
      <details className="mt-4 rounded-xl bg-dashem-bg p-4"><summary className="cursor-pointer text-xs font-black text-white">Fórmulas da produtividade</summary><div className="mt-3 grid gap-2 md:grid-cols-2">{Object.entries(productivity.formulas).map(([metric, formula]) => <p key={metric} className="text-[11px] text-dashem-muted"><strong className="text-dashem-red">{metric}:</strong> {formula}</p>)}</div></details>
    </section>

    {drilldown && <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><div className="flex justify-between"><div><p className="text-[10px] font-black uppercase tracking-wider text-dashem-red">Drill-down rastreável</p><h3 className="mt-1 font-black text-white">{new Date(`${drilldown.competence_date}T12:00:00`).toLocaleDateString('pt-BR')} · {drilldown.total} fontes</h3></div><button onClick={() => setDrilldown(null)} className="rounded-lg border border-dashem-border p-2"><X className="h-4 w-4" /></button></div><div className="mt-4 divide-y divide-dashem-border">{drilldown.items.map((item) => <div key={item.source_id} className="flex justify-between py-3 text-xs"><div><p className="font-black text-white">{item.source_type} · {item.source_id}</p><p className="text-dashem-muted">{new Date(item.occurred_at).toLocaleString('pt-BR')}</p></div><p className="font-black text-white">{formatCurrency(item.amount)}</p></div>)}</div></section>}

    <details className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><summary className="cursor-pointer font-black text-white">Fórmulas e fontes publicadas</summary><div className="mt-4 grid gap-3 md:grid-cols-2">{Object.entries(overview.formulas).map(([metric, formula]) => <div key={metric} className="rounded-xl bg-dashem-bg p-4"><p className="text-xs font-black text-dashem-red">{metric}</p><p className="mt-2 text-xs leading-5 text-dashem-muted">{formula}</p></div>)}</div></details>

    <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><h2 className="font-black text-white">Preparar e administrar a operação</h2><p className="mt-1 text-sm text-dashem-muted">Atalhos da retaguarda, separados da operação do PDV.</p><div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{shortcuts.map(([module, label, hint, Icon]) => <button key={module} onClick={() => onOpenModule?.(module)} className="group rounded-2xl border border-dashem-border bg-dashem-bg p-4 text-left hover:border-slate-600"><div className="flex justify-between"><Icon className="h-5 w-5 text-dashem-red" /><ArrowRight className="h-4 w-4 text-slate-600" /></div><p className="mt-4 text-sm font-black text-white">{label}</p><p className="mt-1 text-xs text-dashem-muted">{hint}</p></button>)}</div></section>
  </div>
}

function State({ text, error = false }: { text: string; error?: boolean }) {
  return <div className={`flex min-h-64 items-center justify-center rounded-3xl border border-dashem-border bg-dashem-surface text-sm font-bold ${error ? 'text-red-300' : 'text-dashem-muted'}`}>{!error && <Loader2 className="mr-3 h-5 w-5 animate-spin" />}{text}</div>
}
