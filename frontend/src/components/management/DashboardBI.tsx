import { ResponsiveTable } from '../common/DataTable'
import React, { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle, ArrowRight, Banknote, Boxes, CheckCircle2, ChefHat, CircleDollarSign, Database,
  Monitor, Receipt, RefreshCw, ShoppingCart, Store as StoreIcon, TrendingUp, Users, X,
} from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { BiDrilldown, fetchBiDrilldown, fetchManagementOverview, fetchOperationalProductivity, ManagementOverview, OperationalProductivity, rebuildOperationalProductivity, refreshBiProjection } from '../../services/api'
import { formatCurrency, formatProductDateTime } from '../../utils/format'
import { Button } from '../common/Button'
import { Card, SectionHeader } from '../common/Surface'
import { StatCard } from '../common/StatCard'
import { Badge } from '../common/Badge'
import { EmptyState, ErrorState, LoadingState } from '../common/EmptyState'

type ShortcutModule = 'products' | 'tables' | 'devices' | 'team'

/**
 * Human names for the metric keys published by the BI service. The technical key
 * stays visible next to the label inside "Como calculamos", so traceability is kept
 * without putting column names on the dashboard itself.
 */
const METRIC_LABELS: Record<string, string> = {
  net_revenue: 'Faturamento líquido',
  average_ticket: 'Ticket médio',
  confirmed_receipts: 'Recebimentos confirmados',
  refunds_total: 'Estornos',
  table_average_minutes: 'Tempo médio de mesa',
  production_average_minutes: 'Tempo médio de produção',
  approval_rate: 'Taxa de aprovação',
  execution_rate: 'Taxa de execução',
  confirmation_rate: 'Taxa de confirmação',
  confirmed_amount: 'Valor confirmado',
}

const metricLabel = (key: string) => METRIC_LABELS[key]
  ?? key.replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase())

export const DashboardBI: React.FC<{
  onOpenModule?: (module: ShortcutModule) => void
  availableModules?: ReadonlySet<string>
}> = ({ onOpenModule, availableModules }) => {
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
  if (error) return <ErrorState text={error} action={<Button variant="secondary" icon={RefreshCw} onClick={load}>Tentar novamente</Button>} />
  if (!overview || !productivity) return <LoadingState text="Carregando indicadores da unidade..." />

  const primaryCards = [
    { label: 'Faturamento hoje', value: formatCurrency(overview.revenue_today), meta: `${overview.sales_today} venda(s)`, icon: CircleDollarSign, accent: 'positive' as const },
    { label: `Faturamento ${days} dias`, value: formatCurrency(overview.revenue_30d), meta: `${overview.sales_30d} venda(s)`, icon: TrendingUp, accent: 'brand' as const },
    { label: 'Ticket médio', value: formatCurrency(overview.average_ticket_30d), meta: `Últimos ${days} dias`, icon: Receipt, accent: 'neutral' as const },
    { label: 'Vendas em aberto', value: String(overview.open_sales), meta: 'Agora, no balcão', icon: ShoppingCart, accent: 'warning' as const },
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
  const shortcuts = ([
    ['products', 'Cadastrar mercadorias', 'Produtos, preços e acesso rápido', Boxes],
    ['tables', 'Organizar atendimento', 'Ambientes, mesas e reservas', ChefHat],
    ['devices', 'Preparar terminais', 'PDV, KDS e impressão', Monitor],
    ['team', 'Montar a equipe', 'Convites, funções e unidades', Users],
  ] as const).filter(([module]) => !availableModules || availableModules.has(module))
  const setupFacts: Array<{
    label: string
    value: string
    ready: boolean
    module?: ShortcutModule
    icon: React.ComponentType<{ className?: string }>
  }> = [
    { label: 'Unidade em contexto', value: store?.name ?? 'Não selecionada', ready: Boolean(store), icon: StoreIcon },
    { label: 'Catálogo', value: `${overview.products} produto(s)`, ready: overview.products > 0, module: 'products', icon: Boxes },
    { label: 'Equipe ativa', value: `${overview.active_team_members} integrante(s)`, ready: overview.active_team_members > 0, module: 'team', icon: Users },
    { label: 'Terminais configurados', value: `${overview.resource_usage.DEVICES?.configured ?? 0} dispositivo(s)`, ready: (overview.resource_usage.DEVICES?.configured ?? 0) > 0, module: 'devices', icon: Monitor },
  ]
  // The setup block only takes the top of the page while something is still missing.
  const setupPending = setupFacts.some((fact) => !fact.ready)
  const dataDelayed = Boolean(overview.source_watermark) && overview.projection_lag_seconds > 300

  return <div className="space-y-6">
    {/* Page header: identity, period control and data freshness */}
    <Card tone="raised" padding="lg">
      <SectionHeader
        eyebrow="Visão geral da unidade"
        title={store?.name ?? 'Unidade'}
        description={`${tenant?.name ?? ''} · atualizado em ${formatProductDateTime(overview.generated_at)}`}
        actions={<>
          <div className="flex rounded-xl border border-dashem-border bg-dashem-surface-elevated p-1">
            {[7, 30, 90].map((period) => (
              <button
                key={period}
                onClick={() => setDays(period)}
                className={`min-h-9 rounded-lg px-3 text-xs font-black transition
                  ${days === period ? 'bg-brand text-brand-contrast shadow-sm' : 'text-dashem-muted hover:text-dashem-strong'}`}
              >
                {period} dias
              </button>
            ))}
          </div>
          {permissions.includes('bi.refresh') && (
            <Button icon={RefreshCw} onClick={refresh} loading={refreshing}>Atualizar</Button>
          )}
        </>}
      />
      <div className="mt-5">
        {!overview.source_watermark
          ? <Badge tone="neutral" icon={Database}>Ainda não há movimento registrado neste período</Badge>
          : dataDelayed
            ? <Badge tone="warning" icon={Database}>Dados com atraso de {overview.projection_lag_seconds}s · última leitura {formatProductDateTime(overview.source_watermark)}</Badge>
            : <Badge tone="positive" icon={Database}>Dados em dia · última leitura {formatProductDateTime(overview.source_watermark)}</Badge>}
      </div>
    </Card>

    {/* Primary numbers come first: this is what the manager opens the page for */}
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {primaryCards.map((card) => <StatCard key={card.label} {...card} />)}
    </section>

    {/* Revenue trend + what needs attention */}
    <section className="grid gap-5 xl:grid-cols-[1.45fr_1fr]">
      <Card padding="lg">
        <SectionHeader
          title="Faturamento diário"
          description="Clique em uma barra para ver as vendas que compõem o dia."
          actions={<TrendingUp className="h-5 w-5 text-brand-ink" />}
        />
        {/* Fixed height: letting the plot grow to match a taller neighbour turned a
            single day of revenue into a full-height block. */}
        <div className="mt-6 flex h-48 items-end gap-1.5">
          {chart.map((item) => (
            <button
              type="button"
              onClick={() => openDay(item.date)}
              key={item.date}
              className="group flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-2"
              title={`${item.date}: ${formatCurrency(item.revenue)} · ${item.sales} venda(s)`}
            >
              <span
                className="w-full rounded-t-lg bg-brand/85 transition group-hover:bg-brand"
                style={{ height: `${Math.max(item.revenue > 0 ? 8 : 2, (item.revenue / maxRevenue) * 100)}%` }}
              />
              <span className="hidden text-xs font-bold text-dashem-muted sm:block">{item.date.slice(8)}</span>
            </button>
          ))}
        </div>
        <p className="mt-3 text-xs text-dashem-muted">Maior dia do período: {formatCurrency(maxRevenue)}</p>
      </Card>

      <Card padding="lg">
        <SectionHeader title="Pendências que exigem atenção" actions={<AlertTriangle className="h-5 w-5 text-amber-500" />} />
        {overview.alerts.length
          ? <ul className="mt-4 space-y-2">
              {overview.alerts.map((alert) => (
                <li key={alert} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm font-semibold leading-5 text-amber-800">{alert}</li>
              ))}
            </ul>
          : <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-bold text-emerald-700">Nenhuma pendência no momento.</div>}
        <div className="mt-4 grid grid-cols-2 gap-2">
          {operations.map(([label, value, Icon]) => (
            <div key={label} className="rounded-xl border border-dashem-border bg-dashem-surface-elevated p-3">
              <Icon className="h-4 w-4 text-dashem-muted" />
              <p className="mt-2 font-black text-dashem-strong">{value}</p>
              <p className="mt-1 text-xs font-bold text-dashem-muted">{label}</p>
            </div>
          ))}
        </div>
      </Card>
    </section>

    {/* Setup: prominent while incomplete, a quiet shortcut row once everything is ready */}
    {setupPending ? (
      <Card padding="lg">
        <SectionHeader
          title="Prontidão da configuração"
          description="Complete estes itens para a unidade operar sem bloqueios."
        />
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {setupFacts.map(({ label, value, ready, module, icon: Icon }) => {
            const actionable = module && availableModules?.has(module)
            const body = <>
              <div className="flex items-center justify-between">
                <Icon className="h-5 w-5 text-dashem-muted" />
                {ready ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> : <AlertTriangle className="h-5 w-5 text-amber-500" />}
              </div>
              <p className="mt-4 text-xs font-black uppercase tracking-wide text-dashem-muted">{label}</p>
              <p className="mt-1 text-sm font-black text-dashem-strong">{value}</p>
              {actionable && !ready && <p className="mt-3 flex items-center gap-1 text-xs font-black text-brand-ink">Configurar <ArrowRight className="h-3.5 w-3.5" /></p>}
            </>
            return actionable
              ? <button key={label} onClick={() => onOpenModule?.(module)} className="rounded-2xl border border-dashem-border bg-dashem-surface-elevated p-4 text-left transition hover:border-brand/40 hover:bg-dashem-surface">{body}</button>
              : <article key={label} className="rounded-2xl border border-dashem-border bg-dashem-surface-elevated p-4">{body}</article>
          })}
        </div>
      </Card>
    ) : null}

    <Card padding="lg">
      <SectionHeader
        title="Preparar e administrar a operação"
        description="Atalhos para as tarefas de configuração autorizadas para o seu perfil."
      />
      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {shortcuts.map(([module, label, hint, Icon]) => (
          <button
            key={module}
            onClick={() => onOpenModule?.(module)}
            className="group rounded-2xl border border-dashem-border bg-dashem-surface-elevated p-4 text-left transition hover:border-brand/40 hover:bg-dashem-surface"
          >
            <div className="flex justify-between">
              <Icon className="h-5 w-5 text-brand-ink" />
              <ArrowRight className="h-4 w-4 text-dashem-muted transition group-hover:translate-x-0.5" />
            </div>
            <p className="mt-4 text-sm font-black text-dashem-strong">{label}</p>
            <p className="mt-1 text-xs leading-5 text-dashem-muted">{hint}</p>
          </button>
        ))}
      </div>
    </Card>

    {/* Operator productivity */}
    <Card padding="lg">
      <SectionHeader
        title="Produtividade por operador e turno"
        description="Calculada a partir da cadeia de solicitação, autorização, execução e resultado do pagamento."
        actions={<span className="text-xs font-bold text-dashem-muted">
          {productivity.source_watermark ? `Dados até ${formatProductDateTime(productivity.source_watermark)}` : 'Sem eventos no período'}
        </span>}
      />
      {productivity.items.length === 0
        ? <EmptyState
            className="mt-5"
            icon={Users}
            title="Nenhum pagamento registrado por operador neste período"
            description="Assim que a equipe finalizar vendas com sessão autenticada, a produtividade aparece aqui."
          />
        : <div className="mt-5 overflow-x-auto">
            <ResponsiveTable className="w-full min-w-[760px] text-left text-xs">
              <thead className="text-[10px] font-black uppercase tracking-wide text-dashem-muted">
                <tr>
                  <th className="pb-3">Operador</th><th className="pb-3">Turnos</th><th className="pb-3">Solicitados</th>
                  <th className="pb-3">Executados</th><th className="pb-3">Confirmados</th><th className="pb-3">Falhas</th>
                  <th className="pb-3">Conversão</th><th className="pb-3 text-right">Valor confirmado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-dashem-border">
                {productivity.items.map((item) => (
                  <tr key={item.operator_id}>
                    <td className="py-4 font-black text-dashem-strong">{item.operator_name}</td>
                    <td className="py-4 text-dashem-muted">{item.shift_count}</td>
                    <td className="py-4 text-dashem-muted">{item.requested_count}</td>
                    <td className="py-4 text-dashem-muted">{item.executed_count}</td>
                    <td className="py-4 font-bold text-emerald-600">{item.confirmed_count}</td>
                    <td className="py-4 font-bold text-red-600">{item.failed_count}</td>
                    <td className="py-4 font-black text-dashem-strong">{(item.confirmation_rate * 100).toFixed(1)}%</td>
                    <td className="py-4 text-right font-black text-dashem-strong">{formatCurrency(item.confirmed_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </ResponsiveTable>
          </div>}
    </Card>

    {drilldown && (
      <Card padding="lg">
        <SectionHeader
          eyebrow="Detalhamento rastreável"
          title={`${new Date(`${drilldown.competence_date}T12:00:00`).toLocaleDateString('pt-BR')} · ${drilldown.total} origem(ns)`}
          actions={<Button variant="secondary" icon={X} onClick={() => setDrilldown(null)} aria-label="Fechar detalhamento" className="px-3" />}
        />
        <div className="mt-4 divide-y divide-dashem-border">
          {drilldown.items.map((item) => (
            <div key={item.source_id} className="flex items-center justify-between gap-3 py-3 text-xs">
              <div className="min-w-0">
                <p className="truncate font-black text-dashem-strong">{item.source_type} · {item.source_id}</p>
                <p className="text-dashem-muted">{formatProductDateTime(item.occurred_at)}</p>
              </div>
              <p className="shrink-0 font-black text-dashem-strong">{formatCurrency(item.amount)}</p>
            </div>
          ))}
        </div>
      </Card>
    )}

    {/*
      Formulas stay published for auditability, but collapsed and named in plain
      Portuguese; the technical key remains next to each label.
    */}
    <details className="rounded-2xl border border-dashem-border bg-dashem-surface">
      <summary className="cursor-pointer px-6 py-4 text-sm font-black text-dashem-strong">Como calculamos estes indicadores</summary>
      <div className="space-y-6 px-6 pb-6">
        <FormulaGroup title="Indicadores gerenciais" formulas={overview.formulas} />
        <FormulaGroup title="Produtividade" formulas={productivity.formulas} />
      </div>
    </details>

  </div>
}

function FormulaGroup({ title, formulas }: { title: string; formulas: Record<string, string> }) {
  const entries = Object.entries(formulas)
  if (entries.length === 0) return null
  return (
    <div>
      <p className="text-xs font-black uppercase tracking-wide text-dashem-muted">{title}</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {entries.map(([metric, formula]) => (
          <div key={metric} className="rounded-xl border border-dashem-border bg-dashem-surface-elevated p-4">
            <p className="text-xs font-black text-dashem-strong">{metricLabel(metric)}</p>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-wide text-dashem-muted">{metric}</p>
            <p className="mt-2 text-xs leading-5 text-dashem-muted">{formula}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
