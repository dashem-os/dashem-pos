import React, { useEffect, useMemo, useState } from 'react'
import { Armchair, Ban, CalendarClock, CheckCircle2, LayoutGrid, MapPinned, MoreHorizontal, Plus, RefreshCw, Users, XCircle } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Modal } from '../common/Modal'
import * as api from '../../services/api'

type View = 'AREAS' | 'TABLES' | 'RESERVATIONS'
type Dialog = 'AREA' | 'TABLE' | 'RESERVATION' | null

const kindLabel: Record<api.ServiceArea['kind'], string> = {
  INTERNAL: 'Salão interno', EXTERNAL: 'Área externa', COUNTER: 'Balcão', TAKEAWAY: 'Retirada', FLEXIBLE: 'Área flexível',
}

export function ServiceSetupManager() {
  const { tenant, store, operatorId, permissions, showToast } = usePos()
  const [view, setView] = useState<View>('TABLES')
  const [dialog, setDialog] = useState<Dialog>(null)
  const [areas, setAreas] = useState<api.ServiceArea[]>([])
  const [tables, setTables] = useState<api.ServiceTableProjection[]>([])
  const [reservations, setReservations] = useState<api.TableReservation[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [areaForm, setAreaForm] = useState({ code: '', name: '', kind: 'INTERNAL' as api.ServiceArea['kind'] })
  const [tableForm, setTableForm] = useState({ code: '', name: '', capacity: '4', area_id: '' })
  const [reservationForm, setReservationForm] = useState({ table_id: '', customer_name: '', customer_phone: '', party_size: '2', reserved_for: '', duration_minutes: '120', notes: '' })
  const [stateChange, setStateChange] = useState<{ table: api.ServiceTableProjection; blocked: boolean } | null>(null)
  const [stateReason, setStateReason] = useState('')
  const headers = useMemo<Record<string, string>>(() => tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : {} as Record<string, string>, [tenant, store])
  const canConfigure = permissions.includes('table.manage')
  const canReserve = permissions.includes('table.reservation.manage')
  const canSetState = permissions.includes('table.state.update')

  const load = async () => {
    if (!tenant || !store) return
    setLoading(true); setError(null)
    try {
      const [nextAreas, nextTables, nextReservations] = await Promise.all([
        api.fetchServiceAreas(headers), api.fetchServiceTables(headers), api.fetchTableReservations(headers),
      ])
      setAreas(nextAreas); setTables(nextTables); setReservations(nextReservations)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível carregar a estrutura de atendimento.') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [tenant?.id, store?.id])

  const createArea = async (event: React.FormEvent) => {
    event.preventDefault(); if (!store) return; setBusy(true)
    try {
      await api.createServiceArea(headers, { store_id: store.id, ...areaForm, actor_id: operatorId })
      setAreaForm({ code: '', name: '', kind: 'INTERNAL' }); setDialog(null); showToast('success', 'Ambiente cadastrado.'); await load()
    } catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao cadastrar ambiente.') }
    finally { setBusy(false) }
  }

  const createTable = async (event: React.FormEvent) => {
    event.preventDefault(); if (!store) return; setBusy(true)
    try {
      await api.createServiceTable(headers, crypto.randomUUID(), {
        store_id: store.id, code: tableForm.code, name: tableForm.name, capacity: Number(tableForm.capacity),
        area_id: tableForm.area_id || undefined, actor_id: operatorId,
      })
      setTableForm({ code: '', name: '', capacity: '4', area_id: '' }); setDialog(null); showToast('success', 'Mesa adicionada ao mapa.'); await load()
    } catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao cadastrar mesa.') }
    finally { setBusy(false) }
  }

  const createReservation = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true)
    try {
      await api.createTableReservation(headers, reservationForm.table_id, crypto.randomUUID(), {
        customer_name: reservationForm.customer_name, customer_phone: reservationForm.customer_phone || undefined,
        party_size: Number(reservationForm.party_size), reserved_for: new Date(reservationForm.reserved_for).toISOString(),
        duration_minutes: Number(reservationForm.duration_minutes),
        notes: reservationForm.notes || undefined, actor_id: operatorId,
      })
      setReservationForm({ table_id: '', customer_name: '', customer_phone: '', party_size: '2', reserved_for: '', duration_minutes: '120', notes: '' })
      setDialog(null); showToast('success', 'Reserva sinalizada no mapa operacional.'); await load()
    } catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao registrar reserva.') }
    finally { setBusy(false) }
  }

  const setTableState = async (table: api.ServiceTableProjection, blocked: boolean, reason?: string) => {
    if (!reason) {
      setStateChange({ table, blocked })
      setStateReason('')
      return
    }
    if (reason.trim().length < 3) return
    setBusy(true)
    try {
      await api.setServiceTableState(headers, table.id, { expected_version: table.version, target: blocked ? 'BLOCKED' : 'AVAILABLE', reason, actor_id: operatorId })
      setStateChange(null); setStateReason('')
      showToast('success', blocked ? 'Mesa bloqueada e sinalizada.' : 'Mesa liberada novamente.'); await load()
    } catch (reasonValue) { showToast('error', reasonValue instanceof Error ? reasonValue.message : 'Falha ao alterar mesa.') }
    finally { setBusy(false) }
  }

  const archiveTable = async (table: api.ServiceTableProjection) => {
    if (!window.confirm(`Arquivar ${table.name}? Ela sairá do mapa operacional.`)) return
    setBusy(true)
    try {
      await api.updateServiceTable(headers, table.id, { expected_version: table.version, is_active: false, reason: 'Arquivamento administrativo da mesa', actor_id: operatorId })
      showToast('success', 'Mesa arquivada.'); await load()
    } catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao arquivar mesa.') }
    finally { setBusy(false) }
  }

  const endReservation = async (reservation: api.TableReservation, target: 'CANCELED' | 'NO_SHOW') => {
    setBusy(true)
    try {
      await api.transitionTableReservation(headers, reservation.id, { target, reason: target === 'CANCELED' ? 'Cancelada na retaguarda' : 'Cliente não compareceu', actor_id: operatorId })
      showToast('success', target === 'CANCELED' ? 'Reserva cancelada.' : 'Não comparecimento registrado.'); await load()
    } catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao atualizar reserva.') }
    finally { setBusy(false) }
  }

  const reservableTables = tables.filter((table) => table.status !== 'BLOCKED')
  const activeReservations = reservations.filter((item) => item.status === 'BOOKED')
  const areaCounts = new Map(areas.map((area) => [area.id, tables.filter((table) => table.area_id === area.id).length]))

  return <div className="space-y-6">
    <section className="overflow-hidden rounded-3xl border border-dashem-border bg-dashem-surface">
      <div className="flex flex-col justify-between gap-5 p-6 lg:flex-row lg:items-end">
        <div><p className="text-[11px] font-black uppercase tracking-[.18em] text-orange-700">Estrutura do atendimento</p><h1 className="mt-2 text-3xl font-black text-dashem-strong">Ambientes, mesas e reservas</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-dashem-muted">Configure aqui o mapa e a agenda. Na tela operacional a equipe abre mesas e comandas, confirma chegadas e sinaliza impedimentos.</p></div>
        <button onClick={() => void load()} disabled={loading} className="flex h-11 items-center justify-center gap-2 rounded-xl border border-dashem-border px-4 text-xs font-black text-dashem-strong"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Atualizar estrutura</button>
      </div>
      <div className="grid border-t border-dashem-border sm:grid-cols-3">
        <Summary label="Ambientes" value={areas.length} icon={MapPinned} />
        <Summary label="Mesas ativas" value={tables.length} icon={Armchair} />
        <Summary label="Reservas pendentes" value={activeReservations.length} icon={CalendarClock} />
      </div>
    </section>

    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
      <div className="inline-flex w-fit rounded-xl border border-dashem-border bg-dashem-surface p-1">
        {([['TABLES', 'Mesas'], ['AREAS', 'Ambientes'], ['RESERVATIONS', 'Reservas']] as const).map(([id, label]) => <button key={id} onClick={() => setView(id)} className={`h-9 rounded-lg px-4 text-xs font-black ${view === id ? 'bg-brand text-brand-contrast' : 'text-dashem-muted hover:text-dashem-strong'}`}>{label}</button>)}
      </div>
      <div className="flex flex-wrap gap-2">
        {canReserve && <button onClick={() => setDialog('RESERVATION')} disabled={!reservableTables.length} className="flex h-10 items-center gap-2 rounded-xl border border-orange-200 px-4 text-xs font-black text-orange-700 disabled:opacity-40"><CalendarClock className="h-4 w-4" />Nova reserva</button>}
        {canConfigure && <button onClick={() => setDialog(view === 'AREAS' ? 'AREA' : 'TABLE')} className="flex h-10 items-center gap-2 rounded-xl bg-dashem-red px-4 text-xs font-black text-brand-contrast"><Plus className="h-4 w-4" />{view === 'AREAS' ? 'Novo ambiente' : 'Nova mesa'}</button>}
      </div>
    </div>

    {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</div>}
    {view === 'AREAS' && <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{areas.map((area) => <article key={area.id} className="rounded-2xl border border-dashem-border bg-dashem-surface p-5"><div className="flex items-start justify-between"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-orange-50 text-orange-700"><MapPinned className="h-5 w-5" /></div><span className="rounded-full bg-dashem-bg px-2 py-1 text-xs font-black text-dashem-muted">{areaCounts.get(area.id) ?? 0} mesas</span></div><h3 className="mt-4 font-black text-dashem-strong">{area.name}</h3><p className="mt-1 text-xs text-dashem-muted">{kindLabel[area.kind]} · {area.code}</p>{canConfigure && <button disabled={(areaCounts.get(area.id) ?? 0) > 0 || busy} onClick={() => void api.updateServiceArea(headers, area.id, { is_active: false, reason: 'Ambiente arquivado pelo administrador', actor_id: operatorId }).then(load)} className="mt-4 text-xs font-black text-dashem-muted disabled:opacity-30">Arquivar ambiente</button>}</article>)}</section>}
    {view === 'TABLES' && <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{tables.map((table) => <article key={table.id} className="group rounded-2xl border border-dashem-border bg-dashem-surface p-5 transition hover:border-brand/40"><div className="flex items-start justify-between"><div className={`flex h-11 w-11 items-center justify-center rounded-xl ${table.status === 'AVAILABLE' ? 'bg-emerald-50 text-emerald-700' : table.status === 'RESERVED' ? 'bg-sky-50 text-sky-700' : table.status === 'BLOCKED' ? 'bg-red-50 text-red-700' : 'bg-orange-50 text-orange-700'}`}><Armchair className="h-5 w-5" /></div><span className="rounded-full border border-dashem-border px-2 py-1 text-xs font-black text-dashem-muted">{table.status}</span></div><h3 className="mt-4 text-lg font-black text-dashem-strong">{table.name}</h3><p className="mt-1 text-xs text-dashem-muted">{table.area || 'Sem ambiente'} · {table.capacity} lugares · {table.code}</p>{table.blocking_reason && <p className="mt-3 rounded-xl bg-red-50 p-3 text-xs font-bold text-red-700">{table.status === 'OCCUPIED' ? 'Bloqueio após fechamento: ' : ''}{table.blocking_reason}</p>}{table.active_reservation && <p className="mt-3 rounded-xl bg-sky-50 p-3 text-xs font-bold text-sky-700">{table.active_reservation.customer_name} · {new Date(table.active_reservation.reserved_for).toLocaleString('pt-BR')}</p>}<div className="mt-5 flex flex-wrap gap-2">{canSetState && ['AVAILABLE', 'OCCUPIED'].includes(table.status) && !table.blocking_reason && <button disabled={busy} onClick={() => void setTableState(table, true)} className="rounded-lg border border-red-200 px-3 py-2 text-xs font-black text-red-700"><Ban className="mr-1 inline h-3.5 w-3.5" />{table.status === 'OCCUPIED' ? 'Bloquear ao fechar' : 'Bloquear'}</button>}{canSetState && (table.status === 'BLOCKED' || (table.status === 'OCCUPIED' && table.blocking_reason)) && <button disabled={busy} onClick={() => void setTableState(table, false)} className="rounded-lg border border-emerald-200 px-3 py-2 text-xs font-black text-emerald-700"><CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />{table.status === 'OCCUPIED' ? 'Cancelar bloqueio' : 'Liberar'}</button>}{canConfigure && !['OCCUPIED', 'RESERVED'].includes(table.status) && <button disabled={busy} onClick={() => void archiveTable(table)} className="rounded-lg px-3 py-2 text-xs font-black text-dashem-muted"><MoreHorizontal className="mr-1 inline h-3.5 w-3.5" />Arquivar</button>}</div></article>)}</section>}
    {view === 'RESERVATIONS' && <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface"><div className="divide-y divide-dashem-border">{reservations.map((reservation) => { const table = tables.find((item) => item.id === reservation.service_table_id); return <article key={reservation.id} className="flex flex-col justify-between gap-4 p-5 md:flex-row md:items-center"><div><div className="flex items-center gap-2"><span className="font-black text-dashem-strong">{reservation.customer_name}</span><span className="rounded-full bg-dashem-bg px-2 py-1 text-xs font-black text-dashem-muted">{reservation.status}</span></div><p className="mt-1 text-sm text-dashem-muted">{table?.name || 'Mesa arquivada'} · {reservation.party_size} pessoas · {new Date(reservation.reserved_for).toLocaleString('pt-BR')}</p>{reservation.customer_phone && <p className="mt-1 text-xs text-dashem-muted">{reservation.customer_phone}</p>}</div>{canReserve && reservation.status === 'BOOKED' && <div className="flex gap-2"><button disabled={busy} onClick={() => void endReservation(reservation, 'NO_SHOW')} className="rounded-xl border border-dashem-border px-3 py-2 text-xs font-black text-dashem-muted">Não compareceu</button><button disabled={busy} onClick={() => void endReservation(reservation, 'CANCELED')} className="rounded-xl border border-red-200 px-3 py-2 text-xs font-black text-red-700"><XCircle className="mr-1 inline h-4 w-4" />Cancelar</button></div>}</article> })}</div>{reservations.length === 0 && <Empty icon={CalendarClock} title="Nenhuma reserva registrada" text="As reservas futuras aparecerão aqui e serão sinalizadas antes da abertura da mesa." />}</section>}
    {!loading && view === 'TABLES' && tables.length === 0 && <Empty icon={LayoutGrid} title="Comece pelo mapa do salão" text="Cadastre primeiro um ambiente e depois as mesas que pertencem a ele." />}

    <Modal isOpen={dialog === 'AREA'} onClose={() => setDialog(null)} title="Novo ambiente" subtitle="Organize salão, área externa, balcão ou retirada."><form onSubmit={createArea} className="space-y-4"><Field label="Código" value={areaForm.code} onChange={(value) => setAreaForm({ ...areaForm, code: value })} placeholder="SALAO" /><Field label="Nome" value={areaForm.name} onChange={(value) => setAreaForm({ ...areaForm, name: value })} placeholder="Salão principal" /><label className="block text-xs font-black text-dashem-strong">Tipo<select value={areaForm.kind} onChange={(event) => setAreaForm({ ...areaForm, kind: event.target.value as api.ServiceArea['kind'] })} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong">{Object.entries(kindLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><Submit busy={busy} label="Cadastrar ambiente" /></form></Modal>
    <Modal isOpen={dialog === 'TABLE'} onClose={() => setDialog(null)} title="Nova mesa" subtitle="Configuração exclusiva da retaguarda."><form onSubmit={createTable} className="space-y-4"><div className="grid grid-cols-1 sm:grid-cols-2 gap-3"><Field label="Código" value={tableForm.code} onChange={(value) => setTableForm({ ...tableForm, code: value })} placeholder="MESA-01" /><Field label="Nome visível" value={tableForm.name} onChange={(value) => setTableForm({ ...tableForm, name: value })} placeholder="Mesa 01" /></div><Field label="Capacidade" type="number" value={tableForm.capacity} onChange={(value) => setTableForm({ ...tableForm, capacity: value })} /><label className="block text-xs font-black text-dashem-strong">Ambiente<select required value={tableForm.area_id} onChange={(event) => setTableForm({ ...tableForm, area_id: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong"><option value="">Selecione</option>{areas.map((area) => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label><Submit busy={busy} label="Adicionar ao mapa" /></form></Modal>
    <Modal isOpen={dialog === 'RESERVATION'} onClose={() => setDialog(null)} title="Nova reserva" subtitle="A agenda aceita mesas livres ou ocupadas e impede conflito de horário."><form onSubmit={createReservation} className="space-y-4"><label className="block text-xs font-black text-dashem-strong">Mesa<select required value={reservationForm.table_id} onChange={(event) => setReservationForm({ ...reservationForm, table_id: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong"><option value="">Selecione</option>{reservableTables.map((table) => <option key={table.id} value={table.id}>{table.name} · {table.area} · {table.status}</option>)}</select></label><div className="grid grid-cols-1 sm:grid-cols-2 gap-3"><Field label="Responsável" value={reservationForm.customer_name} onChange={(value) => setReservationForm({ ...reservationForm, customer_name: value })} /><Field label="Telefone" value={reservationForm.customer_phone} onChange={(value) => setReservationForm({ ...reservationForm, customer_phone: value })} /></div><div className="grid gap-3 sm:grid-cols-3"><Field label="Pessoas" type="number" value={reservationForm.party_size} onChange={(value) => setReservationForm({ ...reservationForm, party_size: value })} /><Field label="Data e hora" type="datetime-local" value={reservationForm.reserved_for} onChange={(value) => setReservationForm({ ...reservationForm, reserved_for: value })} /><Field label="Duração (min)" type="number" value={reservationForm.duration_minutes} onChange={(value) => setReservationForm({ ...reservationForm, duration_minutes: value })} /></div><Field label="Observação" value={reservationForm.notes} onChange={(value) => setReservationForm({ ...reservationForm, notes: value })} /><Submit busy={busy} label="Confirmar reserva" /></form></Modal>
    <Modal isOpen={Boolean(stateChange)} onClose={() => { setStateChange(null); setStateReason('') }} title={stateChange?.blocked ? 'Sinalizar impedimento' : 'Liberar mesa'} subtitle={stateChange?.blocked ? 'Use para defeito, manutenção ou impedimento real. Reservas possuem agenda própria.' : 'A justificativa mantém a alteração rastreável.'}><form onSubmit={(event) => { event.preventDefault(); if (stateChange) void setTableState(stateChange.table, stateChange.blocked, stateReason) }} className="space-y-4"><div className="rounded-xl bg-dashem-bg p-4 text-sm font-black text-dashem-strong">{stateChange?.table.name}</div><label className="block text-xs font-black text-dashem-strong">Motivo<textarea autoFocus required minLength={3} value={stateReason} onChange={(event) => setStateReason(event.target.value)} placeholder={stateChange?.blocked ? 'Ex.: cadeira danificada; aguardando manutenção' : 'Ex.: manutenção concluída'} className="mt-2 min-h-24 w-full resize-none rounded-xl border border-dashem-border bg-dashem-surface-elevated p-3 text-sm text-dashem-strong outline-none focus:border-dashem-red" /></label><Submit busy={busy || stateReason.trim().length < 3} label={stateChange?.blocked ? 'Confirmar impedimento' : 'Confirmar liberação'} /></form></Modal>
  </div>
}

function Summary({ label, value, icon: Icon }: { label: string; value: number; icon: React.ComponentType<{ className?: string }> }) { return <div className="flex items-center gap-4 border-dashem-border p-5 sm:border-r last:border-r-0"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-dashem-bg text-orange-700"><Icon className="h-5 w-5" /></div><div><p className="text-2xl font-black text-dashem-strong">{value}</p><p className="text-xs font-bold text-dashem-muted">{label}</p></div></div> }
function Empty({ icon: Icon, title, text }: { icon: React.ComponentType<{ className?: string }>; title: string; text: string }) { return <div className="flex min-h-64 items-center justify-center rounded-2xl border border-dashed border-dashem-border bg-dashem-surface/50 p-8 text-center"><div><Icon className="mx-auto h-10 w-10 text-slate-600" /><h3 className="mt-4 font-black text-dashem-strong">{title}</h3><p className="mt-2 max-w-md text-sm text-dashem-muted">{text}</p></div></div> }
function Field({ label, value, onChange, placeholder, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) { return <label className="block text-xs font-black text-dashem-strong">{label}<input required={label !== 'Telefone' && label !== 'Observação'} type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong outline-none focus:border-dashem-red" /></label> }
function Submit({ busy, label }: { busy: boolean; label: string }) { return <button disabled={busy} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">{busy ? 'Salvando...' : label}</button> }
