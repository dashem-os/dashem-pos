import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Loader2, Send } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'

const kindLabel: Record<api.CommercialChangeKind, string> = {
  ACTIVITY: 'Atividade comercial', CAPABILITY: 'Capability', INTEGRATION: 'Integração',
  USER_LIMIT: 'Limite de usuários', DEVICE_LIMIT: 'Limite de dispositivos',
  UNIT_LIMIT: 'Limite de unidades', STORAGE_LIMIT: 'Limite de storage',
}
const statusLabel: Record<api.CommercialRequestStatus, string> = {
  PENDING: 'Em análise', APPROVED: 'Aprovada', DECLINED: 'Recusada', CANCELED: 'Cancelada',
}

export function CommercialRequestsPanel() {
  const { tenant, store, permissions, showToast } = usePos()
  const [catalog, setCatalog] = useState<api.CommercialRequestCatalog | null>(null)
  const [storage, setStorage] = useState<api.StorageQuotaUsage | null>(null)
  const [requests, setRequests] = useState<api.CommercialChangeRequest[]>([])
  const [reason, setReason] = useState('')
  const [quota, setQuota] = useState<{ kind: api.CommercialChangeKind; value: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const headers = tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : null
  const canRequest = permissions.includes('team.manage')

  const load = useCallback(async () => {
    if (!headers) return
    setError('')
    try {
      const [nextCatalog, nextRequests, nextStorage] = await Promise.all([
        api.fetchCommercialRequestCatalog(headers), api.fetchCommercialRequests(headers),
        api.fetchTenantStorageQuota(headers),
      ])
      setCatalog(nextCatalog); setRequests(nextRequests); setStorage(nextStorage)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Falha ao carregar solicitações.') }
  }, [tenant?.id, store?.id])
  useEffect(() => { void load() }, [load])

  const send = async (kind: api.CommercialChangeKind, payload: Record<string, unknown>) => {
    if (!headers || reason.trim().length < 4) { setError('Descreva o motivo da solicitação.'); return }
    setBusy(true); setError('')
    try {
      await api.createCommercialRequest(headers, { kind, payload, reason: reason.trim() })
      setReason(''); setQuota(null); await load()
      showToast('success', 'Solicitação enviada ao Owner. Nenhum direito foi liberado automaticamente.')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Falha ao enviar solicitação.') }
    finally { setBusy(false) }
  }

  if (!catalog) return error ? <p className="rounded-xl border border-red-900 bg-red-950/30 p-4 text-sm font-bold text-red-300">{error}</p> : <Loader2 className="mx-auto h-6 w-6 animate-spin text-dashem-red" />
  const quotaOptions: Array<[api.CommercialChangeKind, keyof typeof catalog.contracted_limits, string]> = [
    ['USER_LIMIT', 'users', 'Usuários'], ['DEVICE_LIMIT', 'devices', 'Dispositivos'],
    ['UNIT_LIMIT', 'units', 'Unidades'], ['STORAGE_LIMIT', 'storage_mb', 'Storage (MB)'],
  ]
  return <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6">
    <div><p className="text-[10px] font-black uppercase tracking-[.16em] text-dashem-red">Governança comercial</p><h3 className="mt-1 text-xl font-black text-white">Solicitar expansão contratual</h3><p className="mt-2 text-sm text-dashem-muted">O pedido não libera acesso. O Owner analisa e, se aprovar, cria uma nova versão auditada do contrato.</p></div>
    {storage && <div className="mt-5 rounded-xl border border-dashem-border p-4"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-black text-white">Storage do tenant</p><div className="flex gap-2"><span className="rounded-full bg-dashem-bg px-2 py-1 font-mono text-[10px] font-black text-slate-200">{storage.measurement_status}</span><span className="rounded-full bg-dashem-bg px-2 py-1 font-mono text-[10px] font-black text-slate-200">{storage.quota_status}</span></div></div><p className="mt-2 font-mono text-xs text-slate-400">{storage.status_code}</p><p className="mt-2 text-xs font-bold text-slate-200">Uso observado: {formatBytes(storage.used_bytes)} · reservado: {formatBytes(storage.reserved_bytes)} · disponível: {formatBytes(storage.available_bytes)}</p></div>}
    {error && <p className="mt-4 rounded-xl border border-red-900 bg-red-950/30 p-3 text-xs font-bold text-red-300">{error}</p>}
    {canRequest ? <><label className="mt-5 block text-xs font-black text-slate-300">Motivo e contexto<input value={reason} onChange={event => setReason(event.target.value)} placeholder="Explique a necessidade operacional" className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm text-white outline-none focus:border-dashem-red" /></label>
      {(catalog.activities.length > 0 || catalog.capabilities.length > 0) && <div className="mt-5 grid gap-4 lg:grid-cols-2"><RequestChoices title="Atividades disponíveis" items={catalog.activities} busy={busy} onRequest={item => void send('ACTIVITY', { activity_key: item.key })} /><RequestChoices title="Add-ons disponíveis" items={catalog.capabilities} busy={busy} onRequest={item => void send('CAPABILITY', { capability_key: item.key })} /></div>}
      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{quotaOptions.map(([kind, resource, label]) => <div key={kind} className="rounded-xl bg-dashem-bg p-4"><p className="text-xs font-black text-white">{label}</p><p className="mt-1 text-[11px] text-dashem-muted">Contratado: {catalog.contracted_limits[resource] ?? 'não informado'} · teto do plano: {catalog.plan_limits[resource] ?? 'sem teto'}</p>{quota?.kind === kind ? <div className="mt-3 flex gap-2"><input autoFocus type="number" min={Number(catalog.contracted_limits[resource] ?? 0) + 1} max={catalog.plan_limits[resource] ?? undefined} inputMode="numeric" value={quota.value} onChange={event => setQuota({ kind, value: event.target.value.replace(/\D/g, '') })} className="h-9 min-w-0 flex-1 rounded-lg border border-dashem-border bg-dashem-surface px-2 text-sm" /><button disabled={busy || !quota.value} onClick={() => void send(kind, { requested_limit: Number(quota.value) })} className="rounded-lg bg-dashem-red px-3 text-xs font-black"><Send className="h-4 w-4" /></button></div> : <button onClick={() => setQuota({ kind, value: '' })} className="mt-3 text-xs font-black text-dashem-red">Solicitar aumento</button>}</div>)}</div>
    </> : <p className="mt-5 rounded-xl border border-amber-900/50 bg-amber-950/30 p-3 text-xs font-bold text-amber-300">Seu acesso permite acompanhar solicitações, mas não criar uma nova.</p>}
    <div className="mt-6 border-t border-dashem-border pt-5"><h4 className="text-sm font-black text-white">Histórico</h4><div className="mt-3 space-y-2">{requests.map(item => <article key={item.id} className="rounded-xl bg-dashem-bg p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-black text-white">{kindLabel[item.kind]}</p><span className={`rounded-full px-2 py-1 text-[10px] font-black ${item.status === 'APPROVED' ? 'bg-emerald-950 text-emerald-300' : item.status === 'DECLINED' ? 'bg-red-950 text-red-300' : 'bg-amber-950 text-amber-300'}`}>{statusLabel[item.status]}</span></div><p className="mt-2 text-xs text-dashem-muted">{item.reason}</p>{item.decision && <p className="mt-2 flex items-center gap-1 text-xs text-slate-300"><CheckCircle2 className="h-3.5 w-3.5" />Decisão do Owner: {item.decision.reason}</p>}</article>)}{requests.length === 0 && <p className="text-xs text-dashem-muted">Nenhuma solicitação enviada.</p>}</div></div>
  </section>
}

function formatBytes(value?: number) {
  if (value == null) return '—'
  return value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} GB`
    : `${(value / 1024 ** 2).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} MB`
}

function RequestChoices({ title, items, busy, onRequest }: { title: string; items: Array<{ key: string; name: string; description: string }>; busy: boolean; onRequest: (item: { key: string; name: string; description: string }) => void }) {
  return <div><h4 className="text-sm font-black text-white">{title}</h4><div className="mt-2 space-y-2">{items.map(item => <button key={item.key} disabled={busy} onClick={() => onRequest(item)} className="w-full rounded-xl border border-dashem-border bg-dashem-bg p-3 text-left hover:border-dashem-red disabled:opacity-40"><span className="text-xs font-black text-white">{item.name}</span><span className="mt-1 block text-[11px] text-dashem-muted">{item.description}</span></button>)}{items.length === 0 && <p className="text-xs text-dashem-muted">Nenhuma opção compatível com a contratação atual.</p>}</div></div>
}
