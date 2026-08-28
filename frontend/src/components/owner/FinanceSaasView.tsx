import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight, Banknote, CheckCircle2, Clock3, FileClock, Loader2,
  ReceiptText, RefreshCw, ShieldAlert, UserRoundCheck,
} from 'lucide-react'

import {
  fetchPlatformFinanceOverview,
  PlatformFinanceOverview,
  PlatformFinanceSubscription,
  SubscriptionStatus,
} from '../../services/api'

type FinanceFilter = 'ALL' | 'ACTIVE' | 'TRIAL' | 'PENDING' | 'BILLING_READY'

const money = (value: number) => Number(value || 0).toLocaleString('pt-BR', {
  style: 'currency', currency: 'BRL',
})

const subscriptionLabel: Record<SubscriptionStatus, string> = {
  PENDING: 'Pendente', TRIAL: 'Em avaliação', ACTIVE: 'Ativa',
  PAUSED: 'Pausada', CANCELED: 'Cancelada',
}

export function FinanceSaasView({ onTenant }: { onTenant: (tenantId: string) => void }) {
  const [overview, setOverview] = useState<PlatformFinanceOverview | null>(null)
  const [filter, setFilter] = useState<FinanceFilter>('ALL')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true); setError('')
    try { setOverview(await fetchPlatformFinanceOverview()) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível carregar o financeiro SaaS.') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const rows = useMemo(() => (overview?.subscriptions ?? []).filter(item => {
    if (filter === 'ALL') return true
    if (filter === 'BILLING_READY') return item.billing_account_ready
    return item.subscription_status === filter
  }), [filter, overview])

  const cards: Array<{ label: string; value: string | number; filter: FinanceFilter; icon: typeof Banknote; hint: string }> = [
    { label: 'MRR contratado', value: money(overview?.contracted_mrr ?? 0), filter: 'ACTIVE', icon: Banknote, hint: 'Soma das mensalidades de assinaturas ativas' },
    { label: 'Assinaturas ativas', value: overview?.active_subscriptions ?? 0, filter: 'ACTIVE', icon: CheckCircle2, hint: 'Contratos com assinatura ativa' },
    { label: 'Em avaliação', value: overview?.trial_subscriptions ?? 0, filter: 'TRIAL', icon: Clock3, hint: 'Assinaturas em período de avaliação' },
    { label: 'Contas aptas', value: `${overview?.billing_accounts_ready ?? 0}/${overview?.subscriptions.length ?? 0}`, filter: 'BILLING_READY', icon: UserRoundCheck, hint: 'Cadastro fiscal e contato de cobrança completos' },
  ]

  const planned = [
    { label: 'Faturas SaaS', available: overview?.facts.invoices, icon: FileClock, detail: 'Depende da entrega do domínio de faturas e itens.' },
    { label: 'Recebimentos', available: overview?.facts.payments, icon: ReceiptText, detail: 'Depende de pagamentos e alocações confirmados.' },
    { label: 'Inadimplência', available: overview?.facts.delinquency, icon: ShieldAlert, detail: 'Será derivada de faturas vencidas, nunca de campo manual.' },
  ]

  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div><p className="text-xs font-black uppercase tracking-wider text-[#E12120]">Financeiro do SaaS</p><h2 className="mt-2 text-3xl font-black">Saúde financeira contratual</h2><p className="mt-2 max-w-3xl text-slate-500">Mensalidades e assinaturas da Dashem baseadas em registros persistidos. Nenhum faturamento, caixa, venda ou lucro dos tenants é consultado.</p></div><button onClick={load} className="flex h-11 items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-4 text-sm font-black"><RefreshCw className="h-4 w-4" />Atualizar</button></div>
    <p className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-semibold text-blue-900">Disponível com fonte real: assinaturas, mensalidades e contas de cobrança SaaS. Recursos sem fatos persistidos aparecem abaixo como “Em implementação” e não recebem valor zero fictício.</p>
    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
    {loading ? <Loader2 className="mx-auto my-24 h-8 w-8 animate-spin text-[#E12120]" /> : <>
      <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{cards.map(card => <button key={card.label} onClick={() => setFilter(card.filter)} className={`rounded-2xl border bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${filter === card.filter ? 'border-[#E12120] ring-2 ring-red-100' : 'border-slate-200'}`}><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase text-slate-400">{card.label}</p><p className="mt-3 text-2xl font-black">{card.value}</p></div><card.icon className="h-5 w-5 text-[#E12120]" /></div><p className="mt-4 flex items-center justify-between text-xs font-bold text-slate-500">{card.hint}<ArrowRight className="h-4 w-4" /></p></button>)}</section>
      <SubscriptionTable rows={rows} filter={filter} onAll={() => setFilter('ALL')} onTenant={onTenant} />
      <section className="mt-6"><div><h3 className="font-black">Próximas capacidades financeiras</h3><p className="mt-1 text-sm text-slate-500">Estágio declarado pelo backend; sem totais até existirem os fatos correspondentes.</p></div><div className="mt-4 grid gap-4 md:grid-cols-3">{planned.map(item => <article key={item.label} className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5"><div className="flex items-start justify-between gap-3"><item.icon className="h-5 w-5 text-slate-500" /><span className={`rounded-full px-2.5 py-1 text-xs font-black ${item.available ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>{item.available ? 'Disponível' : 'Em implementação'}</span></div><h4 className="mt-4 font-black">{item.label}</h4><p className="mt-2 text-sm text-slate-500">{item.detail}</p></article>)}</div></section>
    </>}
  </div>
}

function SubscriptionTable({ rows, filter, onAll, onTenant }: { rows: PlatformFinanceSubscription[]; filter: FinanceFilter; onAll: () => void; onTenant: (tenantId: string) => void }) {
  return <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="flex items-center justify-between border-b border-slate-100 p-5"><div><h3 className="font-black">Contratos SaaS</h3><p className="text-sm text-slate-500">{filter === 'ALL' ? 'Todos os registros contratuais' : `Filtro ativo: ${filter}`}</p></div>{filter !== 'ALL' && <button onClick={onAll} className="text-sm font-black text-[#E12120]">Ver todos</button>}</div><div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-400"><tr><th className="px-5 py-3">Cliente</th><th className="px-5 py-3">Plano</th><th className="px-5 py-3">Assinatura</th><th className="px-5 py-3">Mensalidade</th><th className="px-5 py-3">Conta de cobrança</th><th className="px-5 py-3">Cobrança contratual prevista</th></tr></thead><tbody className="divide-y divide-slate-100">{rows.map(item => <tr key={item.tenant_id}><td className="px-5 py-4"><button onClick={() => onTenant(item.tenant_id)} className="flex items-center gap-2 text-left font-black hover:text-[#E12120]">{item.tenant_name}<ArrowRight className="h-4 w-4" /></button><p className="mt-1 text-xs text-slate-400">Contrato v{item.contract_version ?? '—'}</p></td><td className="px-5 py-4">{item.plan_name || 'Sem plano'}</td><td className="px-5 py-4">{subscriptionLabel[item.subscription_status]}</td><td className="px-5 py-4 font-bold">{money(item.monthly_amount)}</td><td className="px-5 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${item.billing_account_ready ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>{item.billing_account_ready ? 'APTA' : 'INCOMPLETA'}</span><p className="mt-2 text-xs text-slate-500">{item.billing_contact_email || 'Contato não configurado'}</p></td><td className="px-5 py-4">{item.next_due_date ? new Date(`${item.next_due_date}T12:00:00`).toLocaleDateString('pt-BR') : 'Não definida'}</td></tr>)}{rows.length === 0 && <tr><td colSpan={6} className="px-5 py-12 text-center text-slate-500">Nenhum contrato neste filtro.</td></tr>}</tbody></table></div></section>
}
