import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowRight, Building2, CheckCircle2, FileWarning,
  HeartPulse, LayoutGrid, Loader2, LogOut, Menu, Plus, RefreshCw, Search,
  ShieldCheck, Store, Users, Workflow, X,
} from 'lucide-react'

import { useAuth } from '../../context/AuthContext'
import {
  AuthMe, ControlHealthComponent, ControlLead, fetchControlHealth, fetchControlLeads,
  fetchPlatformHealth, fetchPlatformOverview, HealthComponent,
  PlatformOverview, PlatformSystemHealth, PlatformTenantSummary,
} from '../../services/api'
import { CreateTenantPanel } from './CreateTenantPanel'
import { TenantWorkspace } from './TenantWorkspace'

type View = 'overview' | 'organizations' | 'operations' | 'health' | 'tenant'
type OrganizationFilter = 'ALL' | 'ACTIVE' | 'IMPLEMENTATION' | 'ATTENTION'

const statusLabel: Record<string, string> = {
  PROVISIONING: 'Provisionando', TRIAL: 'Avaliação', ACTIVE: 'Ativo', PAUSED: 'Pausado',
  SUSPENDED: 'Suspenso', CANCELED: 'Cancelado', ARCHIVED: 'Arquivado',
}
const typeLabel: Record<string, string> = { TEST: 'Teste', PILOT: 'Piloto', CUSTOMER: 'Cliente', INTERNAL: 'Interno' }

export function OwnerConsoleShell({ me }: { me: AuthMe }) {
  const { signOut } = useAuth()
  const [view, setView] = useState<View>('overview')
  const [filter, setFilter] = useState<OrganizationFilter>('ALL')
  const [overview, setOverview] = useState<PlatformOverview | null>(null)
  const [health, setHealth] = useState<PlatformSystemHealth | null>(null)
  const [selected, setSelected] = useState<PlatformTenantSummary | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    const results = await Promise.allSettled([fetchPlatformOverview(), fetchPlatformHealth()])
    if (results[0].status === 'fulfilled') setOverview(results[0].value)
    else setError(results[0].reason instanceof Error ? results[0].reason.message : 'Não foi possível carregar os clientes.')
    if (results[1].status === 'fulfilled') setHealth(results[1].value)
  }, [])
  useEffect(() => { load() }, [load])

  const navigate = (next: View, nextFilter: OrganizationFilter = 'ALL') => {
    setView(next); setFilter(nextFilter); setSelected(null); setMobileNav(false); window.scrollTo({ top: 0 })
  }
  const openTenant = (tenant: PlatformTenantSummary) => { setSelected(tenant); setView('tenant'); window.scrollTo({ top: 0 }) }
  const title = view === 'overview' ? 'Visão geral da plataforma' : view === 'organizations' ? 'Clientes e organizações' : view === 'operations' ? 'Operações do Control' : view === 'health' ? 'Saúde da plataforma' : selected?.name || 'Cliente'

  return <div className="min-h-screen bg-[#f4f6f9] text-[#022444] lg:grid lg:h-screen lg:grid-cols-[260px_minmax(0,1fr)] lg:overflow-hidden">
    <aside className={`${mobileNav ? 'flex' : 'hidden'} fixed inset-y-0 left-0 z-40 w-[280px] flex-col overflow-hidden bg-[#022444] p-5 text-white shadow-2xl lg:static lg:flex lg:h-screen lg:w-auto lg:shadow-none`}>
      <div className="flex items-center justify-between"><div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#E12120] font-black shadow-lg shadow-red-900/30">D</div><div><p className="font-black">DASHEM</p><p className="text-[10px] font-bold uppercase tracking-[.2em] text-slate-400">Control</p></div></div><button className="rounded-xl border border-white/10 p-2 lg:hidden" onClick={() => setMobileNav(false)}><X className="h-5 w-5" /></button></div>
      <nav className="mt-10 space-y-2">
        <NavButton active={view === 'overview'} icon={LayoutGrid} label="Visão geral" onClick={() => navigate('overview')} />
        <NavButton active={view === 'organizations' || view === 'tenant'} icon={Building2} label="Organizações" onClick={() => navigate('organizations')} />
        <NavButton active={view === 'operations'} icon={Workflow} label="Operações do Control" onClick={() => navigate('operations')} />
        <NavButton active={view === 'health'} icon={HeartPulse} label="Saúde da plataforma" onClick={() => navigate('health')} />
      </nav>
      <div className="mt-auto rounded-2xl border border-white/10 bg-white/[.04] p-4"><div className="flex items-center gap-2 text-xs font-bold text-emerald-400"><ShieldCheck className="h-4 w-4" />Sessão Owner protegida</div><p className="mt-3 truncate text-sm font-bold">{me.user?.full_name}</p><p className="truncate text-xs text-slate-500">{me.user?.email}</p><button onClick={signOut} className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-white/10 text-xs font-bold text-slate-300 hover:bg-white/10"><LogOut className="h-4 w-4" />Sair do Dashem Control</button></div>
    </aside>
    {mobileNav && <button className="fixed inset-0 z-30 bg-[#022444]/50 lg:hidden" onClick={() => setMobileNav(false)} />}

    <main className="min-w-0 lg:h-screen lg:overflow-y-auto"><header className="sticky top-0 z-20 flex h-20 items-center justify-between border-b border-slate-200 bg-white px-5 sm:px-8"><div className="flex items-center gap-3"><button className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 lg:hidden" onClick={() => setMobileNav(true)}><Menu className="h-5 w-5" /></button><div><p className="text-xs font-bold uppercase tracking-[.16em] text-slate-400">Dashem Control</p><h1 className="text-lg font-black">{title}</h1></div></div>{view === 'organizations' && <button onClick={() => setCreateOpen(true)} className="flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-4 text-sm font-black text-white shadow-lg shadow-red-900/20"><Plus className="h-4 w-4" /><span className="hidden sm:inline">Novo cliente</span></button>}</header>

      {error && <div className="mx-auto mt-5 max-w-[1500px] px-5 sm:px-8"><p className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}<button onClick={load} className="ml-3 underline">Tentar novamente</button></p></div>}
      {view === 'overview' && <OverviewView overview={overview} health={health} onOrganizations={nextFilter => navigate('organizations', nextFilter)} onHealth={() => navigate('health')} onTenant={openTenant} />}
      {view === 'organizations' && <OrganizationsView overview={overview} filter={filter} onFilter={setFilter} onTenant={openTenant} />}
      {view === 'operations' && <ControlOperationsView />}
      {view === 'health' && <SystemHealthView health={health} onRefresh={load} />}
      {view === 'tenant' && selected && <TenantWorkspace tenant={selected} onBack={() => navigate('organizations')} onChanged={load} />}
    </main>
    {createOpen && <CreateTenantPanel onClose={() => setCreateOpen(false)} onCreated={async () => { setCreateOpen(false); await load(); navigate('organizations') }} />}
  </div>
}

function NavButton({ active, icon: Icon, label, onClick }: { active: boolean; icon: React.ComponentType<{ className?: string }>; label: string; onClick: () => void }) { return <button onClick={onClick} className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-bold transition ${active ? 'bg-white/10 text-white' : 'text-slate-400 hover:bg-white/[.06] hover:text-white'}`}><Icon className={`h-5 w-5 ${active ? 'text-[#E12120]' : ''}`} />{label}</button> }

function OverviewView({ overview, health, onOrganizations, onHealth, onTenant }: { overview: PlatformOverview | null; health: PlatformSystemHealth | null; onOrganizations: (filter: OrganizationFilter) => void; onHealth: () => void; onTenant: (tenant: PlatformTenantSummary) => void }) {
  const incomplete = overview?.tenants.filter(item => !item.profile_complete).length ?? 0
  const cards = [
    { label: 'Clientes', value: overview?.tenant_count, hint: 'Todos os registros', icon: Building2, filter: 'ALL' as const },
    { label: 'Em operação', value: overview?.active_count, hint: 'Clientes ativos', icon: CheckCircle2, filter: 'ACTIVE' as const },
    { label: 'Em implantação', value: overview?.trial_count, hint: 'Avaliação e onboarding', icon: Users, filter: 'IMPLEMENTATION' as const },
    { label: 'Requer atenção', value: incomplete, hint: 'Cadastros incompletos', icon: FileWarning, filter: 'ATTENTION' as const },
  ]
  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8"><section className="rounded-3xl bg-[#022444] p-7 text-white sm:p-9"><div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between"><div><p className="text-xs font-black uppercase tracking-[.18em] text-[#E12120]">Control plane · dados em tempo real</p><h2 className="mt-3 text-3xl font-black">Operação da plataforma</h2><p className="mt-3 max-w-2xl leading-7 text-slate-300">Clientes, acessos, contratos e saúde operacional conectados aos registros reais do Dashem.</p></div><button onClick={onHealth} className={`min-w-60 rounded-2xl border p-4 text-left ${health?.status === 'HEALTHY' ? 'border-emerald-400/20 bg-emerald-400/10' : 'border-amber-400/20 bg-amber-400/10'}`}><p className="text-xs font-black uppercase text-slate-400">Saúde da plataforma</p><p className="mt-2 flex items-center gap-2 font-black">{health ? statusText(health.status) : 'Verificando…'}<ArrowRight className="h-4 w-4" /></p></button></div></section><section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{cards.map(card => <button key={card.label} onClick={() => onOrganizations(card.filter)} className="rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-[#E12120]/40 hover:shadow-md"><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase tracking-wider text-slate-400">{card.label}</p><p className="mt-3 text-3xl font-black">{overview ? card.value : '—'}</p></div><div className="rounded-xl bg-slate-100 p-2.5"><card.icon className="h-5 w-5" /></div></div><p className="mt-4 flex items-center justify-between text-xs font-semibold text-slate-500">{card.hint}<ArrowRight className="h-4 w-4" /></p></button>)}</section><section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-center justify-between"><div><h3 className="font-black">Clientes recentes</h3><p className="text-sm text-slate-500">Abra o workspace operacional completo.</p></div><button onClick={() => onOrganizations('ALL')} className="text-sm font-black text-[#E12120]">Ver todos</button></div><div className="mt-5 divide-y divide-slate-100">{overview?.tenants.slice(0, 5).map(tenant => <button key={tenant.id} onClick={() => onTenant(tenant)} className="flex w-full items-center justify-between py-4 text-left"><div><p className="font-black">{tenant.name}</p><p className="text-sm text-slate-500">{tenant.legal_name || tenant.slug}</p></div><div className="flex items-center gap-3"><span className="text-xs font-black text-slate-500">{statusLabel[tenant.status]}</span><ArrowRight className="h-4 w-4" /></div></button>)}{overview?.tenants.length === 0 && <p className="py-10 text-center text-sm text-slate-500">Nenhum cliente cadastrado.</p>}</div></section></div>
}

function OrganizationsView({ overview, filter, onFilter, onTenant }: { overview: PlatformOverview | null; filter: OrganizationFilter; onFilter: (filter: OrganizationFilter) => void; onTenant: (tenant: PlatformTenantSummary) => void }) {
  const [query, setQuery] = useState('')
  const tenants = useMemo(() => (overview?.tenants ?? []).filter(tenant => {
    const matchesFilter = filter === 'ALL' || (filter === 'ACTIVE' && tenant.status === 'ACTIVE') || (filter === 'IMPLEMENTATION' && ['PROVISIONING', 'TRIAL'].includes(tenant.status)) || (filter === 'ATTENTION' && (!tenant.profile_complete || ['PAUSED', 'SUSPENDED'].includes(tenant.status)))
    const needle = query.toLowerCase().trim(); const matchesQuery = !needle || tenant.name.toLowerCase().includes(needle) || tenant.legal_name?.toLowerCase().includes(needle) || tenant.tax_id?.includes(needle.replace(/\D/g, '')) || tenant.slug.includes(needle)
    return matchesFilter && matchesQuery
  }), [overview, filter, query])
  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8"><div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between"><div><p className="text-xs font-black uppercase tracking-wider text-[#E12120]">Operação de clientes</p><h2 className="mt-2 text-3xl font-black">Organizações</h2><p className="mt-2 text-slate-500">Cadastros, ciclo de vida, estruturas, acessos e contrato.</p></div><label className="relative block lg:w-96"><Search className="absolute left-4 top-3.5 h-4 w-4 text-slate-400" /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Nome, razão social, CPF, CNPJ ou identificador" className="h-11 w-full rounded-xl border border-slate-300 bg-white pl-11 pr-4 font-semibold" /></label></div><div className="mt-6 flex flex-wrap gap-2">{([['ALL', 'Todos'], ['ACTIVE', 'Em operação'], ['IMPLEMENTATION', 'Em implantação'], ['ATTENTION', 'Requer atenção']] as Array<[OrganizationFilter, string]>).map(([key, label]) => <button key={key} onClick={() => onFilter(key)} className={`rounded-full px-4 py-2 text-sm font-black ${filter === key ? 'bg-[#022444] text-white' : 'border border-slate-300 bg-white text-slate-600'}`}>{label}</button>)}</div><section className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">{!overview ? <Loader2 className="mx-auto my-20 h-7 w-7 animate-spin text-[#E12120]" /> : <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left"><thead className="bg-slate-50 text-xs font-black uppercase tracking-wider text-slate-400"><tr><th className="p-4">Cliente</th><th className="p-4">Classificação</th><th className="p-4">Ciclo</th><th className="p-4">Estruturas</th><th className="p-4">Cadastro</th><th className="p-4" /></tr></thead><tbody className="divide-y divide-slate-100">{tenants.map(tenant => <tr key={tenant.id} className="hover:bg-slate-50"><td className="p-4"><button onClick={() => onTenant(tenant)} className="text-left"><p className="font-black">{tenant.name}</p><p className="text-sm text-slate-500">{tenant.legal_name || tenant.slug}</p><p className="mt-1 font-mono text-xs text-slate-400">{tenant.tax_id || 'CPF/CNPJ não informado'}</p></button></td><td className="p-4 text-sm font-black">{typeLabel[tenant.customer_type ?? 'TEST']}</td><td className="p-4"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${tenant.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{statusLabel[tenant.status]}</span></td><td className="p-4"><span className="flex items-center gap-2 font-bold"><Store className="h-4 w-4" />{tenant.store_count}</span></td><td className="p-4"><span className={`text-xs font-black ${tenant.profile_complete ? 'text-emerald-700' : 'text-amber-700'}`}>{tenant.profile_complete ? 'COMPLETO' : 'INCOMPLETO'}</span></td><td className="p-4"><button onClick={() => onTenant(tenant)} className="flex items-center gap-2 rounded-xl bg-[#022444] px-3 py-2 text-xs font-black text-white">Abrir <ArrowRight className="h-4 w-4" /></button></td></tr>)}</tbody></table>{tenants.length === 0 && <p className="py-16 text-center text-sm font-semibold text-slate-500">Nenhum cliente corresponde ao filtro.</p>}</div>}</section></div>
}

function ControlOperationsView() {
  const [leads, setLeads] = useState<ControlLead[]>([])
  const [components, setComponents] = useState<ControlHealthComponent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    const [leadResult, healthResult] = await Promise.allSettled([fetchControlLeads(), fetchControlHealth()])
    if (leadResult.status === 'fulfilled') setLeads(leadResult.value)
    else setError(leadResult.reason instanceof Error ? leadResult.reason.message : 'Falha no funil comercial.')
    if (healthResult.status === 'fulfilled') setComponents(healthResult.value.components)
    else setError(current => current || (healthResult.reason instanceof Error ? healthResult.reason.message : 'Falha na instrumentação.'))
    setLoading(false)
  }, [])
  useEffect(() => { load() }, [load])
  if (loading) return <Loader2 className="mx-auto my-32 h-8 w-8 animate-spin text-[#E12120]" />
  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-black uppercase tracking-wider text-[#E12120]">Control plane</p><h2 className="mt-2 text-3xl font-black">Comercial, onboarding e instrumentação</h2><p className="mt-2 text-slate-500">Estado real do funil e das integrações. Ausência de telemetria nunca aparece como saudável.</p></div><button onClick={load} className="flex h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 text-sm font-black"><RefreshCw className="h-4 w-4" />Atualizar</button></div>{error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}<section className="mt-6 grid gap-4 xl:grid-cols-[1.15fr_.85fr]"><article className="overflow-hidden rounded-2xl border border-slate-200 bg-white"><div className="border-b border-slate-100 p-5"><h3 className="font-black">Funil comercial</h3><p className="text-sm text-slate-500">Leads persistidos e conversões vinculadas ao tenant.</p></div><div className="divide-y divide-slate-100">{leads.map(lead => <div key={lead.id} className="flex items-center justify-between gap-4 p-4"><div><p className="font-black">{lead.company_name}</p><p className="text-sm text-slate-500">{lead.contact_name}{lead.email ? ` · ${lead.email}` : ''}</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-black">{lead.status}</span></div>)}{leads.length === 0 && <p className="p-10 text-center text-sm text-slate-500">Nenhum lead cadastrado.</p>}</div></article><article className="rounded-2xl border border-slate-200 bg-white p-5"><h3 className="font-black">Instrumentação obrigatória</h3><p className="text-sm text-slate-500">Heartbeat e última evidência por componente.</p><div className="mt-4 space-y-3">{components.map(component => <div key={component.key} className="flex items-center justify-between rounded-xl border border-slate-200 p-3"><div><p className="font-bold">{component.label}</p><p className="text-xs text-slate-500">{component.last_seen_at ? `Último sinal ${new Date(component.last_seen_at).toLocaleString('pt-BR')}` : 'Sem heartbeat registrado'}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-black ${component.status === 'HEALTHY' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{component.status}</span></div>)}</div></article></section></div>
}

function SystemHealthView({ health, onRefresh }: { health: PlatformSystemHealth | null; onRefresh: () => Promise<void> }) {
  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8"><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase tracking-wider text-[#E12120]">Observabilidade</p><h2 className="mt-2 text-3xl font-black">Saúde da plataforma</h2><p className="mt-2 text-slate-500">Sondagens executadas agora; nenhum componente é marcado saudável sem evidência.</p></div><button onClick={onRefresh} className="flex h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 text-sm font-black"><RefreshCw className="h-4 w-4" />Atualizar</button></div>{!health ? <Loader2 className="mx-auto my-24 h-8 w-8 animate-spin text-[#E12120]" /> : <><section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Object.entries(health.totals).map(([key, value]) => <article key={key} className="rounded-2xl border border-slate-200 bg-white p-5"><p className="text-xs font-black uppercase text-slate-400">{totalLabel(key)}</p><p className="mt-3 text-3xl font-black">{value}</p></article>)}</section><section className="mt-6 grid gap-4 lg:grid-cols-2">{health.components.map(component => <ComponentHealth key={component.key} component={component} />)}</section><p className="mt-5 text-xs font-semibold text-slate-500">Verificado em {new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(health.checked_at))}</p></>}</div>
}

function ComponentHealth({ component }: { component: HealthComponent }) { const healthy = component.status === 'HEALTHY'; const attention = ['DEGRADED', 'UNKNOWN', 'NOT_CONFIGURED'].includes(component.status); return <article className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase text-slate-400">{component.key}</p><h3 className="mt-2 text-lg font-black">{component.label}</h3></div>{healthy ? <CheckCircle2 className="h-6 w-6 text-emerald-500" /> : <AlertTriangle className={`h-6 w-6 ${attention ? 'text-amber-500' : 'text-red-500'}`} />}</div><div className="mt-4 flex items-center gap-3"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${healthy ? 'bg-emerald-50 text-emerald-700' : attention ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700'}`}>{component.status}</span>{component.latency_ms !== undefined && <span className="text-sm font-bold text-slate-500">{component.latency_ms} ms</span>}</div><dl className="mt-4 grid gap-2 text-xs text-slate-500">{Object.entries(component.details).filter(([, value]) => value !== null).map(([key, value]) => <div key={key} className="flex justify-between gap-4"><dt>{key}</dt><dd className="font-mono font-bold text-slate-700">{String(value)}</dd></div>)}</dl></article> }

function statusText(status: string) { return status === 'HEALTHY' ? 'Saudável' : status === 'DEGRADED' ? 'Requer atenção' : 'Indisponível' }
function totalLabel(key: string) { return ({ tenants: 'Clientes', active_stores: 'Unidades ativas', active_users: 'Usuários ativos', open_cash_sessions: 'Caixas abertos', pending_outbox: 'Eventos pendentes', failed_outbox: 'Eventos com falha' } as Record<string, string>)[key] || key }
