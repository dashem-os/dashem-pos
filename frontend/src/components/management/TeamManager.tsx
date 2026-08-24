import React, { useEffect, useState } from 'react'
import { Ban, KeyRound, Loader2, Mail, Plus, RefreshCw as RotateCcwKey, ShieldCheck, UserRoundCog, X } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'

type AccessMode = 'EMAIL' | 'PIN'

const roleLabel: Record<string, string> = {
  OWNER: 'Responsável do tenant', TENANT_OWNER: 'Responsável do tenant', ADMIN: 'Administrador', MANAGER: 'Gerente',
  SUPERVISOR: 'Supervisor', CASHIER: 'Caixa', OPERATOR: 'Atendente',
}

export function TeamManager() {
  const { tenant, permissions } = usePos()
  const [members, setMembers] = useState<api.TeamMember[]>([])
  const [stores, setStores] = useState<api.Store[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [mode, setMode] = useState<AccessMode>('PIN')
  const [emailForm, setEmailForm] = useState({ full_name: '', email: '', role: 'MANAGER' })
  const [pinForm, setPinForm] = useState({ full_name: '', role: 'OPERATOR' as 'SUPERVISOR' | 'CASHIER' | 'OPERATOR', store_id: '', employee_code: '', pin: '', confirm_pin: '' })
  const [pinResetMember, setPinResetMember] = useState<api.TeamMember | null>(null)
  const [newPin, setNewPin] = useState('')
  const canManage = permissions.includes('team.manage')
  const headers: Record<string, string> = tenant ? { 'X-Tenant-ID': tenant.id } : {}

  const load = async () => {
    if (!tenant) return
    setLoading(true); setError(null)
    try {
      const [team, tenantStores] = await Promise.all([api.fetchTeam(headers), api.fetchStores(tenant.id)])
      setMembers(team); setStores(tenantStores)
      setPinForm(current => ({ ...current, store_id: current.store_id || (tenantStores.length === 1 ? tenantStores[0].id : '') }))
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao carregar equipe.') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [tenant?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); if (!tenant) return
    setSaving(true); setError(null)
    try {
      if (mode === 'EMAIL') {
        await api.inviteTeamMember(headers, emailForm)
        setEmailForm({ full_name: '', email: '', role: 'MANAGER' })
      } else {
        await api.createOperationalMember(headers, {
          full_name: pinForm.full_name, role: pinForm.role, store_id: pinForm.store_id,
          employee_code: pinForm.employee_code, pin: pinForm.pin,
        })
        setPinForm(current => ({ ...current, full_name: '', employee_code: '', pin: '', confirm_pin: '' }))
      }
      setFormOpen(false); await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao cadastrar acesso.') }
    finally { setSaving(false) }
  }

  const changeStatus = async (member: api.TeamMember, status: string) => {
    setSaving(true); setError(null)
    try {
      await api.updateTeamMember(headers, member.membership_id, {
        role: member.role, status, store_id: member.store_id,
        reason: `Alteração de acesso solicitada pela administração do tenant em ${new Date().toISOString()}`,
      })
      await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao alterar acesso.') }
    finally { setSaving(false) }
  }

  const resetPin = async (event: React.FormEvent) => {
    event.preventDefault(); if (!pinResetMember) return
    setSaving(true); setError(null)
    try {
      await api.resetOperationalPin(headers, pinResetMember.membership_id, { pin: newPin, reason: 'PIN redefinido pela administração do tenant' })
      setPinResetMember(null); setNewPin(''); await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao redefinir PIN.') }
    finally { setSaving(false) }
  }

  const pinValid = /^\d{4,8}$/.test(pinForm.pin) && pinForm.pin === pinForm.confirm_pin
  const emailCount = members.filter(member => member.access_mode === 'EMAIL').length
  const pinCount = members.filter(member => member.access_mode === 'PIN').length

  return <div className="space-y-5">
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><p className="text-xs font-black uppercase tracking-[.16em] text-dashem-red">Administração do tenant</p><h2 className="mt-1 text-2xl font-black text-white">Equipe e identidades</h2><p className="mt-1 max-w-2xl text-sm text-dashem-muted">Gestores entram por e-mail. Supervisor, caixa e atendente assumem a operação com código e PIN individual.</p></div>{canManage && <button onClick={() => setFormOpen(true)} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-dashem-red px-5 text-sm font-black text-white"><Plus className="h-4 w-4" />Adicionar pessoa</button>}</div>
    <div className="grid gap-3 sm:grid-cols-2"><Summary icon={<Mail />} value={emailCount} title="Acessos por e-mail" text="Administradores e gerentes" /><Summary icon={<KeyRound />} value={pinCount} title="Acessos por PIN" text="Supervisor, caixa e atendente" /></div>
    {error && <p className="rounded-xl border border-red-800/50 bg-red-950/40 p-4 text-sm font-bold text-red-300">{error}</p>}
    <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface">{loading ? <div className="flex min-h-48 items-center justify-center text-sm font-bold text-dashem-muted"><Loader2 className="mr-3 h-5 w-5 animate-spin" />Carregando equipe...</div> : <div className="overflow-x-auto"><table className="w-full min-w-[820px] text-left"><thead className="border-b border-dashem-border bg-dashem-surface-elevated text-xs font-black uppercase text-dashem-muted"><tr><th className="p-4">Pessoa</th><th className="p-4">Entrada</th><th className="p-4">Função</th><th className="p-4">Unidade</th><th className="p-4">Estado</th><th className="p-4">Ações</th></tr></thead><tbody className="divide-y divide-dashem-border">{members.map(member => <tr key={member.membership_id}><td className="p-4"><p className="font-black text-white">{member.full_name}</p><p className="text-xs text-dashem-muted">{member.email || `Código ${member.employee_code}`}</p></td><td className="p-4"><span className={`rounded-full px-2 py-1 text-[10px] font-black ${member.access_mode === 'PIN' ? 'bg-violet-950 text-violet-300' : 'bg-sky-950 text-sky-300'}`}>{member.access_mode === 'PIN' ? 'CÓDIGO + PIN' : 'E-MAIL'}</span></td><td className="p-4 text-sm font-bold text-slate-200">{roleLabel[member.role] || member.role}</td><td className="p-4 text-sm text-slate-300">{member.store_name || 'Tenant inteiro'}</td><td className="p-4"><span className="rounded-full bg-dashem-bg px-2 py-1 text-xs font-black text-slate-300">{member.status === 'ACTIVE' ? 'Ativo' : member.status === 'SUSPENDED' ? 'Suspenso' : member.status}</span></td><td className="p-4"><div className="flex gap-2">{canManage && member.access_mode === 'PIN' && <button disabled={saving} onClick={() => { setPinResetMember(member); setNewPin('') }} className="flex items-center gap-1 rounded-lg border border-violet-800 px-3 py-2 text-xs font-black text-violet-300"><RotateCcwKey className="h-4 w-4" />Novo PIN</button>}{canManage && (member.status === 'ACTIVE' ? <button disabled={saving} onClick={() => void changeStatus(member, 'SUSPENDED')} className="flex items-center gap-1 rounded-lg border border-amber-800 px-3 py-2 text-xs font-black text-amber-300"><Ban className="h-4 w-4" />Suspender</button> : <button disabled={saving} onClick={() => void changeStatus(member, 'ACTIVE')} className="flex items-center gap-1 rounded-lg border border-emerald-800 px-3 py-2 text-xs font-black text-emerald-300"><ShieldCheck className="h-4 w-4" />Reativar</button>)}</div></td></tr>)}</tbody></table>{members.length === 0 && <p className="p-10 text-center text-sm font-bold text-dashem-muted">Nenhuma pessoa cadastrada.</p>}</div>}</section>
    {!canManage && <p className="flex items-center gap-2 text-sm font-semibold text-dashem-muted"><UserRoundCog className="h-4 w-4" />Seu perfil permite consulta, mas não alteração da equipe.</p>}

    {formOpen && <Modal title="Adicionar pessoa" onClose={() => setFormOpen(false)}><div className="grid grid-cols-2 rounded-xl bg-dashem-bg p-1"><button onClick={() => setMode('PIN')} className={`h-10 rounded-lg text-xs font-black ${mode === 'PIN' ? 'bg-white text-slate-950' : 'text-dashem-muted'}`}>Operação · PIN</button><button onClick={() => setMode('EMAIL')} className={`h-10 rounded-lg text-xs font-black ${mode === 'EMAIL' ? 'bg-white text-slate-950' : 'text-dashem-muted'}`}>Gestão · e-mail</button></div><form onSubmit={submit} className="mt-5 space-y-4">{mode === 'EMAIL' ? <><Field label="Nome completo" value={emailForm.full_name} onChange={value => setEmailForm(current => ({ ...current, full_name: value }))} /><Field label="E-mail corporativo" type="email" value={emailForm.email} onChange={value => setEmailForm(current => ({ ...current, email: value }))} /><Select label="Função" value={emailForm.role} onChange={value => setEmailForm(current => ({ ...current, role: value }))} options={[['MANAGER','Gerente'],['ADMIN','Administrador']]} /><Info>Um convite seguro será enviado por e-mail. Este perfil acessa a Gestão, nunca entra por PIN.</Info></> : <><Field label="Nome completo" value={pinForm.full_name} onChange={value => setPinForm(current => ({ ...current, full_name: value }))} /><div className="grid gap-4 sm:grid-cols-2"><Select label="Função" value={pinForm.role} onChange={value => setPinForm(current => ({ ...current, role: value as typeof pinForm.role }))} options={[['OPERATOR','Atendente'],['CASHIER','Caixa'],['SUPERVISOR','Supervisor']]} /><Select label="Unidade" value={pinForm.store_id} onChange={value => setPinForm(current => ({ ...current, store_id: value }))} options={stores.map(store => [store.id, store.name])} /></div><Field label="Código do colaborador" value={pinForm.employee_code} onChange={value => setPinForm(current => ({ ...current, employee_code: value.toUpperCase() }))} /><div className="grid gap-4 sm:grid-cols-2"><Field label="PIN (4 a 8 números)" type="password" value={pinForm.pin} onChange={value => setPinForm(current => ({ ...current, pin: value.replace(/\D/g, '').slice(0, 8) }))} /><Field label="Confirmar PIN" type="password" value={pinForm.confirm_pin} onChange={value => setPinForm(current => ({ ...current, confirm_pin: value.replace(/\D/g, '').slice(0, 8) }))} /></div><Info>Sem e-mail fictício: o colaborador fica vinculado à unidade e cada ação registra sua identidade real.</Info></>}<button disabled={saving || !emailForm.full_name && mode === 'EMAIL' || mode === 'EMAIL' && !emailForm.email.includes('@') || mode === 'PIN' && (!pinForm.full_name || !pinForm.store_id || pinForm.employee_code.length < 3 || !pinValid)} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-white disabled:opacity-40">{saving ? 'Salvando...' : mode === 'PIN' ? 'Criar acesso operacional' : 'Enviar convite de gestão'}</button></form></Modal>}
    {pinResetMember && <Modal title={`Novo PIN · ${pinResetMember.full_name}`} onClose={() => setPinResetMember(null)}><form onSubmit={resetPin} className="space-y-4"><Info>O PIN anterior deixará de funcionar imediatamente. Informe o novo PIN ao colaborador por um canal seguro.</Info><Field label="Novo PIN (4 a 8 números)" type="password" value={newPin} onChange={value => setNewPin(value.replace(/\D/g, '').slice(0, 8))} /><button disabled={saving || !/^\d{4,8}$/.test(newPin)} className="h-12 w-full rounded-xl bg-dashem-red font-black text-white disabled:opacity-40">Redefinir PIN</button></form></Modal>}
  </div>
}

function Summary({ icon, value, title, text }: { icon: React.ReactNode; value: number; title: string; text: string }) { return <div className="flex items-center gap-4 rounded-2xl border border-dashem-border bg-dashem-surface p-4"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-dashem-bg text-dashem-red">{icon}</div><div><p className="text-xl font-black text-white">{value}</p><p className="text-sm font-black text-slate-200">{title}</p><p className="text-xs text-dashem-muted">{text}</p></div></div> }
function Field({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) { return <label className="block text-xs font-black uppercase text-dashem-muted">{label}<input required type={type} value={value} onChange={event => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold normal-case text-white outline-none focus:border-dashem-red" /></label> }
function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[][] }) { return <label className="block text-xs font-black uppercase text-dashem-muted">{label}<select required value={value} onChange={event => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold normal-case text-white"><option value="">Selecione...</option>{options.map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label> }
function Info({ children }: { children: React.ReactNode }) { return <p className="rounded-xl border border-sky-900/60 bg-sky-950/30 p-3 text-xs leading-5 text-sky-200">{children}</p> }
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4"><section className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-dashem-border bg-dashem-surface p-6 shadow-2xl"><div className="flex items-center justify-between"><h3 className="text-xl font-black text-white">{title}</h3><button onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-xl border border-dashem-border text-dashem-muted"><X className="h-5 w-5" /></button></div>{children}</section></div> }
