import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight, FilePlus2, Loader2, ReceiptText, RefreshCw, ShieldAlert,
  Download, Eye, X,
} from 'lucide-react'

import {
  fetchPlatformFinanceOverview, fetchSaasInvoice, fetchSaasInvoiceExport,
  fetchSaasInvoices, generateSaasInvoices, issueSaasInvoice, voidSaasInvoice,
  PlatformFinanceOverview, PlatformFinanceSubscription, SaasInvoice,
  SaasInvoiceDetail, SaasInvoiceListItem, SaasInvoiceStatus, SubscriptionStatus,
} from '../../services/api'

type ContractFilter = 'ALL' | 'ACTIVE' | 'TRIAL' | 'PENDING' | 'BILLING_READY'
type InvoiceFilter = 'ALL' | SaasInvoiceStatus

const money = (value: number) => Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const localDate = (value?: string) => value ? new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString('pt-BR') : '—'
const competenceNow = () => new Date().toISOString().slice(0, 7)

const subscriptionLabel: Record<SubscriptionStatus, string> = {
  PENDING: 'Pendente', TRIAL: 'Em avaliação', ACTIVE: 'Ativa', PAUSED: 'Pausada', CANCELED: 'Cancelada',
}
const invoiceLabel: Record<SaasInvoiceStatus, string> = {
  DRAFT: 'Rascunho', OPEN: 'Aberta', PARTIALLY_PAID: 'Parcialmente paga', PAID: 'Paga',
  OVERDUE: 'Vencida', VOID: 'Anulada', UNCOLLECTIBLE: 'Incobrável',
}

export function FinanceSaasView({ onTenant }: { onTenant: (tenantId: string) => void }) {
  const [overview, setOverview] = useState<PlatformFinanceOverview | null>(null)
  const [invoices, setInvoices] = useState<SaasInvoiceListItem[]>([])
  const [invoiceTotal, setInvoiceTotal] = useState(0)
  const [contractFilter, setContractFilter] = useState<ContractFilter>('ALL')
  const [invoiceFilter, setInvoiceFilter] = useState<InvoiceFilter>('ALL')
  const [competence, setCompetence] = useState(competenceNow)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [detail, setDetail] = useState<SaasInvoiceDetail | null>(null)
  const [command, setCommand] = useState<{ kind: 'ISSUE' | 'VOID'; invoice: SaasInvoice } | null>(null)

  const loadOverview = async () => setOverview(await fetchPlatformFinanceOverview())
  const loadInvoices = async (filter = invoiceFilter) => {
    const result = await fetchSaasInvoices(filter === 'ALL' ? undefined : filter)
    setInvoices(result.items); setInvoiceTotal(result.total)
  }
  const refresh = async () => {
    setLoading(true); setError('')
    try { await Promise.all([loadOverview(), loadInvoices()]) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível carregar o financeiro SaaS.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void refresh() }, [])
  useEffect(() => {
    if (!loading) void loadInvoices(invoiceFilter).catch(reason => setError(reason instanceof Error ? reason.message : 'Não foi possível filtrar as faturas.'))
  }, [invoiceFilter])

  const contractRows = useMemo(() => (overview?.subscriptions ?? []).filter(item => {
    if (contractFilter === 'ALL') return true
    if (contractFilter === 'BILLING_READY') return item.billing_account_ready
    return item.subscription_status === contractFilter
  }), [contractFilter, overview])

  const generate = async () => {
    setWorking(true); setError(''); setNotice('')
    try {
      const result = await generateSaasInvoices(`${competence}-01`)
      setNotice(`${result.generated.length} fatura(s) gerada(s), ${result.existing.length} já existente(s) e ${result.skipped.length} não gerada(s) por fonte incompleta.`)
      await Promise.all([loadOverview(), loadInvoices()])
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível gerar as faturas.') }
    finally { setWorking(false) }
  }
  const exportCsv = async () => {
    setWorking(true); setError('')
    try {
      const blob = await fetchSaasInvoiceExport()
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a')
      anchor.href = url; anchor.download = `faturas-saas-${new Date().toISOString().slice(0, 10)}.csv`; anchor.click()
      URL.revokeObjectURL(url)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível exportar as faturas.') }
    finally { setWorking(false) }
  }
  const openDetail = async (invoiceId: string) => {
    setWorking(true); setError('')
    try { setDetail(await fetchSaasInvoice(invoiceId)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível abrir a fatura.') }
    finally { setWorking(false) }
  }

  const invoiceCards: Array<{ label: string; value: string | number; filter: InvoiceFilter; hint: string }> = [
    { label: 'Faturado SaaS', value: money(overview?.invoiced_total ?? 0), filter: 'OPEN', hint: 'Faturas emitidas e não anuladas' },
    { label: 'Saldo aberto', value: money(overview?.open_invoice_balance ?? 0), filter: 'OPEN', hint: 'Saldo real das faturas abertas' },
    { label: 'Rascunhos', value: overview?.draft_invoices ?? 0, filter: 'DRAFT', hint: 'Documentos ainda não emitidos' },
    { label: 'Anuladas', value: overview?.void_invoices ?? 0, filter: 'VOID', hint: 'Documentos anulados com motivo' },
  ]
  const contractCards: Array<{ label: string; value: string | number; filter: ContractFilter; hint: string }> = [
    { label: 'MRR contratado', value: money(overview?.contracted_mrr ?? 0), filter: 'ACTIVE', hint: 'Mensalidades das assinaturas ativas' },
    { label: 'Assinaturas ativas', value: overview?.active_subscriptions ?? 0, filter: 'ACTIVE', hint: 'Contratos com assinatura ativa' },
    { label: 'Em avaliação', value: overview?.trial_subscriptions ?? 0, filter: 'TRIAL', hint: 'Assinaturas em período de avaliação' },
    { label: 'Contas aptas', value: `${overview?.billing_accounts_ready ?? 0}/${overview?.subscriptions.length ?? 0}`, filter: 'BILLING_READY', hint: 'Cadastro fiscal e contato completos' },
  ]

  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
    <header className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
      <div><p className="text-xs font-black uppercase tracking-wider text-[#E12120]">Financeiro do SaaS</p><h2 className="mt-2 text-3xl font-black">Saúde financeira contratual</h2><p className="mt-2 max-w-3xl text-slate-500">Assinaturas e faturas da Dashem baseadas em registros persistidos. Nenhum faturamento, caixa, venda ou lucro dos tenants é consultado.</p></div>
      <div className="flex flex-wrap gap-2"><button onClick={() => void refresh()} disabled={loading || working} className="flex h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 text-sm font-black disabled:opacity-50"><RefreshCw className="h-4 w-4" />Atualizar</button><button onClick={() => void exportCsv()} disabled={working} className="flex h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 text-sm font-black disabled:opacity-50"><Download className="h-4 w-4" />Exportar CSV</button></div>
    </header>
    <p className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-semibold text-blue-900">Faturas exibidas abaixo existem no domínio financeiro SaaS. Recebimentos e inadimplência permanecem identificados como “Em implementação” até seus fatos serem persistidos.</p>
    {error && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
    {notice && <p className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-bold text-emerald-800">{notice}</p>}
    {loading ? <Loader2 className="mx-auto my-24 h-8 w-8 animate-spin text-[#E12120]" /> : <>
      <SectionTitle title="Faturamento SaaS" detail="Valores derivados das faturas persistidas." />
      <section className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{invoiceCards.map(card => <MetricCard key={card.label} {...card} active={invoiceFilter === card.filter} onClick={() => { setInvoiceFilter(card.filter); document.getElementById('saas-invoices')?.scrollIntoView({ behavior: 'smooth' }) }} />)}</section>
      <section className="mt-5 flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:flex-row sm:items-end sm:justify-between"><label className="text-sm font-black">Competência<input aria-label="Competência" type="month" value={competence} onChange={event => setCompetence(event.target.value)} className="mt-2 block h-11 rounded-xl border border-slate-300 px-3 font-medium" /></label><button onClick={() => void generate()} disabled={working || !competence} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-[#E12120] px-5 text-sm font-black text-white disabled:opacity-50">{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePlus2 className="h-4 w-4" />}Gerar faturas da competência</button></section>
      <InvoiceTable rows={invoices} total={invoiceTotal} filter={invoiceFilter} onAll={() => setInvoiceFilter('ALL')} onDetail={openDetail} onCommand={setCommand} />
      <SectionTitle title="Base contratual" detail="Assinaturas que alimentam a geração das faturas." />
      <section className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{contractCards.map(card => <MetricCard key={card.label} {...card} active={contractFilter === card.filter} onClick={() => setContractFilter(card.filter)} />)}</section>
      <SubscriptionTable rows={contractRows} filter={contractFilter} onAll={() => setContractFilter('ALL')} onTenant={onTenant} />
      <section className="mt-7"><SectionTitle title="Próximas capacidades financeiras" detail="Nenhum total é exibido antes de existirem fatos persistidos." /><div className="mt-4 grid gap-4 md:grid-cols-2"><PlannedCard icon={ReceiptText} label="Recebimentos" detail="Depende de pagamentos e alocações confirmados." /><PlannedCard icon={ShieldAlert} label="Inadimplência" detail="Será derivada de faturas vencidas e saldos reais, nunca de campo manual." /></div></section>
    </>}
    {detail && <InvoiceDetailModal detail={detail} onClose={() => setDetail(null)} />}
    {command && <InvoiceCommandModal command={command} onClose={() => setCommand(null)} onDone={async () => { setCommand(null); await Promise.all([loadOverview(), loadInvoices()]) }} />}
  </div>
}

function SectionTitle({ title, detail }: { title: string; detail: string }) { return <div className="mt-7"><h3 className="text-lg font-black">{title}</h3><p className="mt-1 text-sm text-slate-500">{detail}</p></div> }
function MetricCard({ label, value, hint, active, onClick }: { label: string; value: string | number; hint: string; active: boolean; onClick: () => void }) { return <button onClick={onClick} className={`rounded-2xl border bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${active ? 'border-[#E12120] ring-2 ring-red-100' : 'border-slate-200'}`}><p className="text-xs font-black uppercase text-slate-400">{label}</p><p className="mt-3 text-2xl font-black">{value}</p><p className="mt-4 flex items-center justify-between text-xs font-bold text-slate-500">{hint}<ArrowRight className="h-4 w-4" /></p></button> }

function InvoiceTable({ rows, total, filter, onAll, onDetail, onCommand }: { rows: SaasInvoiceListItem[]; total: number; filter: InvoiceFilter; onAll: () => void; onDetail: (id: string) => void; onCommand: (value: { kind: 'ISSUE' | 'VOID'; invoice: SaasInvoice }) => void }) {
  return <section id="saas-invoices" className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="flex items-center justify-between border-b border-slate-100 p-5"><div><h3 className="font-black">Faturas SaaS</h3><p className="text-sm text-slate-500">{filter === 'ALL' ? `${total} documento(s)` : `${invoiceLabel[filter]} · ${total} documento(s)`}</p></div>{filter !== 'ALL' && <button onClick={onAll} className="text-sm font-black text-[#E12120]">Ver todas</button>}</div><div className="overflow-x-auto"><table className="w-full min-w-[1050px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-400"><tr><th className="px-5 py-3">Número</th><th className="px-5 py-3">Cliente</th><th className="px-5 py-3">Competência</th><th className="px-5 py-3">Vencimento</th><th className="px-5 py-3">Situação</th><th className="px-5 py-3">Total</th><th className="px-5 py-3">Ações</th></tr></thead><tbody className="divide-y divide-slate-100">{rows.map(({ invoice, tenant_name }) => <tr key={invoice.id}><td className="px-5 py-4 font-black">{invoice.public_number}</td><td className="px-5 py-4">{tenant_name}<p className="mt-1 text-xs text-slate-400">Contrato v{invoice.contract_version}</p></td><td className="px-5 py-4">{localDate(invoice.period_start)}</td><td className="px-5 py-4">{localDate(invoice.due_date)}</td><td className="px-5 py-4"><StatusBadge status={invoice.status} /></td><td className="px-5 py-4 font-black">{money(invoice.total_amount)}</td><td className="px-5 py-4"><div className="flex gap-2"><button title="Ver detalhes" onClick={() => onDetail(invoice.id)} className="rounded-lg border p-2"><Eye className="h-4 w-4" /></button>{invoice.status === 'DRAFT' && <button onClick={() => onCommand({ kind: 'ISSUE', invoice })} className="rounded-lg bg-[#E12120] px-3 py-2 text-xs font-black text-white">Emitir</button>}{invoice.status === 'OPEN' && <button onClick={() => onCommand({ kind: 'VOID', invoice })} className="rounded-lg border border-red-200 px-3 py-2 text-xs font-black text-red-700">Anular</button>}</div></td></tr>)}{rows.length === 0 && <tr><td colSpan={7} className="px-5 py-12 text-center text-slate-500">Nenhuma fatura neste filtro.</td></tr>}</tbody></table></div></section>
}
function StatusBadge({ status }: { status: SaasInvoiceStatus }) { return <span className={`rounded-full px-2.5 py-1 text-xs font-black ${status === 'OPEN' ? 'bg-blue-50 text-blue-700' : status === 'DRAFT' ? 'bg-amber-50 text-amber-800' : status === 'VOID' ? 'bg-slate-100 text-slate-600' : 'bg-emerald-50 text-emerald-700'}`}>{invoiceLabel[status]}</span> }

function SubscriptionTable({ rows, filter, onAll, onTenant }: { rows: PlatformFinanceSubscription[]; filter: ContractFilter; onAll: () => void; onTenant: (tenantId: string) => void }) {
  return <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="flex items-center justify-between border-b border-slate-100 p-5"><div><h3 className="font-black">Contratos SaaS</h3><p className="text-sm text-slate-500">{filter === 'ALL' ? 'Todos os registros contratuais' : `Filtro ativo: ${filter}`}</p></div>{filter !== 'ALL' && <button onClick={onAll} className="text-sm font-black text-[#E12120]">Ver todos</button>}</div><div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-400"><tr><th className="px-5 py-3">Cliente</th><th className="px-5 py-3">Plano</th><th className="px-5 py-3">Assinatura</th><th className="px-5 py-3">Mensalidade</th><th className="px-5 py-3">Conta de cobrança</th><th className="px-5 py-3">Próximo vencimento contratual</th></tr></thead><tbody className="divide-y divide-slate-100">{rows.map(item => <tr key={item.tenant_id}><td className="px-5 py-4"><button onClick={() => onTenant(item.tenant_id)} className="flex items-center gap-2 text-left font-black hover:text-[#E12120]">{item.tenant_name}<ArrowRight className="h-4 w-4" /></button><p className="mt-1 text-xs text-slate-400">Contrato v{item.contract_version ?? '—'}</p></td><td className="px-5 py-4">{item.plan_name || 'Sem plano'}</td><td className="px-5 py-4">{subscriptionLabel[item.subscription_status]}</td><td className="px-5 py-4 font-bold">{money(item.monthly_amount)}</td><td className="px-5 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${item.billing_account_ready ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>{item.billing_account_ready ? 'APTA' : 'INCOMPLETA'}</span><p className="mt-2 text-xs text-slate-500">{item.billing_contact_email || 'Contato não configurado'}</p></td><td className="px-5 py-4">{localDate(item.next_due_date)}</td></tr>)}{rows.length === 0 && <tr><td colSpan={6} className="px-5 py-12 text-center text-slate-500">Nenhum contrato neste filtro.</td></tr>}</tbody></table></div></section>
}
function PlannedCard({ icon: Icon, label, detail }: { icon: typeof ShieldAlert; label: string; detail: string }) { return <article className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5"><div className="flex items-start justify-between"><Icon className="h-5 w-5 text-slate-500" /><span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-black text-amber-800">Em implementação</span></div><h4 className="mt-4 font-black">{label}</h4><p className="mt-2 text-sm text-slate-500">{detail}</p></article> }

function InvoiceDetailModal({ detail, onClose }: { detail: SaasInvoiceDetail; onClose: () => void }) {
  const { invoice } = detail
  return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4"><section className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl"><div className="flex justify-between gap-4"><div><p className="text-xs font-black uppercase text-[#E12120]">Fatura SaaS</p><h3 className="mt-1 text-xl font-black">{invoice.public_number}</h3><p className="text-sm text-slate-500">{detail.tenant_name} · <StatusBadge status={invoice.status} /></p></div><button onClick={onClose} className="h-10 rounded-lg border p-2"><X className="h-5 w-5" /></button></div><div className="mt-6 grid gap-3 rounded-xl bg-slate-50 p-4 sm:grid-cols-2"><p><b>Plano:</b> {invoice.plan_name_snapshot} ({invoice.plan_code_snapshot})</p><p><b>Contrato:</b> versão {invoice.contract_version}</p><p><b>Competência:</b> {localDate(invoice.period_start)} a {localDate(invoice.period_end)}</p><p><b>Vencimento:</b> {localDate(invoice.due_date)}</p><p><b>Razão social:</b> {invoice.billing_legal_name_snapshot}</p><p><b>Contato:</b> {invoice.billing_contact_email_snapshot}</p></div><h4 className="mt-6 font-black">Itens congelados</h4><div className="mt-3 divide-y rounded-xl border">{detail.lines.map(line => <div key={line.id} className="flex justify-between gap-4 p-4"><div><p className="font-bold">{line.description}</p><p className="text-xs text-slate-500">{line.line_type} · {line.quantity} × {money(line.unit_amount)}</p></div><p className="font-black">{money(line.total_amount)}</p></div>)}</div><p className="mt-5 text-right text-xl font-black">Total: {money(invoice.total_amount)}</p>{invoice.void_reason && <p className="mt-4 rounded-xl bg-slate-100 p-4 text-sm"><b>Motivo da anulação:</b> {invoice.void_reason}</p>}</section></div>
}

function InvoiceCommandModal({ command, onClose, onDone }: { command: { kind: 'ISSUE' | 'VOID'; invoice: SaasInvoice }; onClose: () => void; onDone: () => Promise<void> }) {
  const [reason, setReason] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const submit = async () => { setBusy(true); setError(''); try { if (command.kind === 'ISSUE') await issueSaasInvoice(command.invoice.id, command.invoice.version, reason); else await voidSaasInvoice(command.invoice.id, command.invoice.version, reason); await onDone() } catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível executar o comando.') } finally { setBusy(false) } }
  return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4"><section className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl"><div className="flex justify-between"><h3 className="text-xl font-black">{command.kind === 'ISSUE' ? 'Emitir fatura' : 'Anular fatura'}</h3><button onClick={onClose} className="rounded-lg border p-2"><X className="h-5 w-5" /></button></div><p className="mt-2 text-sm text-slate-500">{command.invoice.public_number} · {money(command.invoice.total_amount)}. Esta operação exige sessão MFA e será auditada.</p><label className="mt-5 block text-sm font-black">Motivo<textarea value={reason} onChange={event => setReason(event.target.value)} rows={3} maxLength={500} className="mt-2 w-full rounded-xl border border-slate-300 p-3 font-normal" placeholder="Informe o motivo real da operação" /></label>{error && <p className="mt-3 text-sm font-bold text-red-700">{error}</p>}<div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-xl border px-4 py-2 font-black">Cancelar</button><button onClick={() => void submit()} disabled={busy || reason.trim().length < 4} className="rounded-xl bg-[#E12120] px-4 py-2 font-black text-white disabled:opacity-50">{busy ? 'Processando…' : 'Confirmar'}</button></div></section></div>
}
