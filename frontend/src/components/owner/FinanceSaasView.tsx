import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight, FilePlus2, Loader2, RefreshCw, ShieldAlert,
  Download, Eye, X, CalendarClock, RotateCcw,
} from 'lucide-react'

import {
  fetchPlatformFinanceOverview, fetchSaasInvoice, fetchSaasInvoiceExport,
  fetchSaasInvoices, generateSaasInvoices, issueSaasInvoice, voidSaasInvoice,
  fetchSaasPayments, markSaasInvoicesOverdue, recordManualSaasPayment, refundSaasPayment,
  PlatformFinanceOverview, PlatformFinanceSubscription, SaasInvoice,
  SaasInvoiceDetail, SaasInvoiceListItem, SaasInvoiceStatus, SaasPaymentListItem,
  SubscriptionStatus,
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
  const [payments, setPayments] = useState<SaasPaymentListItem[]>([])
  const [paymentTotal, setPaymentTotal] = useState(0)
  const [contractFilter, setContractFilter] = useState<ContractFilter>('ALL')
  const [invoiceFilter, setInvoiceFilter] = useState<InvoiceFilter>('ALL')
  const [competence, setCompetence] = useState(competenceNow)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [detail, setDetail] = useState<SaasInvoiceDetail | null>(null)
  const [command, setCommand] = useState<{ kind: 'ISSUE' | 'VOID'; invoice: SaasInvoice } | null>(null)
  const [receiptInvoice, setReceiptInvoice] = useState<SaasInvoice | null>(null)
  const [refundCommand, setRefundCommand] = useState<{ row: SaasPaymentListItem; invoice: SaasInvoice } | null>(null)

  const loadOverview = async () => setOverview(await fetchPlatformFinanceOverview())
  const loadInvoices = async (filter = invoiceFilter) => {
    const result = await fetchSaasInvoices(filter === 'ALL' ? undefined : filter)
    setInvoices(result.items); setInvoiceTotal(result.total)
  }
  const loadPayments = async () => {
    const result = await fetchSaasPayments()
    setPayments(result.items); setPaymentTotal(result.total)
  }
  const refresh = async () => {
    setLoading(true); setError('')
    try { await Promise.all([loadOverview(), loadInvoices(), loadPayments()]) }
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
      await Promise.all([loadOverview(), loadInvoices(), loadPayments()])
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
  const openRefund = async (row: SaasPaymentListItem) => {
    const invoiceId = row.invoice_ids[0]
    if (!invoiceId) { setError('Este pagamento ainda não possui alocação estornável.'); return }
    setWorking(true); setError('')
    try { const invoiceDetail = await fetchSaasInvoice(invoiceId); setRefundCommand({ row, invoice: invoiceDetail.invoice }) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível abrir o estorno.') }
    finally { setWorking(false) }
  }

  const invoiceCards: Array<{ label: string; value: string | number; filter: InvoiceFilter; hint: string }> = [
    { label: 'Faturado SaaS', value: money(overview?.invoiced_total ?? 0), filter: 'OPEN', hint: 'Faturas emitidas e não anuladas' },
    { label: 'Saldo aberto', value: money(overview?.open_invoice_balance ?? 0), filter: 'OPEN', hint: 'Saldo real das faturas abertas' },
    { label: 'Rascunhos', value: overview?.draft_invoices ?? 0, filter: 'DRAFT', hint: 'Documentos ainda não emitidos' },
    { label: 'Anuladas', value: overview?.void_invoices ?? 0, filter: 'VOID', hint: 'Documentos anulados com motivo' },
  ]
  const paymentCards: Array<{ label: string; value: string | number; target: 'PAYMENTS' | 'INVOICES'; filter?: InvoiceFilter; hint: string }> = [
    { label: 'Recebido SaaS', value: money(overview?.received_total ?? 0), target: 'PAYMENTS', hint: 'Abrir os recebimentos que compõem o valor' },
    { label: 'Estornado', value: money(overview?.refunded_total ?? 0), target: 'PAYMENTS', hint: 'Abrir os fatos compensatórios persistidos' },
    { label: 'Saldo vencido', value: money(overview?.overdue_invoice_balance ?? 0), target: 'INVOICES', filter: 'OVERDUE', hint: 'Abrir faturas que compõem o saldo' },
    { label: 'Faturas vencidas', value: overview?.overdue_invoices ?? 0, target: 'INVOICES', filter: 'OVERDUE', hint: 'Abrir os documentos vencidos' },
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
    <p className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-semibold text-blue-900">Faturas, recebimentos, alocações, estornos e atrasos abaixo vêm do ledger financeiro SaaS persistido. O webhook externo permanece indisponível até existir segredo e identidade técnica configurados.</p>
    {error && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
    {notice && <p className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-bold text-emerald-800">{notice}</p>}
    {loading ? <Loader2 className="mx-auto my-24 h-8 w-8 animate-spin text-[#E12120]" /> : <>
      <SectionTitle title="Faturamento SaaS" detail="Valores derivados das faturas persistidas." />
      <section className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{invoiceCards.map(card => <MetricCard key={card.label} {...card} active={invoiceFilter === card.filter} onClick={() => { setInvoiceFilter(card.filter); document.getElementById('saas-invoices')?.scrollIntoView({ behavior: 'smooth' }) }} />)}</section>
      <section className="mt-5 flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:flex-row sm:items-end sm:justify-between"><label className="text-sm font-black">Competência<input aria-label="Competência" type="month" value={competence} onChange={event => setCompetence(event.target.value)} className="mt-2 block h-11 rounded-xl border border-slate-300 px-3 font-medium" /></label><div className="flex flex-wrap gap-2"><button onClick={async () => { setWorking(true); setError(''); try { const changed = await markSaasInvoicesOverdue(new Date().toISOString().slice(0, 10)); setNotice(`${changed.length} fatura(s) marcada(s) como vencida(s) a partir de fatos reais.`); await Promise.all([loadOverview(), loadInvoices(), loadPayments()]) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível derivar vencimentos.') } finally { setWorking(false) } }} disabled={working} className="flex h-11 items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-4 text-sm font-black disabled:opacity-50"><CalendarClock className="h-4 w-4" />Derivar vencimentos</button><button onClick={() => void generate()} disabled={working || !competence} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-[#E12120] px-5 text-sm font-black text-white disabled:opacity-50">{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePlus2 className="h-4 w-4" />}Gerar faturas da competência</button></div></section>
      <InvoiceTable rows={invoices} total={invoiceTotal} filter={invoiceFilter} onAll={() => setInvoiceFilter('ALL')} onDetail={openDetail} onCommand={setCommand} onReceipt={setReceiptInvoice} />
      <SectionTitle title="Recebimentos e cobrança" detail="Valores líquidos derivados de pagamentos, alocações, estornos e vencimentos persistidos." />
      <section className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{paymentCards.map(card => <MetricCard key={card.label} label={card.label} value={card.value} hint={card.hint} active={card.target === 'INVOICES' && invoiceFilter === card.filter} onClick={() => { if (card.target === 'INVOICES' && card.filter) setInvoiceFilter(card.filter); document.getElementById(card.target === 'PAYMENTS' ? 'saas-payments' : 'saas-invoices')?.scrollIntoView({ behavior: 'smooth' }) }} />)}</section>
      <PaymentTable rows={payments} total={paymentTotal} onRefund={openRefund} />
      <SectionTitle title="Base contratual" detail="Assinaturas que alimentam a geração das faturas." />
      <section className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{contractCards.map(card => <MetricCard key={card.label} {...card} active={contractFilter === card.filter} onClick={() => setContractFilter(card.filter)} />)}</section>
      <SubscriptionTable rows={contractRows} filter={contractFilter} onAll={() => setContractFilter('ALL')} onTenant={onTenant} />
      <section className="mt-7"><SectionTitle title="Próxima capacidade financeira" detail="Indicadores recorrentes só serão exibidos após a projeção reconstruível da Fase 4." /><div className="mt-4"><PlannedCard icon={ShieldAlert} label="MRR, ARR e churn históricos" detail="Previsto para a Fase 4 com watermark, versão de fórmula e drill-down até os fatos SaaS." /></div></section>
    </>}
    {detail && <InvoiceDetailModal detail={detail} onClose={() => setDetail(null)} />}
    {command && <InvoiceCommandModal command={command} onClose={() => setCommand(null)} onDone={async () => { setCommand(null); await Promise.all([loadOverview(), loadInvoices()]) }} />}
    {receiptInvoice && <ReceiptModal invoice={receiptInvoice} onClose={() => setReceiptInvoice(null)} onDone={async () => { setReceiptInvoice(null); await Promise.all([loadOverview(), loadInvoices(), loadPayments()]) }} />}
    {refundCommand && <RefundModal command={refundCommand} onClose={() => setRefundCommand(null)} onDone={async () => { setRefundCommand(null); await Promise.all([loadOverview(), loadInvoices(), loadPayments()]) }} />}
  </div>
}

function SectionTitle({ title, detail }: { title: string; detail: string }) { return <div className="mt-7"><h3 className="text-lg font-black">{title}</h3><p className="mt-1 text-sm text-slate-500">{detail}</p></div> }
function MetricCard({ label, value, hint, active, onClick }: { label: string; value: string | number; hint: string; active: boolean; onClick: () => void }) { return <button onClick={onClick} className={`rounded-2xl border bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${active ? 'border-[#E12120] ring-2 ring-red-100' : 'border-slate-200'}`}><p className="text-xs font-black uppercase text-slate-400">{label}</p><p className="mt-3 text-2xl font-black">{value}</p><p className="mt-4 flex items-center justify-between text-xs font-bold text-slate-500">{hint}<ArrowRight className="h-4 w-4" /></p></button> }

function InvoiceTable({ rows, total, filter, onAll, onDetail, onCommand, onReceipt }: { rows: SaasInvoiceListItem[]; total: number; filter: InvoiceFilter; onAll: () => void; onDetail: (id: string) => void; onCommand: (value: { kind: 'ISSUE' | 'VOID'; invoice: SaasInvoice }) => void; onReceipt: (invoice: SaasInvoice) => void }) {
  return <section id="saas-invoices" className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="flex items-center justify-between border-b border-slate-100 p-5"><div><h3 className="font-black">Faturas SaaS</h3><p className="text-sm text-slate-500">{filter === 'ALL' ? `${total} documento(s)` : `${invoiceLabel[filter]} · ${total} documento(s)`}</p></div>{filter !== 'ALL' && <button onClick={onAll} className="text-sm font-black text-[#E12120]">Ver todas</button>}</div><div className="overflow-x-auto"><table className="w-full min-w-[1120px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-400"><tr><th className="px-5 py-3">Número</th><th className="px-5 py-3">Cliente</th><th className="px-5 py-3">Competência</th><th className="px-5 py-3">Vencimento</th><th className="px-5 py-3">Situação</th><th className="px-5 py-3">Total / saldo</th><th className="px-5 py-3">Ações</th></tr></thead><tbody className="divide-y divide-slate-100">{rows.map(({ invoice, tenant_name }) => <tr key={invoice.id}><td className="px-5 py-4 font-black">{invoice.public_number}</td><td className="px-5 py-4">{tenant_name}<p className="mt-1 text-xs text-slate-400">Contrato v{invoice.contract_version}</p></td><td className="px-5 py-4">{localDate(invoice.period_start)}</td><td className="px-5 py-4">{localDate(invoice.due_date)}</td><td className="px-5 py-4"><StatusBadge status={invoice.status} /></td><td className="px-5 py-4 font-black">{money(invoice.total_amount)}<p className="mt-1 text-xs font-medium text-slate-500">Saldo {money(invoice.balance_amount)}</p></td><td className="px-5 py-4"><div className="flex flex-wrap gap-2"><button title="Ver detalhes" onClick={() => onDetail(invoice.id)} className="rounded-lg border p-2"><Eye className="h-4 w-4" /></button>{invoice.status === 'DRAFT' && <button onClick={() => onCommand({ kind: 'ISSUE', invoice })} className="rounded-lg bg-[#E12120] px-3 py-2 text-xs font-black text-white">Emitir</button>}{invoice.status === 'OPEN' && <button onClick={() => onCommand({ kind: 'VOID', invoice })} className="rounded-lg border border-red-200 px-3 py-2 text-xs font-black text-red-700">Anular</button>}{['OPEN', 'PARTIALLY_PAID', 'OVERDUE'].includes(invoice.status) && <button onClick={() => onReceipt(invoice)} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-black text-white">Receber</button>}</div></td></tr>)}{rows.length === 0 && <tr><td colSpan={7} className="px-5 py-12 text-center text-slate-500">Nenhuma fatura neste filtro.</td></tr>}</tbody></table></div></section>
}
function StatusBadge({ status }: { status: SaasInvoiceStatus }) { return <span className={`rounded-full px-2.5 py-1 text-xs font-black ${status === 'OPEN' ? 'bg-blue-50 text-blue-700' : status === 'DRAFT' ? 'bg-amber-50 text-amber-800' : status === 'OVERDUE' ? 'bg-red-50 text-red-700' : status === 'VOID' || status === 'UNCOLLECTIBLE' ? 'bg-slate-100 text-slate-600' : 'bg-emerald-50 text-emerald-700'}`}>{invoiceLabel[status]}</span> }

const paymentLabel = { PENDING: 'Pendente', PROCESSING: 'Processando', SUCCEEDED: 'Confirmado', FAILED: 'Falhou', UNKNOWN: 'A reconciliar', PARTIALLY_REFUNDED: 'Estorno parcial', REFUNDED: 'Estornado' } as const
const paymentBadge = { PENDING: 'bg-amber-50 text-amber-800', PROCESSING: 'bg-blue-50 text-blue-700', SUCCEEDED: 'bg-emerald-50 text-emerald-700', FAILED: 'bg-red-50 text-red-700', UNKNOWN: 'bg-amber-50 text-amber-800', PARTIALLY_REFUNDED: 'bg-orange-50 text-orange-800', REFUNDED: 'bg-slate-100 text-slate-600' } as const
function PaymentTable({ rows, total, onRefund }: { rows: SaasPaymentListItem[]; total: number; onRefund: (row: SaasPaymentListItem) => void }) {
  return <section id="saas-payments" className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="border-b border-slate-100 p-5"><h3 className="font-black">Recebimentos SaaS</h3><p className="text-sm text-slate-500">{total} fato(s) persistido(s); nenhum pagamento do tenant aparece aqui.</p></div><div className="overflow-x-auto"><table className="w-full min-w-[1000px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-400"><tr><th className="px-5 py-3">Cliente</th><th className="px-5 py-3">Data</th><th className="px-5 py-3">Origem</th><th className="px-5 py-3">Situação</th><th className="px-5 py-3">Valor</th><th className="px-5 py-3">Alocado / estornado</th><th className="px-5 py-3">Ação</th></tr></thead><tbody className="divide-y divide-slate-100">{rows.map(row => <tr key={row.payment.id}><td className="px-5 py-4 font-black">{row.tenant_name}</td><td className="px-5 py-4">{new Date(row.payment.received_at).toLocaleString('pt-BR')}</td><td className="px-5 py-4">{row.payment.provider}<p className="mt-1 text-xs text-slate-400">{row.payment.payment_method_summary || 'Meio sanitizado não informado'}</p></td><td className="px-5 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${paymentBadge[row.payment.status]}`}>{paymentLabel[row.payment.status]}</span></td><td className="px-5 py-4 font-black">{money(row.payment.amount)}</td><td className="px-5 py-4">{money(row.allocated_amount)}<p className="mt-1 text-xs text-slate-500">Estornado {money(row.refunded_amount)}</p></td><td className="px-5 py-4">{Number(row.allocated_amount) > Number(row.refunded_amount) && ['SUCCEEDED', 'PARTIALLY_REFUNDED'].includes(row.payment.status) ? <button onClick={() => onRefund(row)} className="flex items-center gap-1 rounded-lg border border-red-200 px-3 py-2 text-xs font-black text-red-700"><RotateCcw className="h-3.5 w-3.5" />Estornar</button> : '—'}</td></tr>)}{rows.length === 0 && <tr><td colSpan={7} className="px-5 py-12 text-center text-slate-500">Nenhum recebimento persistido.</td></tr>}</tbody></table></div></section>
}

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

function ReceiptModal({ invoice, onClose, onDone }: { invoice: SaasInvoice; onClose: () => void; onDone: () => Promise<void> }) {
  const [amount, setAmount] = useState(String(invoice.balance_amount)); const [receivedAt, setReceivedAt] = useState(new Date().toISOString().slice(0, 16)); const [evidence, setEvidence] = useState(''); const [reason, setReason] = useState(''); const [method, setMethod] = useState('PIX_CONFIRMADO'); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const submit = async () => { setBusy(true); setError(''); try { await recordManualSaasPayment({ invoice_id: invoice.id, expected_invoice_version: invoice.version, amount: Number(amount), received_at: new Date(receivedAt).toISOString(), evidence_reference: evidence, reason, payment_method_summary: method }); await onDone() } catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível registrar o recebimento.') } finally { setBusy(false) } }
  return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4"><section className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl"><div className="flex justify-between"><div><p className="text-xs font-black uppercase text-emerald-700">Recebimento SaaS</p><h3 className="mt-1 text-xl font-black">{invoice.public_number}</h3></div><button onClick={onClose} className="rounded-lg border p-2"><X className="h-5 w-5" /></button></div><p className="mt-2 text-sm text-slate-500">Saldo atual {money(invoice.balance_amount)}. Registre somente após conferir uma evidência externa real.</p><div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="text-sm font-black">Valor<input type="number" min="0.01" max={invoice.balance_amount} step="0.01" value={amount} onChange={event => setAmount(event.target.value)} className="mt-2 h-11 w-full rounded-xl border px-3 font-normal" /></label><label className="text-sm font-black">Recebido em<input type="datetime-local" value={receivedAt} onChange={event => setReceivedAt(event.target.value)} className="mt-2 h-11 w-full rounded-xl border px-3 font-normal" /></label><label className="text-sm font-black">Meio sanitizado<select value={method} onChange={event => setMethod(event.target.value)} className="mt-2 h-11 w-full rounded-xl border px-3 font-normal"><option value="PIX_CONFIRMADO">PIX confirmado</option><option value="TRANSFERENCIA_CONFIRMADA">Transferência confirmada</option><option value="BOLETO_CONFIRMADO">Boleto confirmado</option></select></label><label className="text-sm font-black">Referência da evidência<input value={evidence} onChange={event => setEvidence(event.target.value)} maxLength={240} placeholder="Ex.: extrato:abc123" className="mt-2 h-11 w-full rounded-xl border px-3 font-normal" /></label></div><label className="mt-4 block text-sm font-black">Motivo<textarea value={reason} onChange={event => setReason(event.target.value)} rows={3} maxLength={500} className="mt-2 w-full rounded-xl border p-3 font-normal" /></label>{error && <p className="mt-3 text-sm font-bold text-red-700">{error}</p>}<div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-xl border px-4 py-2 font-black">Cancelar</button><button onClick={() => void submit()} disabled={busy || Number(amount) <= 0 || Number(amount) > Number(invoice.balance_amount) || evidence.trim().length < 4 || reason.trim().length < 4} className="rounded-xl bg-emerald-600 px-4 py-2 font-black text-white disabled:opacity-50">{busy ? 'Registrando…' : 'Confirmar recebimento'}</button></div></section></div>
}

function RefundModal({ command, onClose, onDone }: { command: { row: SaasPaymentListItem; invoice: SaasInvoice }; onClose: () => void; onDone: () => Promise<void> }) {
  const available = Number(command.row.allocated_amount) - Number(command.row.refunded_amount); const [amount, setAmount] = useState(String(available)); const [reason, setReason] = useState(''); const [evidence, setEvidence] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const submit = async () => { setBusy(true); setError(''); try { await refundSaasPayment(command.row.payment.id, { invoice_id: command.invoice.id, expected_invoice_version: command.invoice.version, amount: Number(amount), reason, evidence_reference: evidence }); await onDone() } catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível registrar o estorno.') } finally { setBusy(false) } }
  return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4"><section className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl"><div className="flex justify-between"><div><p className="text-xs font-black uppercase text-red-700">Fato compensatório</p><h3 className="mt-1 text-xl font-black">Registrar estorno SaaS</h3></div><button onClick={onClose} className="rounded-lg border p-2"><X className="h-5 w-5" /></button></div><p className="mt-2 text-sm text-slate-500">Disponível para estorno: {money(available)}. O recebimento original será preservado.</p><label className="mt-5 block text-sm font-black">Valor<input type="number" min="0.01" max={available} step="0.01" value={amount} onChange={event => setAmount(event.target.value)} className="mt-2 h-11 w-full rounded-xl border px-3 font-normal" /></label><label className="mt-4 block text-sm font-black">Referência da evidência<input value={evidence} onChange={event => setEvidence(event.target.value)} maxLength={240} className="mt-2 h-11 w-full rounded-xl border px-3 font-normal" /></label><label className="mt-4 block text-sm font-black">Motivo<textarea value={reason} onChange={event => setReason(event.target.value)} rows={3} maxLength={500} className="mt-2 w-full rounded-xl border p-3 font-normal" /></label>{error && <p className="mt-3 text-sm font-bold text-red-700">{error}</p>}<div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-xl border px-4 py-2 font-black">Cancelar</button><button onClick={() => void submit()} disabled={busy || Number(amount) <= 0 || Number(amount) > available || evidence.trim().length < 4 || reason.trim().length < 4} className="rounded-xl bg-[#E12120] px-4 py-2 font-black text-white disabled:opacity-50">{busy ? 'Registrando…' : 'Confirmar estorno'}</button></div></section></div>
}
