import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Banknote, CheckCircle2, Clock3, Loader2, RefreshCw } from 'lucide-react'

import {
  fetchPlatformFinanceOverview,
  PlatformFinanceOverview,
  PlatformFinanceSubscription,
} from '../../services/api'

type FinanceFilter = 'ALL' | 'ACTIVE' | 'TRIAL' | 'OVERDUE' | 'PENDING'

const money = (value: number) => Number(value || 0).toLocaleString('pt-BR', {
  style: 'currency', currency: 'BRL',
})

export function FinanceSaasView() {
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
    if (filter === 'OVERDUE' || filter === 'PENDING') return item.billing_status === filter
    return item.subscription_status === filter
  }), [filter, overview])

  const cards: Array<{ label: string; value: string | number; filter: FinanceFilter; icon: typeof Banknote }> = [
    { label: 'MRR contratado', value: money(overview?.contracted_mrr ?? 0), filter: 'ACTIVE', icon: Banknote },
    { label: 'Assinaturas ativas', value: overview?.active_subscriptions ?? 0, filter: 'ACTIVE', icon: CheckCircle2 },
    { label: 'Em avaliação', value: overview?.trial_subscriptions ?? 0, filter: 'TRIAL', icon: Clock3 },
    { label: 'Em atraso', value: overview?.overdue_subscriptions ?? 0, filter: 'OVERDUE', icon: AlertTriangle },
  ]

  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div><p className="text-xs font-black uppercase tracking-wider text-[#E12120]">Financeiro do SaaS</p><h2 className="mt-2 text-3xl font-black">Saúde financeira contratual</h2><p className="mt-2 max-w-3xl text-slate-500">Mensalidades e situações contratuais do Dashem. Nenhum faturamento, caixa, venda ou lucro dos tenants é consultado.</p></div><button onClick={load} className="flex h-11 items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-4 text-sm font-black"><RefreshCw className="h-4 w-4" />Atualizar</button></div>
    <p className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-semibold text-blue-900">Base real disponível agora: assinaturas e mensalidades contratadas. Faturas, recebimentos, inadimplência por título e conciliação ainda não existem no domínio — por isso não são simulados nesta tela.</p>
    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
    {loading ? <Loader2 className="mx-auto my-24 h-8 w-8 animate-spin text-[#E12120]" /> : <>
      <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{cards.map(card => <button key={card.label} onClick={() => setFilter(card.filter)} className={`rounded-2xl border bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${filter === card.filter ? 'border-[#E12120] ring-2 ring-red-100' : 'border-slate-200'}`}><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase text-slate-400">{card.label}</p><p className="mt-3 text-2xl font-black">{card.value}</p></div><card.icon className="h-5 w-5 text-[#E12120]" /></div><p className="mt-4 text-xs font-bold text-slate-500">Clique para filtrar os contratos</p></button>)}</section>
      <SubscriptionTable rows={rows} filter={filter} onAll={() => setFilter('ALL')} />
    </>}
  </div>
}

function SubscriptionTable({ rows, filter, onAll }: { rows: PlatformFinanceSubscription[]; filter: FinanceFilter; onAll: () => void }) {
  return <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="flex items-center justify-between border-b border-slate-100 p-5"><div><h3 className="font-black">Contratos SaaS</h3><p className="text-sm text-slate-500">{filter === 'ALL' ? 'Todos os registros contratuais' : `Filtro ativo: ${filter}`}</p></div>{filter !== 'ALL' && <button onClick={onAll} className="text-sm font-black text-[#E12120]">Ver todos</button>}</div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-400"><tr><th className="px-5 py-3">Cliente</th><th className="px-5 py-3">Plano</th><th className="px-5 py-3">Assinatura</th><th className="px-5 py-3">Mensalidade</th><th className="px-5 py-3">Situação</th><th className="px-5 py-3">Próximo vencimento</th></tr></thead><tbody className="divide-y divide-slate-100">{rows.map(item => <tr key={item.tenant_id}><td className="px-5 py-4 font-black">{item.tenant_name}</td><td className="px-5 py-4">{item.plan_name || 'Sem plano'}</td><td className="px-5 py-4">{item.subscription_status}</td><td className="px-5 py-4 font-bold">{money(item.monthly_amount)}</td><td className="px-5 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${item.billing_status === 'OVERDUE' ? 'bg-red-50 text-red-700' : item.billing_status === 'CURRENT' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{item.billing_status}</span></td><td className="px-5 py-4">{item.next_due_date ? new Date(`${item.next_due_date}T12:00:00`).toLocaleDateString('pt-BR') : 'Não definido'}</td></tr>)}{rows.length === 0 && <tr><td colSpan={6} className="px-5 py-12 text-center text-slate-500">Nenhum contrato neste filtro.</td></tr>}</tbody></table></div></section>
}
