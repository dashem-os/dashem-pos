import { ResponsiveTable } from '../common/DataTable'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, Plus, Radio, RefreshCw, Send, Tag, Wallet } from 'lucide-react'

import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { formatApiDateTime, formatCurrency, maskCurrencyInput, parseCurrencyInput } from '../../utils/format'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'


const connectionLabels: Record<api.MerchantConnection['status'], string> = {
  NOT_CONNECTED: 'Não conectado', VALIDATING: 'Validando', CONNECTED: 'Conectado',
  DEGRADED: 'Degradado', SUSPENDED: 'Suspenso',
}
const offerStatusLabels: Record<api.ChannelCatalogOffer['last_publication_status'], string> = {
  PENDING: 'Aguardando o canal', SUCCEEDED: 'Publicado', FAILED: 'Recusado pelo canal',
}
const batchStatusLabels: Record<api.ChannelPublicationBatch['status'], string> = {
  PENDING: 'Enviado, aguardando o canal', PROCESSING: 'Em processamento', PARTIAL: 'Parcial',
  SUCCEEDED: 'Concluído', FAILED: 'Recusado',
}
const settlementStatusLabels: Record<api.MarketplaceSettlement['status'], string> = {
  PENDING: 'A receber', PARTIAL: 'Recebido em parte', PAID: 'Recebido', DIVERGENT: 'Divergente',
}
/** A competence date is a calendar day the marketplace named, not an instant.
 *  `new Date('2026-09-04')` would read it as midnight UTC and show the day
 *  before to anyone west of Greenwich, so the parts are reordered as text. */
function formatCompetence(value: string): string {
  const [year, month, day] = value.slice(0, 10).split('-')
  return day && month && year ? `${day}/${month}/${year}` : value
}
const inputClass = 'mt-1 h-11 w-full min-w-0 rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong outline-none focus:border-dashem-red'
const labelClass = 'block text-xs font-bold text-dashem-strong'

export function ChannelHubWorkspace() {
  const { tenant, store, operatorId, permissions, showToast } = usePos()
  const [connections, setConnections] = useState<api.MerchantConnection[]>([])
  const [events, setEvents] = useState<api.ChannelInboxEvent[]>([])
  const [offers, setOffers] = useState<api.ChannelCatalogOffer[]>([])
  const [batches, setBatches] = useState<api.ChannelPublicationBatch[]>([])
  const [mappings, setMappings] = useState<api.ChannelCatalogMapping[]>([])
  const [settlements, setSettlements] = useState<api.MarketplaceSettlement[]>([])
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [formOpen, setFormOpen] = useState(false)
  const [webhookSecret, setWebhookSecret] = useState<string | null>(null)
  const headers = useMemo<Record<string, string>>(() => {
    if (!tenant || !store) return {} as Record<string, string>
    return { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
  }, [tenant, store])
  const load = useCallback(async () => {
    if (!tenant || !store) return
    setLoading(true)
    try {
      const [nextConnections, nextEvents, catalog, nextSettlements] = await Promise.all([api.fetchMerchantConnections(headers), api.fetchChannelInbox(headers), api.fetchChannelCatalogState(headers), api.fetchMarketplaceSettlements(headers)])
      setConnections(nextConnections); setEvents(nextEvents); setOffers(catalog.offers); setBatches(catalog.batches); setMappings(catalog.mappings ?? []); setSettlements(nextSettlements)
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Channel Hub indisponível.') }
    finally { setLoading(false) }
  }, [headers, showToast, store, tenant])
  useEffect(() => { void load() }, [load])
  const validate = async (id: string) => {
    setBusy(true)
    try {
      const result = await api.validateMerchantConnection(headers, id, crypto.randomUUID(), operatorId)
      showToast(result.status === 'CONNECTED' ? 'success' : 'info', result.status === 'CONNECTED' ? 'Conexão externa validada.' : 'O provider ainda não confirmou a conexão.')
      await load()
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Falha na validação.') }
    finally { setBusy(false) }
  }
  return <section className="space-y-5 text-slate-950">
    <header className="flex flex-col justify-between gap-4 rounded-2xl border border-dashem-border bg-dashem-surface p-6 text-dashem-strong sm:flex-row sm:items-center"><div><p className="text-xs font-black uppercase tracking-[.16em] text-cyan-700">Omnichannel · inbox durável</p><h1 className="mt-1 text-2xl font-black">Dashem Channel Hub</h1><p className="mt-2 max-w-2xl text-sm text-dashem-muted">Eventos externos entram no mesmo Order Engine. Conexão só aparece ativa após validação real do adapter.</p></div><div className="flex gap-2"><button onClick={() => void load()} className="flex h-11 items-center gap-2 rounded-xl border border-dashem-border px-4 text-xs font-black"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Atualizar</button>{permissions.includes('channel.configure') && <button onClick={() => setFormOpen(true)} className="flex h-11 items-center gap-2 rounded-xl bg-cyan-600 px-4 text-xs font-black"><Plus className="h-4 w-4" />Nova conexão</button>}</div></header>
    {webhookSecret && <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4"><p className="text-xs font-black text-amber-900">Segredo de webhook exibido uma única vez</p><code className="mt-2 block break-all rounded-lg bg-white p-3 text-xs">{webhookSecret}</code><button onClick={() => setWebhookSecret(null)} className="mt-2 text-xs font-black text-amber-800">Já armazenei com segurança</button></div>}
    <div className="grid gap-5 xl:grid-cols-[420px_1fr]"><section className="rounded-3xl border border-slate-200 bg-white p-5"><h2 className="font-black">Conexões</h2><p className="text-xs text-slate-500">{connections.length} merchants persistidos</p><div className="mt-4 space-y-3">{loading && <Loader2 className="h-5 w-5 animate-spin" />}{!loading && connections.length === 0 && <Empty text="Nenhum canal configurado. iFood e 99Food não serão mostrados como conectados sem credenciais e validação." />}{connections.map((connection) => <article key={connection.id} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-start justify-between"><div><p className="font-black">{connection.provider_code}</p><p className="text-xs text-slate-500">{connection.merchant_external_id}</p></div><span className={`rounded-full px-2 py-1 text-xs font-black ${connection.status === 'CONNECTED' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-900'}`}>{connectionLabels[connection.status]}</span></div>{connection.last_error_code && <p className="mt-2 text-xs text-amber-800">{connection.last_error_code}</p>}{permissions.includes('channel.configure') && connection.status !== 'CONNECTED' && <button disabled={busy} onClick={() => void validate(connection.id)} className="mt-3 h-9 w-full rounded-xl border border-cyan-300 text-xs font-black text-cyan-800">Validar com provider</button>}</article>)}</div></section>
      <section className="rounded-3xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><div><h2 className="font-black">External Order Inbox</h2><p className="text-xs text-slate-500">Persistência, ack, normalização e quarentena observáveis</p></div><Radio className="h-5 w-5 text-cyan-600" /></div><div className="mt-4 overflow-x-auto"><ResponsiveTable className="w-full text-left text-xs"><thead><tr className="border-b text-[10px] uppercase text-dashem-muted"><th className="p-3">Recebido</th><th className="p-3">Pedido externo</th><th className="p-3">Estado</th><th className="p-3">Order</th></tr></thead><tbody>{events.map((event) => <tr key={event.id} className="border-b border-slate-100"><td className="p-3">{formatApiDateTime(event.received_at)}</td><td className="p-3 font-bold">{event.external_order_id}</td><td className="p-3"><span className="flex items-center gap-1 font-black">{event.status === 'QUARANTINED' ? <AlertTriangle className="h-3.5 w-3.5 text-amber-600" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />}{event.status}</span>{event.quarantine_reason && <p className="mt-1 max-w-xs text-xs text-amber-700">{event.quarantine_reason}</p>}</td><td className="p-3 font-mono text-xs">{event.order_id || '—'}</td></tr>)}</tbody></ResponsiveTable>{!loading && events.length === 0 && <Empty text="Nenhum evento externo recebido. A tela não injeta pedidos demonstrativos." />}</div></section></div>
    <ChannelCatalogPanel headers={headers} actorId={operatorId} connections={connections} offers={offers} batches={batches} mappings={mappings} loading={loading} canManage={permissions.includes('channel.catalog.manage')} onChanged={load} showToast={showToast} />
    <SettlementPanel headers={headers} actorId={operatorId} connections={connections} settlements={settlements} loading={loading} canManage={permissions.includes('channel.settlement.manage')} onChanged={load} showToast={showToast} />
    {formOpen && store && <ConnectionDialog storeId={store.id} actorId={operatorId} headers={headers} onClose={() => setFormOpen(false)} onCreated={async (secret) => { setWebhookSecret(secret); setFormOpen(false); await load() }} showToast={showToast} />}
  </section>
}

type Toast = (type: 'success' | 'error' | 'info', text: string) => void
interface PanelProps { headers: Record<string, string>; actorId: string; connections: api.MerchantConnection[]; loading: boolean; canManage: boolean; onChanged: () => Promise<void>; showToast: Toast }

/**
 * Publishing a catalogue to a marketplace is a request, not a result.
 *
 * The shopkeeper says what the offer is and asks for it to go out; the channel
 * answers item by item through its adapter. That answer has no button here on
 * purpose: a screen that let a person mark their own publication as accepted
 * would be inventing the marketplace's word, and every batch would read green
 * while the channel had never been called.
 */
function ChannelCatalogPanel({ headers, actorId, connections, offers, batches, mappings, loading, canManage, onChanged, showToast }: PanelProps & { offers: api.ChannelCatalogOffer[]; batches: api.ChannelPublicationBatch[]; mappings: api.ChannelCatalogMapping[] }) {
  const [connectionId, setConnectionId] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [dialog, setDialog] = useState<'offer' | 'mapping' | null>(null)
  const [editing, setEditing] = useState<api.ChannelCatalogOffer | null>(null)
  const [busy, setBusy] = useState(false)
  const active = connections.find((item) => item.id === connectionId) ?? connections[0] ?? null
  useEffect(() => { if (active && active.id !== connectionId) setConnectionId(active.id) }, [active, connectionId])
  // Changing channel discards a selection that belonged to the previous one: a
  // batch carries exactly one connection and must never mix merchants.
  useEffect(() => { setSelected([]) }, [connectionId])
  const channelOffers = useMemo(() => offers.filter((item) => item.merchant_connection_id === active?.id), [offers, active])
  const channelBatches = useMemo(() => batches.filter((item) => item.merchant_connection_id === active?.id), [batches, active])
  const channelMappings = useMemo(() => mappings.filter((item) => item.merchant_connection_id === active?.id), [mappings, active])
  const pending = channelOffers.filter((item) => item.last_publication_status !== 'SUCCEEDED' || item.published_version < item.desired_version)
  const toggle = (id: string) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  const publish = async () => {
    if (!active || selected.length === 0) return
    setBusy(true)
    try {
      const result = await api.publishChannelCatalogOffers(headers, crypto.randomUUID(), { connection_id: active.id, offer_ids: selected, actor_id: actorId })
      showToast('info', `Lote com ${result.items.length} item(ns) enviado. O canal confirma item a item.`)
      setSelected([]); await onChanged()
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível enviar o lote.') }
    finally { setBusy(false) }
  }
  return <section className="rounded-3xl border border-slate-200 bg-white p-5">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div><h2 className="font-black">Catálogo por canal</h2><p className="text-xs text-slate-500">Identidade canônica e publicação item a item</p></div>
      <div className="flex flex-wrap items-center gap-2">
        {connections.length > 1 && <select aria-label="Canal" value={active?.id ?? ''} onChange={(event) => setConnectionId(event.target.value)} className="h-11 rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-xs font-bold text-dashem-strong">{connections.map((item) => <option key={item.id} value={item.id}>{item.provider_code} · {item.merchant_external_id}</option>)}</select>}
        {canManage && active && <>
          <Button size="sm" variant="secondary" icon={Tag} onClick={() => setDialog('mapping')}>Vincular código</Button>
          <Button size="sm" variant="secondary" icon={Plus} onClick={() => { setEditing(null); setDialog('offer') }}>Nova oferta</Button>
          <Button size="sm" icon={Send} loading={busy} disabled={selected.length === 0} onClick={() => void publish()}>Publicar {selected.length > 0 ? `(${selected.length})` : 'selecionadas'}</Button>
        </>}
      </div>
    </div>
    <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3"><Metric label="Ofertas" value={channelOffers.length} /><Metric label="Pendências" value={pending.length} /><Metric label="Lotes parciais" value={channelBatches.filter((item) => item.status === 'PARTIAL' || item.status === 'FAILED').length} /></div>
    {!loading && connections.length === 0 && <Empty text="Nenhum canal configurado. Cadastre e valide uma conexão antes de montar catálogo por canal." />}
    {connections.length > 0 && channelOffers.length === 0 && !loading && <Empty text="Nenhuma oferta persistida neste canal. O catálogo local continua sendo a fonte canônica." />}
    {channelOffers.length > 0 && <div className="mt-4 overflow-x-auto"><ResponsiveTable className="w-full text-left text-xs"><thead><tr className="border-b text-[10px] uppercase text-dashem-muted">{canManage && <th className="p-3 w-10"><span className="sr-only">Selecionar</span></th>}<th className="p-3">Produto</th><th className="p-3">Preço no canal</th><th className="p-3">Disponível</th><th className="p-3">Versão</th><th className="p-3">Último envio</th>{canManage && <th className="p-3 text-right">Ação</th>}</tr></thead><tbody>
      {channelOffers.map((offer) => <tr key={offer.id} className="border-b border-slate-100">
        {canManage && <td className="p-3"><input type="checkbox" aria-label={`Selecionar ${offer.product_name ?? 'oferta'}`} checked={selected.includes(offer.id)} onChange={() => toggle(offer.id)} className="h-5 w-5 rounded border-slate-300" /></td>}
        <td className="p-3"><p className="font-bold text-dashem-strong">{offer.product_name ?? 'Produto removido do catálogo'}</p><p className="text-[11px] text-slate-500">{offer.product_sku ?? '—'}</p></td>
        <td className="p-3 font-bold">{formatCurrency(offer.price)}</td>
        <td className="p-3">{offer.available ? 'Sim' : 'Não'}{offer.stock_quantity != null && <span className="block text-[11px] text-slate-500">estoque {offer.stock_quantity}</span>}</td>
        <td className="p-3"><span className={offer.published_version < offer.desired_version ? 'font-black text-amber-700' : ''}>{offer.published_version}/{offer.desired_version}</span></td>
        <td className="p-3"><StatusPill tone={offer.last_publication_status === 'SUCCEEDED' ? 'good' : offer.last_publication_status === 'FAILED' ? 'bad' : 'wait'} text={offerStatusLabels[offer.last_publication_status]} /></td>
        {canManage && <td className="p-3 text-right"><Button size="sm" variant="ghost" onClick={() => { setEditing(offer); setDialog('offer') }}>Editar</Button></td>}
      </tr>)}
    </tbody></ResponsiveTable></div>}
    {canManage && channelOffers.length > 0 && <p className="mt-3 rounded-xl bg-slate-50 p-3 text-[11px] leading-5 text-slate-600">Publicar registra o pedido de envio e nada mais. O canal responde item a item pelo adapter, e nenhuma tela marca sucesso no lugar dele — por isso um lote pode ficar pendente enquanto o provider não estiver homologado.</p>}
    {channelBatches.length > 0 && <div className="mt-5"><h3 className="text-xs font-black uppercase tracking-wide text-dashem-muted">Lotes de publicação</h3><div className="mt-2 space-y-2">{channelBatches.map((batch) => <article key={batch.id} className="rounded-2xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-xs font-black text-dashem-strong">{formatApiDateTime(batch.created_at)}</p><p className="text-[11px] text-slate-500">{batch.items.length} item(ns)</p></div><StatusPill tone={batch.status === 'SUCCEEDED' ? 'good' : batch.status === 'PENDING' || batch.status === 'PROCESSING' ? 'wait' : 'bad'} text={batchStatusLabels[batch.status]} /></div>
      <ul className="mt-3 space-y-1">{batch.items.map((item) => <li key={item.id} className="flex flex-wrap items-baseline justify-between gap-2 border-t border-slate-100 pt-1 text-[11px]"><span className="font-bold text-dashem-strong">{item.product_name ?? 'Produto removido do catálogo'}</span><span className={item.status === 'FAILED' ? 'text-red-700' : item.status === 'SUCCEEDED' ? 'text-emerald-700' : 'text-slate-500'}>{offerStatusLabels[item.status]}{item.error_code ? ` · ${item.error_code}` : ''}</span>{item.error_message && <span className="w-full text-red-700">{item.error_message}</span>}</li>)}</ul>
    </article>)}</div></div>}
    {channelMappings.length > 0 && <div className="mt-5"><h3 className="text-xs font-black uppercase tracking-wide text-dashem-muted">Códigos do canal</h3><div className="mt-2 overflow-x-auto"><ResponsiveTable className="w-full text-left text-xs"><thead><tr className="border-b text-[10px] uppercase text-dashem-muted"><th className="p-3">Item interno</th><th className="p-3">Tipo</th><th className="p-3">Código no canal</th></tr></thead><tbody>{channelMappings.map((item) => <tr key={item.id} className="border-b border-slate-100"><td className="p-3 font-bold text-dashem-strong">{item.internal_name ?? item.internal_id}</td><td className="p-3">{item.entity_type}</td><td className="p-3 font-mono">{item.external_id}</td></tr>)}</tbody></ResponsiveTable></div></div>}
    {dialog === 'offer' && active && <OfferDialog headers={headers} actorId={actorId} connection={active} offer={editing} onClose={() => { setDialog(null); setEditing(null) }} onSaved={async () => { setDialog(null); setEditing(null); await onChanged() }} showToast={showToast} />}
    {dialog === 'mapping' && active && <MappingDialog headers={headers} actorId={actorId} connection={active} onClose={() => setDialog(null)} onSaved={async () => { setDialog(null); await onChanged() }} showToast={showToast} />}
  </section>
}

/** A product picker that asks the server, so it never depends on a page of the
 *  catalogue that happened to be loaded elsewhere. */
function ProductPicker({ headers, value, onPick }: { headers: Record<string, string>; value: api.Product | null; onPick: (product: api.Product | null) => void }) {
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<api.Product[]>([])
  const [searching, setSearching] = useState(false)
  useEffect(() => {
    if (search.trim().length < 2) { setResults([]); return }
    let current = true
    const timer = setTimeout(() => {
      setSearching(true)
      api.fetchProducts(headers, search.trim()).then((rows) => { if (current) setResults(rows.slice(0, 20)) }).catch(() => { if (current) setResults([]) }).finally(() => { if (current) setSearching(false) })
    }, 250)
    return () => { current = false; clearTimeout(timer) }
  }, [search, headers])
  if (value) return <div className="rounded-xl border border-dashem-border bg-dashem-surface-elevated p-3"><p className="text-sm font-black text-dashem-strong">{value.name}</p><p className="text-[11px] text-slate-500">{value.sku}</p><button type="button" onClick={() => { setSearch(''); onPick(null) }} className="mt-1 text-[11px] font-black text-dashem-red">Trocar produto</button></div>
  return <div>
    <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar nome ou SKU (2 caracteres)" className={inputClass} />
    {searching && <p className="mt-2 text-[11px] text-slate-500">Buscando...</p>}
    {!searching && search.trim().length >= 2 && results.length === 0 && <p className="mt-2 text-[11px] text-slate-500">Nenhum produto encontrado no catálogo canônico.</p>}
    <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto">{results.map((product) => <li key={product.id}><button type="button" onClick={() => onPick(product)} className="w-full rounded-xl border border-dashem-border p-2 text-left hover:bg-dashem-surface-elevated"><span className="block text-xs font-bold text-dashem-strong">{product.name}</span><span className="block text-[11px] text-slate-500">{product.sku}</span></button></li>)}</ul>
  </div>
}

function OfferDialog({ headers, actorId, connection, offer, onClose, onSaved, showToast }: { headers: Record<string, string>; actorId: string; connection: api.MerchantConnection; offer: api.ChannelCatalogOffer | null; onClose: () => void; onSaved: () => Promise<void>; showToast: Toast }) {
  const [product, setProduct] = useState<api.Product | null>(offer ? ({ id: offer.product_id, name: offer.product_name ?? 'Produto', sku: offer.product_sku ?? '' } as api.Product) : null)
  const [price, setPrice] = useState(offer ? maskCurrencyInput(Number(offer.price).toFixed(2)) : '')
  const [available, setAvailable] = useState(offer ? offer.available : true)
  const [stock, setStock] = useState(offer?.stock_quantity != null ? String(offer.stock_quantity) : '')
  const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!product) { showToast('error', 'Escolha o produto canônico da oferta.'); return }
    setSaving(true)
    try {
      await api.saveChannelCatalogOffer(headers, crypto.randomUUID(), { connection_id: connection.id, product_id: product.id, price: parseCurrencyInput(price), available, stock_quantity: stock.trim() === '' ? null : Number(stock), actor_id: actorId })
      showToast('success', 'Oferta salva. Ela sobe ao canal no próximo lote.')
      await onSaved()
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível salvar a oferta.') }
    finally { setSaving(false) }
  }
  return <Modal isOpen onClose={onClose} title={offer ? 'Editar oferta do canal' : 'Nova oferta do canal'} subtitle={`${connection.provider_code} · ${connection.merchant_external_id}`}>
    <form onSubmit={submit} className="space-y-4">
      <div><span className={labelClass}>Produto canônico</span><div className="mt-1"><ProductPicker headers={headers} value={product} onPick={setProduct} /></div></div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={labelClass}>Preço no canal (R$)<input type="text" inputMode="decimal" required value={price} onChange={(event) => setPrice(maskCurrencyInput(event.target.value))} onKeyDown={(event) => { if ((event.key === 'Backspace' || event.key === 'Delete') && parseCurrencyInput(price) === 0) { event.preventDefault(); setPrice('') } }} placeholder="Ex.: 0,00" className={inputClass} /></label>
        <label className={labelClass}>Estoque exposto (opcional)<input type="text" inputMode="numeric" value={stock} onChange={(event) => setStock(event.target.value.replace(/[^0-9.]/g, ''))} placeholder="Sem limite declarado" className={inputClass} /></label>
      </div>
      <label className="flex items-center gap-2 text-xs font-bold text-dashem-strong"><input type="checkbox" checked={available} onChange={(event) => setAvailable(event.target.checked)} className="h-5 w-5 rounded border-slate-300" />Disponível para venda no canal</label>
      <p className="rounded-xl bg-slate-50 p-3 text-[11px] leading-5 text-slate-600">Salvar altera o que se deseja publicar e devolve a oferta ao estado pendente. O preço do canal é próprio e não altera o preço da unidade.</p>
      <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancelar</Button><Button type="submit" loading={saving}>Salvar oferta</Button></div>
    </form>
  </Modal>
}

function MappingDialog({ headers, actorId, connection, onClose, onSaved, showToast }: { headers: Record<string, string>; actorId: string; connection: api.MerchantConnection; onClose: () => void; onSaved: () => Promise<void>; showToast: Toast }) {
  const [product, setProduct] = useState<api.Product | null>(null)
  const [externalId, setExternalId] = useState('')
  const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!product) { showToast('error', 'Escolha o produto canônico a vincular.'); return }
    setSaving(true)
    try {
      await api.mapChannelCatalogEntity(headers, crypto.randomUUID(), { connection_id: connection.id, entity_type: 'PRODUCT', internal_id: product.id, external_id: externalId.trim(), actor_id: actorId })
      showToast('success', 'Código do canal vinculado ao produto.')
      await onSaved()
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível vincular o código.') }
    finally { setSaving(false) }
  }
  return <Modal isOpen onClose={onClose} title="Vincular código do canal" subtitle={`${connection.provider_code} · ${connection.merchant_external_id}`}>
    <form onSubmit={submit} className="space-y-4">
      <div><span className={labelClass}>Produto canônico</span><div className="mt-1"><ProductPicker headers={headers} value={product} onPick={setProduct} /></div></div>
      <label className={labelClass}>Código do item no canal<input required value={externalId} onChange={(event) => setExternalId(event.target.value)} placeholder="Ex.: 8842-XYZ" className={inputClass} /></label>
      <p className="rounded-xl bg-slate-50 p-3 text-[11px] leading-5 text-slate-600">A identidade do Dashem continua sendo a do produto. O código do canal é a tradução usada com aquele merchant, e vale só para ele.</p>
      <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancelar</Button><Button type="submit" loading={saving}>Vincular</Button></div>
    </form>
  </Modal>
}

/**
 * Selling and being paid are separate facts.
 *
 * The document the marketplace issues is typed here as the marketplace stated
 * it; the expected net is derived by the server from those parts and never by
 * the browser, and a payment adds a fact instead of correcting the document.
 */
function SettlementPanel({ headers, actorId, connections, settlements, loading, canManage, onChanged, showToast }: PanelProps & { settlements: api.MarketplaceSettlement[] }) {
  const [dialog, setDialog] = useState<'import' | null>(null)
  const [paying, setPaying] = useState<api.MarketplaceSettlement | null>(null)
  return <section className="rounded-3xl border border-slate-200 bg-white p-5">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div><h2 className="font-black">Repasses do marketplace</h2><p className="text-xs text-slate-500">Venda e liquidação financeira são fatos separados</p></div>
      {canManage && connections.length > 0 && <Button size="sm" variant="secondary" icon={Wallet} onClick={() => setDialog('import')}>Importar documento</Button>}
    </div>
    <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3"><Metric label="Documentos" value={settlements.length} /><Metric label="Pendentes" value={settlements.filter((item) => item.status !== 'PAID').length} /><Metric label="Divergentes" value={settlements.filter((item) => item.status === 'DIVERGENT').length} /></div>
    {!loading && settlements.length === 0 && <Empty text="Nenhum documento importado. Vendas externas não aparecem conciliadas por suposição." />}
    {settlements.length > 0 && <div className="mt-4 overflow-x-auto"><ResponsiveTable className="w-full text-left text-xs"><thead><tr className="border-b text-[10px] uppercase text-dashem-muted"><th className="p-3">Documento</th><th className="p-3">Competência</th><th className="p-3">Bruto</th><th className="p-3">Descontos</th><th className="p-3">Líquido esperado</th><th className="p-3">Recebido</th><th className="p-3">Estado</th>{canManage && <th className="p-3 text-right">Ação</th>}</tr></thead><tbody>
      {settlements.map((item) => <tr key={item.id} className="border-b border-slate-100">
        <td className="p-3"><p className="font-bold text-dashem-strong">{item.provider_document_ref}</p><p className="text-[11px] text-slate-500">{item.provider_code ?? '—'}{item.external_order_id ? ` · ${item.external_order_id}` : ''}</p></td>
        <td className="p-3">{formatCompetence(item.competence_date)}</td>
        <td className="p-3">{formatCurrency(item.gross_amount)}</td>
        <td className="p-3 text-[11px] text-slate-600">comissão {formatCurrency(item.commission_amount)}<br />taxa {formatCurrency(item.fee_amount)}<br />promoção {formatCurrency(item.promotion_amount)}<br />ajuste {formatCurrency(item.adjustment_amount)}</td>
        <td className="p-3 font-bold">{formatCurrency(item.expected_net_amount)}</td>
        <td className="p-3">{formatCurrency(item.paid_amount)}{item.payments?.length > 0 && <span className="block text-[11px] text-slate-500">{item.payments.length} pagamento(s)</span>}</td>
        <td className="p-3"><StatusPill tone={item.status === 'PAID' ? 'good' : item.status === 'DIVERGENT' ? 'bad' : 'wait'} text={settlementStatusLabels[item.status]} /></td>
        {canManage && <td className="p-3 text-right"><Button size="sm" variant="ghost" onClick={() => setPaying(item)}>Registrar pagamento</Button></td>}
      </tr>)}
    </tbody></ResponsiveTable></div>}
    {dialog === 'import' && <SettlementDialog headers={headers} actorId={actorId} connections={connections} onClose={() => setDialog(null)} onSaved={async () => { setDialog(null); await onChanged() }} showToast={showToast} />}
    {paying && <PaymentDialog headers={headers} actorId={actorId} settlement={paying} onClose={() => setPaying(null)} onSaved={async () => { setPaying(null); await onChanged() }} showToast={showToast} />}
  </section>
}

function SettlementDialog({ headers, actorId, connections, onClose, onSaved, showToast }: { headers: Record<string, string>; actorId: string; connections: api.MerchantConnection[]; onClose: () => void; onSaved: () => Promise<void>; showToast: Toast }) {
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? '')
  const [form, setForm] = useState({ document: '', externalOrder: '', competence: new Date().toISOString().slice(0, 10), gross: '', commission: '', fee: '', promotion: '', adjustment: '' })
  const [adjustmentSign, setAdjustmentSign] = useState<'CREDIT' | 'DEBIT'>('CREDIT')
  const [saving, setSaving] = useState(false)
  const money = (key: 'gross' | 'commission' | 'fee' | 'promotion' | 'adjustment') => ({ value: form[key], onChange: (event: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: maskCurrencyInput(event.target.value) }) })
  const adjustment = parseCurrencyInput(form.adjustment) * (adjustmentSign === 'DEBIT' ? -1 : 1)
  const expected = parseCurrencyInput(form.gross) - parseCurrencyInput(form.commission) - parseCurrencyInput(form.fee) - parseCurrencyInput(form.promotion) + adjustment
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.importMarketplaceSettlement(headers, crypto.randomUUID(), {
        connection_id: connectionId, provider_document_ref: form.document.trim(), external_order_id: form.externalOrder.trim() || undefined,
        competence_date: form.competence, gross_amount: parseCurrencyInput(form.gross), commission_amount: parseCurrencyInput(form.commission),
        fee_amount: parseCurrencyInput(form.fee), promotion_amount: parseCurrencyInput(form.promotion), adjustment_amount: adjustment, actor_id: actorId,
      })
      showToast('success', 'Documento de repasse registrado.')
      await onSaved()
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível registrar o documento.') }
    finally { setSaving(false) }
  }
  return <Modal isOpen onClose={onClose} title="Importar documento de repasse" subtitle="Os valores são os que o marketplace declarou" maxWidth="lg">
    <form onSubmit={submit} className="space-y-4">
      {connections.length > 1 && <label className={labelClass}>Canal<select value={connectionId} onChange={(event) => setConnectionId(event.target.value)} className={inputClass}>{connections.map((item) => <option key={item.id} value={item.id}>{item.provider_code} · {item.merchant_external_id}</option>)}</select></label>}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={labelClass}>Documento do provider<input required value={form.document} onChange={(event) => setForm({ ...form, document: event.target.value })} placeholder="Ex.: DOC-55" className={inputClass} /></label>
        <label className={labelClass}>Competência<input required type="date" value={form.competence} onChange={(event) => setForm({ ...form, competence: event.target.value })} className={inputClass} /></label>
      </div>
      <label className={labelClass}>Pedido externo (opcional)<input value={form.externalOrder} onChange={(event) => setForm({ ...form, externalOrder: event.target.value })} placeholder="Identificador do pedido no canal" className={inputClass} /></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={labelClass}>Bruto (R$)<input required type="text" inputMode="decimal" {...money('gross')} placeholder="0,00" className={inputClass} /></label>
        <label className={labelClass}>Comissão (R$)<input type="text" inputMode="decimal" {...money('commission')} placeholder="0,00" className={inputClass} /></label>
        <label className={labelClass}>Taxa (R$)<input type="text" inputMode="decimal" {...money('fee')} placeholder="0,00" className={inputClass} /></label>
        <label className={labelClass}>Promoção (R$)<input type="text" inputMode="decimal" {...money('promotion')} placeholder="0,00" className={inputClass} /></label>
        <label className={labelClass}>Ajuste (R$)<input type="text" inputMode="decimal" {...money('adjustment')} placeholder="0,00" className={inputClass} /></label>
        <label className={labelClass}>Natureza do ajuste<select value={adjustmentSign} onChange={(event) => setAdjustmentSign(event.target.value as 'CREDIT' | 'DEBIT')} className={inputClass}><option value="CREDIT">A favor da loja</option><option value="DEBIT">Contra a loja</option></select></label>
      </div>
      <p className="rounded-xl bg-slate-50 p-3 text-[11px] leading-5 text-slate-600">Líquido esperado por estes valores: <strong>{formatCurrency(expected)}</strong>. Quem calcula e persiste o líquido é o servidor; este número é só a conferência do que você digitou.</p>
      <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancelar</Button><Button type="submit" loading={saving}>Registrar documento</Button></div>
    </form>
  </Modal>
}

function PaymentDialog({ headers, actorId, settlement, onClose, onSaved, showToast }: { headers: Record<string, string>; actorId: string; settlement: api.MarketplaceSettlement; onClose: () => void; onSaved: () => Promise<void>; showToast: Toast }) {
  const remaining = Number(settlement.expected_net_amount) - Number(settlement.paid_amount)
  const [reference, setReference] = useState('')
  const [amount, setAmount] = useState(remaining > 0 ? maskCurrencyInput(remaining.toFixed(2)) : '')
  const [paidAt, setPaidAt] = useState(new Date().toISOString().slice(0, 16))
  const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setSaving(true)
    try {
      const updated = await api.recordMarketplaceSettlementPayment(headers, settlement.id, { provider_payment_ref: reference.trim(), amount: parseCurrencyInput(amount), paid_at: `${paidAt}:00`, actor_id: actorId })
      showToast(updated.status === 'DIVERGENT' ? 'info' : 'success', updated.status === 'DIVERGENT' ? 'Pagamento registrado. O recebido passou do esperado e o documento ficou divergente.' : 'Pagamento registrado.')
      await onSaved()
    } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível registrar o pagamento.') }
    finally { setSaving(false) }
  }
  return <Modal isOpen onClose={onClose} title="Registrar pagamento do repasse" subtitle={settlement.provider_document_ref}>
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-2 rounded-xl bg-slate-50 p-3 text-[11px] text-slate-600 sm:grid-cols-3"><span>Esperado<strong className="block text-sm text-dashem-strong">{formatCurrency(settlement.expected_net_amount)}</strong></span><span>Recebido<strong className="block text-sm text-dashem-strong">{formatCurrency(settlement.paid_amount)}</strong></span><span>Falta<strong className="block text-sm text-dashem-strong">{formatCurrency(remaining)}</strong></span></div>
      <label className={labelClass}>Referência do pagamento no provider<input required value={reference} onChange={(event) => setReference(event.target.value)} placeholder="Ex.: PAY-1" className={inputClass} /></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={labelClass}>Valor recebido (R$)<input required type="text" inputMode="decimal" value={amount} onChange={(event) => setAmount(maskCurrencyInput(event.target.value))} placeholder="0,00" className={inputClass} /></label>
        <label className={labelClass}>Recebido em<input required type="datetime-local" value={paidAt} onChange={(event) => setPaidAt(event.target.value)} className={inputClass} /></label>
      </div>
      <p className="rounded-xl bg-slate-50 p-3 text-[11px] leading-5 text-slate-600">A mesma referência enviada duas vezes não soma duas vezes. O pagamento acrescenta um fato ao documento e nunca reescreve o que o marketplace declarou.</p>
      <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancelar</Button><Button type="submit" loading={saving}>Registrar pagamento</Button></div>
    </form>
  </Modal>
}

function StatusPill({ tone, text }: { tone: 'good' | 'bad' | 'wait'; text: string }) {
  const styles = { good: 'bg-emerald-100 text-emerald-800', bad: 'bg-red-100 text-red-800', wait: 'bg-amber-100 text-amber-900' }
  return <span className={`inline-block rounded-full px-2 py-1 text-[10px] font-black ${styles[tone]}`}>{text}</span>
}
function Empty({ text }: { text: string }) { return <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">{text}</div> }
function Metric({label,value}:{label:string;value:number}){return <div className="rounded-xl bg-slate-50 p-3"><p className="text-[10px] font-black uppercase text-dashem-muted">{label}</p><p className="mt-1 text-xl font-black">{value}</p></div>}
function ConnectionDialog({ storeId, actorId, headers, onClose, onCreated, showToast }: { storeId: string; actorId: string; headers: Record<string, string>; onClose: () => void; onCreated: (secret: string) => Promise<void>; showToast: (type: 'success' | 'error' | 'info', text: string) => void }) {
  const [form, setForm] = useState({ provider: 'IFOOD', merchant: '', name: '', credentials: '' }); const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); try { const result = await api.createMerchantConnection(headers, crypto.randomUUID(), { store_id: storeId, provider_code: form.provider, merchant_external_id: form.merchant, channel_name: form.name, credentials_ref: form.credentials || undefined, actor_id: actorId }); showToast('success', 'Conexão cadastrada como não validada.'); await onCreated(result.webhook_secret) } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível cadastrar a conexão.') } finally { setSaving(false) } }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4"><form onSubmit={submit} className="responsive-dialog w-full max-w-lg space-y-3 rounded-3xl bg-white p-6"><div className="flex justify-between"><div><p className="text-xs font-black uppercase text-cyan-700">Configuração persistida</p><h2 className="text-xl font-black">Nova conexão</h2></div><button type="button" onClick={onClose}>×</button></div><label className="block text-xs font-black">Provider<select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} className="mt-1 h-11 w-full rounded-xl border px-3"><option value="IFOOD">iFood</option><option value="99FOOD">99Food</option><option value="OTHER">Outro adapter</option></select></label><Field label="ID do merchant" value={form.merchant} onChange={(value) => setForm({ ...form, merchant: value })} /><Field label="Nome do canal" value={form.name} onChange={(value) => setForm({ ...form, name: value })} /><Field label="Referência segura das credenciais" value={form.credentials} onChange={(value) => setForm({ ...form, credentials: value })} placeholder="secret://tenant/provider" /><p className="text-xs leading-5 text-slate-500">Cadastrar não significa conectar. O status só muda após o adapter validar credenciais e merchant.</p><button disabled={saving} className="h-11 w-full rounded-xl bg-cyan-700 text-sm font-black text-white">{saving ? 'Salvando...' : 'Cadastrar sem fingir conexão'}</button></form></div>
}
function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) { return <label className="block text-xs font-black">{label}<input required value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="mt-1 h-11 w-full rounded-xl border px-3" /></label> }
