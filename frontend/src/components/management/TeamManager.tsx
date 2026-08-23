import React, { useEffect, useState } from 'react'
import { Ban, Loader2, Plus, ShieldCheck, UserRoundCog } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'

export function TeamManager() {
  const { tenant, permissions } = usePos()
  const [members, setMembers] = useState<api.TeamMember[]>([])
  const [stores, setStores] = useState<api.Store[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState({ full_name: '', email: '', role: 'OPERATOR', store_id: '' })
  const canManage = permissions.includes('team.manage')
  const headers: Record<string, string> = tenant ? { 'X-Tenant-ID': tenant.id } : {}

  const load = async () => {
    if (!tenant) return
    setLoading(true); setError(null)
    try {
      const [team, tenantStores] = await Promise.all([api.fetchTeam(headers), api.fetchStores(tenant.id)])
      setMembers(team); setStores(tenantStores)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao carregar equipe.') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [tenant?.id])

  const invite = async (event: React.FormEvent) => {
    event.preventDefault(); if (!tenant) return
    setSaving(true); setError(null)
    try {
      await api.inviteTeamMember(headers, { ...form, store_id: form.store_id || undefined })
      setForm({ full_name: '', email: '', role: 'OPERATOR', store_id: '' }); setFormOpen(false); await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao convidar membro.') }
    finally { setSaving(false) }
  }

  const changeStatus = async (member: api.TeamMember, status: string) => {
    setSaving(true); setError(null)
    try {
      await api.updateTeamMember(headers, member.membership_id, {
        role: member.role, status, store_id: member.store_id,
        reason: `Alteração de acesso solicitada pelo Tenant Admin em ${new Date().toISOString()}`,
      })
      await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao alterar acesso.') }
    finally { setSaving(false) }
  }

  return <div className="space-y-5"><div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><p className="text-xs font-black uppercase tracking-[.16em] text-dashem-red">Administração do tenant</p><h2 className="mt-1 text-2xl font-black text-white">Equipe e acessos</h2><p className="mt-1 text-sm text-dashem-muted">Convites, papéis e escopos respeitam o limite contratado e são auditados.</p></div>{canManage && <button onClick={() => setFormOpen((value) => !value)} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-dashem-red px-5 text-sm font-black text-white"><Plus className="h-4 w-4" />Convidar membro</button>}</div>{error && <p className="rounded-xl border border-red-800/50 bg-red-950/40 p-4 text-sm font-bold text-red-300">{error}</p>}{formOpen && canManage && <form onSubmit={invite} className="grid gap-4 rounded-2xl border border-dashem-border bg-dashem-surface p-5 md:grid-cols-2 xl:grid-cols-4"><Field label="Nome" value={form.full_name} onChange={(value) => setForm((current) => ({ ...current, full_name: value }))} /><Field label="E-mail" type="email" value={form.email} onChange={(value) => setForm((current) => ({ ...current, email: value }))} /><label className="text-xs font-black uppercase text-dashem-muted">Papel<select value={form.role} onChange={(event) => setForm((current) => ({ ...current, role: event.target.value }))} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold text-white"><option value="ADMIN">Administrador</option><option value="MANAGER">Gerente</option><option value="AUDITOR">Auditor</option><option value="CASHIER">Caixa</option><option value="OPERATOR">Operador</option></select></label><label className="text-xs font-black uppercase text-dashem-muted">Unidade<select value={form.store_id} onChange={(event) => setForm((current) => ({ ...current, store_id: event.target.value }))} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold text-white"><option value="">Tenant inteiro</option>{stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}</select></label><button disabled={saving || !form.full_name || !form.email.includes('@') || ((form.role === 'CASHIER' || form.role === 'OPERATOR') && !form.store_id)} className="h-11 rounded-xl bg-white px-5 text-sm font-black text-slate-950 disabled:opacity-40 md:col-span-2 xl:col-span-4">{saving ? 'Enviando convite...' : 'Enviar convite seguro'}</button></form>}<section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface">{loading ? <div className="flex min-h-48 items-center justify-center text-sm font-bold text-dashem-muted"><Loader2 className="mr-3 h-5 w-5 animate-spin" />Carregando equipe...</div> : <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left"><thead className="border-b border-dashem-border bg-dashem-surface-elevated text-xs font-black uppercase text-dashem-muted"><tr><th className="p-4">Pessoa</th><th className="p-4">Papel</th><th className="p-4">Escopo</th><th className="p-4">Estado</th><th className="p-4">Ação</th></tr></thead><tbody className="divide-y divide-dashem-border">{members.map((member) => <tr key={member.membership_id}><td className="p-4"><p className="font-black text-white">{member.full_name}</p><p className="text-xs text-dashem-muted">{member.email}</p></td><td className="p-4 text-sm font-bold text-slate-200">{member.role}</td><td className="p-4 text-sm text-slate-300">{member.store_name || 'Tenant inteiro'}</td><td className="p-4"><span className="rounded-full bg-dashem-bg px-2 py-1 text-xs font-black text-slate-300">{member.status}</span></td><td className="p-4">{canManage && (member.status === 'ACTIVE' ? <button disabled={saving} onClick={() => changeStatus(member, 'SUSPENDED')} className="flex items-center gap-2 rounded-lg border border-amber-800 px-3 py-2 text-xs font-black text-amber-300"><Ban className="h-4 w-4" />Suspender</button> : <button disabled={saving} onClick={() => changeStatus(member, 'ACTIVE')} className="flex items-center gap-2 rounded-lg border border-emerald-800 px-3 py-2 text-xs font-black text-emerald-300"><ShieldCheck className="h-4 w-4" />Reativar</button>)}</td></tr>)}</tbody></table>{members.length === 0 && <p className="p-10 text-center text-sm font-bold text-dashem-muted">Nenhum membro encontrado.</p>}</div>}</section>{!canManage && <p className="flex items-center gap-2 text-sm font-semibold text-dashem-muted"><UserRoundCog className="h-4 w-4" />Seu perfil permite consulta, mas não alteração da equipe.</p>}</div>
}

function Field({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return <label className="text-xs font-black uppercase text-dashem-muted">{label}<input required type={type} value={value} onChange={(event) => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold normal-case text-white outline-none focus:border-dashem-red" /></label>
}
