import React, { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, BadgeDollarSign, CalendarClock, RefreshCw, ShieldCheck } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { CreditPolicyProjection, Customer, fetchCreditPolicy, fetchCustomers, fetchReceivables, Receivable, saveCreditPolicy } from '../../services/api'

const money = (value: number) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value)

export const ReceivablesManager: React.FC = () => {
  const { tenant, store } = usePos()
  const headers = useMemo(() => ({ 'X-Tenant-ID': tenant!.id, 'X-Store-ID': store!.id }), [tenant, store])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [receivables, setReceivables] = useState<Receivable[]>([])
  const [customerId, setCustomerId] = useState('')
  const [policy, setPolicy] = useState<CreditPolicyProjection | null>(null)
  const [limit, setLimit] = useState('0')
  const [terms, setTerms] = useState('30')
  const [blocked, setBlocked] = useState(false)
  const [allowOverdue, setAllowOverdue] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const load = async () => {
    setError('')
    try {
      const [clients, titles] = await Promise.all([fetchCustomers(headers), fetchReceivables(headers)])
      setCustomers(clients); setReceivables(titles)
      if (!customerId && clients[0]) setCustomerId(clients[0].id)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Falha ao carregar o financeiro.') }
  }
  useEffect(() => { void load() }, [headers])
  useEffect(() => {
    if (!customerId) return
    fetchCreditPolicy(headers, customerId).then((value) => {
      setPolicy(value); setLimit(String(value.policy.credit_limit)); setTerms(String(value.policy.terms_days))
      setBlocked(value.policy.status === 'BLOCKED'); setAllowOverdue(value.policy.allow_overdue)
    }).catch(() => { setPolicy(null); setLimit('0'); setTerms('30'); setBlocked(false); setAllowOverdue(false) })
  }, [customerId, headers])

  const save = async () => {
    setSaving(true); setError('')
    try {
      setPolicy(await saveCreditPolicy(headers, customerId, {
        credit_limit: Number(limit), terms_days: Number(terms), allow_overdue: allowOverdue,
        status: blocked ? 'BLOCKED' : 'ACTIVE', expected_version: policy?.policy.version,
      }))
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Falha ao salvar.') } finally { setSaving(false) }
  }
  const open = receivables.filter((item) => ['OPEN', 'PARTIALLY_PAID', 'OVERDUE'].includes(item.status))
  const balance = open.reduce((sum, item) => sum + Number(item.balance), 0)
  const overdue = open.filter((item) => new Date(item.due_at) < new Date()).reduce((sum, item) => sum + Number(item.balance), 0)

  return <div className="space-y-6">
    <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-dashem-red">Financeiro · fonte persistida</p><h1 className="mt-1 text-2xl font-black text-white">Crediário e contas a receber</h1><p className="mt-1 text-xs text-dashem-muted">Limite, exposição e títulos são calculados no servidor e isolados por tenant.</p></div><button onClick={() => void load()} className="flex h-10 items-center gap-2 rounded-xl border border-dashem-border px-4 text-xs font-black"><RefreshCw className="h-4 w-4" />Atualizar</button></header>
    <section className="grid gap-3 sm:grid-cols-3"><Metric icon={BadgeDollarSign} label="Saldo em aberto" value={money(balance)} /><Metric icon={AlertTriangle} label="Saldo vencido" value={money(overdue)} danger={overdue > 0} /><Metric icon={CalendarClock} label="Títulos ativos" value={String(open.length)} /></section>
    <section className="grid gap-5 xl:grid-cols-[.9fr_1.5fr]"><div className="rounded-3xl border border-dashem-border bg-dashem-surface p-5"><div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-emerald-400" /><h2 className="font-black">Política do cliente</h2></div><label className="mt-5 block text-xs font-bold text-dashem-muted">Cliente<select value={customerId} onChange={(event) => setCustomerId(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm text-white">{customers.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.cpf_cnpj || 'documento pendente'}</option>)}</select></label><div className="mt-4 grid grid-cols-2 gap-3"><Field label="Limite" value={limit} onChange={setLimit} /><Field label="Prazo (dias)" value={terms} onChange={setTerms} /></div><label className="mt-4 flex items-center gap-2 text-xs font-bold"><input type="checkbox" checked={allowOverdue} onChange={(e) => setAllowOverdue(e.target.checked)} />Permitir novo crédito com atraso</label><label className="mt-3 flex items-center gap-2 text-xs font-bold text-amber-300"><input type="checkbox" checked={blocked} onChange={(e) => setBlocked(e.target.checked)} />Bloquear crediário</label>{policy && <div className="mt-4 grid grid-cols-2 gap-2 rounded-2xl bg-dashem-bg p-4 text-xs"><span className="text-dashem-muted">Exposição</span><strong className="text-right">{money(policy.exposure)}</strong><span className="text-dashem-muted">Disponível</span><strong className="text-right text-emerald-400">{money(policy.available)}</strong></div>}<button disabled={!customerId || saving} onClick={() => void save()} className="mt-5 h-11 w-full rounded-xl bg-dashem-red text-xs font-black disabled:opacity-50">{saving ? 'Salvando…' : 'Salvar política auditada'}</button></div>
    <div className="overflow-hidden rounded-3xl border border-dashem-border bg-dashem-surface"><div className="border-b border-dashem-border p-5"><h2 className="font-black">Títulos emitidos</h2><p className="text-xs text-dashem-muted">Principal imutável, saldo e vínculo com venda/negociação.</p></div><div className="divide-y divide-dashem-border">{receivables.length === 0 ? <p className="p-8 text-center text-sm text-dashem-muted">Nenhum título emitido neste contexto.</p> : receivables.map((item) => { const customer = customers.find((value) => value.id === item.customer_id); return <div key={item.id} className="grid gap-3 p-4 text-xs sm:grid-cols-[1.2fr_.8fr_.8fr_.7fr]"><div><p className="font-black text-white">{customer?.name || item.customer_id}</p><p className="mt-1 font-mono text-[10px] text-dashem-muted">{item.id}</p></div><Value label="Principal" value={money(Number(item.principal_amount))} /><Value label="Saldo" value={money(Number(item.balance))} accent /><Value label="Vencimento" value={new Date(item.due_at).toLocaleDateString('pt-BR')} /></div> })}</div></div></section>{error && <p className="rounded-xl border border-red-900 bg-red-950/50 p-3 text-xs font-bold text-red-200">{error}</p>}
  </div>
}

function Metric({ icon: Icon, label, value, danger = false }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string; danger?: boolean }) { return <div className="rounded-2xl border border-dashem-border bg-dashem-surface p-5"><Icon className={`h-5 w-5 ${danger ? 'text-red-400' : 'text-dashem-red'}`} /><p className="mt-4 text-[10px] font-black uppercase tracking-wider text-dashem-muted">{label}</p><p className={`mt-1 text-2xl font-black ${danger ? 'text-red-300' : 'text-white'}`}>{value}</p></div> }
function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="text-xs font-bold text-dashem-muted">{label}<input type="number" min="0" value={value} onChange={(event) => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm text-white" /></label> }
function Value({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) { return <div><p className="text-dashem-muted">{label}</p><p className={`mt-1 font-black ${accent ? 'text-amber-300' : ''}`}>{value}</p></div> }
