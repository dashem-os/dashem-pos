import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowRight, Building2, CheckCircle2, LayoutGrid, Loader2,
  LogOut, Menu, Plus, Search, ShieldCheck, Sparkles, Store, Users, X,
  MapPin, Phone, Mail, FileText, Activity, BadgeCheck,
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { CreateTenantPanel as CompleteTenantPanel } from './CreateTenantPanel'
import {
  AuthMe, fetchPlatformOverview, PlatformOverview,
  fetchPlatformTenantDetail, invitePlatformTenantUser, PlatformTenantDetail,
  PlatformTenantSummary, fetchServicePlans, ServicePlan, TenantCustomerType,
  TenantLifecycleStatus, updatePlatformTenantLifecycle,
} from '../../services/api'

const statusLabel: Record<string, string> = {
  PROVISIONING: 'Provisionando',
  TRIAL: 'Avaliação',
  ACTIVE: 'Ativo',
  PAUSED: 'Pausado',
  SUSPENDED: 'Suspenso',
  CANCELED: 'Cancelado',
  ARCHIVED: 'Arquivado',
}

const customerTypeLabel: Record<string, string> = {
  TEST: 'Teste', PILOT: 'Piloto', CUSTOMER: 'Cliente', INTERNAL: 'Interno',
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
      tenant.name.toLowerCase().includes(needle)
      || tenant.legal_name?.toLowerCase().includes(needle)
      || tenant.tax_id?.includes(needle.replace(/\D/g, ''))
      || tenant.slug.includes(needle)
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
          <button aria-label="Fechar menu do Dashem Control" className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 lg:hidden" onClick={() => setMobileNav(false)}><X className="h-5 w-5" /></button>
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
          <div className="flex min-w-0 items-center gap-3 sm:gap-4"><button aria-label="Abrir menu do Dashem Control" onClick={() => setMobileNav(true)} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-slate-200 lg:hidden"><Menu className="h-5 w-5" /></button><div className="min-w-0"><p className="truncate text-xs font-bold uppercase tracking-[.16em] text-slate-400">Dashem Control</p><h1 className="text-base font-black leading-tight tracking-tight sm:text-lg">Visão geral da plataforma</h1></div></div>
          <div className="flex shrink-0 items-center gap-2"><button aria-label="Nova organização" title="Nova organização" onClick={() => setCreateOpen(true)} className="flex h-11 min-w-11 items-center justify-center gap-2 rounded-xl bg-rose-600 px-3 text-sm font-black text-white shadow-lg shadow-rose-600/20 transition hover:bg-rose-700 sm:px-4"><Plus className="h-4 w-4" /><span className="hidden sm:inline">Nova organização</span></button><button onClick={signOut} title="Sair da plataforma" aria-label="Sair da plataforma" className="flex h-11 min-w-11 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm font-black text-slate-600 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700"><LogOut className="h-4 w-4" /><span className="hidden xl:inline">Sair</span></button></div>
        </header>

        <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
          <section className="relative overflow-hidden rounded-3xl bg-[#0b172a] p-7 text-white sm:p-9">
            <div className="absolute right-0 top-0 h-64 w-64 translate-x-1/3 -translate-y-1/3 rounded-full bg-emerald-500/10 blur-3xl" />
            <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between"><div className="max-w-3xl"><p className="text-xs font-black uppercase tracking-[.18em] text-rose-400">Control plane · uso interno Dashem</p><h2 className="mt-3 text-3xl font-black tracking-[-.03em]">Operação da plataforma</h2><p className="mt-3 max-w-2xl leading-7 text-slate-300">Cadastre, implante e acompanhe clientes, estruturas, contratos e acessos em um único registro operacional auditado.</p></div><div className={`flex min-w-56 items-center gap-3 rounded-2xl border p-4 ${error ? 'border-amber-400/20 bg-amber-400/10' : 'border-emerald-400/20 bg-emerald-400/10'}`}><span className={`h-2.5 w-2.5 rounded-full ${error ? 'bg-amber-400' : overview ? 'bg-emerald-400 shadow-[0_0_0_6px_rgba(52,211,153,.12)]' : 'animate-pulse bg-slate-400'}`} /><div><p className={`text-xs font-black uppercase tracking-wider ${error ? 'text-amber-300' : 'text-emerald-300'}`}>API do Console</p><p className="mt-1 font-bold">{error ? 'Requer atenção' : overview ? 'Conectada' : 'Verificando'}</p><p className="mt-1 text-[11px] text-slate-400">Saúde ampliada será exibida com telemetria real.</p></div></div></div>
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
                  <thead className="bg-slate-50 text-[11px] font-black uppercase tracking-[.12em] text-slate-400"><tr><th className="px-5 py-3">Cliente</th><th className="px-5 py-3">Classificação</th><th className="px-5 py-3">Ciclo de vida</th><th className="px-5 py-3">Estruturas</th><th className="px-5 py-3">Cadastro</th><th className="px-5 py-3" /></tr></thead>
                  <tbody className="divide-y divide-slate-100">{tenants.map(tenant => (
                    <tr key={tenant.id} onClick={() => setSelectedTenant(tenant)} tabIndex={0} role="button" onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') setSelectedTenant(tenant) }} className="group cursor-pointer hover:bg-slate-50 focus:bg-rose-50 focus:outline-none">
                      <td className="px-5 py-4"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 font-black text-slate-600">{tenant.name.charAt(0).toUpperCase()}</div><div><p className="font-black">{tenant.name}</p><p className="text-xs text-slate-400">{tenant.legal_name || tenant.slug}</p></div></div></td>
                      <td className="px-5 py-4"><p className="text-sm font-black text-slate-700">{customerTypeLabel[tenant.customer_type ?? 'TEST']}</p><p className="mt-1 font-mono text-xs text-slate-400">{tenant.tax_id || 'CNPJ não informado'}</p></td>
                      <td className="px-5 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${tenant.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : tenant.status === 'TRIAL' ? 'bg-sky-50 text-sky-700' : 'bg-slate-100 text-slate-600'}`}>{statusLabel[tenant.status] ?? tenant.status}</span></td>
                      <td className="px-5 py-4"><span className="inline-flex items-center gap-2 text-sm font-bold"><Store className="h-4 w-4 text-slate-400" />{tenant.store_count}</span></td>
                      <td className="px-5 py-4"><span className={`inline-flex items-center gap-1.5 text-xs font-black ${tenant.profile_complete ? 'text-emerald-700' : 'text-amber-700'}`}>{tenant.profile_complete ? <BadgeCheck className="h-4 w-4" /> : <FileText className="h-4 w-4" />}{tenant.profile_complete ? 'Completo' : 'Incompleto'}</span></td>
                      <td className="px-5 py-4 text-right"><button onClick={event => { event.stopPropagation(); setSelectedTenant(tenant) }} title="Detalhes do tenant" className="rounded-lg p-2 text-slate-400 hover:bg-white hover:text-rose-600"><ArrowRight className="h-4 w-4" /></button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </main>

      {createOpen && <CompleteTenantPanel onClose={() => setCreateOpen(false)} onCreated={async () => { setCreateOpen(false); await load() }} />}
      {selectedTenant && <TenantAccessPanel tenant={selectedTenant} onClose={() => setSelectedTenant(null)} onChanged={load} />}
    </div>
  )
}

function TenantAccessPanel({ tenant, onClose, onChanged }: { tenant: PlatformTenantSummary; onClose: () => void; onChanged: () => Promise<void> }) {
  const [detail, setDetail] = useState<PlatformTenantDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [nextStatus, setNextStatus] = useState<TenantLifecycleStatus>(tenant.status)
  const [lifecycleReason, setLifecycleReason] = useState('')
  const [updatingLifecycle, setUpdatingLifecycle] = useState(false)
  const loadDetail = useCallback(async () => {
    setLoading(true); setError(null)
    try { setDetail(await fetchPlatformTenantDetail(tenant.id)) }
    catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível carregar o tenant.') }
    finally { setLoading(false) }
  }, [tenant.id])
  useEffect(() => { loadDetail() }, [loadDetail])
  const contractualAdmins = detail?.accesses.filter(access => access.role === 'TENANT_OWNER' || access.role === 'OWNER') ?? []
  const primaryContact = detail?.contacts.find(contact => contact.is_primary && contact.is_active)
  const headquarters = detail?.stores.find(store => store.is_headquarters) ?? detail?.stores[0]
  const submitInvite = async (event: React.FormEvent) => {
    event.preventDefault(); setSending(true); setError(null); setNotice(null)
    try {
      const result = await invitePlatformTenantUser(tenant.id, { full_name: fullName.trim(), email: email.trim() })
      setNotice(result.delivery_status === 'ENVIADO' ? 'Convite enviado ao administrador contratual. O acesso será ativado após a criação da senha.' : 'Administrador contratual associado à identidade existente.')
      setFullName(''); setEmail(''); setInviteOpen(false); await loadDetail()
    } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível enviar o convite.') }
    finally { setSending(false) }
  }
  const changeLifecycle = async (event: React.FormEvent) => {
    event.preventDefault()
    setUpdatingLifecycle(true); setError(null); setNotice(null)
    try {
      await updatePlatformTenantLifecycle(tenant.id, nextStatus, lifecycleReason.trim())
      setNotice(`Estado alterado para ${statusLabel[nextStatus] ?? nextStatus}.`)
      setLifecycleReason('')
      await Promise.all([loadDetail(), onChanged()])
    } catch (err) { setError(err instanceof Error ? err.message : 'Não foi possível alterar o ciclo de vida.') }
    finally { setUpdatingLifecycle(false) }
  }
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/55 backdrop-blur-sm">
    <button aria-label="Fechar detalhes" className="absolute inset-0" onClick={onClose} />
    <section className="relative flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl">
      <header className="flex items-start justify-between border-b border-slate-200 p-6 sm:p-8">
        <div><p className="text-xs font-black uppercase tracking-[.16em] text-rose-600">Ficha do cliente</p><h2 className="mt-2 text-2xl font-black">{tenant.name}</h2><p className="mt-2 font-mono text-sm text-slate-500">{tenant.slug}</p></div>
        <button onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500"><X className="h-5 w-5" /></button>
      </header>
      <div className="flex-1 overflow-y-auto p-6 sm:p-8">
        {error && <p role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}
        {notice && <p className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-bold text-emerald-700">{notice}</p>}
        {loading ? <Loader2 className="mx-auto mt-12 h-7 w-7 animate-spin text-rose-600" /> : detail && <div className="space-y-6">
          {!detail.tenant.profile_complete && <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900"><strong>Cadastro incompleto.</strong> O registro foi preservado sem inventar dados. Complete os campos legais, o responsável e o endereço da matriz antes da ativação comercial.</div>}

          <section className="rounded-2xl border border-slate-200 p-5">
            <div className="flex items-center gap-2"><Building2 className="h-5 w-5 text-rose-600" /><h3 className="font-black">Dados da empresa</h3></div>
            <dl className="mt-5 grid gap-4 text-sm sm:grid-cols-2">
              <div><dt className="text-xs font-black uppercase text-slate-400">Razão social</dt><dd className="mt-1 font-bold">{detail.profile?.legal_name || 'Não informada'}</dd></div>
              <div><dt className="text-xs font-black uppercase text-slate-400">CNPJ</dt><dd className="mt-1 font-mono font-bold">{detail.profile?.tax_id || 'Não informado'}</dd></div>
              <div><dt className="text-xs font-black uppercase text-slate-400">Área de atuação</dt><dd className="mt-1 font-bold">{detail.profile?.industry || 'Não informada'}</dd></div>
              <div><dt className="text-xs font-black uppercase text-slate-400">Classificação</dt><dd className="mt-1 font-bold">{customerTypeLabel[detail.profile?.customer_type ?? 'TEST']}</dd></div>
              <div><dt className="text-xs font-black uppercase text-slate-400">Inscrição estadual</dt><dd className="mt-1 font-bold">{detail.profile?.state_registration || 'Não informada'}</dd></div>
              <div><dt className="text-xs font-black uppercase text-slate-400">Inscrição municipal</dt><dd className="mt-1 font-bold">{detail.profile?.municipal_registration || 'Não informada'}</dd></div>
            </dl>
          </section>

          <div className="grid gap-5 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-200 p-5"><div className="flex items-center gap-2"><Users className="h-5 w-5 text-rose-600" /><h3 className="font-black">Contato principal</h3></div>{primaryContact ? <div className="mt-4 space-y-2 text-sm"><p className="font-black">{primaryContact.full_name}</p><p className="text-slate-500">{primaryContact.job_title || 'Cargo não informado'}</p>{primaryContact.email && <p className="flex items-center gap-2"><Mail className="h-4 w-4 text-slate-400" />{primaryContact.email}</p>}{primaryContact.phone && <p className="flex items-center gap-2"><Phone className="h-4 w-4 text-slate-400" />{primaryContact.phone}</p>}</div> : <p className="mt-4 text-sm font-semibold text-amber-700">Responsável não cadastrado.</p>}</section>
            <section className="rounded-2xl border border-slate-200 p-5"><div className="flex items-center gap-2"><MapPin className="h-5 w-5 text-rose-600" /><h3 className="font-black">Matriz e filiais</h3></div>{headquarters ? <div className="mt-4 text-sm"><p className="font-black">{headquarters.name}</p><p className="mt-1 text-slate-500">{[headquarters.street, headquarters.street_number, headquarters.district, headquarters.city, headquarters.state].filter(Boolean).join(', ') || 'Endereço não informado'}</p><p className="mt-3 text-xs font-black text-slate-400">{detail.stores.length} estrutura(s) cadastrada(s)</p></div> : <p className="mt-4 text-sm font-semibold text-amber-700">Nenhuma estrutura cadastrada.</p>}</section>
          </div>

          <section className="rounded-2xl border border-slate-200 p-5"><div className="flex items-center gap-2"><FileText className="h-5 w-5 text-rose-600" /><h3 className="font-black">Plano e capacidades</h3></div><div className="mt-4 grid gap-4 sm:grid-cols-2"><div><p className="text-xs font-black uppercase text-slate-400">Plano</p><p className="mt-1 font-black">{detail.plan?.name || 'Ainda não definido'}</p></div><div><p className="text-xs font-black uppercase text-slate-400">Assinatura</p><p className="mt-1 font-black">{detail.subscription?.status || 'PENDENTE'}</p></div></div>{detail.plan && <p className="mt-4 text-xs font-semibold text-slate-500">Limites: {detail.plan.store_limit ?? '—'} unidades · {detail.plan.user_limit ?? '—'} usuários · {detail.plan.terminal_limit ?? '—'} terminais</p>}<div className="mt-4 flex flex-wrap gap-2">{detail.capabilities.length ? detail.capabilities.map(capability => <span key={capability.id} className={`rounded-full px-2.5 py-1 text-xs font-black ${capability.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{capability.key}</span>) : <span className="text-sm font-semibold text-slate-500">Nenhuma capacidade contratada.</span>}</div></section>

          <section className="rounded-2xl border border-slate-200 p-5"><div className="flex items-center gap-2"><Activity className="h-5 w-5 text-rose-600" /><h3 className="font-black">Ciclo operacional</h3></div><form onSubmit={changeLifecycle} className="mt-4 grid gap-3 sm:grid-cols-[180px_1fr_auto]"><select value={nextStatus} onChange={e => setNextStatus(e.target.value as TenantLifecycleStatus)} className="h-11 rounded-xl border border-slate-300 px-3 font-bold">{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input value={lifecycleReason} onChange={e => setLifecycleReason(e.target.value)} placeholder="Motivo obrigatório para auditoria" className="h-11 rounded-xl border border-slate-300 px-3 font-semibold" /><button disabled={updatingLifecycle || nextStatus === detail.tenant.status || lifecycleReason.trim().length < 3} className="h-11 rounded-xl bg-slate-950 px-4 text-sm font-black text-white disabled:opacity-40">{updatingLifecycle ? 'Aplicando…' : 'Aplicar'}</button></form></section>

          <section className="rounded-2xl border border-slate-200 p-5">
            <div className="flex items-center justify-between gap-4"><div><h3 className="font-black">Acessos do tenant</h3><p className="text-sm text-slate-500">Entrega inicial do administrador contratual.</p></div><button onClick={() => setInviteOpen(value => !value)} className="flex h-10 shrink-0 items-center gap-2 rounded-xl bg-rose-600 px-4 text-sm font-black text-white"><Plus className="h-4 w-4" />Conceder acesso</button></div>
            {inviteOpen && <form onSubmit={submitInvite} className="mt-5 space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-5"><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-black">Nome completo<input value={fullName} onChange={e => setFullName(e.target.value)} className="mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3 font-semibold" /></label><label className="text-sm font-black">E-mail corporativo<input type="email" value={email} onChange={e => setEmail(e.target.value)} className="mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3 font-semibold" /></label></div><button disabled={sending || fullName.trim().length < 2 || !email.includes('@')} className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#0b172a] font-black text-white disabled:opacity-40">{sending ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Enviar acesso ao administrador'}</button></form>}
            {contractualAdmins.length ? <div className="mt-5 space-y-3">{contractualAdmins.map(access => <article key={access.membership_id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-4"><div><p className="font-black">{access.full_name}</p><p className="text-sm text-slate-500">{access.email}</p></div><p className={`text-xs font-black ${access.status === 'ACTIVE' ? 'text-emerald-600' : 'text-amber-600'}`}>{access.status}</p></div></article>)}</div> : <p className="mt-5 text-sm font-semibold text-amber-700">Administrador ainda não indicado.</p>}
          </section>

          <section className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5"><div className="flex items-center gap-2"><Activity className="h-5 w-5 text-slate-500" /><h3 className="font-black">Saúde e métricas</h3></div><p className="mt-3 text-sm leading-6 text-slate-600">Séries temporais por cliente ainda não estão instrumentadas. Nenhum gráfico será mostrado até existirem medições reais de API, banco, worker, uso e falhas.</p></section>
        </div>}
      </div>
    </section>
  </div>
}
