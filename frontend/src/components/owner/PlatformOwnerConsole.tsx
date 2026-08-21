import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowRight, Building2, CheckCircle2, LayoutGrid, Loader2,
  LogOut, Menu, Plus, Search, ShieldCheck, Sparkles, Store, Users, X,
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import {
  AuthMe, fetchPlatformOverview, PlatformOverview, provisionPlatformTenant,
  fetchPlatformTenantDetail, invitePlatformTenantUser, PlatformTenantDetail,
  PlatformTenantSummary,
} from '../../services/api'

const statusLabel: Record<string, string> = {
  PROVISIONING: 'Provisionando',
  TRIAL: 'Avaliação',
  ACTIVE: 'Ativo',
  SUSPENDED: 'Suspenso',
  CANCELED: 'Cancelado',
}

function normalizeSlug(value: string) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

export function PlatformOwnerConsole({ me }: { me: AuthMe }) {
  const { signOut } = useAuth()
  const [overview, setOverview] = useState<PlatformOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const [selectedTenant, setSelectedTenant] = useState<PlatformTenantSummary | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setOverview(await fetchPlatformOverview())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível carregar a plataforma.')
    }
  }, [])

  useEffect(() => { load() }, [load])

  const tenants = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return overview?.tenants ?? []
    return (overview?.tenants ?? []).filter(tenant =>
      tenant.name.toLowerCase().includes(needle) || tenant.slug.includes(needle)
    )
  }, [overview, query])
  const statCards = [
    { label: 'Organizações', value: overview?.tenant_count, icon: Building2, hint: 'Clientes provisionados' },
    { label: 'Em operação', value: overview?.active_count, icon: CheckCircle2, hint: 'Acesso comercial liberado' },
    { label: 'Em implantação', value: overview?.trial_count, icon: Sparkles, hint: 'Avaliação e onboarding' },
    { label: 'Oportunidades', value: overview?.lead_count, icon: Users, hint: 'Leads em acompanhamento' },
  ]

  return (
    <div className="min-h-screen bg-[#f4f6f9] text-slate-950 lg:grid lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className={`${mobileNav ? 'flex' : 'hidden'} fixed inset-y-0 left-0 z-40 w-[280px] flex-col bg-[#081222] p-5 text-white shadow-2xl lg:static lg:flex lg:w-auto lg:shadow-none`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-600 font-black shadow-lg shadow-rose-600/30">D</div><div><p className="font-black tracking-tight">DASHEM</p><p className="text-[10px] font-bold uppercase tracking-[.2em] text-slate-500">Control</p></div></div>
          <button className="lg:hidden" onClick={() => setMobileNav(false)}><X className="h-5 w-5" /></button>
        </div>
        <nav className="mt-10 space-y-2">
          <button onClick={() => { window.scrollTo({ top: 0, behavior: 'smooth' }); setMobileNav(false) }} className="flex w-full items-center gap-3 rounded-xl bg-white/10 px-4 py-3 text-left text-sm font-bold"><LayoutGrid className="h-5 w-5 text-rose-400" />Visão geral</button>
          <button onClick={() => { document.getElementById('organizacoes')?.scrollIntoView({ behavior: 'smooth' }); setMobileNav(false) }} className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-bold text-slate-400 transition hover:bg-white/[.06] hover:text-white"><Building2 className="h-5 w-5" />Organizações</button>
        </nav>
        <div className="mt-auto rounded-2xl border border-white/10 bg-white/[.04] p-4">
          <div className="flex items-center gap-2 text-xs font-bold text-emerald-400"><ShieldCheck className="h-4 w-4" />Sessão Owner protegida</div>
          <p className="mt-3 truncate text-sm font-bold text-white">{me.user?.full_name}</p>
          <p className="truncate text-xs text-slate-500">{me.user?.email}</p>
          <button onClick={signOut} className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-white/10 text-xs font-bold text-slate-300 transition hover:bg-white/10 hover:text-white"><LogOut className="h-4 w-4" />Sair do Dashem Control</button>
        </div>
      </aside>
      {mobileNav && <button aria-label="Fechar navegação" className="fixed inset-0 z-30 bg-slate-950/50 lg:hidden" onClick={() => setMobileNav(false)} />}

      <main className="min-w-0">
        <header className="flex h-20 items-center justify-between border-b border-slate-200 bg-white px-5 sm:px-8">
          <div className="flex items-center gap-4"><button onClick={() => setMobileNav(true)} className="rounded-xl border border-slate-200 p-2 lg:hidden"><Menu className="h-5 w-5" /></button><div><p className="text-xs font-bold uppercase tracking-[.16em] text-slate-400">Dashem Control</p><h1 className="text-lg font-black tracking-tight">Visão geral da plataforma</h1></div></div>
          <div className="flex items-center gap-2"><button onClick={() => setCreateOpen(true)} className="flex h-11 items-center gap-2 rounded-xl bg-rose-600 px-4 text-sm font-black text-white shadow-lg shadow-rose-600/20 transition hover:bg-rose-700"><Plus className="h-4 w-4" /><span className="hidden sm:inline">Nova organização</span></button><button onClick={signOut} title="Sair da plataforma" className="flex h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm font-black text-slate-600 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700"><LogOut className="h-4 w-4" /><span className="hidden xl:inline">Sair</span></button></div>
        </header>

        <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
          <section className="relative overflow-hidden rounded-3xl bg-[#0b172a] p-7 text-white sm:p-9">
            <div className="absolute right-0 top-0 h-64 w-64 translate-x-1/3 -translate-y-1/3 rounded-full bg-emerald-500/10 blur-3xl" />
            <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between"><div className="max-w-3xl"><p className="text-xs font-black uppercase tracking-[.18em] text-rose-400">Control plane · uso interno Dashem</p><h2 className="mt-3 text-3xl font-black tracking-[-.03em]">Operação da plataforma</h2><p className="mt-3 max-w-2xl leading-7 text-slate-300">Provisione organizações e entregue o primeiro acesso ao administrador contratual. Papéis e permissões internas pertencem ao cliente.</p></div><div className={`flex min-w-56 items-center gap-3 rounded-2xl border p-4 ${error ? 'border-amber-400/20 bg-amber-400/10' : 'border-emerald-400/20 bg-emerald-400/10'}`}><span className={`h-2.5 w-2.5 rounded-full ${error ? 'bg-amber-400' : overview ? 'bg-emerald-400 shadow-[0_0_0_6px_rgba(52,211,153,.12)]' : 'animate-pulse bg-slate-400'}`} /><div><p className={`text-xs font-black uppercase tracking-wider ${error ? 'text-amber-300' : 'text-emerald-300'}`}>Conexão da plataforma</p><p className="mt-1 font-bold">{error ? 'Requer atenção' : overview ? 'API conectada' : 'Verificando'}</p></div></div></div>
          </section>

          {error && <div role="alert" className="mt-6 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}<button onClick={load} className="ml-3 underline">Tentar novamente</button></div>}

          <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {statCards.map(({ label, value, icon: Icon, hint }) => (
              <article key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase tracking-[.12em] text-slate-400">{label}</p><p className="mt-3 text-3xl font-black">{overview ? String(value) : '—'}</p></div><div className="rounded-xl bg-slate-100 p-2.5 text-slate-700"><Icon className="h-5 w-5" /></div></div><p className="mt-4 text-xs font-semibold text-slate-400">{hint}</p></article>
            ))}
          </section>

          <section id="organizacoes" className="mt-6 scroll-mt-24 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-col gap-4 border-b border-slate-200 p-5 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="font-black">Organizações provisionadas</h2><p className="mt-1 text-sm text-slate-500">Ciclo de vida comercial e estruturas contratadas.</p></div><label className="relative block sm:w-80"><Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-400" /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Buscar organização ou identificador" className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-10 pr-4 text-sm font-semibold outline-none focus:border-rose-400" /></label></div>
            {!overview ? <div className="flex justify-center py-20"><Loader2 className="h-7 w-7 animate-spin text-rose-600" /></div> : tenants.length === 0 ? <div className="py-16 text-center"><Building2 className="mx-auto h-9 w-9 text-slate-300" /><p className="mt-4 font-black">Nenhum tenant encontrado</p><p className="mt-1 text-sm text-slate-500">Crie o primeiro ambiente operacional da plataforma.</p></div> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left">
                  <thead className="bg-slate-50 text-[11px] font-black uppercase tracking-[.12em] text-slate-400"><tr><th className="px-5 py-3">Organização</th><th className="px-5 py-3">Identificador</th><th className="px-5 py-3">Ciclo de vida</th><th className="px-5 py-3">Estruturas</th><th className="px-5 py-3">Provisionada em</th><th className="px-5 py-3" /></tr></thead>
                  <tbody className="divide-y divide-slate-100">{tenants.map(tenant => (
                    <tr key={tenant.id} onClick={() => setSelectedTenant(tenant)} tabIndex={0} role="button" onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') setSelectedTenant(tenant) }} className="group cursor-pointer hover:bg-slate-50 focus:bg-rose-50 focus:outline-none">
                      <td className="px-5 py-4"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 font-black text-slate-600">{tenant.name.charAt(0).toUpperCase()}</div><div><p className="font-black">{tenant.name}</p><p className="text-xs text-slate-400">{tenant.id.slice(0, 8)}</p></div></div></td>
                      <td className="px-5 py-4 font-mono text-sm font-bold text-slate-600">{tenant.slug}</td>
                      <td className="px-5 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${tenant.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : tenant.status === 'TRIAL' ? 'bg-sky-50 text-sky-700' : 'bg-slate-100 text-slate-600'}`}>{statusLabel[tenant.status] ?? tenant.status}</span></td>
                      <td className="px-5 py-4"><span className="inline-flex items-center gap-2 text-sm font-bold"><Store className="h-4 w-4 text-slate-400" />{tenant.store_count}</span></td>
                      <td className="px-5 py-4 text-sm font-semibold text-slate-500">{new Intl.DateTimeFormat('pt-BR').format(new Date(tenant.created_at))}</td>
                      <td className="px-5 py-4 text-right"><button onClick={event => { event.stopPropagation(); setSelectedTenant(tenant) }} title="Detalhes do tenant" className="rounded-lg p-2 text-slate-400 hover:bg-white hover:text-rose-600"><ArrowRight className="h-4 w-4" /></button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </main>

      {createOpen && <CreateTenantPanel onClose={() => setCreateOpen(false)} onCreated={async () => { setCreateOpen(false); await load() }} />}
      {selectedTenant && <TenantAccessPanel tenant={selectedTenant} onClose={() => setSelectedTenant(null)} />}
    </div>
  )
}

function TenantAccessPanel({ tenant, onClose }: { tenant: PlatformTenantSummary; onClose: () => void }) {
  const [detail, setDetail] = useState<PlatformTenantDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const loadDetail = useCallback(async () => {
    setLoading(true); setError(null)
    try { setDetail(await fetchPlatformTenantDetail(tenant.id)) }
    catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível carregar o tenant.') }
    finally { setLoading(false) }
  }, [tenant.id])
  useEffect(() => { loadDetail() }, [loadDetail])
  const contractualAdmins = detail?.accesses.filter(access => access.role === 'TENANT_OWNER' || access.role === 'OWNER') ?? []
  const submitInvite = async (event: React.FormEvent) => {
    event.preventDefault(); setSending(true); setError(null); setNotice(null)
    try {
      const result = await invitePlatformTenantUser(tenant.id, { full_name: fullName.trim(), email: email.trim() })
      setNotice(result.delivery_status === 'ENVIADO' ? 'Convite enviado ao administrador contratual. O acesso será ativado após a criação da senha.' : 'Administrador contratual associado à identidade existente.')
      setFullName(''); setEmail(''); setInviteOpen(false); await loadDetail()
    } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível enviar o convite.') }
    finally { setSending(false) }
  }
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/55 backdrop-blur-sm"><button aria-label="Fechar detalhes" className="absolute inset-0" onClick={onClose} /><section className="relative flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl"><header className="flex items-start justify-between border-b border-slate-200 p-6 sm:p-8"><div><p className="text-xs font-black uppercase tracking-[.16em] text-rose-600">Organização</p><h2 className="mt-2 text-2xl font-black">{tenant.name}</h2><p className="mt-2 font-mono text-sm text-slate-500">{tenant.slug}</p></div><button onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500"><X className="h-5 w-5" /></button></header><div className="flex-1 overflow-y-auto p-6 sm:p-8">
    <div className="rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm leading-6 text-sky-900"><strong>Fronteira de responsabilidade:</strong> a Dashem entrega o primeiro acesso ao administrador indicado no contrato. A partir daí, o cliente organiza sua equipe, seus papéis e suas permissões no Dashem Gestão.</div>
    {error && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}
    {notice && <p className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-bold text-emerald-700">{notice}</p>}
    <div className="mt-6 flex items-center justify-between gap-4"><div><h3 className="font-black">Administrador contratual</h3><p className="text-sm text-slate-500">Responsável indicado pela empresa contratante.</p></div><button onClick={() => setInviteOpen(value => !value)} className="flex h-10 shrink-0 items-center gap-2 rounded-xl bg-rose-600 px-4 text-sm font-black text-white"><Plus className="h-4 w-4" />Entregar acesso</button></div>
    {inviteOpen && <form onSubmit={submitInvite} className="mt-5 space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-5"><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-black">Nome completo<input value={fullName} onChange={e => setFullName(e.target.value)} className="mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3 font-semibold" /></label><label className="text-sm font-black">E-mail corporativo<input type="email" value={email} onChange={e => setEmail(e.target.value)} className="mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3 font-semibold" /></label></div><p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-semibold leading-5 text-amber-900">Este acesso recebe a administração inicial da organização. A Dashem não define funções internas da empresa.</p><button disabled={sending || fullName.trim().length < 2 || !email.includes('@')} className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#0b172a] font-black text-white disabled:opacity-40">{sending ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Enviar acesso ao administrador'}</button></form>}
    {loading ? <Loader2 className="mx-auto mt-12 h-7 w-7 animate-spin text-rose-600" /> : contractualAdmins.length ? <div className="mt-5 space-y-3">{contractualAdmins.map(access => <article key={access.membership_id} className="rounded-2xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-4"><div><p className="font-black">{access.full_name}</p><p className="text-sm text-slate-500">{access.email}</p><p className="mt-2 text-xs font-bold text-slate-400">Administrador da organização</p></div><div className="text-right"><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-black">CONTRATUAL</span><p className={`mt-3 text-xs font-black ${access.status === 'ACTIVE' ? 'text-emerald-600' : 'text-amber-600'}`}>{access.status === 'ACTIVE' ? 'ACESSO ATIVO' : 'CONVITE PENDENTE'}</p></div></div></article>)}</div> : <div className="mt-8 rounded-2xl border border-dashed border-slate-300 p-8 text-center"><Users className="mx-auto h-8 w-8 text-slate-300" /><p className="mt-3 font-black">Administrador ainda não indicado</p><p className="mt-1 text-sm text-slate-500">Entregue o primeiro acesso conforme o contrato.</p></div>}
  </div></section></div>
}

function CreateTenantPanel({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [storeName, setStoreName] = useState('Unidade Principal')
  const [storeCode, setStoreCode] = useState('MATRIZ')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const changeName = (value: string) => {
    setName(value)
    if (!slugTouched) setSlug(normalizeSlug(value))
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await provisionPlatformTenant({ name: name.trim(), slug, first_store_name: storeName.trim(), first_store_code: storeCode.trim() })
      await onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível criar o tenant.')
      setLoading(false)
    }
  }

  const valid = name.trim().length >= 2 && slug.length >= 3 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) && storeName.trim().length >= 2 && storeCode.trim().length >= 2
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/55 backdrop-blur-sm"><button aria-label="Fechar criação" className="absolute inset-0" onClick={onClose} /><section className="relative flex h-full w-full max-w-xl flex-col bg-white shadow-2xl"><header className="flex items-start justify-between border-b border-slate-200 p-6 sm:p-8"><div><p className="text-xs font-black uppercase tracking-[.16em] text-rose-600">Provisionamento</p><h2 className="mt-2 text-2xl font-black tracking-tight">Nova organização</h2><p className="mt-2 text-sm leading-6 text-slate-500">Cria o cliente e sua primeira estrutura operacional em uma transação auditada.</p></div><button onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500"><X className="h-5 w-5" /></button></header><form onSubmit={submit} className="flex flex-1 flex-col overflow-y-auto"><div className="space-y-6 p-6 sm:p-8"><label className="block text-sm font-black">Nome da organização<input autoFocus value={name} onChange={e => changeName(e.target.value)} placeholder="Ex.: Lanchonete Central" className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 font-semibold outline-none focus:border-rose-500 focus:ring-4 focus:ring-rose-100" /></label><label className="block text-sm font-black">Identificador único<div className="mt-2 flex h-12 items-center rounded-xl border border-slate-300 bg-white px-4 focus-within:border-rose-500 focus-within:ring-4 focus-within:ring-rose-100"><span className="text-sm font-semibold text-slate-400">dashem /</span><input value={slug} onChange={e => { setSlugTouched(true); setSlug(normalizeSlug(e.target.value)) }} placeholder="lanchonete-central" className="min-w-0 flex-1 pl-2 font-mono text-sm font-bold outline-none" /></div><p className="mt-2 text-xs text-slate-400">Referência técnica permanente. Não substitui os dados cadastrais ou contratuais da empresa.</p></label><div className="h-px bg-slate-200" /><div><p className="font-black">Primeira estrutura contratada</p><p className="mt-1 text-sm text-slate-500">A organização nasce com sua primeira unidade operacional.</p></div><div className="grid gap-4 sm:grid-cols-[1fr_160px]"><label className="block text-sm font-black">Nome da unidade<input value={storeName} onChange={e => setStoreName(e.target.value)} className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 font-semibold outline-none focus:border-rose-500" /></label><label className="block text-sm font-black">Código interno<input value={storeCode} onChange={e => setStoreCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''))} className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 font-mono font-bold outline-none focus:border-rose-500" /></label></div><p className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs font-semibold leading-5 text-slate-600">Dados legais, plano, limites, capacidades e ciclo contratual serão tratados no módulo de contratos. Este formulário não cria papéis internos da empresa.</p>{error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}</div><footer className="mt-auto flex gap-3 border-t border-slate-200 bg-slate-50 p-6 sm:p-8"><button type="button" onClick={onClose} className="h-12 flex-1 rounded-xl border border-slate-300 bg-white font-black text-slate-600">Cancelar</button><button disabled={!valid || loading} className="flex h-12 flex-[1.5] items-center justify-center gap-2 rounded-xl bg-rose-600 font-black text-white shadow-lg shadow-rose-600/20 disabled:opacity-40">{loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <><Plus className="h-5 w-5" />Provisionar organização</>}</button></footer></form></section></div>
}
