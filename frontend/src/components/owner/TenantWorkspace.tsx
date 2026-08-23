import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity, ArrowLeft, BadgeCheck, Ban, Building2, CheckCircle2, PauseCircle,
  FilePenLine, FileText, Loader2, MapPin, Plus, RefreshCw, ShieldOff, Store,
  Trash2, UserCog, Users,
} from 'lucide-react'

import {
  CapabilityCatalogItem, createPlatformStore, fetchPlatformTenantDetail, fetchServicePlans,
  fetchTenantCapabilityCatalog,
  fetchTenantMetrics, invitePlatformTenantUser, PlatformTenantDetail,
  PlatformTenantSummary, ServicePlan, SubscriptionStatus, TenantCustomerType,
  TenantLifecycleStatus, TenantOperationalMetrics, updatePlatformStore,
  updatePlatformTenantAccess, updatePlatformTenantLifecycle,
  updatePlatformTenantProfile, updateTenantCapability, updateTenantSubscription,
} from '../../services/api'
import { formatCurrency } from '../../utils/format'

type Tab = 'summary' | 'registration' | 'stores' | 'access' | 'contract' | 'health'

const lifecycleLabel: Record<string, string> = {
  PROVISIONING: 'Provisionando', TRIAL: 'Avaliação', ACTIVE: 'Ativo',
  PAUSED: 'Pausado', SUSPENDED: 'Suspenso', CANCELED: 'Cancelado', ARCHIVED: 'Arquivado',
}
const typeLabel: Record<string, string> = { TEST: 'Teste', PILOT: 'Piloto', CUSTOMER: 'Cliente', INTERNAL: 'Interno' }
const inputClass = 'h-11 w-full rounded-xl border border-slate-300 bg-white px-3 font-semibold outline-none focus:border-rose-500 focus:ring-4 focus:ring-rose-100'

export function TenantWorkspace({ tenant, onBack, onChanged }: {
  tenant: PlatformTenantSummary
  onBack: () => void
  onChanged: () => Promise<void>
}) {
  const [tab, setTab] = useState<Tab>('summary')
  const [detail, setDetail] = useState<PlatformTenantDetail | null>(null)
  const [metrics, setMetrics] = useState<TenantOperationalMetrics | null>(null)
  const [plans, setPlans] = useState<ServicePlan[]>([])
  const [capabilityCatalog, setCapabilityCatalog] = useState<CapabilityCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [lifecycleAction, setLifecycleAction] = useState<TenantLifecycleStatus | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [nextDetail, nextMetrics, nextPlans, nextCapabilities] = await Promise.all([
        fetchPlatformTenantDetail(tenant.id), fetchTenantMetrics(tenant.id), fetchServicePlans(),
        fetchTenantCapabilityCatalog(tenant.id),
      ])
      setDetail(nextDetail); setMetrics(nextMetrics); setPlans(nextPlans); setCapabilityCatalog(nextCapabilities)
    } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível carregar o cliente.') }
    finally { setLoading(false) }
  }, [tenant.id])

  useEffect(() => { load() }, [load])

  const refresh = async () => { await Promise.all([load(), onChanged()]) }
  const tabs: Array<{ key: Tab; label: string }> = [
    { key: 'summary', label: 'Resumo' }, { key: 'registration', label: 'Cadastro' },
    { key: 'stores', label: 'Matriz e filiais' }, { key: 'access', label: 'Acessos' },
    { key: 'contract', label: 'Plano e capacidades' }, { key: 'health', label: 'Saúde e métricas' },
  ]

  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
    <button onClick={onBack} className="flex items-center gap-2 text-sm font-black text-slate-500 hover:text-rose-600"><ArrowLeft className="h-4 w-4" />Voltar para organizações</button>
    <header className="mt-5 rounded-3xl bg-[#0b172a] p-6 text-white sm:p-8">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div><div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-white/10 px-3 py-1 text-xs font-black">{typeLabel[detail?.profile?.customer_type ?? tenant.customer_type ?? 'TEST']}</span><span className={`rounded-full px-3 py-1 text-xs font-black ${detail?.tenant.status === 'ACTIVE' ? 'bg-emerald-400/15 text-emerald-300' : 'bg-amber-400/15 text-amber-200'}`}>{lifecycleLabel[detail?.tenant.status ?? tenant.status]}</span></div><h1 className="mt-4 text-3xl font-black tracking-tight">{detail?.tenant.name ?? tenant.name}</h1><p className="mt-2 text-sm text-slate-400">{detail?.profile?.legal_name || 'Razão social não informada'} · <span className="font-mono">{detail?.profile?.tax_id || 'CNPJ pendente'}</span></p></div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setTab('registration')} className="flex h-11 items-center gap-2 rounded-xl border border-white/15 px-4 text-sm font-black hover:bg-white/10"><FilePenLine className="h-4 w-4" />Editar cliente</button>
          {detail?.tenant.status === 'ACTIVE' || detail?.tenant.status === 'TRIAL' ? <button onClick={() => setLifecycleAction('PAUSED')} className="flex h-11 items-center gap-2 rounded-xl bg-amber-400 px-4 text-sm font-black text-slate-950"><PauseCircle className="h-4 w-4" />Pausar</button> : <button onClick={() => setLifecycleAction('ACTIVE')} className="flex h-11 items-center gap-2 rounded-xl bg-emerald-400 px-4 text-sm font-black text-slate-950"><CheckCircle2 className="h-4 w-4" />Reativar</button>}
          <button onClick={() => setLifecycleAction('ARCHIVED')} className="flex h-11 items-center gap-2 rounded-xl border border-rose-400/40 px-4 text-sm font-black text-rose-300 hover:bg-rose-400/10"><Trash2 className="h-4 w-4" />Arquivar</button>
        </div>
      </div>
    </header>

    {error && <p role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
    {notice && <div className="mt-5 flex items-center justify-between rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-bold text-emerald-700"><span>{notice}</span><button onClick={() => setNotice(null)}>Fechar</button></div>}

    <nav className="mt-6 flex gap-2 overflow-x-auto border-b border-slate-200 pb-px">
      {tabs.map(item => <button key={item.key} onClick={() => setTab(item.key)} className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm font-black ${tab === item.key ? 'border-rose-600 text-rose-600' : 'border-transparent text-slate-500 hover:text-slate-900'}`}>{item.label}</button>)}
    </nav>

    {loading && !detail ? <div className="flex justify-center py-24"><Loader2 className="h-8 w-8 animate-spin text-rose-600" /></div> : detail && <div className="mt-6">
      {tab === 'summary' && <SummaryTab detail={detail} metrics={metrics} onNavigate={setTab} />}
      {tab === 'registration' && <RegistrationTab detail={detail} onSaved={async () => { setNotice('Ficha cadastral atualizada e auditada.'); await refresh() }} />}
      {tab === 'stores' && <StoresTab detail={detail} onSaved={async message => { setNotice(message); await refresh() }} />}
      {tab === 'access' && <AccessTab detail={detail} onSaved={async message => { setNotice(message); await refresh() }} />}
      {tab === 'contract' && <ContractTab detail={detail} plans={plans} capabilities={capabilityCatalog} onSaved={async message => { setNotice(message); await refresh() }} />}
      {tab === 'health' && <HealthTab metrics={metrics} onRefresh={load} />}
    </div>}

    {lifecycleAction && <LifecycleDialog status={lifecycleAction} tenantId={tenant.id} onClose={() => setLifecycleAction(null)} onApplied={async () => { setLifecycleAction(null); setNotice(`Cliente ${lifecycleLabel[lifecycleAction]?.toLowerCase()}.`); await refresh() }} />}
  </div>
}

function MetricCard({ label, value, hint, attention = false }: { label: string; value: React.ReactNode; hint: string; attention?: boolean }) {
  return <article className={`rounded-2xl border bg-white p-5 shadow-sm ${attention ? 'border-amber-200' : 'border-slate-200'}`}><p className="text-xs font-black uppercase tracking-wider text-slate-400">{label}</p><p className={`mt-3 text-2xl font-black ${attention ? 'text-amber-700' : 'text-slate-950'}`}>{value}</p><p className="mt-2 text-xs font-semibold text-slate-500">{hint}</p></article>
}

function SummaryTab({ detail, metrics, onNavigate }: { detail: PlatformTenantDetail; metrics: TenantOperationalMetrics | null; onNavigate: (tab: Tab) => void }) {
  return <div className="space-y-6">
    {!detail.tenant.profile_complete && <button onClick={() => onNavigate('registration')} className="flex w-full items-center justify-between rounded-2xl border border-amber-200 bg-amber-50 p-4 text-left text-sm font-bold text-amber-900"><span>Cadastro incompleto: conclua dados legais, responsável e endereço da matriz.</span><FilePenLine className="h-5 w-5" /></button>}
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Vendas hoje" value={metrics?.sales_today ?? '—'} hint={formatCurrency(metrics?.revenue_today ?? 0)} />
      <MetricCard label="Últimos 30 dias" value={metrics?.sales_30d ?? '—'} hint={formatCurrency(metrics?.revenue_30d ?? 0)} />
      <MetricCard label="Usuários ativos" value={metrics ? `${metrics.users_active}/${metrics.users_total}` : '—'} hint={`${metrics?.users_invited ?? 0} convite(s) pendente(s)`} attention={Boolean(metrics && metrics.users_active === 0)} />
      <MetricCard label="Falhas operacionais" value={(metrics?.outbox_failed ?? 0) + (metrics?.agent_failures_30d ?? 0)} hint={`${metrics?.outbox_pending ?? 0} evento(s) na fila`} attention={Boolean(metrics && metrics.outbox_failed > 0)} />
    </section>
    <div className="grid gap-5 lg:grid-cols-3">
      <button onClick={() => onNavigate('stores')} className="rounded-2xl border border-slate-200 bg-white p-5 text-left hover:border-rose-300"><Store className="h-5 w-5 text-rose-600" /><p className="mt-4 font-black">Estruturas</p><p className="mt-1 text-sm text-slate-500">{metrics?.stores_active ?? 0} ativas de {metrics?.stores_total ?? 0} · {metrics?.registers_active ?? 0} terminais</p></button>
      <button onClick={() => onNavigate('access')} className="rounded-2xl border border-slate-200 bg-white p-5 text-left hover:border-rose-300"><Users className="h-5 w-5 text-rose-600" /><p className="mt-4 font-black">Acessos</p><p className="mt-1 text-sm text-slate-500">{metrics?.users_suspended ?? 0} suspensos · {metrics?.users_revoked ?? 0} revogados</p></button>
      <button onClick={() => onNavigate('health')} className="rounded-2xl border border-slate-200 bg-white p-5 text-left hover:border-rose-300"><Activity className="h-5 w-5 text-rose-600" /><p className="mt-4 font-black">Saúde operacional</p><p className="mt-1 text-sm text-slate-500">{metrics?.status === 'HEALTHY' ? 'Sem falhas detectadas' : 'Requer atenção'}</p></button>
    </div>
    <SalesChart metrics={metrics} />
  </div>
}

function SalesChart({ metrics }: { metrics: TenantOperationalMetrics | null }) {
  const values = metrics?.daily.map(item => Number(item.revenue)) ?? []
  const max = Math.max(...values, 0)
  return <section className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><div><h3 className="font-black">Receita diária</h3><p className="text-sm text-slate-500">Vendas pagas ou concluídas nos últimos 30 dias.</p></div><Activity className="h-5 w-5 text-rose-600" /></div>{max === 0 ? <div className="mt-8 rounded-xl border border-dashed border-slate-300 py-12 text-center text-sm font-semibold text-slate-500">Nenhuma venda concluída no período.</div> : <div className="mt-6 flex h-48 items-end gap-1">{values.map((value, index) => <div key={metrics?.daily[index].date} title={`${metrics?.daily[index].date}: ${formatCurrency(value)}`} className="min-w-1 flex-1 rounded-t bg-rose-500/80 hover:bg-rose-600" style={{ height: `${Math.max(3, (value / max) * 100)}%` }} />)}</div>}</section>
}

function RegistrationTab({ detail, onSaved }: { detail: PlatformTenantDetail; onSaved: () => Promise<void> }) {
  const hq = detail.stores.find(store => store.is_headquarters) ?? detail.stores[0]
  const contact = detail.contacts.find(item => item.is_primary && item.is_active)
  const [form, setForm] = useState({
    name: detail.tenant.name, customer_type: (detail.profile?.customer_type ?? 'TEST') as TenantCustomerType,
    legal_name: detail.profile?.legal_name ?? '', tax_id: detail.profile?.tax_id ?? '',
    state_registration: detail.profile?.state_registration ?? '', municipal_registration: detail.profile?.municipal_registration ?? '',
    industry: detail.profile?.industry ?? '', company_email: detail.profile?.company_email ?? '',
    company_phone: detail.profile?.company_phone ?? '', website: detail.profile?.website ?? '', notes: detail.profile?.notes ?? '',
    contact_name: contact?.full_name ?? '', contact_job_title: contact?.job_title ?? '', contact_email: contact?.email ?? '', contact_phone: contact?.phone ?? '',
    store_name: hq?.name ?? '', store_code: hq?.code ?? '', postal_code: hq?.postal_code ?? '', street: hq?.street ?? '',
    street_number: hq?.street_number ?? '', address_complement: hq?.address_complement ?? '', district: hq?.district ?? '', city: hq?.city ?? '', state: hq?.state ?? '',
  })
  const [saving, setSaving] = useState(false); const [error, setError] = useState<string | null>(null)
  const set = (key: string, value: string) => setForm(current => ({ ...current, [key]: value }))
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); setError(null); try { await updatePlatformTenantProfile(detail.tenant.id, form); await onSaved() } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível salvar.') } finally { setSaving(false) } }
  return <form onSubmit={submit} className="space-y-6"><section className="rounded-2xl border border-slate-200 bg-white p-5"><h3 className="font-black">Dados legais e comerciais</h3><div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3"><Field label="Nome fantasia" value={form.name} onChange={value => set('name', value)} /><Field label="Razão social" value={form.legal_name} onChange={value => set('legal_name', value)} /><Field label="CNPJ" value={form.tax_id} onChange={value => set('tax_id', value.replace(/\D/g, '').slice(0, 14))} /><Field label="Inscrição estadual" value={form.state_registration} onChange={value => set('state_registration', value)} /><Field label="Inscrição municipal" value={form.municipal_registration} onChange={value => set('municipal_registration', value)} /><Field label="Área de atuação" value={form.industry} onChange={value => set('industry', value)} /><Field label="Telefone" value={form.company_phone} onChange={value => set('company_phone', value)} /><Field label="E-mail" value={form.company_email} onChange={value => set('company_email', value)} type="email" /><Field label="Site" value={form.website} onChange={value => set('website', value)} /><label className="text-sm font-black">Classificação<select className={`mt-2 ${inputClass}`} value={form.customer_type} onChange={e => setForm(current => ({ ...current, customer_type: e.target.value as TenantCustomerType }))}><option value="TEST">Teste</option><option value="PILOT">Piloto</option><option value="CUSTOMER">Cliente</option><option value="INTERNAL">Interno</option></select></label></div></section><section className="rounded-2xl border border-slate-200 bg-white p-5"><h3 className="font-black">Responsável direto</h3><div className="mt-4 grid gap-4 sm:grid-cols-2"><Field label="Nome" value={form.contact_name} onChange={value => set('contact_name', value)} /><Field label="Cargo" value={form.contact_job_title} onChange={value => set('contact_job_title', value)} /><Field label="E-mail" value={form.contact_email} onChange={value => set('contact_email', value)} type="email" /><Field label="Telefone" value={form.contact_phone} onChange={value => set('contact_phone', value)} /></div></section><section className="rounded-2xl border border-slate-200 bg-white p-5"><h3 className="font-black">Endereço da matriz</h3><div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3"><Field label="Unidade" value={form.store_name} onChange={value => set('store_name', value)} /><Field label="Código" value={form.store_code} onChange={value => set('store_code', value.toUpperCase())} /><Field label="CEP" value={form.postal_code} onChange={value => set('postal_code', value.replace(/\D/g, '').slice(0, 8))} /><Field label="Logradouro" value={form.street} onChange={value => set('street', value)} /><Field label="Número" value={form.street_number} onChange={value => set('street_number', value)} /><Field label="Complemento" value={form.address_complement} onChange={value => set('address_complement', value)} /><Field label="Bairro" value={form.district} onChange={value => set('district', value)} /><Field label="Cidade" value={form.city} onChange={value => set('city', value)} /><Field label="UF" value={form.state} onChange={value => set('state', value.toUpperCase().slice(0, 2))} /></div></section>{error && <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}<button disabled={saving} className="h-12 rounded-xl bg-rose-600 px-6 font-black text-white disabled:opacity-50">{saving ? 'Salvando…' : 'Salvar ficha cadastral'}</button></form>
}

function Field({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) { return <label className="text-sm font-black">{label}<input type={type} value={value} onChange={e => onChange(e.target.value)} className={`mt-2 ${inputClass}`} /></label> }

function StoresTab({ detail, onSaved }: { detail: PlatformTenantDetail; onSaved: (message: string) => Promise<void> }) {
  const empty = { name: '', code: '', site_type: 'BRANCH', tax_id: '', state_registration: '', email: '', phone: '', postal_code: '', street: '', street_number: '', address_complement: '', district: '', city: '', state: '' }
  const [editingId, setEditingId] = useState<string | 'new' | null>(null)
  const [form, setForm] = useState(empty)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const edit = (store: PlatformTenantDetail['stores'][number]) => {
    setEditingId(store.id)
    setForm({
      name: store.name, code: store.code, site_type: store.site_type || (store.is_headquarters ? 'HEADQUARTERS' : 'BRANCH'),
      tax_id: store.tax_id || '', state_registration: store.state_registration || '', email: store.email || '', phone: store.phone || '',
      postal_code: store.postal_code || '', street: store.street || '', street_number: store.street_number || '', address_complement: store.address_complement || '',
      district: store.district || '', city: store.city || '', state: store.state || '',
    })
    setError(null)
  }
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setSaving(true); setError(null)
    try {
      if (editingId === 'new') {
        await createPlatformStore(detail.tenant.id, { ...form, code: form.code.toUpperCase() })
        await onSaved('Filial criada e auditada.')
      } else if (editingId) {
        await updatePlatformStore(detail.tenant.id, editingId, { ...form, code: form.code.toUpperCase() })
        await onSaved('Unidade atualizada e auditada.')
      }
      setEditingId(null); setForm(empty)
    } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível salvar a unidade.') }
    finally { setSaving(false) }
  }
  const toggle = async (store: PlatformTenantDetail['stores'][number]) => {
    try {
      await updatePlatformStore(detail.tenant.id, store.id, {
        name: store.name, code: store.code, site_type: store.site_type || 'BRANCH', tax_id: store.tax_id,
        state_registration: store.state_registration, email: store.email, phone: store.phone, postal_code: store.postal_code,
        street: store.street, street_number: store.street_number, address_complement: store.address_complement,
        district: store.district, city: store.city, state: store.state, is_active: !store.is_active,
      })
      await onSaved(store.is_active ? 'Unidade desativada.' : 'Unidade reativada.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível alterar a unidade.') }
  }
  const labels: Record<string, string> = { name: 'Nome', code: 'Código', tax_id: 'CNPJ', state_registration: 'Inscrição estadual', email: 'E-mail', phone: 'Telefone', postal_code: 'CEP', street: 'Logradouro', street_number: 'Número', address_complement: 'Complemento', district: 'Bairro', city: 'Cidade', state: 'UF' }
  return <div className="space-y-5">
    <div className="flex items-center justify-between"><div><h2 className="text-xl font-black">Matriz e filiais</h2><p className="text-sm text-slate-500">Crie, edite, desative ou reative estruturas persistidas.</p></div><button onClick={() => { setEditingId('new'); setForm(empty); setError(null) }} className="flex h-11 items-center gap-2 rounded-xl bg-rose-600 px-4 text-sm font-black text-white"><Plus className="h-4 w-4" />Nova filial</button></div>
    {editingId && <form onSubmit={submit} className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><h3 className="font-black">{editingId === 'new' ? 'Nova filial' : 'Editar unidade'}</h3><button type="button" onClick={() => setEditingId(null)} className="text-sm font-black text-slate-500">Cancelar</button></div><div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(form).filter(([key]) => key !== 'site_type').map(([key, value]) => <Field key={key} label={labels[key]} value={value} onChange={next => setForm(current => ({ ...current, [key]: next }))} />)}</div>{error && <p className="mt-4 text-sm font-bold text-red-700">{error}</p>}<button disabled={saving || !form.name || !form.code} className="mt-5 h-11 rounded-xl bg-slate-950 px-5 text-sm font-black text-white disabled:opacity-50">{saving ? 'Salvando…' : editingId === 'new' ? 'Criar filial' : 'Salvar unidade'}</button></form>}
    {!editingId && error && <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}
    <div className="grid gap-4 lg:grid-cols-2">{detail.stores.map(store => <article key={store.id} className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-start justify-between"><div><div className="flex items-center gap-2"><Store className="h-5 w-5 text-rose-600" /><h3 className="font-black">{store.name}</h3></div><p className="mt-2 font-mono text-xs text-slate-400">{store.code} · {store.is_headquarters ? 'MATRIZ' : 'FILIAL'}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-black ${store.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{store.is_active ? 'ATIVA' : 'INATIVA'}</span></div><p className="mt-4 text-sm text-slate-500">{[store.street, store.street_number, store.district, store.city, store.state].filter(Boolean).join(', ') || 'Endereço não informado'}</p><div className="mt-4 flex gap-4"><button onClick={() => edit(store)} className="text-sm font-black text-slate-700">Editar unidade</button>{!store.is_headquarters && <button onClick={() => toggle(store)} className="text-sm font-black text-rose-600">{store.is_active ? 'Desativar unidade' : 'Reativar unidade'}</button>}</div></article>)}</div>
  </div>
}

function AccessTab({ detail, onSaved }: { detail: PlatformTenantDetail; onSaved: (message: string) => Promise<void> }) {
  const [open, setOpen] = useState(false); const [form, setForm] = useState({ full_name: '', email: '', role: 'TENANT_OWNER', store_id: '' }); const [saving, setSaving] = useState(false); const [error, setError] = useState<string | null>(null); const [reason, setReason] = useState('Alteração solicitada pelo administrador da plataforma.')
  const invite = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); setError(null); try { await invitePlatformTenantUser(detail.tenant.id, { ...form, store_id: form.store_id || undefined }); setOpen(false); setForm({ full_name: '', email: '', role: 'TENANT_OWNER', store_id: '' }); await onSaved('Convite enviado.') } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível conceder o acesso.') } finally { setSaving(false) } }
  const change = async (access: PlatformTenantDetail['accesses'][number], status: string) => { try { await updatePlatformTenantAccess(detail.tenant.id, access.membership_id, { role: access.role, status, store_id: access.store_id, reason }); await onSaved(status === 'REVOKED' ? 'Acesso revogado.' : status === 'SUSPENDED' ? 'Acesso suspenso.' : 'Acesso reativado.') } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível alterar o acesso.') } }
  return <div className="space-y-5"><div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="text-xl font-black">Administrador contratual e segurança</h2><p className="text-sm text-slate-500">O Control entrega o primeiro administrador. A equipe cotidiana é gerida pelo cliente no Dashem Gestão.</p></div><button onClick={() => setOpen(value => !value)} className="flex h-11 items-center gap-2 rounded-xl bg-rose-600 px-4 text-sm font-black text-white"><Plus className="h-4 w-4" />Entregar acesso</button></div>{error && <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}{open && <form onSubmit={invite} className="rounded-2xl border border-slate-200 bg-white p-5"><div className="grid gap-4 sm:grid-cols-2"><Field label="Nome do administrador contratual" value={form.full_name} onChange={value => setForm(current => ({ ...current, full_name: value, role: 'TENANT_OWNER', store_id: '' }))} /><Field label="E-mail" value={form.email} onChange={value => setForm(current => ({ ...current, email: value }))} type="email" /></div><button disabled={saving || !form.full_name || !form.email.includes('@')} className="mt-5 h-11 rounded-xl bg-slate-950 px-5 text-sm font-black text-white">{saving ? 'Enviando…' : 'Entregar acesso de administrador'}</button></form>}<label className="block max-w-2xl text-sm font-black">Motivo obrigatório para ação de segurança<input value={reason} onChange={e => setReason(e.target.value)} className={`mt-2 ${inputClass}`} /></label><div className="overflow-hidden rounded-2xl border border-slate-200 bg-white"><table className="w-full min-w-[760px] text-left"><thead className="bg-slate-50 text-xs font-black uppercase text-slate-400"><tr><th className="p-4">Usuário</th><th className="p-4">Papel</th><th className="p-4">Escopo</th><th className="p-4">Estado</th><th className="p-4">Segurança</th></tr></thead><tbody className="divide-y divide-slate-100">{detail.accesses.map(access => <tr key={access.membership_id}><td className="p-4"><p className="font-black">{access.full_name}</p><p className="text-sm text-slate-500">{access.email}</p></td><td className="p-4 text-sm font-bold">{access.role}</td><td className="p-4 text-sm">{access.store_name || 'Tenant inteiro'}</td><td className="p-4"><span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-black">{access.status}</span></td><td className="p-4"><div className="flex gap-2">{access.status === 'ACTIVE' ? <><button onClick={() => change(access, 'SUSPENDED')} title="Suspender por segurança" className="rounded-lg border border-amber-200 p-2 text-amber-700"><Ban className="h-4 w-4" /></button><button onClick={() => change(access, 'REVOKED')} title="Revogar por segurança" className="rounded-lg border border-red-200 p-2 text-red-700"><ShieldOff className="h-4 w-4" /></button></> : <button onClick={() => change(access, 'ACTIVE')} className="rounded-lg border border-emerald-200 px-3 py-2 text-xs font-black text-emerald-700">Reativar</button>}</div></td></tr>)}</tbody></table>{detail.accesses.length === 0 && <p className="p-8 text-center text-sm font-semibold text-slate-500">Nenhum acesso concedido.</p>}</div></div>
}

function ContractTab({ detail, plans, capabilities, onSaved }: {
  detail: PlatformTenantDetail
  plans: ServicePlan[]
  capabilities: CapabilityCatalogItem[]
  onSaved: (message: string) => Promise<void>
}) {
  const [planId, setPlanId] = useState(detail.subscription?.plan_id ?? '')
  const [status, setStatus] = useState<SubscriptionStatus>(detail.subscription?.status ?? 'PENDING')
  const [saving, setSaving] = useState(false)
  const [changingKey, setChangingKey] = useState<string | null>(null)
  const [reason, setReason] = useState('Ajuste do escopo contratado pelo cliente.')
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    setSaving(true); setError(null)
    try { await updateTenantSubscription(detail.tenant.id, planId || undefined, status); await onSaved('Contrato atualizado.') }
    catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível atualizar o contrato.') }
    finally { setSaving(false) }
  }
  const toggleCapability = async (capability: CapabilityCatalogItem) => {
    setChangingKey(capability.key); setError(null)
    try {
      await updateTenantCapability(detail.tenant.id, capability.key, {
        enabled: !capability.enabled,
        contract_limits: capability.contract_limits,
        reason,
      })
      await onSaved(capability.enabled ? `${capability.name} removida do contrato.` : `${capability.name} adicionada ao contrato.`)
    } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível atualizar a capacidade.') }
    finally { setChangingKey(null) }
  }
  return <div className="space-y-5">
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="text-xl font-black">Plano contratado</h2>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-black">Plano<select className={`mt-2 ${inputClass}`} value={planId} onChange={e => setPlanId(e.target.value)}><option value="">Sem plano definido</option>{plans.filter(plan => plan.is_active).map(plan => <option key={plan.id} value={plan.id}>{plan.name}</option>)}</select></label>
        <label className="text-sm font-black">Estado da assinatura<select className={`mt-2 ${inputClass}`} value={status} onChange={e => setStatus(e.target.value as SubscriptionStatus)}><option value="PENDING">Pendente</option><option value="TRIAL">Avaliação</option><option value="ACTIVE">Ativa</option><option value="PAUSED">Pausada</option><option value="CANCELED">Cancelada</option></select></label>
      </div>
      <button onClick={save} disabled={saving} className="mt-5 h-11 rounded-xl bg-rose-600 px-5 text-sm font-black text-white disabled:opacity-50">{saving ? 'Salvando…' : 'Salvar contrato'}</button>
    </section>
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><h3 className="font-black">Capacidades contratadas</h3><p className="mt-1 text-sm text-slate-500">Ative ou reduza módulos; dependências são aplicadas automaticamente.</p></div><label className="w-full max-w-lg text-sm font-black">Motivo da alteração<input value={reason} onChange={event => setReason(event.target.value)} className={`mt-2 ${inputClass}`} /></label></div>
      {error && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}
      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {capabilities.map(capability => <article key={capability.key} className={`rounded-xl border p-4 ${capability.enabled ? 'border-emerald-200 bg-emerald-50/50' : 'border-slate-200'}`}>
          <div className="flex items-start justify-between gap-3"><div><p className="font-black">{capability.name}</p><p className="mt-1 text-xs font-bold uppercase tracking-wide text-slate-400">{capability.scope} · v{capability.version}</p></div><button disabled={changingKey !== null || reason.trim().length < 4} onClick={() => toggleCapability(capability)} className={`rounded-lg px-3 py-2 text-xs font-black disabled:opacity-40 ${capability.enabled ? 'border border-red-200 bg-white text-red-700' : 'bg-slate-950 text-white'}`}>{changingKey === capability.key ? 'Aplicando…' : capability.enabled ? 'Remover' : 'Adicionar'}</button></div>
          <p className="mt-3 text-sm text-slate-600">{capability.description}</p>
          {capability.requires.length > 0 && <p className="mt-3 text-xs font-semibold text-slate-500">Requer: {capability.requires.join(', ')}</p>}
        </article>)}
      </div>
    </section>
  </div>
}

function HealthTab({ metrics, onRefresh }: { metrics: TenantOperationalMetrics | null; onRefresh: () => Promise<void> }) {
  return <div className="space-y-6"><div className="flex items-center justify-between"><div><h2 className="text-xl font-black">Saúde operacional do cliente</h2><p className="text-sm text-slate-500">Calculada agora a partir dos registros do tenant.</p></div><button onClick={onRefresh} className="flex h-10 items-center gap-2 rounded-xl border border-slate-300 px-4 text-sm font-black"><RefreshCw className="h-4 w-4" />Atualizar</button></div><section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Caixas abertos" value={metrics?.cash_sessions_open ?? '—'} hint={`${metrics?.registers_active ?? 0} terminais ativos`} attention={Boolean(metrics?.cash_sessions_open)} /><MetricCard label="Estoque crítico" value={metrics?.low_stock_items ?? '—'} hint={`${metrics?.products_total ?? 0} produtos cadastrados`} attention={Boolean(metrics?.low_stock_items)} /><MetricCard label="Fila pendente" value={metrics?.outbox_pending ?? '—'} hint={`${metrics?.outbox_failed ?? 0} falhas`} attention={Boolean(metrics?.outbox_failed)} /><MetricCard label="Execuções de IA" value={metrics?.agent_runs_30d ?? '—'} hint={`${metrics?.agent_failures_30d ?? 0} falhas em 30 dias`} attention={Boolean(metrics?.agent_failures_30d)} /></section><SalesChart metrics={metrics} /><p className="text-xs font-semibold text-slate-500">Última atividade: {metrics?.last_activity_at ? new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(metrics.last_activity_at)) : 'nenhuma atividade registrada'}</p></div>
}

function LifecycleDialog({ status, tenantId, onClose, onApplied }: { status: TenantLifecycleStatus; tenantId: string; onClose: () => void; onApplied: () => Promise<void> }) {
  const [reason, setReason] = useState(''); const [saving, setSaving] = useState(false); const [error, setError] = useState<string | null>(null)
  const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); setError(null); try { await updatePlatformTenantLifecycle(tenantId, status, reason); await onApplied() } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível alterar o cliente.') } finally { setSaving(false) } }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4"><button className="absolute inset-0" onClick={onClose} /><form onSubmit={submit} className="relative w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"><h2 className="text-xl font-black">{lifecycleLabel[status]} cliente</h2><p className="mt-2 text-sm text-slate-500">A operação será registrada na auditoria e não apagará o histórico.</p><label className="mt-5 block text-sm font-black">Motivo<input autoFocus value={reason} onChange={e => setReason(e.target.value)} className={`mt-2 ${inputClass}`} /></label>{error && <p className="mt-3 text-sm font-bold text-red-700">{error}</p>}<div className="mt-6 flex gap-3"><button type="button" onClick={onClose} className="h-11 flex-1 rounded-xl border border-slate-300 font-black">Cancelar</button><button disabled={saving || reason.trim().length < 3} className="h-11 flex-1 rounded-xl bg-rose-600 font-black text-white disabled:opacity-40">{saving ? 'Aplicando…' : 'Confirmar'}</button></div></form></div>
}
