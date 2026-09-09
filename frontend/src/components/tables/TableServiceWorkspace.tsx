import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Armchair, ArrowRightLeft, Ban, CalendarClock, CheckCircle2, Clock3, CreditCard, Loader2, Plus, Receipt, RefreshCw, WalletCards, X,
} from 'lucide-react'

import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { formatApiDateTime, formatCurrency, millisecondsSince, parseApiDate } from '../../utils/format'
import { TableProductSelector } from './TableProductSelector'


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

const isLegacyReservationBlock = (table: api.ServiceTableProjection) =>
  table.status === 'BLOCKED' && /reserv/i.test(table.blocking_reason || '')

export function TableServiceWorkspace() {
  const { tenant, store, register, operatorId, products, permissions, cashSession, showToast } = usePos()
  const [tables, setTables] = useState<api.ServiceTableProjection[]>([])
  const [sessions, setSessions] = useState<api.TableSessionSummary[]>([])
  const [selected, setSelected] = useState<api.TableSession | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [dialog, setDialog] = useState<'TAB' | null>(null)
  const [pendingReservationTable, setPendingReservationTable] = useState<api.ServiceTableProjection | null>(null)
  const [stateDialogTable, setStateDialogTable] = useState<api.ServiceTableProjection | null>(null)
  const [stateReason, setStateReason] = useState('')

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
    if (table.status === 'RESERVED') { setPendingReservationTable(table); return }
    if (table.status !== 'AVAILABLE') return
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

  const confirmReservedTable = async () => {
    const table = pendingReservationTable
    if (!store || !table?.active_reservation) return
    setBusy(true)
    try {
      const opened = await api.openTableSession(headers, crypto.randomUUID(), {
        store_id: store.id, service_table_id: table.id, reservation_id: table.active_reservation.id, actor_id: operatorId,
      })
      setPendingReservationTable(null); setSelected(opened)
      showToast('success', `Chegada confirmada. ${table.name} aberta para ${table.active_reservation.customer_name}.`)
      await load(false)
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível confirmar a reserva.') }
    finally { setBusy(false) }
  }

  const repairLegacyReservationAndOpen = async (table: api.ServiceTableProjection) => {
    if (!store || !permissions.includes('table.state.update') || !permissions.includes('table.session.open')) return
    setBusy(true)
    try {
      await api.setServiceTableState(headers, table.id, {
        expected_version: table.version,
        target: 'AVAILABLE',
        reason: 'Correção de registro legado: reserva gravada indevidamente como bloqueio',
        actor_id: operatorId,
      })
      const opened = await api.openTableSession(headers, crypto.randomUUID(), {
        store_id: store.id, service_table_id: table.id, actor_id: operatorId,
      })
      setSelected(opened)
      showToast('success', `${table.name} corrigida e aberta para o atendimento.`)
      await load(false)
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível corrigir e abrir a mesa.') }
    finally { setBusy(false) }
  }

  const changeTableState = async () => {
    const table = stateDialogTable
    if (!table || stateReason.trim().length < 3) return
    const releasing = table.status === 'BLOCKED' || (table.status === 'OCCUPIED' && Boolean(table.blocking_reason))
    setBusy(true)
    try {
      await api.setServiceTableState(headers, table.id, { expected_version: table.version, target: releasing ? 'AVAILABLE' : 'BLOCKED', reason: stateReason.trim(), actor_id: operatorId })
      setStateDialogTable(null); setStateReason('')
      showToast('success', releasing ? 'Impedimento removido.' : table.status === 'OCCUPIED' ? 'Mesa será bloqueada ao encerrar a conta.' : 'Mesa bloqueada e sinalizada para a equipe.'); await load(false)
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível alterar a mesa.') }
    finally { setBusy(false) }
  }

  const individualTabs = sessions.filter((item) => item.kind === 'INDIVIDUAL_TAB')

  return <section className="space-y-5 text-slate-950">
    <header className="flex flex-col gap-4 rounded-3xl bg-[#07172b] p-5 text-white shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <div><p className="text-xs font-black uppercase tracking-[.16em] text-orange-400">Food Service · sessão operacional</p><h1 className="mt-1 text-2xl font-black">Mesas e comandas</h1><p className="mt-2 max-w-2xl text-sm text-slate-300">A mesa física, a sessão de atendimento e cada comanda possuem identidade e histórico próprios.</p></div>
      <div className="flex flex-wrap gap-2">
        <button onClick={() => void load()} disabled={loading} className="flex h-11 items-center gap-2 rounded-xl border border-slate-600 px-4 text-xs font-black"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Atualizar</button>
        {permissions.includes('table.session.open') && <button onClick={() => setDialog('TAB')} className="flex h-11 items-center gap-2 rounded-xl bg-orange-500 px-4 text-xs font-black text-white"><Receipt className="h-4 w-4" />Comanda individual</button>}
      </div>
    </header>

    {individualTabs.length > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-3 flex items-center gap-2"><Receipt className="h-4 w-4 text-orange-500" /><h2 className="text-sm font-black">Comandas sem mesa</h2></div><div className="flex flex-wrap gap-2">{individualTabs.map((item) => <button key={item.id} onClick={() => void openExisting(item.id)} className="rounded-xl border border-orange-200 bg-orange-50 px-4 py-3 text-left"><span className="block text-xs font-black text-orange-900">{item.display_label}</span><span className="mt-1 block text-xs text-orange-700">{item.item_count} itens · {formatCurrency(Number(item.consolidated_total))}</span></button>)}</div></section>}

    {/* Side-by-side from lg (1024px) so a landscape tablet keeps the session panel
        next to the map instead of stacking it below the fold. */}
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_clamp(22rem,32vw,29rem)]">
      <section className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <div className="mb-4 flex items-center justify-between"><div><h2 className="font-black">Mapa operacional</h2><p className="text-xs text-slate-500">{tables.length} mesas persistidas nesta unidade</p></div>{loading && <Loader2 className="h-5 w-5 animate-spin text-slate-400" />}</div>
        {tables.filter(table => table.status === 'RESERVED' && table.active_reservation).map(table => <button key={`arrival-${table.id}`} disabled={busy} onClick={() => setPendingReservationTable(table)} className="mb-4 mr-2 rounded-xl border border-sky-300 bg-sky-50 px-4 py-3 text-left text-xs font-black text-sky-900"><CalendarClock className="mr-2 inline h-4 w-4" />{table.name}: {table.active_reservation?.customer_name} chegou · confirmar abertura</button>)}
        {!loading && tables.length === 0 ? <EmptyState /> : <div className="grid grid-cols-1 min-[400px]:grid-cols-2 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">{tables.map((table) => {
          const legacyReservation = isLegacyReservationBlock(table)
          const visualStatus = legacyReservation ? 'RESERVED' : table.status
          return <article key={table.id} className={`overflow-hidden rounded-2xl border-2 transition hover:-translate-y-0.5 hover:shadow-md ${statusClass[visualStatus]}`}><button disabled={busy || table.status === 'BLOCKED'} onClick={() => void openTable(table)} className="min-h-32 w-full p-4 text-left disabled:cursor-not-allowed"><div className="flex items-start justify-between gap-2"><Armchair className="h-5 w-5" /><span className="rounded-full bg-white/70 px-2 py-1 text-[10px] font-black uppercase">{statusLabel[visualStatus]}</span></div><p className="mt-4 text-lg font-black">{table.name}</p><p className="text-xs opacity-70">{table.area || 'Área geral'} · {table.capacity} lugares</p>{table.blocking_reason && !legacyReservation && <p className="mt-2 rounded-lg bg-red-100/80 p-2 text-xs font-black text-red-800">{table.status === 'OCCUPIED' ? 'Bloquear ao fechar: ' : ''}{table.blocking_reason}</p>}{legacyReservation && <p className="mt-2 rounded-lg bg-sky-100/80 p-2 text-xs font-black text-sky-800">Reserva aguardando chegada</p>}{table.active_reservation && <div className="mt-3 rounded-lg bg-white/60 p-2 text-xs font-bold"><p>{table.active_reservation.customer_name} · {table.active_reservation.party_size} pessoas</p><p>{formatApiDateTime(table.active_reservation.reserved_for, 'time')}</p></div>}{table.active_session_id && <div className="mt-3 border-t border-current/15 pt-2 text-xs font-bold"><p>{table.item_count} itens · {table.order_count} comandas</p><p className="mt-0.5 text-sm font-black">{formatCurrency(Number(table.consolidated_total))}</p></div>}</button>{legacyReservation ? <button disabled={busy} onClick={() => void repairLegacyReservationAndOpen(table)} className="flex h-10 w-full items-center justify-center gap-1 border-t border-sky-200 bg-sky-600 text-[10px] font-black uppercase text-white disabled:opacity-40"><CheckCircle2 className="h-3.5 w-3.5" />Cliente chegou · abrir mesa</button> : permissions.includes('table.state.update') && ['AVAILABLE', 'OCCUPIED', 'BLOCKED'].includes(table.status) && <button disabled={busy} onClick={() => { setStateDialogTable(table); setStateReason('') }} className="flex h-9 w-full items-center justify-center gap-1 border-t border-current/15 bg-white/40 text-[10px] font-black uppercase"><Ban className="h-3.5 w-3.5" />{table.status === 'BLOCKED' ? 'Liberar mesa' : table.status === 'OCCUPIED' && table.blocking_reason ? 'Cancelar bloqueio' : table.status === 'OCCUPIED' ? 'Bloquear ao fechar' : 'Sinalizar impedimento'}</button>}</article>
        })}</div>}
      </section>
      <SessionPanel session={selected} availableSessions={sessions} availableTables={tables} headers={headers} products={products} operatorId={operatorId} permissions={permissions} cashSession={cashSession} registerId={register?.id} busy={busy} setBusy={setBusy} onChanged={async (sessionId) => { setSelected(await api.getTableSession(headers, sessionId)); await load(false) }} onClosed={async () => { setSelected(null); await load(false) }} onClose={() => setSelected(null)} showToast={showToast} />
    </div>

    {dialog === 'TAB' && store && <OpenTabDialog storeId={store.id} actorId={operatorId} headers={headers} onClose={() => setDialog(null)} onOpened={async (session) => { setDialog(null); setSelected(session); await load(false) }} showToast={showToast} />}
    {stateDialogTable && <Dialog title={stateDialogTable.status === 'BLOCKED' || stateDialogTable.blocking_reason ? 'Liberar impedimento' : stateDialogTable.status === 'OCCUPIED' ? 'Bloquear após fechamento' : 'Sinalizar impedimento'} onClose={() => { setStateDialogTable(null); setStateReason('') }}><div className="rounded-2xl bg-slate-50 p-4"><p className="text-xs font-black uppercase tracking-wide text-slate-500">{stateDialogTable.name}</p><p className="mt-2 text-sm leading-6 text-slate-600">{stateDialogTable.status === 'OCCUPIED' && !stateDialogTable.blocking_reason ? 'A conta continua ativa. A mesa será bloqueada automaticamente quando o atendimento terminar.' : 'Informe o motivo para manter a alteração auditável.'}</p></div><label className="mt-4 block text-xs font-black text-slate-700">Motivo<textarea autoFocus rows={3} value={stateReason} onChange={(event) => setStateReason(event.target.value)} placeholder="Descreva o defeito, impedimento ou motivo da liberação" className="mt-2 w-full resize-none rounded-xl border border-slate-300 p-3 text-sm outline-none focus:border-orange-500" /></label><div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3"><button onClick={() => { setStateDialogTable(null); setStateReason('') }} className="h-11 rounded-xl border border-slate-300 text-sm font-black text-slate-600">Cancelar</button><button disabled={busy || stateReason.trim().length < 3} onClick={() => void changeTableState()} className="h-11 rounded-xl bg-slate-950 text-sm font-black text-white disabled:opacity-40">Confirmar alteração</button></div></Dialog>}
    {pendingReservationTable?.active_reservation && <Dialog title="Mesa reservada" onClose={() => setPendingReservationTable(null)}><div className="rounded-2xl border border-sky-200 bg-sky-50 p-4"><div className="flex items-center gap-2 text-sky-800"><CalendarClock className="h-5 w-5" /><p className="text-xs font-black uppercase">Confirme antes de abrir</p></div><h3 className="mt-3 text-xl font-black">{pendingReservationTable.active_reservation.customer_name}</h3><p className="mt-1 text-sm text-slate-600">{pendingReservationTable.active_reservation.party_size} pessoas · {formatApiDateTime(pendingReservationTable.active_reservation.reserved_for)}</p>{pendingReservationTable.active_reservation.notes && <p className="mt-3 rounded-xl bg-white p-3 text-sm text-slate-600">{pendingReservationTable.active_reservation.notes}</p>}</div><div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3"><button onClick={() => setPendingReservationTable(null)} className="h-11 rounded-xl border border-slate-300 text-sm font-black text-slate-600">Voltar</button><button disabled={busy} onClick={() => void confirmReservedTable()} className="h-11 rounded-xl bg-sky-600 text-sm font-black text-white disabled:opacity-40">Confirmar chegada e abrir</button></div></Dialog>}
  </section>
}

function SessionPanel({ session, availableSessions, availableTables, headers, products, operatorId, permissions, cashSession, registerId, busy, setBusy, onChanged, onClosed, onClose, showToast }: {
  session: api.TableSession | null; availableSessions: api.TableSessionSummary[]; availableTables: api.ServiceTableProjection[]; headers: Record<string, string>; products: api.SellableProduct[]; operatorId: string; permissions: string[]; cashSession: api.CashSession | null; registerId?: string; busy: boolean; setBusy: (value: boolean) => void; onChanged: (sessionId: string) => Promise<void>; onClosed: () => Promise<void>; onClose: () => void; showToast: (type: 'success' | 'error' | 'info', text: string) => void
}) {
  const [orderId, setOrderId] = useState('')
  const [selectingProducts, setSelectingProducts] = useState(false)
  const [negotiation, setNegotiation] = useState<api.CheckoutNegotiation | null>(null)
  const [paymentMethod, setPaymentMethod] = useState<api.NegotiationPaymentMethod | 'TEF_CREDIT' | 'TEF_DEBIT'>('PIX')
  const [paymentAmount, setPaymentAmount] = useState('')
  const [tefTerminal, setTefTerminal] = useState<api.TefBridgeTerminal | null>(null)
  const [tefBinding, setTefBinding] = useState<api.PaymentDeviceBinding | null>(null)
  const [transferMode, setTransferMode] = useState<'ITEM' | 'ORDER' | 'MERGE'>('ITEM')
  const [transfer, setTransfer] = useState({ itemId: '', orderId: '', destinationId: '', quantity: '1', reason: '' })
  const [transferHistory, setTransferHistory] = useState<api.TransferRecord[]>([])
  const [checkoutOrderId, setCheckoutOrderId] = useState('')
  const [settledOrderId, setSettledOrderId] = useState('')
  // Three ways of building the same PaymentAllocation, never three systems.
  const [payMode, setPayMode] = useState<PayMode>('ALL')
  const [payerLabel, setPayerLabel] = useState('')
  const [peopleCount, setPeopleCount] = useState('2')
  const [pickedItems, setPickedItems] = useState<string[]>([])
  useEffect(() => {
    setOrderId(session?.orders.find((order) => order.status === 'OPEN')?.id || '')
    setSelectingProducts(false)
    setNegotiation(null); setPaymentAmount(''); setCheckoutOrderId(''); setSettledOrderId('')
    setPayMode('ALL'); setPayerLabel(''); setPeopleCount('2'); setPickedItems([])
    setTransfer({ itemId: '', orderId: '', destinationId: '', quantity: '1', reason: '' })
  }, [session?.id, session?.orders.length])
  useEffect(() => {
    if (!session || !permissions.includes('transfer.read')) { setTransferHistory([]); return }
    void api.fetchTransfers(headers, session.id).then(setTransferHistory).catch(() => setTransferHistory([]))
  }, [headers, permissions, session?.id, session?.version])
  if (!session) return <aside className="flex min-h-[480px] items-center justify-center rounded-3xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center"><div><Receipt className="mx-auto h-10 w-10 text-slate-300" /><h2 className="mt-4 font-black">Selecione uma mesa ou comanda</h2><p className="mt-2 text-sm leading-6 text-slate-500">A conta consolidada e o histórico real aparecerão aqui.</p></div></aside>
  const activeOrders = session.orders.filter((order) => ['OPEN', 'SUBMITTED'].includes(order.status))
  const destinationSessions = availableSessions.filter((item) => item.id !== session.id && ['OPEN', 'IN_SERVICE'].includes(item.status))
  const destinationTables = availableTables.filter((table) => table.status === 'AVAILABLE' && !table.active_session_id && table.id !== session.service_table_id)
  const attendantIds = Array.from(new Set([
    session.attendant_id, session.opened_by,
    ...session.orders.map((order) => order.opened_by),
    ...session.orders.flatMap((order) => order.items.map((item) => item.added_by)),
    ...session.events.map((event) => event.actor_id),
  ].filter(Boolean)))
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
  const transferItem = async () => {
    const destination=availableSessions.find(item=>item.id===transfer.destinationId)
    if(!destination||!transfer.itemId||Number(transfer.quantity)<=0||transfer.reason.trim().length<3)return
    setBusy(true)
    try {
      const record=await api.transferOrderItem(headers,crypto.randomUUID(),{source_session_id:session.id,destination_session_id:destination.id,order_item_id:transfer.itemId,quantity:Number(transfer.quantity),expected_source_version:session.version,expected_destination_version:destination.version,reason:transfer.reason,actor_id:operatorId})
      setTransfer({itemId:'',orderId:'',destinationId:'',quantity:'1',reason:''});await onChanged(session.id)
      showToast('success',record.production_compensation_required?'Item transferido; compensação de produção sinalizada.':'Item transferido com linhagem preservada.')
    } catch(error){showToast('error',error instanceof Error?error.message:'Não foi possível transferir o item.')} finally{setBusy(false)}
  }
  const transferWholeOrder = async () => {
    const destination=destinationSessions.find(item=>item.id===transfer.destinationId)
    const destinationTable=destinationTables.find(item=>`table:${item.id}`===transfer.destinationId)
    if((!destination&&!destinationTable)||!transfer.orderId||transfer.reason.trim().length<3)return
    setBusy(true)
    try {
      if(destinationTable)await api.transferOrderToTable(headers,crypto.randomUUID(),{source_session_id:session.id,destination_table_id:destinationTable.id,order_id:transfer.orderId,expected_source_version:session.version,expected_table_version:destinationTable.version,reason:transfer.reason.trim(),actor_id:operatorId})
      else if(destination)await api.transferOrder(headers,crypto.randomUUID(),{source_session_id:session.id,destination_session_id:destination.id,order_id:transfer.orderId,expected_source_version:session.version,expected_destination_version:destination.version,reason:transfer.reason.trim(),actor_id:operatorId})
      setTransfer({itemId:'',orderId:'',destinationId:'',quantity:'1',reason:''});await onChanged(session.id)
      showToast('success',destinationTable?'Comanda separada para a nova mesa, com identidade e autoria preservadas.':'Comanda transferida inteira, com identidade e autoria preservadas.')
    } catch(error){showToast('error',error instanceof Error?error.message:'Não foi possível transferir a comanda.')} finally{setBusy(false)}
  }
  const mergeIntoDestination = async () => {
    const destination=destinationSessions.find(item=>item.id===transfer.destinationId)
    const destinationTable=destinationTables.find(item=>`table:${item.id}`===transfer.destinationId)
    if((!destination&&!destinationTable)||transfer.reason.trim().length<3)return
    setBusy(true)
    try {
      if(destinationTable){
        await api.moveTableSession(headers,crypto.randomUUID(),{source_session_id:session.id,destination_table_id:destinationTable.id,expected_source_version:session.version,expected_table_version:destinationTable.version,reason:transfer.reason.trim(),actor_id:operatorId})
        showToast('success',`Atendimento inteiro movido para ${destinationTable.name}, com a mesma sessão e histórico.`);await onChanged(session.id)
      }else if(destination){
        await api.mergeTableSessions(headers,crypto.randomUUID(),{source_session_id:session.id,destination_session_id:destination.id,expected_source_version:session.version,expected_destination_version:destination.version,reason:transfer.reason.trim(),actor_id:operatorId})
        showToast('success',`Atendimento unido a ${destination.display_label}; a origem foi encerrada com histórico.`);await onClosed()
      }
    } catch(error){showToast('error',error instanceof Error?error.message:'Não foi possível juntar os atendimentos.')} finally{setBusy(false)}
  }
  const openCheckout = async () => {
    setBusy(true)
    try {
      const scopedOrder=activeOrders.find((order)=>order.id===checkoutOrderId)
      const opened = await api.openCheckoutNegotiation(headers, crypto.randomUUID(), {
        store_id: session.store_id,
        ...(scopedOrder ? { order_ids: [scopedOrder.id] } : { table_session_id: session.id }),
        actor_id: operatorId,
      })
      setSettledOrderId(scopedOrder?.id || ''); setNegotiation(opened); setPaymentAmount(cobravelAgoraDe(opened).toFixed(2))
      if (registerId && permissions.includes('provider.read')) {
        const [bindings, terminals] = await Promise.all([
          api.fetchPaymentDeviceBindings(headers, registerId),
          api.fetchTefBridgeTerminals(headers, registerId),
        ])
        const binding = bindings.find((item) => item.status === 'ACTIVE' && item.execution_mode === 'TEF_BRIDGE') || null
        setTefBinding(binding)
        setTefTerminal(binding ? terminals.find((item) => item.id === binding.tef_bridge_terminal_id) || null : null)
      }
      showToast('success', 'Conta congelada em um snapshot financeiro autoritativo.')
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível abrir a conta.') }
    finally { setBusy(false) }
  }
  const addAndConfirmPayment = async () => {
    if (!negotiation || Number(paymentAmount) <= 0) return
    if (paymentMethod === 'CASH' && cashSession?.status !== 'OPEN') { showToast('error', 'Abra uma sessão de caixa para receber em dinheiro.'); return }
    if ((paymentMethod === 'TEF_CREDIT' || paymentMethod === 'TEF_DEBIT') && !tefBinding) {
      showToast('error', 'TEF não possui vínculo ativo neste caixa.'); return
    }
    setBusy(true)
    try {
      const isTef = paymentMethod === 'TEF_CREDIT' || paymentMethod === 'TEF_DEBIT'
      const canonicalMethod: api.NegotiationPaymentMethod = paymentMethod === 'TEF_CREDIT' ? 'CREDIT_CARD' : paymentMethod === 'TEF_DEBIT' ? 'DEBIT_CARD' : paymentMethod
      // Paying by item names the lines; paying it all, or a share of it, names
      // nothing and lets the server take it from the account's balance.
      const byItem = payMode === 'ITEMS'
        ? pickedItems
          .map((id) => negotiation.item_settlements.find((row) => row.order_item_id === id))
          .filter((row): row is api.ItemSettlement => Boolean(row))
          .map((row) => ({ amount: Number(row.available_amount), order_item_id: row.order_item_id }))
        : null
      const created = await api.createNegotiationPaymentIntent(headers, negotiation.id, crypto.randomUUID(), {
        method: canonicalMethod, amount: Number(paymentAmount),
        cash_session_id: paymentMethod === 'CASH' ? cashSession?.id : undefined,
        tendered_amount: paymentMethod === 'CASH' ? Number(paymentAmount) : undefined,
        allocations: byItem && byItem.length > 0
          ? byItem
          : settledOrderId ? [{ amount: Number(paymentAmount), order_id: settledOrderId }] : undefined,
        payer_label: payerLabel.trim() || undefined,
        // Declared here so the server proves the chain *before* holding a line
        // of the bill. The screen used to create the parcel and only then find
        // the bridge offline, leaving a reserve nobody could pay or release.
        payment_device_binding_id: isTef ? tefBinding?.id : undefined,
        actor_id: operatorId,
      })
      const pending = [...created.intents].reverse().find((item) => item.status === 'PENDING')
      if (!pending) throw new Error('A parcela persistida não ficou disponível para confirmação.')
      if (isTef) {
        if (!tefBinding) throw new Error('TEF não possui vínculo ativo neste caixa.')
        const execution = await api.executeProviderTransaction(headers, crypto.randomUUID(), {
          payment_intent_id: pending.id, payment_device_binding_id: tefBinding.id, actor_id: operatorId,
        })
        setNegotiation(execution.negotiation)
        // O valor proposto tem de ser recalculado aqui também. Sem isto o campo
        // guardava o valor de quando a conta abriu, e a tela continuava
        // oferecendo cobrar de novo o que já estava numa cobrança sem resposta.
        setPaymentAmount(cobravelAgoraDe(execution.negotiation).toFixed(2))
        setPickedItems([]); setPayerLabel('')
        showToast('info', execution.transaction.status === 'CONFIRMED' ? 'Parcela TEF confirmada.' : 'Transação enviada ao bridge; aguardando resultado ou reconciliação.')
        return
      }
      const confirmed = await api.confirmNegotiationPaymentIntent(headers, pending.id, crypto.randomUUID(), operatorId)
      setNegotiation(confirmed); setPickedItems([]); setPayerLabel('')
      setPaymentAmount(cobravelAgoraDe(confirmed).toFixed(2))
      showToast('success', `Parcela confirmada. Falta ${formatCurrency(Number(confirmed.remaining_amount))}.`)
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível confirmar a parcela.') }
    finally { setBusy(false) }
  }
  const queryParcel = async (intentId: string) => {
    setBusy(true)
    try {
      const updated = await api.queryNegotiationPaymentIntent(headers, intentId, operatorId)
      setNegotiation(updated)
      const parcel = updated.intents.find((row) => row.id === intentId)
      showToast(
        parcel?.awaiting_provider ? 'info' : 'success',
        parcel?.awaiting_provider
          ? 'O provider ainda não respondeu. A reserva continua com esta pessoa.'
          : 'Resultado recebido do provider.',
      )
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível consultar o pagamento.') }
    finally { setBusy(false) }
  }
  const cancelParcel = async (intentId: string) => {
    setBusy(true)
    try {
      const updated = await api.cancelNegotiationPaymentIntent(headers, intentId, crypto.randomUUID(), {
        reason: 'Reserva cancelada no balcão sem cobrança iniciada', actor_id: operatorId,
      })
      setNegotiation(updated); setPickedItems([])
      setPaymentAmount(cobravelAgoraDe(updated).toFixed(2))
      showToast('success', 'Reserva cancelada; o item voltou a ficar disponível.')
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível cancelar a reserva.') }
    finally { setBusy(false) }
  }
  const refundParcel = async (intentId: string, amount: number, reason: string) => {
    setBusy(true)
    try {
      const updated = await api.refundNegotiationPaymentIntent(headers, intentId, crypto.randomUUID(), {
        amount, reason, actor_id: operatorId,
      })
      setNegotiation(updated); setPickedItems([])
      setPaymentAmount(cobravelAgoraDe(updated).toFixed(2))
      const parcel = updated.intents.find((row) => row.id === intentId)
      // Pedir não é devolver: enquanto o adquirente não disser quanto reverteu,
      // a conta não muda, e a tela precisa dizer isso em vez de comemorar.
      showToast(
        parcel?.awaiting_refund ? 'info' : 'success',
        parcel?.awaiting_refund
          ? 'Estorno enviado ao provider. O saldo só volta quando ele confirmar o valor revertido.'
          : 'Estorno registrado; o item voltou a ficar disponível.',
      )
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível estornar a parcela.') }
    finally { setBusy(false) }
  }
  const finalize = async () => {
    if (!negotiation) return
    setBusy(true)
    try {
      const finalized = await api.finalizeCheckoutNegotiation(headers, negotiation.id, crypto.randomUUID(), negotiation.version, operatorId)
      setNegotiation(finalized)
      if (settledOrderId) {
        showToast('success', 'Comanda individual quitada; os demais grupos continuam no atendimento.')
        setNegotiation(null); setSettledOrderId(''); setCheckoutOrderId(''); await onChanged(session.id)
      } else {
        showToast('success', 'Venda materializada, conta finalizada e mesa liberada.'); await onClosed()
      }
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível finalizar a conta.') }
    finally { setBusy(false) }
  }
  return <aside className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-black uppercase tracking-[.16em] text-orange-600">{session.kind === 'TABLE' ? 'Sessão de mesa' : 'Comanda individual'}</p><h2 className="mt-1 text-xl font-black">{session.display_label}</h2><p className="mt-1 flex items-center gap-1 text-xs text-slate-500"><Clock3 className="h-3.5 w-3.5" />Aberta em {(parseApiDate(session.opened_at) ?? new Date()).toLocaleString('pt-BR')}</p></div><button onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 text-slate-500"><X className="h-4 w-4" /></button></div><div className="mt-4 grid grid-cols-1 gap-2 rounded-2xl bg-slate-50 p-3 text-center sm:grid-cols-3"><Metric label="Comandas" value={String(session.order_count)} /><Metric label="Itens" value={String(session.active_item_count)} /><Metric label="Total" value={formatCurrency(Number(session.consolidated_total))} /></div><p className="mt-2 text-xs font-bold text-slate-500">Atendimento auditado por {attendantIds.length} {attendantIds.length === 1 ? 'profissional' : 'profissionais'}; abertura, lançamentos e transferências preservam o ator de cada ação.</p>
    {permissions.includes('table.session.update') && !negotiation && <div className="mt-4 space-y-3 rounded-2xl border border-slate-200 p-3">
      <div className="flex items-center justify-between"><p className="text-xs font-black">Adicionar ao atendimento</p><button disabled={busy} onClick={() => void addOrder()} className="min-h-11 text-xs font-black text-orange-600">Nova comanda</button></div>
      <label className="block text-sm font-bold">Comanda de destino<select aria-label="Comanda de destino" value={orderId} onChange={event => setOrderId(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm text-slate-900">{activeOrders.filter(order => order.status === 'OPEN').map((order, index) => <option key={order.id} value={order.id}>{order.notes || `Comanda ${index + 1}`}</option>)}</select></label>
      <button disabled={busy || !activeOrders.some(order => order.id === orderId && order.status === 'OPEN')} onClick={() => setSelectingProducts(true)} className="min-h-11 w-full rounded-xl bg-orange-600 px-4 text-sm font-black text-white disabled:opacity-40">Escolher produtos</button>
    </div>}
    {selectingProducts && session.orders.some(order => order.id === orderId) && <TableProductSelector key={`${session.id}/${orderId}`} session={session} order={session.orders.find(order => order.id === orderId)!} onClose={() => setSelectingProducts(false)} onChanged={() => onChanged(session.id)} />}
    <div className="mt-4 max-h-72 space-y-3 overflow-y-auto">{session.orders.map((order, index) => <article key={order.id} className="rounded-2xl border border-slate-200 p-3"><div className="flex items-center justify-between"><p className="text-xs font-black">{order.notes || `Comanda ${index + 1}`}</p><span className="text-xs font-bold text-slate-400">{order.status}</span></div>{order.items.filter((item) => item.status === 'ACTIVE').length === 0 ? <p className="mt-2 text-xs text-slate-400">Sem lançamentos.</p> : <div className="mt-2 space-y-2">{order.items.filter((item) => item.status === 'ACTIVE').map((item) => <div key={item.id} className="flex justify-between gap-3 text-xs"><span><b>{Number(item.quantity)}×</b> {item.product_name}</span><b>{formatCurrency(Number(item.unit_price) * Number(item.quantity))}</b></div>)}</div>}</article>)}</div>
    {permissions.includes('transfer.execute')&&!negotiation&&(destinationSessions.length>0||destinationTables.length>0)&&<section className="mt-4 space-y-3 rounded-2xl border border-violet-200 bg-violet-50 p-3">
      <p className="flex items-center gap-2 text-xs font-black text-violet-900"><ArrowRightLeft className="h-4 w-4"/>Mover ou juntar com linhagem</p>
      <div className="grid grid-cols-3 gap-1 rounded-xl bg-white p-1">{([['ITEM','Item'],['ORDER','Comanda'],['MERGE','Tudo']] as const).map(([mode,label])=><button key={mode} disabled={mode==='ITEM'?(session.active_item_count===0||destinationSessions.length===0):mode==='ORDER'?activeOrders.length===0:false} onClick={()=>{setTransferMode(mode);setTransfer({...transfer,destinationId:''})}} className={`h-9 rounded-lg text-xs font-black disabled:opacity-30 ${transferMode===mode?'bg-violet-700 text-white':'text-violet-900'}`}>{label}</button>)}</div>
      {transferMode==='ITEM'&&<><select value={transfer.itemId} onChange={e=>setTransfer({...transfer,itemId:e.target.value})} className="h-10 w-full rounded-xl border px-3 text-xs"><option value="">Selecione o item</option>{activeOrders.flatMap(order=>order.items).filter(item=>item.status==='ACTIVE').map(item=><option key={item.id} value={item.id}>{Number(item.quantity)}× {item.product_name}</option>)}</select><div className="grid grid-cols-[80px_1fr] gap-2"><input aria-label="Quantidade a transferir" type="number" min="0.001" step="0.001" value={transfer.quantity} onChange={e=>setTransfer({...transfer,quantity:e.target.value})} className="h-10 rounded-xl border px-2 text-xs"/><input aria-label="Motivo da transferência" value={transfer.reason} onChange={e=>setTransfer({...transfer,reason:e.target.value})} placeholder="Motivo obrigatório" className="h-10 rounded-xl border px-3 text-xs"/></div></>}
      {transferMode==='ORDER'&&<><select value={transfer.orderId} onChange={e=>setTransfer({...transfer,orderId:e.target.value})} className="h-10 w-full rounded-xl border px-3 text-xs"><option value="">Selecione a comanda ou grupo</option>{activeOrders.map((order,index)=><option key={order.id} value={order.id}>{order.notes||`Comanda ${index+1}`}</option>)}</select><input aria-label="Motivo da transferência" value={transfer.reason} onChange={e=>setTransfer({...transfer,reason:e.target.value})} placeholder="Motivo obrigatório" className="h-10 w-full rounded-xl border px-3 text-xs"/></>}
      {transferMode==='MERGE'&&<><p className="rounded-xl bg-white p-3 text-xs leading-5 text-violet-900">Todas as comandas irão para o destino e esta sessão será encerrada. Pedidos, itens e autoria não são recriados.</p><input aria-label="Motivo da junção" value={transfer.reason} onChange={e=>setTransfer({...transfer,reason:e.target.value})} placeholder="Motivo obrigatório" className="h-10 w-full rounded-xl border px-3 text-xs"/></>}
      <select value={transfer.destinationId} onChange={e=>setTransfer({...transfer,destinationId:e.target.value})} className="h-10 w-full rounded-xl border px-3 text-xs"><option value="">Mesa ou comanda de destino</option>{destinationSessions.map(item=><option key={item.id} value={item.id}>{item.display_label} · atendimento ativo</option>)}{transferMode!=='ITEM'&&destinationTables.map(table=><option key={table.id} value={`table:${table.id}`}>{table.name} · {table.area||'Área geral'} · mesa livre</option>)}</select>
      <button disabled={busy||!transfer.destinationId||transfer.reason.trim().length<3||(transferMode==='ITEM'&&!transfer.itemId)||(transferMode==='ORDER'&&!transfer.orderId)} onClick={()=>void(transferMode==='ITEM'?transferItem():transferMode==='ORDER'?transferWholeOrder():mergeIntoDestination())} className="h-10 w-full rounded-xl bg-violet-700 text-xs font-black text-white disabled:opacity-40">{transferMode==='ITEM'?'Transferir quantidade':transferMode==='ORDER'?'Mover comanda inteira':'Juntar tudo no destino'}</button>
    </section>}
    {permissions.includes('transfer.read')&&transferHistory.length>0&&<details className="mt-3 rounded-2xl border border-slate-200 p-3"><summary className="cursor-pointer text-xs font-black text-slate-700">Histórico de movimentações ({transferHistory.length})</summary><div className="mt-3 space-y-2">{transferHistory.slice(0,10).map((record)=><div key={record.id} className="rounded-xl bg-slate-50 p-3 text-xs"><div className="flex items-center justify-between gap-2"><b>{record.transfer_type==='ITEM'?'Item transferido':record.transfer_type==='ORDER'?'Comanda transferida':record.transfer_type==='SESSION_MOVE'?'Atendimento mudou de mesa':'Atendimentos unidos'}</b><span>{formatApiDateTime(record.created_at)}</span></div><p className="mt-1 text-slate-600">{record.reason}</p><p className="mt-1 text-slate-500">Ator {record.actor_id===operatorId?'atual':record.actor_id.slice(0,8)}</p></div>)}</div></details>}
    {session.active_item_count === 0 && permissions.includes('table.session.close') && <button disabled={busy} onClick={() => void close()} className="mt-4 h-10 w-full rounded-xl border border-slate-300 text-xs font-black text-slate-600">Encerrar sessão vazia</button>}
    {session.active_item_count > 0 && permissions.includes('checkout.open') && !negotiation && <section className="mt-4 space-y-2"><label className="block text-xs font-black text-slate-700">Quem vai pagar<select value={checkoutOrderId} onChange={(event)=>setCheckoutOrderId(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm"><option value="">Conta completa da mesa</option>{activeOrders.map((order,index)=><option key={order.id} value={order.id}>{order.notes||`Comanda ${index+1}`} · {formatCurrency(order.items.filter(item=>item.status==='ACTIVE').reduce((total,item)=>total+Number(item.unit_price)*Number(item.quantity),0))}</option>)}</select></label><button disabled={busy} onClick={() => void openCheckout()} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-slate-950 text-sm font-black text-white"><WalletCards className="h-4 w-4" />{checkoutOrderId?'Pagar esta comanda':'Fechar conta completa'}</button></section>}
    {negotiation && <CheckoutSettlement negotiation={negotiation} scopedOrder={settledOrderId} busy={busy} permissions={permissions} tefTerminal={tefTerminal} method={paymentMethod} onMethod={setPaymentMethod} amount={paymentAmount} onAmount={setPaymentAmount} payer={payerLabel} onPayer={setPayerLabel} mode={payMode} onMode={setPayMode} people={peopleCount} onPeople={setPeopleCount} picked={pickedItems} onPicked={setPickedItems} onPay={() => void addAndConfirmPayment()} onFinalize={() => void finalize()} onQuery={(id) => void queryParcel(id)} onCancel={(id) => void cancelParcel(id)} onRefund={(id, amount, reason) => void refundParcel(id, amount, reason)} />}
  </aside>
}

function Metric({ label, value }: { label: string; value: string }) { return <div><p className="text-[10px] font-bold uppercase text-slate-400">{label}</p><p className="mt-1 text-sm font-black">{value}</p></div> }
function EmptyState() { return <div className="flex min-h-72 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center"><div><Armchair className="mx-auto h-10 w-10 text-slate-300" /><h3 className="mt-4 font-black">Mapa ainda não configurado</h3><p className="mt-2 max-w-sm text-sm text-slate-500">O administrador deve cadastrar ambientes e mesas no Dashem Gestão antes do atendimento.</p></div></div> }

function OpenTabDialog({ storeId, actorId, headers, onClose, onOpened, showToast }: { storeId: string; actorId: string; headers: Record<string, string>; onClose: () => void; onOpened: (session: api.TableSession) => Promise<void>; showToast: (type: 'success' | 'error' | 'info', text: string) => void }) {
  const [label, setLabel] = useState(''); const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); try { const session = await api.openTableSession(headers, crypto.randomUUID(), { store_id: storeId, display_label: label, actor_id: actorId }); showToast('success', 'Comanda individual aberta.'); await onOpened(session) } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível abrir a comanda.') } finally { setSaving(false) } }
  return <Dialog title="Abrir comanda individual" onClose={onClose}><form onSubmit={submit} className="space-y-3"><Input label="Identificação" value={label} onChange={setLabel} placeholder="Nome, senha ou referência" /><p className="text-xs leading-5 text-slate-500">A comanda nasce sem mesa fictícia e recebe uma sessão e um pedido próprios.</p><button disabled={saving || label.trim().length < 2} className="h-11 w-full rounded-xl bg-orange-500 text-sm font-black text-white disabled:opacity-40">{saving ? 'Abrindo...' : 'Abrir comanda'}</button></form></Dialog>
}

function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4"><section className="responsive-dialog w-full max-w-lg rounded-3xl bg-white p-6 shadow-2xl"><header className="mb-5 flex items-center justify-between"><h2 className="text-xl font-black">{title}</h2><button onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200"><X className="h-4 w-4" /></button></header>{children}</section></div> }
function Input({ label, value, onChange, placeholder, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) { return <label className="block text-xs font-black text-slate-700">{label}<input required type={type} min={type === 'number' ? 1 : undefined} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-1.5 h-11 w-full rounded-xl border border-slate-300 px-3 text-sm font-medium outline-none focus:border-rose-500" /></label> }

type PayMode = 'ALL' | 'PEOPLE' | 'ITEMS'
const payModes: Array<[PayMode, string]> = [['ALL', 'Tudo'], ['PEOPLE', 'Por pessoa'], ['ITEMS', 'Por itens']]
// Internal codes are not business language: the correction track made that a
// rule, and a parcel is read by whoever is at the counter.
const intentStatusLabel: Record<api.PaymentIntentStatus, string> = {
  PENDING: 'aguardando', PROCESSING: 'processando', CONFIRMED: 'confirmado',
  FAILED: 'falhou', CANCELED: 'cancelado',
}
/**
 * Quanto se pode cobrar agora nesta conta.
 *
 * Não é `remaining_amount`: uma cobrança sem resposta já segura a sua parte, e
 * propor o valor inteiro faz a tela sugerir uma segunda cobrança que o servidor
 * recusa. O valor proposto na tela sai daqui, sempre.
 */
const cobravelAgoraDe = (conta: api.CheckoutNegotiation): number =>
  Math.max(0, Number(conta.remaining_amount) - Number(conta.processing_amount ?? 0))

const methodLabel: Record<api.NegotiationPaymentMethod, string> = {
  CASH: 'Dinheiro', PIX: 'PIX', CREDIT_CARD: 'Crédito', DEBIT_CARD: 'Débito',
  STORE_CREDIT: 'Crediário',
}

/**
 * The bill, while people are still at the table.
 *
 * Paying everything, splitting between four friends and paying for your own
 * hamburger are not three features. They are three ways of building the same
 * PaymentAllocation over one settlement engine, so this panel is one panel with
 * three ways of choosing an amount.
 *
 * Availability is the server's word, never arithmetic here: a line somebody else
 * is paying for right now reads as taken long before their card comes back, and
 * a line already settled says who settled it.
 */
function CheckoutSettlement({
  negotiation, scopedOrder, busy, permissions, tefTerminal, method, onMethod, amount, onAmount,
  payer, onPayer, mode, onMode, people, onPeople, picked, onPicked, onPay, onFinalize,
  onQuery, onCancel, onRefund,
}: {
  negotiation: api.CheckoutNegotiation; scopedOrder: string; busy: boolean; permissions: string[]
  tefTerminal: api.TefBridgeTerminal | null
  method: api.NegotiationPaymentMethod | 'TEF_CREDIT' | 'TEF_DEBIT'
  onMethod: (value: api.NegotiationPaymentMethod | 'TEF_CREDIT' | 'TEF_DEBIT') => void
  amount: string; onAmount: (value: string) => void
  payer: string; onPayer: (value: string) => void
  mode: PayMode; onMode: (value: PayMode) => void
  people: string; onPeople: (value: string) => void
  picked: string[]; onPicked: (value: string[]) => void
  onPay: () => void; onFinalize: () => void
  onQuery: (intentId: string) => void; onCancel: (intentId: string) => void
  onRefund: (intentId: string, amount: number, reason: string) => void
}) {
  const remaining = Number(negotiation.remaining_amount)
  // O que se pode cobrar **agora** não é o que falta: uma cobrança sem resposta
  // já segura a sua parte da conta. Propor o valor inteiro convidava a operadora
  // a mandar uma segunda cobrança que o servidor recusa — e a recusa dele fala
  // em "saldo reservável", que não é língua de balcão. Medido na homologação do
  // TEF em processamento (09/09/2026).
  const processing = Number(negotiation.processing_amount ?? 0)
  const cobravelAgora = cobravelAgoraDe(negotiation)
  // Centavo de tolerância: o valor digitado vem de um campo de texto, e comparar
  // decimais sem folga reprova um "62.00" que é exatamente o limite.
  const pedido = Number(amount)
  const acimaDoLimite = Number.isFinite(pedido) && pedido - cobravelAgora > 0.005
  const lines = negotiation.item_settlements ?? []
  const openLines = lines.filter((row) => Number(row.available_amount) > 0)
  const pickedTotal = lines
    .filter((row) => picked.includes(row.order_item_id))
    .reduce((total, row) => total + Number(row.available_amount), 0)
  const share = Math.max(0, Number(people) || 0) > 0 ? cobravelAgora / Number(people) : 0

  // Choosing a way to pay proposes an amount; the operator may still overwrite it.
  const choose = (next: PayMode) => {
    onMode(next); onPicked([])
    if (next === 'ALL') onAmount(cobravelAgora.toFixed(2))
    if (next === 'PEOPLE') onAmount((cobravelAgora / Math.max(1, Number(people) || 1)).toFixed(2))
    if (next === 'ITEMS') onAmount('0.00')
  }
  const toggle = (row: api.ItemSettlement) => {
    const next = picked.includes(row.order_item_id)
      ? picked.filter((id) => id !== row.order_item_id)
      : [...picked, row.order_item_id]
    onPicked(next)
    onAmount(lines.filter((item) => next.includes(item.order_item_id))
      .reduce((total, item) => total + Number(item.available_amount), 0).toFixed(2))
  }
  return <section className="mt-4 space-y-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-3">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-[10px] font-black uppercase tracking-wider text-emerald-700">{scopedOrder ? 'Pagamento individual ou por grupo' : 'Conta viva da mesa'}</p>
        <p className="text-sm font-black">{negotiation.status === 'COVERED' ? 'Conta integralmente coberta' : 'Pagamento parcial em andamento'}</p>
      </div>
      <CreditCard className="h-5 w-5 text-emerald-700" />
    </div>
    {/*
      "Falta R$ 18,00" com R$ 18,00 em cobrança sem resposta é verdade pela
      metade: falta mesmo, e não se pode cobrar agora. A quarta métrica aparece
      só quando existe cobrança em voo, e é ela que explica a diferença.
    */}
    <div className={`grid grid-cols-1 gap-2 rounded-xl bg-white p-3 text-center ${processing > 0 ? 'min-[400px]:grid-cols-4' : 'min-[400px]:grid-cols-3'}`}>
      <Metric label="Total" value={formatCurrency(Number(negotiation.total_due))} />
      <Metric label="Confirmado" value={formatCurrency(Number(negotiation.confirmed_amount))} />
      {processing > 0 && <Metric label="Em processamento" value={formatCurrency(processing)} />}
      <Metric label="Falta" value={formatCurrency(remaining)} />
    </div>

    {lines.length > 0 && <div className="space-y-1 rounded-xl bg-white p-2">
      <p className="px-1 text-[10px] font-black uppercase tracking-wider text-slate-400">Consumo e quitação</p>
      {lines.map((row) => {
        const taken = Number(row.available_amount) === 0
        const chosen = picked.includes(row.order_item_id)
        const selectable = mode === 'ITEMS' && !taken && negotiation.status !== 'COVERED' && permissions.includes('checkout.payment')
        return <button
          key={row.order_item_id} type="button" disabled={!selectable}
          onClick={() => selectable && toggle(row)}
          aria-pressed={chosen}
          className={`flex w-full items-start justify-between gap-3 rounded-lg px-2 py-2 text-left text-xs ${selectable ? 'hover:bg-emerald-50' : ''} ${chosen ? 'bg-emerald-100' : ''} ${taken ? 'opacity-60' : ''}`}
        >
          <span className="flex min-w-0 items-start gap-2">
            {mode === 'ITEMS' && <span aria-hidden="true" className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px] font-black ${chosen ? 'border-emerald-700 bg-emerald-700 text-white' : taken ? 'border-slate-200 bg-slate-100 text-slate-300' : 'border-emerald-300 bg-white text-transparent'}`}>✓</span>}
            <span className="min-w-0">
            <span className="block font-bold text-slate-800">{Number(row.quantity)}× {row.product_name}</span>
            {row.is_paid && <span className="block text-[11px] font-black text-emerald-700">PAGO{row.settled_by.length > 0 ? ` · ${row.settled_by.join(', ')}` : ''}</span>}
            {!row.is_paid && Number(row.reserved_amount) > 0 && <span className="block text-[11px] font-black text-amber-700">EM PAGAMENTO{row.reserved_by.length > 0 ? ` · ${row.reserved_by.join(', ')}` : ''}</span>}
            {!row.is_paid && Number(row.settled_amount) > 0 && Number(row.available_amount) > 0 && <span className="block text-[11px] text-slate-500">Parcial: {formatCurrency(Number(row.settled_amount))} de {formatCurrency(Number(row.item_total))}</span>}
            </span>
          </span>
          <b className={`whitespace-nowrap ${taken ? 'text-slate-400 line-through' : ''}`}>{formatCurrency(Number(row.available_amount) || Number(row.item_total))}</b>
        </button>
      })}
    </div>}

    {negotiation.intents.length > 0 && <div className="space-y-1">{negotiation.intents.map((intent) => <ParcelRow key={intent.id} intent={intent} busy={busy} canCancel={permissions.includes('checkout.payment.cancel')} canRefund={permissions.includes('checkout.payment.refund')} onQuery={onQuery} onCancel={onCancel} onRefund={onRefund} />)}</div>}
    {negotiation.divergences?.length > 0 && <div className="space-y-1 rounded-xl border border-amber-300 bg-amber-50 p-3">
      <p className="text-[10px] font-black uppercase tracking-wider text-amber-800">Pendente de conciliação</p>
      {negotiation.divergences.map((row) => <p key={row.id} className="text-[11px] leading-5 text-amber-900">
        <b>{divergenceLabel[row.kind] ?? row.kind}</b> · {formatCurrency(Number(row.amount))}{row.detail ? ` — ${row.detail}` : ''}
      </p>)}
      <p className="text-[11px] leading-5 text-amber-800">O provider respondeu algo que não pôde ser aplicado a esta conta. O registro fica aqui até alguém decidir; nada foi liberado nem cobrado por conta disso.</p>
    </div>}
    {permissions.includes('provider.read') && <p className={`rounded-lg px-3 py-2 text-xs font-bold ${tefTerminal?.status === 'ONLINE' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-900'}`}>{tefTerminal?.status === 'ONLINE' ? `TEF online · ${tefTerminal.terminal_code} · bridge ${tefTerminal.bridge_version || 'versão não informada'}` : 'TEF não configurado ou offline; meios locais permanecem disponíveis.'}</p>}

    {negotiation.status !== 'COVERED' && permissions.includes('checkout.payment') && <div className="space-y-2">
      <div className="grid grid-cols-3 gap-1 rounded-xl bg-white p-1">
        {payModes.map(([value, label]) => <button
          key={value} type="button"
          disabled={value === 'ITEMS' && openLines.length === 0}
          onClick={() => choose(value)}
          className={`h-9 rounded-lg text-xs font-black disabled:opacity-30 ${mode === value ? 'bg-emerald-700 text-white' : 'text-emerald-900'}`}
        >{label}</button>)}
      </div>
      {mode === 'PEOPLE' && <div className="grid grid-cols-[92px_1fr] items-end gap-2">
        <label className="block text-[10px] font-black uppercase text-slate-500">Pessoas
          <input aria-label="Quantidade de pessoas" type="number" min="1" step="1" value={people}
            onChange={(event) => { onPeople(event.target.value); onAmount((cobravelAgora / Math.max(1, Number(event.target.value) || 1)).toFixed(2)) }}
            className="mt-1 h-11 w-full rounded-xl border border-emerald-200 px-3 text-sm font-black" />
        </label>
        <p className="pb-3 text-xs text-slate-600">{formatCurrency(share)} por pessoa. O valor abaixo continua editável para quem paga a mais.</p>
      </div>}
      {mode === 'ITEMS' && <p className="rounded-lg bg-white px-3 py-2 text-xs text-slate-600">{picked.length === 0 ? 'Toque nos itens que esta pessoa vai pagar.' : `${picked.length} item(ns) · ${formatCurrency(pickedTotal)}`}</p>}
      <input aria-label="Quem está pagando" value={payer} onChange={(event) => onPayer(event.target.value)} placeholder="Quem está pagando (opcional)" className="h-11 w-full rounded-xl border border-emerald-200 px-3 text-sm" />
      <div className="grid grid-cols-[1fr_110px] gap-2">
        <select aria-label="Meio de pagamento" value={method} onChange={(event) => onMethod(event.target.value as api.NegotiationPaymentMethod | 'TEF_CREDIT' | 'TEF_DEBIT')} className="h-11 rounded-xl border border-emerald-200 bg-white px-3 text-xs font-bold">
          <option value="CASH">Dinheiro</option>
          <option value="PIX">PIX manual</option>
          <option value="CREDIT_CARD">Crédito manual</option>
          <option value="DEBIT_CARD">Débito manual</option>
          {tefTerminal?.status === 'ONLINE' && permissions.includes('provider.execute') && <>
            <option value="TEF_CREDIT">Crédito via TEF</option>
            <option value="TEF_DEBIT">Débito via TEF</option>
          </>}
        </select>
        <input aria-label="Valor da parcela" type="number" min="0.01" step="0.01" max={cobravelAgora.toFixed(2)} value={amount} onChange={(event) => onAmount(event.target.value)} className={`h-11 rounded-xl border px-3 text-sm font-black ${acimaDoLimite ? 'border-amber-500 bg-amber-50' : 'border-emerald-200'}`} />
        <button disabled={busy || cobravelAgora <= 0 || acimaDoLimite || Number(amount) <= 0 || (mode === 'ITEMS' && picked.length === 0)} onClick={onPay} className="col-span-2 h-11 rounded-xl bg-emerald-700 text-xs font-black text-white disabled:opacity-40">
          {mode === 'ITEMS' ? `Pagar ${picked.length} item(ns)` : 'Registrar parcela no meio selecionado'}
        </button>
      </div>
      {/*
        A regra é do dono: não oferecer nova cobrança sem resolver o estado
        anterior. O servidor já recusava — com "Parcela excede o saldo
        reservável de 0.0000", que ninguém no balcão entende. Agora a tela
        explica antes, em vez de deixar a pessoa descobrir pela recusa.
      */}
      {cobravelAgora <= 0 && processing > 0 && <p className="rounded-lg bg-amber-100 px-3 py-2 text-[11px] font-bold leading-5 text-amber-900">
        Não há valor para cobrar agora: {formatCurrency(processing)} desta conta está numa cobrança sem resposta. Consulte o pagamento acima antes de cobrar de novo.
      </p>}
      {/*
        Processamento **parcial**: parte da conta está em voo e parte continua
        cobrável. O limite é dito antes do envio, com o porquê ao lado — o
        servidor continua recusando o que passar dele, e é ele quem decide;
        aqui a pessoa só deixa de descobrir isso por tentativa.
      */}
      {cobravelAgora > 0 && processing > 0 && <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] font-bold leading-5 text-amber-900">
        Máximo a cobrar agora: {formatCurrency(cobravelAgora)}. Os outros {formatCurrency(processing)} desta conta estão numa cobrança sem resposta.
      </p>}
      {acimaDoLimite && <p className="rounded-lg bg-amber-200 px-3 py-2 text-[11px] font-black leading-5 text-amber-950">
        {formatCurrency(pedido)} passa do que dá para cobrar agora ({formatCurrency(cobravelAgora)}). Reduza o valor ou consulte a cobrança que está sem resposta.
      </p>}
      <p className="text-[11px] leading-5 text-slate-500">A mesa continua aberta enquanto houver saldo. Quem já pagou não some do consumo: o item fica marcado com o nome de quem quitou.</p>
    </div>}

    {negotiation.status === 'COVERED' && permissions.includes('checkout.finalize') && <button disabled={busy} onClick={onFinalize} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 text-sm font-black text-white">
      <CheckCircle2 className="h-4 w-4" />{scopedOrder ? 'Finalizar esta comanda' : 'Finalizar venda e liberar mesa'}
    </button>}
  </section>
}

const divergenceLabel: Record<api.SettlementDivergence['kind'], string> = {
  LATE_CONFIRMATION: 'Provider confirmou depois do encerramento',
  LATE_FAILURE: 'Provider recusou uma parcela já confirmada',
  EXTERNAL_CANCEL_AFTER_CONFIRM: 'Cancelamento externo sobre parcela confirmada',
  REFUND_REQUIRES_REVERSAL: 'Estorno no provider exige baixa por estorno',
  REFUND_WITHOUT_CAPTURE: 'Estorno sem prova de reversão integral; o saldo segue reservado',
  STATE_REGRESSION_REFUSED: 'Resposta atrasada recusada para não reabrir a cobrança',
  UNEXPECTED_RESULT: 'Resposta inesperada do provider',
}

/** How long a reserve has been waiting, in words a person uses. */
function waitingFor(since: string | undefined): string {
  const elapsed = millisecondsSince(since)
  if (elapsed === null) return ''
  const minutes = Math.floor(elapsed / 60000)
  if (minutes < 1) return 'há menos de um minuto'
  if (minutes < 60) return `há ${minutes} min`
  return `há ${Math.floor(minutes / 60)} h`
}

/**
 * One parcel of the bill, and what can still be done with it.
 *
 * The two actions are not symmetric and must never look it. "Consultar
 * pagamento" asks the provider what happened and is the only honest way out of
 * an unknown; "Cancelar reserva" gives back a line that was never charged. What
 * does not exist here, on purpose, is a generic unblock: marking a parcel failed
 * by hand while a card is authorising is how the same consumption gets charged
 * twice, so the server refuses it and the screen does not offer it.
 */
function ParcelRow({ intent, busy, canCancel, canRefund, onQuery, onCancel, onRefund }: {
  intent: api.NegotiationPaymentIntent; busy: boolean; canCancel: boolean; canRefund: boolean
  onQuery: (intentId: string) => void; onCancel: (intentId: string) => void
  onRefund: (intentId: string, amount: number, reason: string) => void
}) {
  const waiting = intent.awaiting_provider
  const open = intent.status === 'PENDING' || intent.status === 'PROCESSING'
  // Estornar pede valor e motivo: é dinheiro saindo, e o motivo é o contrapeso
  // de não haver segunda pessoa aprovando.
  const [asking, setAsking] = useState(false)
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const refundable = Number(intent.refundable_amount ?? 0)
  const wanted = Number(amount.replace(',', '.'))
  const valid = Number.isFinite(wanted) && wanted > 0 && wanted <= refundable && reason.trim().length >= 3
  const start = () => { setAmount(refundable.toFixed(2)); setReason(''); setAsking(true) }
  return <div className="rounded-lg bg-white px-3 py-2 text-xs">
    <div className="flex items-center justify-between gap-2">
      <span className="min-w-0">
        {methodLabel[intent.method] ?? intent.method} · {intentStatusLabel[intent.status] ?? intent.status}
        {intent.payer_label ? ` · ${intent.payer_label}` : ''}
      </span>
      <b className="whitespace-nowrap">{formatCurrency(Number(intent.amount))}</b>
    </div>
    {waiting && <p className="mt-1 text-[11px] font-bold text-amber-700">
      Aguardando conciliação {waitingFor(intent.created_at)} · a cobrança saiu e o provider ainda não respondeu.
    </p>}
    {!waiting && open && intent.reserve_expires_at && <p className="mt-1 text-[11px] text-slate-500">
      Reservado {waitingFor(intent.created_at)}, sem cobrança iniciada.
    </p>}
    {intent.status === 'CANCELED' && intent.cancel_reason && <p className="mt-1 text-[11px] text-slate-500">{intent.cancel_reason}</p>}
    {intent.status === 'FAILED' && intent.failure_reason && <p className="mt-1 text-[11px] text-red-700">{intent.failure_reason}</p>}
    {Number(intent.refunded_amount ?? 0) > 0 && <p className="mt-1 text-[11px] font-bold text-slate-600">
      Estornado {formatCurrency(Number(intent.refunded_amount))} desta parcela.
    </p>}
    {intent.awaiting_refund && <p className="mt-1 text-[11px] font-bold text-amber-700">
      Estorno de {formatCurrency(Number(intent.refund_pending_amount))} enviado ao provider · o saldo só volta quando ele confirmar o valor revertido.
    </p>}
    {(intent.can_query_provider || (intent.can_cancel && canCancel) || (intent.can_refund && canRefund)) && <div className="mt-2 flex flex-wrap gap-2">
      {intent.can_query_provider && <button type="button" disabled={busy} onClick={() => onQuery(intent.id)} className="min-h-9 rounded-lg border border-amber-300 px-3 text-[11px] font-black text-amber-900 disabled:opacity-40">Consultar pagamento</button>}
      {intent.can_cancel && canCancel && <button type="button" disabled={busy} onClick={() => onCancel(intent.id)} className="min-h-9 rounded-lg border border-slate-300 px-3 text-[11px] font-black text-slate-700 disabled:opacity-40">Cancelar reserva</button>}
      {intent.can_refund && canRefund && !asking && <button type="button" disabled={busy} onClick={start} className="min-h-9 rounded-lg border border-slate-300 px-3 text-[11px] font-black text-slate-700 disabled:opacity-40">Estornar</button>}
    </div>}
    {asking && <div className="mt-2 space-y-2 rounded-lg bg-slate-50 p-2">
      <p className="text-[11px] text-slate-600">Devolver até {formatCurrency(refundable)} desta parcela. O que entrou continua registrado.</p>
      <label className="block text-[11px] font-bold text-slate-700">Valor a devolver
        <input value={amount} onChange={(event) => setAmount(event.target.value)} inputMode="decimal" className="mt-1 min-h-9 w-full rounded-lg border border-slate-300 px-2 text-xs" />
      </label>
      <label className="block text-[11px] font-bold text-slate-700">Motivo
        <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Por que o dinheiro está voltando" className="mt-1 min-h-9 w-full rounded-lg border border-slate-300 px-2 text-xs" />
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy || !valid} onClick={() => { setAsking(false); onRefund(intent.id, wanted, reason.trim()) }} className="min-h-9 rounded-lg bg-slate-900 px-3 text-[11px] font-black text-white disabled:opacity-40">Confirmar estorno</button>
        <button type="button" disabled={busy} onClick={() => setAsking(false)} className="min-h-9 rounded-lg border border-slate-300 px-3 text-[11px] font-black text-slate-700 disabled:opacity-40">Voltar</button>
      </div>
    </div>}
  </div>
}
