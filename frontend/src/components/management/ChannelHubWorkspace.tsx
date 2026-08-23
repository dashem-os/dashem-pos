import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Link2, Loader2, Plus, Radio, RefreshCw } from 'lucide-react'

import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'


const connectionLabels: Record<api.MerchantConnection['status'], string> = {
  NOT_CONNECTED: 'Não conectado', VALIDATING: 'Validando', CONNECTED: 'Conectado',
  DEGRADED: 'Degradado', SUSPENDED: 'Suspenso',
}

export function ChannelHubWorkspace() {
  const { tenant, store, operatorId, permissions, showToast } = usePos()
  const [connections, setConnections] = useState<api.MerchantConnection[]>([])
  const [events, setEvents] = useState<api.ChannelInboxEvent[]>([])
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
      const [nextConnections, nextEvents] = await Promise.all([api.fetchMerchantConnections(headers), api.fetchChannelInbox(headers)])
      setConnections(nextConnections); setEvents(nextEvents)
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
    <header className="flex flex-col justify-between gap-4 rounded-3xl bg-[#07172b] p-6 text-white sm:flex-row sm:items-center"><div><p className="text-xs font-black uppercase tracking-[.16em] text-cyan-400">Omnichannel · inbox durável</p><h1 className="mt-1 text-2xl font-black">Dashem Channel Hub</h1><p className="mt-2 max-w-2xl text-sm text-slate-300">Eventos externos entram no mesmo Order Engine. Conexão só aparece ativa após validação real do adapter.</p></div><div className="flex gap-2"><button onClick={() => void load()} className="flex h-11 items-center gap-2 rounded-xl border border-slate-600 px-4 text-xs font-black"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Atualizar</button>{permissions.includes('channel.configure') && <button onClick={() => setFormOpen(true)} className="flex h-11 items-center gap-2 rounded-xl bg-cyan-600 px-4 text-xs font-black"><Plus className="h-4 w-4" />Nova conexão</button>}</div></header>
    {webhookSecret && <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4"><p className="text-xs font-black text-amber-900">Segredo de webhook exibido uma única vez</p><code className="mt-2 block break-all rounded-lg bg-white p-3 text-xs">{webhookSecret}</code><button onClick={() => setWebhookSecret(null)} className="mt-2 text-xs font-black text-amber-800">Já armazenei com segurança</button></div>}
    <div className="grid gap-5 xl:grid-cols-[420px_1fr]"><section className="rounded-3xl border border-slate-200 bg-white p-5"><h2 className="font-black">Conexões</h2><p className="text-xs text-slate-500">{connections.length} merchants persistidos</p><div className="mt-4 space-y-3">{loading && <Loader2 className="h-5 w-5 animate-spin" />}{!loading && connections.length === 0 && <Empty text="Nenhum canal configurado. iFood e 99Food não serão mostrados como conectados sem credenciais e validação." />}{connections.map((connection) => <article key={connection.id} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-start justify-between"><div><p className="font-black">{connection.provider_code}</p><p className="text-xs text-slate-500">{connection.merchant_external_id}</p></div><span className={`rounded-full px-2 py-1 text-[10px] font-black ${connection.status === 'CONNECTED' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-900'}`}>{connectionLabels[connection.status]}</span></div>{connection.last_error_code && <p className="mt-2 text-[11px] text-amber-800">{connection.last_error_code}</p>}{permissions.includes('channel.configure') && connection.status !== 'CONNECTED' && <button disabled={busy} onClick={() => void validate(connection.id)} className="mt-3 h-9 w-full rounded-xl border border-cyan-300 text-xs font-black text-cyan-800">Validar com provider</button>}</article>)}</div></section>
      <section className="rounded-3xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><div><h2 className="font-black">External Order Inbox</h2><p className="text-xs text-slate-500">Persistência, ack, normalização e quarentena observáveis</p></div><Radio className="h-5 w-5 text-cyan-600" /></div><div className="mt-4 overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b text-[10px] uppercase text-slate-400"><th className="p-3">Recebido</th><th className="p-3">Pedido externo</th><th className="p-3">Estado</th><th className="p-3">Order</th></tr></thead><tbody>{events.map((event) => <tr key={event.id} className="border-b border-slate-100"><td className="p-3">{new Date(event.received_at).toLocaleString('pt-BR')}</td><td className="p-3 font-bold">{event.external_order_id}</td><td className="p-3"><span className="flex items-center gap-1 font-black">{event.status === 'QUARANTINED' ? <AlertTriangle className="h-3.5 w-3.5 text-amber-600" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />}{event.status}</span>{event.quarantine_reason && <p className="mt-1 max-w-xs text-[10px] text-amber-700">{event.quarantine_reason}</p>}</td><td className="p-3 font-mono text-[10px]">{event.order_id || '—'}</td></tr>)}</tbody></table>{!loading && events.length === 0 && <Empty text="Nenhum evento externo recebido. A tela não injeta pedidos demonstrativos." />}</div></section></div>
    {formOpen && store && <ConnectionDialog storeId={store.id} actorId={operatorId} headers={headers} onClose={() => setFormOpen(false)} onCreated={async (secret) => { setWebhookSecret(secret); setFormOpen(false); await load() }} showToast={showToast} />}
  </section>
}

function Empty({ text }: { text: string }) { return <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">{text}</div> }
function ConnectionDialog({ storeId, actorId, headers, onClose, onCreated, showToast }: { storeId: string; actorId: string; headers: Record<string, string>; onClose: () => void; onCreated: (secret: string) => Promise<void>; showToast: (type: 'success' | 'error' | 'info', text: string) => void }) {
  const [form, setForm] = useState({ provider: 'IFOOD', merchant: '', name: '', credentials: '' }); const [saving, setSaving] = useState(false)
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); try { const result = await api.createMerchantConnection(headers, crypto.randomUUID(), { store_id: storeId, provider_code: form.provider, merchant_external_id: form.merchant, channel_name: form.name, credentials_ref: form.credentials || undefined, actor_id: actorId }); showToast('success', 'Conexão cadastrada como não validada.'); await onCreated(result.webhook_secret) } catch (error) { showToast('error', error instanceof Error ? error.message : 'Não foi possível cadastrar a conexão.') } finally { setSaving(false) } }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4"><form onSubmit={submit} className="w-full max-w-lg space-y-3 rounded-3xl bg-white p-6"><div className="flex justify-between"><div><p className="text-xs font-black uppercase text-cyan-700">Configuração persistida</p><h2 className="text-xl font-black">Nova conexão</h2></div><button type="button" onClick={onClose}>×</button></div><label className="block text-xs font-black">Provider<select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} className="mt-1 h-11 w-full rounded-xl border px-3"><option value="IFOOD">iFood</option><option value="99FOOD">99Food</option><option value="OTHER">Outro adapter</option></select></label><Field label="ID do merchant" value={form.merchant} onChange={(value) => setForm({ ...form, merchant: value })} /><Field label="Nome do canal" value={form.name} onChange={(value) => setForm({ ...form, name: value })} /><Field label="Referência segura das credenciais" value={form.credentials} onChange={(value) => setForm({ ...form, credentials: value })} placeholder="secret://tenant/provider" /><p className="text-xs leading-5 text-slate-500">Cadastrar não significa conectar. O status só muda após o adapter validar credenciais e merchant.</p><button disabled={saving} className="h-11 w-full rounded-xl bg-cyan-700 text-sm font-black text-white">{saving ? 'Salvando...' : 'Cadastrar sem fingir conexão'}</button></form></div>
}
function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) { return <label className="block text-xs font-black">{label}<input required value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="mt-1 h-11 w-full rounded-xl border px-3" /></label> }
