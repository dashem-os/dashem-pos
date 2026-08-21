import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity, ArrowRight, Building2, CheckCircle2, LayoutGrid, Loader2,
  LogOut, Menu, Plus, Search, ShieldCheck, Sparkles, Store, Users, X,
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import {
  AuthMe, fetchPlatformOverview, PlatformOverview, provisionPlatformTenant,
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
    { label: 'Tenants', value: overview?.tenant_count, icon: Building2, hint: 'Total provisionado' },
    { label: 'Ativos', value: overview?.active_count, icon: CheckCircle2, hint: 'Operação liberada' },
    { label: 'Em avaliação', value: overview?.trial_count, icon: Sparkles, hint: 'Ciclo de trial' },
    { label: 'Leads abertos', value: overview?.lead_count, icon: Users, hint: 'Pipeline comercial' },
  ]

  return (
    <div className="min-h-screen bg-[#f4f6f9] text-slate-950 lg:grid lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className={`${mobileNav ? 'flex' : 'hidden'} fixed inset-y-0 left-0 z-40 w-[280px] flex-col bg-[#081222] p-5 text-white shadow-2xl lg:static lg:flex lg:w-auto lg:shadow-none`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-600 font-black shadow-lg shadow-rose-600/30">D</div><div><p className="font-black tracking-tight">DASHEM</p><p className="text-[10px] font-bold uppercase tracking-[.2em] text-slate-500">Platform Owner</p></div></div>
          <button className="lg:hidden" onClick={() => setMobileNav(false)}><X className="h-5 w-5" /></button>
        </div>
        <nav className="mt-10 space-y-2">
          <button className="flex w-full items-center gap-3 rounded-xl bg-white/10 px-4 py-3 text-left text-sm font-bold"><LayoutGrid className="h-5 w-5 text-rose-400" />Visão da plataforma</button>
          <button className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-bold text-slate-400"><Building2 className="h-5 w-5" />Tenants</button>
          <button className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-bold text-slate-400"><Users className="h-5 w-5" />Leads e acessos</button>
          <button className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-bold text-slate-400"><Activity className="h-5 w-5" />Operações e logs</button>
        </nav>
        <div className="mt-auto rounded-2xl border border-white/10 bg-white/[.04] p-4">
          <div className="flex items-center gap-2 text-xs font-bold text-emerald-400"><ShieldCheck className="h-4 w-4" />Sessão Owner protegida</div>
          <p className="mt-3 truncate text-sm font-bold text-white">{me.user?.full_name}</p>
          <p className="truncate text-xs text-slate-500">{me.user?.email}</p>
          <button onClick={signOut} className="mt-4 flex items-center gap-2 text-xs font-bold text-slate-400 hover:text-white"><LogOut className="h-4 w-4" />Encerrar sessão</button>
        </div>
      </aside>
      {mobileNav && <button aria-label="Fechar navegação" className="fixed inset-0 z-30 bg-slate-950/50 lg:hidden" onClick={() => setMobileNav(false)} />}

      <main className="min-w-0">
        <header className="flex h-20 items-center justify-between border-b border-slate-200 bg-white px-5 sm:px-8">
          <div className="flex items-center gap-4"><button onClick={() => setMobileNav(true)} className="rounded-xl border border-slate-200 p-2 lg:hidden"><Menu className="h-5 w-5" /></button><div><p className="text-xs font-bold uppercase tracking-[.16em] text-slate-400">Control plane</p><h1 className="text-lg font-black tracking-tight">Console Owner</h1></div></div>
          <button onClick={() => setCreateOpen(true)} className="flex h-11 items-center gap-2 rounded-xl bg-rose-600 px-4 text-sm font-black text-white shadow-lg shadow-rose-600/20 transition hover:bg-rose-700"><Plus className="h-4 w-4" /><span className="hidden sm:inline">Novo tenant</span></button>
        </header>

        <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
          <section className="relative overflow-hidden rounded-3xl bg-[#0b172a] p-7 text-white sm:p-9">
            <div className="absolute right-0 top-0 h-64 w-64 translate-x-1/3 -translate-y-1/3 rounded-full bg-rose-600/20 blur-3xl" />
            <div className="relative max-w-3xl"><div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-rose-600/15 text-rose-400"><Sparkles className="h-5 w-5" /></div><h2 className="text-3xl font-black tracking-[-.03em]">A plataforma começa pelo contexto certo.</h2><p className="mt-3 max-w-2xl leading-7 text-slate-300">Crie organizações isoladas, acompanhe o ciclo de vida e mantenha cada operação ligada ao tenant e à unidade corretos desde o primeiro registro.</p></div>
          </section>

          {error && <div role="alert" className="mt-6 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}<button onClick={load} className="ml-3 underline">Tentar novamente</button></div>}

          <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {statCards.map(({ label, value, icon: Icon, hint }) => (
              <article key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase tracking-[.12em] text-slate-400">{label}</p><p className="mt-3 text-3xl font-black">{overview ? String(value) : '—'}</p></div><div className="rounded-xl bg-slate-100 p-2.5 text-slate-700"><Icon className="h-5 w-5" /></div></div><p className="mt-4 text-xs font-semibold text-slate-400">{hint}</p></article>
            ))}
          </section>

          <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-col gap-4 border-b border-slate-200 p-5 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="font-black">Tenants da plataforma</h2><p className="mt-1 text-sm text-slate-500">Organizações e suas primeiras unidades operacionais.</p></div><label className="relative block sm:w-80"><Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-400" /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Buscar nome ou slug" className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-10 pr-4 text-sm font-semibold outline-none focus:border-rose-400" /></label></div>
            {!overview ? <div className="flex justify-center py-20"><Loader2 className="h-7 w-7 animate-spin text-rose-600" /></div> : tenants.length === 0 ? <div className="py-16 text-center"><Building2 className="mx-auto h-9 w-9 text-slate-300" /><p className="mt-4 font-black">Nenhum tenant encontrado</p><p className="mt-1 text-sm text-slate-500">Crie o primeiro ambiente operacional da plataforma.</p></div> : (
              <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left"><thead className="bg-slate-50 text-[11px] font-black uppercase tracking-[.12em] text-slate-400"><tr><th className="px-5 py-3">Organização</th><th className="px-5 py-3">Slug</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Unidades</th><th className="px-5 py-3">Criado em</th><th className="px-5 py-3" /></tr></thead><tbody className="divide-y divide-slate-100">{tenants.map(tenant => <tr key={tenant.id} className="group hover:bg-slate-50"><td className="px-5 py-4"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 font-black text-slate-600">{tenant.name.charAt(0).toUpperCase()}</div><div><p className="font-black">{tenant.name}</p><p className="text-xs text-slate-400">{tenant.id.slice(0, 8)}</p></div></div></td><td className="px-5 py-4 font-mono text-sm font-bold text-slate-600">{tenant.slug}</td><td className="px-5 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-black ${tenant.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : tenant.status === 'TRIAL' ? 'bg-sky-50 text-sky-700' : 'bg-slate-100 text-slate-600'}`}>{statusLabel[tenant.status] ?? tenant.status}</span></td><td className="px-5 py-4"><span className="inline-flex items-center gap-2 text-sm font-bold"><Store className="h-4 w-4 text-slate-400" />{tenant.store_count}</span></td><td className="px-5 py-4 text-sm font-semibold text-slate-500">{new Intl.DateTimeFormat('pt-BR').format(new Date(tenant.created_at))}</td><td className="px-5 py-4 text-right"><button title="Detalhes do tenant" className="rounded-lg p-2 text-slate-400 hover:bg-white hover:text-rose-600"><ArrowRight className="h-4 w-4" /></button></td></tr>)}</tbody></table></div>
            )}
          </section>
        </div>
      </main>

      {createOpen && <CreateTenantPanel onClose={() => setCreateOpen(false)} onCreated={async () => { setCreateOpen(false); await load() }} />}
    </div>
  )
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
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/55 backdrop-blur-sm"><button aria-label="Fechar criação" className="absolute inset-0" onClick={onClose} /><section className="relative flex h-full w-full max-w-xl flex-col bg-white shadow-2xl"><header className="flex items-start justify-between border-b border-slate-200 p-6 sm:p-8"><div><p className="text-xs font-black uppercase tracking-[.16em] text-rose-600">Provisionamento</p><h2 className="mt-2 text-2xl font-black tracking-tight">Novo tenant</h2><p className="mt-2 text-sm leading-6 text-slate-500">Cria a organização e sua primeira unidade em uma única transação auditada.</p></div><button onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500"><X className="h-5 w-5" /></button></header><form onSubmit={submit} className="flex flex-1 flex-col overflow-y-auto"><div className="space-y-6 p-6 sm:p-8"><label className="block text-sm font-black">Nome da organização<input autoFocus value={name} onChange={e => changeName(e.target.value)} placeholder="Ex.: Lanchonete Central" className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 font-semibold outline-none focus:border-rose-500 focus:ring-4 focus:ring-rose-100" /></label><label className="block text-sm font-black">Slug único<div className="mt-2 flex h-12 items-center rounded-xl border border-slate-300 bg-white px-4 focus-within:border-rose-500 focus-within:ring-4 focus-within:ring-rose-100"><span className="text-sm font-semibold text-slate-400">dashem /</span><input value={slug} onChange={e => { setSlugTouched(true); setSlug(normalizeSlug(e.target.value)) }} placeholder="lanchonete-central" className="min-w-0 flex-1 pl-2 font-mono text-sm font-bold outline-none" /></div><p className="mt-2 text-xs text-slate-400">Identificador permanente usado nas integrações e no contexto do tenant.</p></label><div className="h-px bg-slate-200" /><div><p className="font-black">Primeira unidade</p><p className="mt-1 text-sm text-slate-500">Todo tenant nasce com ao menos um site operacional.</p></div><div className="grid gap-4 sm:grid-cols-[1fr_160px]"><label className="block text-sm font-black">Nome da unidade<input value={storeName} onChange={e => setStoreName(e.target.value)} className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 font-semibold outline-none focus:border-rose-500" /></label><label className="block text-sm font-black">Código<input value={storeCode} onChange={e => setStoreCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''))} className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 font-mono font-bold outline-none focus:border-rose-500" /></label></div>{error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}</div><footer className="mt-auto flex gap-3 border-t border-slate-200 bg-slate-50 p-6 sm:p-8"><button type="button" onClick={onClose} className="h-12 flex-1 rounded-xl border border-slate-300 bg-white font-black text-slate-600">Cancelar</button><button disabled={!valid || loading} className="flex h-12 flex-[1.5] items-center justify-center gap-2 rounded-xl bg-rose-600 font-black text-white shadow-lg shadow-rose-600/20 disabled:opacity-40">{loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <><Plus className="h-5 w-5" />Criar tenant</>}</button></footer></form></section></div>
}
