import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Armchair, CheckCircle2, Clock3, CreditCard, Loader2, Plus, Receipt, RefreshCw, WalletCards, X,
} from 'lucide-react'

import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { formatCurrency } from '../../utils/format'


const statusLabel: Record<api.ServiceTable['status'], string> = {
  AVAILABLE: 'Livre',
  OCCUPIED: 'Ocupada',
  RESERVED: 'Reservada',
  BLOCKED: 'Bloqueada',
}

const statusClass: Record<api.ServiceTable['status'], string> = {
  AVAILABLE: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  OCCUPIED: 'border-orange-300 bg-orange-50 text-orange-900',
  RESERVED: 'border-sky-300 bg-sky-50 text-sky-900',
  BLOCKED: 'border-slate-300 bg-slate-100 text-slate-600',
}

export function TableServiceWorkspace() {
  const { tenant, store, register, operatorId, products, permissions, cashSession, showToast } = usePos()
  const [tables, setTables] = useState<api.ServiceTableProjection[]>([])
  const [sessions, setSessions] = useState<api.TableSessionSummary[]>([])
  const [selected, setSelected] = useState<api.TableSession | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [dialog, setDialog] = useState<'TABLE' | 'TAB' | null>(null)

  const headers = useMemo<Record<string, string>>(() => {
    if (!tenant || !store) return {} as Record<string, string>
    return { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
  }, [tenant, store])

  const load = useCallback(async (keepSelected = true) => {
    if (!tenant || !store) return
    setLoading(true)
    try {
      const [nextTables, nextSessions] = await Promise.all([
        api.fetchServiceTables(headers),
        api.fetchActiveTableSessions(headers),
      ])
      setTables(nextTables)
      setSessions(nextSessions)
      if (keepSelected && selected) {
        const active = nextSessions.some((item) => item.id === selected.id)
        setSelected(active ? await api.getTableSession(headers, selected.id) : null)
      }
    } catch (error) {
      showToast('error', error instanceof Error ? error.message : 'Não foi possível atualizar mesas e comandas.')
    } finally {
      setLoading(false)
    }
  }, [headers, selected, showToast, store, tenant])

  useEffect(() => { void load(false) }, [headers]) // eslint-disable-line react-hooks/exhaustive-deps

  const openExisting = async (sessionId: string) => {
    setBusy(true)
    try { setSelected(await api.getTableSession(headers, sessionId)) }
    catch (error) { showToast('error', error instanceof Error ? error.message : 'Sessão indisponível.') }
    finally { setBusy(false) }
  }

  const openTable = async (table: api.ServiceTableProjection) => {
    if (!store) return
    if (table.active_session_id) return openExisting(table.active_session_id)
    if (!permissions.includes('table.session.open')) return
    setBusy(true)
    try {
      const opened = await api.openTableSession(headers, crypto.randomUUID(), {
        store_id: store.id, service_table_id: table.id, actor_id: operatorId,
      })
      setSelected(opened)
      showToast('success', `${table.name} aberta com uma comanda persistida.`)
      await load(false)
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível abrir a mesa.') }
    finally { setBusy(false) }
  }

  const individualTabs = sessions.filter((item) => item.kind === 'INDIVIDUAL_TAB')

  return <section className="space-y-5 text-slate-950">
    <header className="flex flex-col gap-4 rounded-3xl bg-[#07172b] p-5 text-white shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <div><p className="text-xs font-black uppercase tracking-[.16em] text-orange-400">Food Service · sessão operacional</p><h1 className="mt-1 text-2xl font-black">Mesas e comandas</h1><p className="mt-2 max-w-2xl text-sm text-slate-300">A mesa física, a sessão de atendimento e cada comanda possuem identidade e histórico próprios.</p></div>
      <div className="flex flex-wrap gap-2">
        <button onClick={() => void load()} disabled={loading} className="flex h-11 items-center gap-2 rounded-xl border border-slate-600 px-4 text-xs font-black"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Atualizar</button>
        {permissions.includes('table.session.open') && <button onClick={() => setDialog('TAB')} className="flex h-11 items-center gap-2 rounded-xl bg-orange-500 px-4 text-xs font-black text-white"><Receipt className="h-4 w-4" />Comanda individual</button>}
        {permissions.includes('table.manage') && <button onClick={() => setDialog('TABLE')} className="flex h-11 items-center gap-2 rounded-xl bg-rose-600 px-4 text-xs font-black text-white"><Plus className="h-4 w-4" />Cadastrar mesa</button>}
      </div>
    </header>

    {individualTabs.length > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-3 flex items-center gap-2"><Receipt className="h-4 w-4 text-orange-500" /><h2 className="text-sm font-black">Comandas sem mesa</h2></div><div className="flex flex-wrap gap-2">{individualTabs.map((item) => <button key={item.id} onClick={() => void openExisting(item.id)} className="rounded-xl border border-orange-200 bg-orange-50 px-4 py-3 text-left"><span className="block text-xs font-black text-orange-900">{item.display_label}</span><span className="mt-1 block text-[11px] text-orange-700">{item.item_count} itens · {formatCurrency(Number(item.consolidated_total))}</span></button>)}</div></section>}

    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_460px]">
      <section className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <div className="mb-4 flex items-center justify-between"><div><h2 className="font-black">Mapa operacional</h2><p className="text-xs text-slate-500">{tables.length} mesas persistidas nesta unidade</p></div>{loading && <Loader2 className="h-5 w-5 animate-spin text-slate-400" />}</div>
        {!loading && tables.length === 0 ? <EmptyState canCreate={permissions.includes('table.manage')} onCreate={() => setDialog('TABLE')} /> : <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{tables.map((table) => <button key={table.id} disabled={busy || ['RESERVED', 'BLOCKED'].includes(table.status)} onClick={() => void openTable(table)} className={`min-h-36 rounded-2xl border-2 p-4 text-left transition hover:-translate-y-0.5 hover:shadow-md disabled:cursor-not-allowed disabled:hover:translate-y-0 ${statusClass[table.status]}`}><div className="flex items-start justify-between gap-2"><Armchair className="h-5 w-5" /><span className="rounded-full bg-white/70 px-2 py-1 text-[10px] font-black uppercase">{statusLabel[table.status]}</span></div><p className="mt-4 text-lg font-black">{table.name}</p><p className="text-[11px] opacity-70">{table.area || 'Área geral'} · {table.capacity} lugares</p>{table.active_session_id && <div className="mt-3 border-t border-current/15 pt-2 text-[11px] font-bold"><p>{table.item_count} itens · {table.order_count} comandas</p><p className="mt-0.5 text-sm font-black">{formatCurrency(Number(table.consolidated_total))}</p></div>}</button>)}</div>}
      </section>
      <SessionPanel session={selected} headers={headers} products={products} operatorId={operatorId} permissions={permissions} cashSession={cashSession} registerId={register?.id} busy={busy} setBusy={setBusy} onChanged={async (sessionId) => { setSelected(await api.getTableSession(headers, sessionId)); await load(false) }} onClosed={async () => { setSelected(null); await load(false) }} onClose={() => setSelected(null)} showToast={showToast} />
    </div>

    {dialog === 'TABLE' && store && <CreateTableDialog storeId={store.id} actorId={operatorId} headers={headers} onClose={() => setDialog(null)} onCreated={async () => { setDialog(null); await load(false) }} showToast={showToast} />}
    {dialog === 'TAB' && store && <OpenTabDialog storeId={store.id} actorId={operatorId} headers={headers} onClose={() => setDialog(null)} onOpened={async (session) => { setDialog(null); setSelected(session); await load(false) }} showToast={showToast} />}
  </section>
}

function SessionPanel({ session, headers, products, operatorId, permissions, cashSession, registerId, busy, setBusy, onChanged, onClosed, onClose, showToast }: {
  session: api.TableSession | null; headers: Record<string, string>; products: api.SellableProduct[]; operatorId: string; permissions: string[]; cashSession: api.CashSession | null; registerId?: string; busy: boolean; setBusy: (value: boolean) => void; onChanged: (sessionId: string) => Promise<void>; onClosed: () => Promise<void>; onClose: () => void; showToast: (type: 'success' | 'error' | 'info', text: string) => void
}) {
  const [orderId, setOrderId] = useState('')
  const [productId, setProductId] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [negotiation, setNegotiation] = useState<api.CheckoutNegotiation | null>(null)
  const [paymentMethod, setPaymentMethod] = useState<api.NegotiationPaymentMethod | 'TEF_CREDIT' | 'TEF_DEBIT'>('PIX')
  const [paymentAmount, setPaymentAmount] = useState('')
  const [tefTerminal, setTefTerminal] = useState<api.TefBridgeTerminal | null>(null)
  useEffect(() => { setOrderId(session?.orders[0]?.id || ''); setNegotiation(null); setPaymentAmount('') }, [session?.id, session?.orders.length])
  if (!session) return <aside className="flex min-h-[480px] items-center justify-center rounded-3xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center"><div><Receipt className="mx-auto h-10 w-10 text-slate-300" /><h2 className="mt-4 font-black">Selecione uma mesa ou comanda</h2><p className="mt-2 text-sm leading-6 text-slate-500">A conta consolidada e o histórico real aparecerão aqui.</p></div></aside>
  const activeOrders = session.orders.filter((order) => order.status === 'OPEN')
  const addItem = async () => {
    if (!orderId || !productId || Number(quantity) <= 0) return
    setBusy(true)
    try { await api.addOrderItem(headers, orderId, crypto.randomUUID(), { product_id: productId, quantity: Number(quantity), actor_id: operatorId }); setProductId(''); setQuantity('1'); await onChanged(session.id); showToast('success', 'Item lançado na comanda.') }
    catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível lançar o item.') }
    finally { setBusy(false) }
  }
  const addOrder = async () => {
    setBusy(true)
    try { const order = await api.addTableSessionOrder(headers, session.id, crypto.randomUUID(), { display_reference: `Comanda ${session.orders.length + 1}`, actor_id: operatorId }); await onChanged(session.id); setOrderId(order.id); showToast('success', 'Nova comanda criada na mesma sessão.') }
    catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível criar a comanda.') }
    finally { setBusy(false) }
  }
  const close = async () => {
    setBusy(true)
    try { await api.closeEmptyTableSession(headers, session.id, crypto.randomUUID(), { expected_version: session.version, reason: 'Sessão vazia encerrada pelo operador', actor_id: operatorId }); await onClosed(); showToast('success', 'Sessão vazia encerrada e mesa liberada.') }
    catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível encerrar a sessão.') }
    finally { setBusy(false) }
  }
  const openCheckout = async () => {
    setBusy(true)
    try {
      const opened = await api.openCheckoutNegotiation(headers, crypto.randomUUID(), {
        store_id: session.store_id, table_session_id: session.id, actor_id: operatorId,
      })
      setNegotiation(opened); setPaymentAmount(String(Number(opened.remaining_amount).toFixed(2)))
      if (registerId && permissions.includes('provider.read')) {
        const terminals = await api.fetchTefBridgeTerminals(headers, registerId)
        setTefTerminal(terminals.find((item) => item.status === 'ONLINE') || terminals[0] || null)
      }
      showToast('success', 'Conta congelada em um snapshot financeiro autoritativo.')
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível abrir a conta.') }
    finally { setBusy(false) }
  }
  const addAndConfirmPayment = async () => {
    if (!negotiation || Number(paymentAmount) <= 0) return
    if (paymentMethod === 'CASH' && cashSession?.status !== 'OPEN') { showToast('error', 'Abra uma sessão de caixa para receber em dinheiro.'); return }
    setBusy(true)
    try {
      const isTef = paymentMethod === 'TEF_CREDIT' || paymentMethod === 'TEF_DEBIT'
      const canonicalMethod: api.NegotiationPaymentMethod = paymentMethod === 'TEF_CREDIT' ? 'CREDIT_CARD' : paymentMethod === 'TEF_DEBIT' ? 'DEBIT_CARD' : paymentMethod
      const created = await api.createNegotiationPaymentIntent(headers, negotiation.id, crypto.randomUUID(), {
        method: canonicalMethod, amount: Number(paymentAmount),
        cash_session_id: paymentMethod === 'CASH' ? cashSession?.id : undefined,
        tendered_amount: paymentMethod === 'CASH' ? Number(paymentAmount) : undefined,
        actor_id: operatorId,
      })
      const pending = [...created.intents].reverse().find((item) => item.status === 'PENDING')
      if (!pending) throw new Error('A parcela persistida não ficou disponível para confirmação.')
      if (isTef) {
        if (!tefTerminal || tefTerminal.status !== 'ONLINE') throw new Error('Dashem TEF Bridge não configurado ou offline neste caixa.')
        const execution = await api.executeProviderTransaction(headers, crypto.randomUUID(), {
          payment_intent_id: pending.id, provider_configuration_id: tefTerminal.provider_configuration_id,
          bridge_terminal_id: tefTerminal.id, actor_id: operatorId,
        })
        setNegotiation(execution.negotiation)
        showToast('info', execution.transaction.status === 'CONFIRMED' ? 'Parcela TEF confirmada.' : 'Transação enviada ao bridge; aguardando resultado ou reconciliação.')
        return
      }
      const confirmed = await api.confirmNegotiationPaymentIntent(headers, pending.id, crypto.randomUUID(), operatorId)
      setNegotiation(confirmed); setPaymentAmount(String(Number(confirmed.remaining_amount).toFixed(2)))
      showToast('success', `Parcela confirmada. Falta ${formatCurrency(Number(confirmed.remaining_amount))}.`)
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível confirmar a parcela.') }
    finally { setBusy(false) }
  }
  const finalize = async () => {
    if (!negotiation) return
    setBusy(true)
    try {
      const finalized = await api.finalizeCheckoutNegotiation(headers, negotiation.id, crypto.randomUUID(), negotiation.version, operatorId)
      setNegotiation(finalized); showToast('success', 'Venda materializada, conta finalizada e mesa liberada.'); await onClosed()
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível finalizar a conta.') }
    finally { setBusy(false) }
  }
  return <aside className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-black uppercase tracking-[.16em] text-orange-600">{session.kind === 'TABLE' ? 'Sessão de mesa' : 'Comanda individual'}</p><h2 className="mt-1 text-xl font-black">{session.display_label}</h2><p className="mt-1 flex items-center gap-1 text-xs text-slate-500"><Clock3 className="h-3.5 w-3.5" />Aberta em {new Date(session.opened_at).toLocaleString('pt-BR')}</p></div><button onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 text-slate-500"><X className="h-4 w-4" /></button></div><div className="mt-4 grid grid-cols-3 gap-2 rounded-2xl bg-slate-50 p-3 text-center"><Metric label="Comandas" value={String(session.order_count)} /><Metric label="Itens" value={String(session.active_item_count)} /><Metric label="Total" value={formatCurrency(Number(session.consolidated_total))} /></div>
    {permissions.includes('table.session.update') && !negotiation && <div className="mt-4 space-y-3 rounded-2xl border border-slate-200 p-3"><div className="flex items-center justify-between"><p className="text-xs font-black">Lançamento incremental</p><button disabled={busy} onClick={() => void addOrder()} className="flex items-center gap-1 text-xs font-black text-orange-600"><Plus className="h-3.5 w-3.5" />Nova comanda</button></div><select value={orderId} onChange={(event) => setOrderId(event.target.value)} className="h-10 w-full rounded-xl border border-slate-300 px-3 text-sm">{activeOrders.map((order, index) => <option key={order.id} value={order.id}>{order.notes || `Comanda ${index + 1}`}</option>)}</select><div className="grid grid-cols-[1fr_76px] gap-2"><select value={productId} onChange={(event) => setProductId(event.target.value)} className="h-11 min-w-0 rounded-xl border border-slate-300 px-3 text-sm"><option value="">Selecione um produto real</option>{products.filter((product) => product.available_for_sale).map((product) => <option key={product.id} value={product.id}>{product.name} · {formatCurrency(Number(product.sale_price))}</option>)}</select><input aria-label="Quantidade" type="number" min="0.001" step="0.001" value={quantity} onChange={(event) => setQuantity(event.target.value)} className="h-11 rounded-xl border border-slate-300 px-3 text-sm" /></div><button disabled={busy || !orderId || !productId} onClick={() => void addItem()} className="h-11 w-full rounded-xl bg-orange-500 text-sm font-black text-white disabled:opacity-40">Lançar na comanda</button></div>}
    <div className="mt-4 max-h-72 space-y-3 overflow-y-auto">{session.orders.map((order, index) => <article key={order.id} className="rounded-2xl border border-slate-200 p-3"><div className="flex items-center justify-between"><p className="text-xs font-black">{order.notes || `Comanda ${index + 1}`}</p><span className="text-[10px] font-bold text-slate-400">{order.status}</span></div>{order.items.filter((item) => item.status === 'ACTIVE').length === 0 ? <p className="mt-2 text-xs text-slate-400">Sem lançamentos.</p> : <div className="mt-2 space-y-2">{order.items.filter((item) => item.status === 'ACTIVE').map((item) => <div key={item.id} className="flex justify-between gap-3 text-xs"><span><b>{Number(item.quantity)}×</b> {item.product_name}</span><b>{formatCurrency(Number(item.unit_price) * Number(item.quantity))}</b></div>)}</div>}</article>)}</div>
    {session.active_item_count === 0 && permissions.includes('table.session.close') && <button disabled={busy} onClick={() => void close()} className="mt-4 h-10 w-full rounded-xl border border-slate-300 text-xs font-black text-slate-600">Encerrar sessão vazia</button>}
    {session.active_item_count > 0 && permissions.includes('checkout.open') && !negotiation && <button disabled={busy} onClick={() => void openCheckout()} className="mt-4 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-slate-950 text-sm font-black text-white"><WalletCards className="h-4 w-4" />Fechar conta</button>}
    {negotiation && <section className="mt-4 space-y-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-3"><div className="flex items-center justify-between"><div><p className="text-[10px] font-black uppercase tracking-wider text-emerald-700">Negociação persistida</p><p className="text-sm font-black">{negotiation.status === 'COVERED' ? 'Conta integralmente coberta' : 'Pagamento parcial em andamento'}</p></div><CreditCard className="h-5 w-5 text-emerald-700" /></div><div className="grid grid-cols-3 gap-2 rounded-xl bg-white p-3 text-center"><Metric label="Total" value={formatCurrency(Number(negotiation.total_due))} /><Metric label="Confirmado" value={formatCurrency(Number(negotiation.confirmed_amount))} /><Metric label="Falta" value={formatCurrency(Number(negotiation.remaining_amount))} /></div>{negotiation.intents.length > 0 && <div className="space-y-1">{negotiation.intents.map((intent) => <div key={intent.id} className="flex items-center justify-between rounded-lg bg-white px-3 py-2 text-[11px]"><span>{intent.method} · {intent.status}</span><b>{formatCurrency(Number(intent.amount))}</b></div>)}</div>}{permissions.includes('provider.read') && <p className={`rounded-lg px-3 py-2 text-[11px] font-bold ${tefTerminal?.status === 'ONLINE' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-900'}`}>{tefTerminal?.status === 'ONLINE' ? `TEF online · ${tefTerminal.terminal_code} · bridge ${tefTerminal.bridge_version || 'versão não informada'}` : 'TEF não configurado ou offline; meios locais permanecem disponíveis.'}</p>}{negotiation.status !== 'COVERED' && permissions.includes('checkout.payment') && <div className="grid grid-cols-[1fr_110px] gap-2"><select aria-label="Meio de pagamento" value={paymentMethod} onChange={(event) => setPaymentMethod(event.target.value as api.NegotiationPaymentMethod | 'TEF_CREDIT' | 'TEF_DEBIT')} className="h-11 rounded-xl border border-emerald-200 bg-white px-3 text-xs font-bold"><option value="CASH">Dinheiro</option><option value="PIX">PIX manual</option><option value="CREDIT_CARD">Crédito manual</option><option value="DEBIT_CARD">Débito manual</option>{tefTerminal?.status === 'ONLINE' && permissions.includes('provider.execute') && <><option value="TEF_CREDIT">Crédito via TEF</option><option value="TEF_DEBIT">Débito via TEF</option></>}</select><input aria-label="Valor da parcela" type="number" min="0.01" step="0.01" value={paymentAmount} onChange={(event) => setPaymentAmount(event.target.value)} className="h-11 rounded-xl border border-emerald-200 px-3 text-sm font-black" /><button disabled={busy || Number(paymentAmount) <= 0} onClick={() => void addAndConfirmPayment()} className="col-span-2 h-11 rounded-xl bg-emerald-700 text-xs font-black text-white disabled:opacity-40">Registrar parcela no meio selecionado</button></div>}{negotiation.status === 'COVERED' && permissions.includes('checkout.finalize') && <button disabled={busy} onClick={() => void finalize()} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 text-sm font-black text-white"><CheckCircle2 className="h-4 w-4" />Finalizar venda e liberar mesa</button>}</section>}
  </aside>
}

function Metric({ label, value }: { label: string; value: string }) { return <div><p className="text-[10px] font-bold uppercase text-slate-400">{label}</p><p className="mt-1 text-sm font-black">{value}</p></div> }
function EmptyState({ canCreate, onCreate }: { canCreate: boolean; onCreate: () => void }) { return <div className="flex min-h-72 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center"><div><Armchair className="mx-auto h-10 w-10 text-slate-300" /><h3 className="mt-4 font-black">Nenhuma mesa cadastrada</h3><p className="mt-2 text-sm text-slate-500">Este é o estado persistido real da unidade.</p>{canCreate && <button onClick={onCreate} className="mt-5 rounded-xl bg-rose-600 px-4 py-2.5 text-xs font-black text-white">Cadastrar primeira mesa</button>}</div></div> }

function CreateTableDialog({ storeId, actorId, headers, onClose, onCreated, showToast }: { storeId: string; actorId: string; headers: Record<string, string>; onClose: () => void; onCreated: () => Promise<void>; showToast: (type: 'success' | 'error' | 'info', text: string) => void }) {
  const [form, setForm] = useState({ code: '', name: '', capacity: '4', area: '' }); const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); try { await api.createServiceTable(headers, crypto.randomUUID(), { store_id: storeId, code: form.code, name: form.name, capacity: Number(form.capacity), area: form.area || undefined, actor_id: actorId }); showToast('success', 'Mesa cadastrada na unidade.'); await onCreated() } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível cadastrar a mesa.') } finally { setSaving(false) } }
  return <Dialog title="Cadastrar mesa" onClose={onClose}><form onSubmit={submit} className="space-y-3"><Input label="Código" value={form.code} onChange={(value) => setForm({ ...form, code: value })} placeholder="MESA-01" /><Input label="Nome visível" value={form.name} onChange={(value) => setForm({ ...form, name: value })} placeholder="Mesa 01" /><div className="grid grid-cols-2 gap-3"><Input label="Capacidade" type="number" value={form.capacity} onChange={(value) => setForm({ ...form, capacity: value })} /><Input label="Área" value={form.area} onChange={(value) => setForm({ ...form, area: value })} placeholder="Salão" /></div><button disabled={saving || !form.code || !form.name} className="h-11 w-full rounded-xl bg-rose-600 text-sm font-black text-white disabled:opacity-40">{saving ? 'Salvando...' : 'Cadastrar mesa'}</button></form></Dialog>
}

function OpenTabDialog({ storeId, actorId, headers, onClose, onOpened, showToast }: { storeId: string; actorId: string; headers: Record<string, string>; onClose: () => void; onOpened: (session: api.TableSession) => Promise<void>; showToast: (type: 'success' | 'error' | 'info', text: string) => void }) {
  const [label, setLabel] = useState(''); const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); try { const session = await api.openTableSession(headers, crypto.randomUUID(), { store_id: storeId, display_label: label, actor_id: actorId }); showToast('success', 'Comanda individual aberta.'); await onOpened(session) } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível abrir a comanda.') } finally { setSaving(false) } }
  return <Dialog title="Abrir comanda individual" onClose={onClose}><form onSubmit={submit} className="space-y-3"><Input label="Identificação" value={label} onChange={setLabel} placeholder="Nome, senha ou referência" /><p className="text-xs leading-5 text-slate-500">A comanda nasce sem mesa fictícia e recebe uma sessão e um pedido próprios.</p><button disabled={saving || label.trim().length < 2} className="h-11 w-full rounded-xl bg-orange-500 text-sm font-black text-white disabled:opacity-40">{saving ? 'Abrindo...' : 'Abrir comanda'}</button></form></Dialog>
}

function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4"><section className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-2xl"><header className="mb-5 flex items-center justify-between"><h2 className="text-xl font-black">{title}</h2><button onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200"><X className="h-4 w-4" /></button></header>{children}</section></div> }
function Input({ label, value, onChange, placeholder, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) { return <label className="block text-xs font-black text-slate-700">{label}<input required type={type} min={type === 'number' ? 1 : undefined} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-1.5 h-11 w-full rounded-xl border border-slate-300 px-3 text-sm font-medium outline-none focus:border-rose-500" /></label> }
