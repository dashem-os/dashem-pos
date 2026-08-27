import React, { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, Ban, Building2, CheckCircle2, Loader2, Plus, ShieldCheck, Users } from 'lucide-react'

import {
  CapabilityCatalogItem, fetchPlatformTenantDetail, fetchTenantCapabilityCatalog,
  invitePlatformTenantUser, PlatformTenantDetail, PlatformTenantSummary,
  TenantLifecycleStatus, updatePlatformTenantLifecycle,
} from '../../services/api'

type Tab = 'summary' | 'registration' | 'contract' | 'administrator'
const nicheLabel = { FOOD_SERVICE: 'Food Service', RETAIL: 'Retail', BEAUTY_RESELLER: 'Beauty Reseller' }
const statusLabel: Record<string, string> = { TRIAL: 'Avaliação', ACTIVE: 'Ativo', PAUSED: 'Pausado', SUSPENDED: 'Suspenso', CANCELED: 'Cancelado', ARCHIVED: 'Arquivado', PROVISIONING: 'Provisionando' }

export function TenantWorkspace({ tenant, onBack, onChanged }: { tenant: PlatformTenantSummary; onBack: () => void; onChanged: () => Promise<void> }) {
  const [tab, setTab] = useState<Tab>('summary')
  const [detail, setDetail] = useState<PlatformTenantDetail | null>(null)
  const [capabilities, setCapabilities] = useState<CapabilityCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lifecycle, setLifecycle] = useState<TenantLifecycleStatus | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    const results = await Promise.allSettled([fetchPlatformTenantDetail(tenant.id), fetchTenantCapabilityCatalog(tenant.id)])
    if (results[0].status === 'fulfilled') setDetail(results[0].value)
    else setError(results[0].reason instanceof Error ? results[0].reason.message : 'Não foi possível carregar o contrato.')
    if (results[1].status === 'fulfilled') setCapabilities(results[1].value)
    setLoading(false)
  }, [tenant.id])
  useEffect(() => { load() }, [load])

  if (loading || !detail) return <div className="p-20"><Loader2 className="mx-auto h-8 w-8 animate-spin text-rose-600" /></div>
  const activeCapabilities = capabilities.filter(item => item.enabled)
  const limits = detail.contract?.limits ?? {}
  const billing = (limits as Record<string, unknown>).billing as { contact_name?: string; email?: string; phone?: string } | undefined
  const admin = detail.accesses[0]
  const headquarters = detail.stores.find(store => store.is_headquarters) ?? detail.stores[0]

  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
    <button onClick={onBack} className="flex items-center gap-2 text-sm font-black text-slate-500"><ArrowLeft className="h-4 w-4" />Voltar para organizações</button>
    <section className="mt-5 rounded-3xl bg-[#0b172a] p-7 text-white sm:p-8">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between"><div><div className="flex flex-wrap gap-2"><span className="rounded-full bg-white/10 px-3 py-1 text-xs font-black">{detail.profile?.customer_type ?? 'CLIENTE'}</span><span className="rounded-full bg-emerald-400/15 px-3 py-1 text-xs font-black text-emerald-300">{detail.niche ? nicheLabel[detail.niche] : 'Nicho não contratado'}</span></div><h2 className="mt-5 text-3xl font-black">{detail.tenant.name}</h2><p className="mt-2 text-slate-300">{detail.profile?.legal_name || 'Razão social não informada'} · {detail.profile?.tax_id || 'CNPJ pendente'}</p></div><div className="flex gap-3"><button onClick={() => setLifecycle('PAUSED')} className="flex h-11 items-center gap-2 rounded-xl bg-amber-400 px-4 font-black text-slate-950"><Ban className="h-4 w-4" />Pausar</button><button onClick={() => setLifecycle('ARCHIVED')} className="h-11 rounded-xl border border-rose-400/40 px-4 font-black text-rose-300">Arquivar</button></div></div>
    </section>
    <nav className="mt-5 flex gap-2 overflow-x-auto border-b border-slate-200">{([['summary', 'Resumo contratual'], ['registration', 'Cadastro'], ['contract', 'Plano e entitlements'], ['administrator', 'Administrador inicial']] as Array<[Tab, string]>).map(([key, label]) => <button key={key} onClick={() => setTab(key)} className={`shrink-0 border-b-2 px-4 py-4 text-sm font-black ${tab === key ? 'border-rose-600 text-rose-600' : 'border-transparent text-slate-500'}`}>{label}</button>)}</nav>
    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
    <main className="mt-6">
      {tab === 'summary' && <div className="grid gap-5 lg:grid-cols-3"><Card icon={Building2} title="Contrato" value={detail.plan?.name || 'Sem plano'} hint={`${detail.niche ? nicheLabel[detail.niche] : 'Sem nicho'} · versão ${detail.contract?.version ?? '—'}`} /><Card icon={ShieldCheck} title="Entitlements" value={`${activeCapabilities.length} capabilities`} hint="Somente o escopo efetivamente contratado" /><Card icon={Users} title="Administrador" value={admin?.full_name || 'Pendente'} hint={admin?.email || 'Primeiro acesso ainda não entregue'} /><section className="rounded-2xl border border-slate-200 bg-white p-6 lg:col-span-3"><h3 className="text-lg font-black">Limites contratados</h3><div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Limit label="Usuários" value={limits.users} /><Limit label="Dispositivos" value={limits.devices} /><Limit label="Unidades" value={limits.units} /><Limit label="Storage" value={limits.storage_mb ? `${limits.storage_mb} MB` : undefined} /></div></section></div>}
      {tab === 'registration' && <div className="grid gap-5 lg:grid-cols-2"><InfoSection title="Empresa"><Info label="Nome fantasia" value={detail.profile?.trade_name} /><Info label="Razão social" value={detail.profile?.legal_name} /><Info label="CNPJ" value={detail.profile?.tax_id} /><Info label="E-mail" value={detail.profile?.company_email} /><Info label="Telefone" value={detail.profile?.company_phone} /></InfoSection><InfoSection title="Responsável contratual"><Info label="Nome" value={detail.contacts[0]?.full_name} /><Info label="Cargo" value={detail.contacts[0]?.job_title} /><Info label="E-mail" value={detail.contacts[0]?.email} /><Info label="Telefone" value={detail.contacts[0]?.phone} /></InfoSection><InfoSection title="Cobrança"><Info label="Contato" value={billing?.contact_name} /><Info label="E-mail" value={billing?.email} /><Info label="Telefone" value={billing?.phone} /></InfoSection><InfoSection title="Matriz cadastral"><Info label="Unidade" value={headquarters?.name} /><Info label="Endereço" value={[headquarters?.street, headquarters?.street_number, headquarters?.district, headquarters?.city, headquarters?.state].filter(Boolean).join(', ')} /></InfoSection></div>}
      {tab === 'contract' && <div className="space-y-5"><section className="rounded-2xl border border-slate-200 bg-white p-6"><div className="grid gap-5 sm:grid-cols-3"><Info label="Nicho" value={detail.niche ? nicheLabel[detail.niche] : undefined} /><Info label="Plano" value={detail.plan?.name} /><Info label="Assinatura" value={statusLabel[detail.subscription?.status || ''] || detail.subscription?.status} /></div></section><section className="rounded-2xl border border-slate-200 bg-white p-6"><h3 className="text-lg font-black">Capabilities filtradas pelo nicho</h3><p className="mt-1 text-sm text-slate-500">Verde: contratado. Cinza: add-on permitido, mas não contratado. Capabilities de outros nichos não aparecem.</p><div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{capabilities.map(item => <article key={item.key} className={`rounded-xl border p-4 ${item.enabled ? 'border-emerald-200 bg-emerald-50' : 'border-slate-200 bg-slate-50'}`}><div className="flex items-start justify-between gap-3"><h4 className="font-black">{item.name}</h4>{item.enabled && <CheckCircle2 className="h-5 w-5 text-emerald-600" />}</div><p className="mt-2 text-sm text-slate-600">{item.description}</p><p className="mt-3 text-xs font-black uppercase text-slate-400">{item.required ? 'Base do nicho' : 'Add-on permitido'} · {item.enabled ? 'Contratado' : 'Não contratado'}</p></article>)}</div></section></div>}
      {tab === 'administrator' && <Administrator detail={detail} onSaved={load} />}
    </main>
    {lifecycle && <LifecycleDialog status={lifecycle} tenantId={tenant.id} onClose={() => setLifecycle(null)} onApplied={async () => { setLifecycle(null); await load(); await onChanged() }} />}
  </div>
}

function Card({ icon: Icon, title, value, hint }: { icon: React.ComponentType<{ className?: string }>; title: string; value: string; hint: string }) { return <article className="rounded-2xl border border-slate-200 bg-white p-6"><Icon className="h-6 w-6 text-rose-600" /><p className="mt-4 text-xs font-black uppercase text-slate-400">{title}</p><p className="mt-2 text-xl font-black">{value}</p><p className="mt-2 text-sm text-slate-500">{hint}</p></article> }
function Limit({ label, value }: { label: string; value: unknown }) { return <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs font-black uppercase text-slate-400">{label}</p><p className="mt-2 text-2xl font-black">{value === undefined ? '—' : String(value)}</p></div> }
function InfoSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="rounded-2xl border border-slate-200 bg-white p-6"><h3 className="border-b border-slate-100 pb-3 text-lg font-black">{title}</h3><dl className="mt-4 grid gap-4 sm:grid-cols-2">{children}</dl></section> }
function Info({ label, value }: { label: string; value?: string }) { return <div><dt className="text-xs font-black uppercase text-slate-400">{label}</dt><dd className="mt-1 font-semibold text-slate-800">{value || 'Não informado'}</dd></div> }

function Administrator({ detail, onSaved }: { detail: PlatformTenantDetail; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState({ full_name: '', email: '' }); const [saving, setSaving] = useState(false); const [error, setError] = useState<string | null>(null)
  const admin = detail.accesses[0]
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); setError(null); try { await invitePlatformTenantUser(detail.tenant.id, form); await onSaved() } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível entregar o acesso.') } finally { setSaving(false) } }
  return <section className="rounded-2xl border border-slate-200 bg-white p-6"><h3 className="text-xl font-black">Primeiro administrador contratual</h3><p className="mt-2 text-sm text-slate-500">O Owner não administra a equipe operacional do cliente.</p>{admin ? <div className="mt-6 flex flex-col gap-3 rounded-xl bg-emerald-50 p-5 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-black">{admin.full_name}</p><p className="text-sm text-slate-600">{admin.email}</p></div><span className="rounded-full bg-emerald-600 px-3 py-1 text-xs font-black text-white">{admin.status}</span></div> : <form onSubmit={submit} className="mt-6 grid gap-4 sm:grid-cols-2"><label className="text-sm font-black">Nome<input value={form.full_name} onChange={event => setForm(current => ({ ...current, full_name: event.target.value }))} className="mt-2 h-11 w-full rounded-xl border border-slate-300 px-3" /></label><label className="text-sm font-black">E-mail<input type="email" value={form.email} onChange={event => setForm(current => ({ ...current, email: event.target.value }))} className="mt-2 h-11 w-full rounded-xl border border-slate-300 px-3" /></label>{error && <p className="text-sm font-bold text-red-700 sm:col-span-2">{error}</p>}<button disabled={saving || !form.email.includes('@') || form.full_name.length < 2} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-rose-600 px-5 font-black text-white disabled:opacity-40 sm:col-span-2 sm:w-fit"><Plus className="h-4 w-4" />{saving ? 'Enviando…' : 'Entregar primeiro acesso'}</button></form>}</section>
}

function LifecycleDialog({ status, tenantId, onClose, onApplied }: { status: TenantLifecycleStatus; tenantId: string; onClose: () => void; onApplied: () => Promise<void> }) {
  const [reason, setReason] = useState(''); const [saving, setSaving] = useState(false); const [error, setError] = useState<string | null>(null)
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); setError(null); try { await updatePlatformTenantLifecycle(tenantId, status, reason); await onApplied() } catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível alterar o ciclo do cliente.') } finally { setSaving(false) } }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4"><button className="absolute inset-0" onClick={onClose} /><form onSubmit={submit} className="relative w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"><h2 className="text-xl font-black">{status === 'PAUSED' ? 'Pausar' : 'Arquivar'} cliente</h2><p className="mt-2 text-sm text-slate-500">A ação preserva contrato, cadastro e auditoria.</p><label className="mt-5 block text-sm font-black">Motivo<input autoFocus value={reason} onChange={event => setReason(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-slate-300 px-3" /></label>{error && <p className="mt-3 text-sm font-bold text-red-700">{error}</p>}<div className="mt-6 flex gap-3"><button type="button" onClick={onClose} className="h-11 flex-1 rounded-xl border border-slate-300 font-black">Cancelar</button><button disabled={saving || reason.trim().length < 3} className="h-11 flex-1 rounded-xl bg-rose-600 font-black text-white disabled:opacity-40">Confirmar</button></div></form></div>
}
