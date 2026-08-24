import React, { useEffect, useMemo, useState } from 'react'
import { Ban, Briefcase, KeyRound, Loader2, Mail, Pencil, Plus, RefreshCw as RotateCcwKey, Search, ShieldCheck, UserRoundCog, X } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'

type AccessMode = 'EMAIL' | 'PIN'
type EmployeeSource = 'EXISTING' | 'NEW'
type View = 'ACCESS' | 'EMPLOYEES'

const roleLabel: Record<string, string> = {
  OWNER: 'Responsável do tenant', TENANT_OWNER: 'Responsável do tenant', ADMIN: 'Administrador', MANAGER: 'Gerente',
  SUPERVISOR: 'Supervisor', CASHIER: 'Caixa', OPERATOR: 'Atendente',
}

const blankEmployee = (): api.EmployeeInput => ({
  employee_number: '', full_name: '', preferred_name: '', tax_id: '', email: '', phone: '',
  job_title: '', department: '', hire_date: '', home_store_id: '', postal_code: '', street: '',
  street_number: '', address_complement: '', district: '', city: '', state: '',
  emergency_contact_name: '', emergency_contact_phone: '', status: 'ACTIVE', notes: '',
})

function strongPin(pin: string) {
  if (!/^\d{4,8}$/.test(pin) || new Set(pin).size === 1) return false
  return !'01234567890123456789'.includes(pin) && !'98765432109876543210'.includes(pin)
}

export function TeamManager() {
  const { tenant, permissions } = usePos()
  const [members, setMembers] = useState<api.TeamMember[]>([])
  const [employees, setEmployees] = useState<api.Employee[]>([])
  const [stores, setStores] = useState<api.Store[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('ACCESS')
  const [formOpen, setFormOpen] = useState(false)
  const [mode, setMode] = useState<AccessMode>('PIN')
  const [employeeSource, setEmployeeSource] = useState<EmployeeSource>('EXISTING')
  const [employeeSearch, setEmployeeSearch] = useState('')
  const [employeeForm, setEmployeeForm] = useState<api.EmployeeInput>(blankEmployee)
  const [editingEmployee, setEditingEmployee] = useState<api.Employee | null>(null)
  const [emailForm, setEmailForm] = useState({ full_name: '', email: '', role: 'MANAGER' })
  const [pinForm, setPinForm] = useState({ employee_id: '', role: 'OPERATOR' as 'SUPERVISOR' | 'CASHIER' | 'OPERATOR', store_id: '', employee_code: '', pin: '', confirm_pin: '' })
  const [pinResetMember, setPinResetMember] = useState<api.TeamMember | null>(null)
  const [newPin, setNewPin] = useState('')
  const canManage = permissions.includes('team.manage')
  const headers: Record<string, string> = tenant ? { 'X-Tenant-ID': tenant.id } : {}

  const load = async () => {
    if (!tenant) return
    setLoading(true); setError(null)
    try {
      const [team, people, tenantStores] = await Promise.all([
        api.fetchTeam(headers), api.fetchEmployees(headers), api.fetchStores(tenant.id),
      ])
      setMembers(team); setEmployees(people); setStores(tenantStores)
      const onlyStore = tenantStores.length === 1 ? tenantStores[0].id : ''
      setPinForm(current => ({ ...current, store_id: current.store_id || onlyStore }))
      setEmployeeForm(current => ({ ...current, home_store_id: current.home_store_id || onlyStore }))
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao carregar equipe.') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [tenant?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const availableEmployees = useMemo(() => {
    const term = employeeSearch.trim().toLocaleLowerCase('pt-BR')
    return employees.filter(employee => {
      const hasAccess = members.some(member => member.employee_id === employee.id && member.store_id === pinForm.store_id)
      const matches = !term || `${employee.full_name} ${employee.preferred_name || ''} ${employee.employee_number}`.toLocaleLowerCase('pt-BR').includes(term)
      return employee.status === 'ACTIVE' && !hasAccess && matches
    })
  }, [employeeSearch, employees, members, pinForm.store_id])

  const selectEmployee = (employeeId: string) => {
    const employee = employees.find(item => item.id === employeeId)
    setPinForm(current => ({
      ...current, employee_id: employeeId,
      employee_code: employee ? employee.employee_number.replace(/[^A-Z0-9_-]/gi, '').toUpperCase().slice(0, 20) : '',
      store_id: employee?.home_store_id || current.store_id,
    }))
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); if (!tenant) return
    setSaving(true); setError(null)
    try {
      if (mode === 'EMAIL') {
        await api.inviteTeamMember(headers, emailForm)
        setEmailForm({ full_name: '', email: '', role: 'MANAGER' })
      } else {
        let employeeId = pinForm.employee_id
        if (employeeSource === 'NEW') {
          const employee = await api.createEmployee(headers, { ...employeeForm, home_store_id: pinForm.store_id })
          employeeId = employee.id
        }
        await api.createOperationalMember(headers, {
          employee_id: employeeId, role: pinForm.role, store_id: pinForm.store_id,
          employee_code: pinForm.employee_code, pin: pinForm.pin,
        })
        setPinForm(current => ({ ...current, employee_id: '', employee_code: '', pin: '', confirm_pin: '' }))
        setEmployeeForm(blankEmployee())
      }
      setFormOpen(false); await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao cadastrar acesso.') }
    finally { setSaving(false) }
  }

  const saveEmployee = async (event: React.FormEvent) => {
    event.preventDefault(); if (!editingEmployee) return
    setSaving(true); setError(null)
    try {
      await api.updateEmployee(headers, editingEmployee.id, employeeForm)
      setEditingEmployee(null); setEmployeeForm(blankEmployee()); await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao atualizar funcionário.') }
    finally { setSaving(false) }
  }

  const openEmployeeEdit = (employee: api.Employee) => {
    const { id: _id, tenant_id: _tenant, user_id: _user, created_at: _created, updated_at: _updated, ...input } = employee
    setEmployeeForm(input); setEditingEmployee(employee)
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

  const pinValid = strongPin(pinForm.pin) && pinForm.pin === pinForm.confirm_pin
  const selectedEmployeeValid = employeeSource === 'EXISTING' ? Boolean(pinForm.employee_id) : Boolean(employeeForm.full_name && employeeForm.employee_number)
  const emailCount = members.filter(member => member.access_mode === 'EMAIL').length
  const pinCount = members.filter(member => member.access_mode === 'PIN').length

  return <div className="space-y-5">
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><p className="text-xs font-black uppercase tracking-[.16em] text-dashem-red">Administração do tenant</p><h2 className="mt-1 text-2xl font-black text-white">Equipe e identidades</h2><p className="mt-1 max-w-3xl text-sm text-dashem-muted">O cadastro do funcionário existe antes do acesso. Gestores entram por e-mail; equipe operacional assume o turno com código e PIN.</p></div>{canManage && <button onClick={() => setFormOpen(true)} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-dashem-red px-5 text-sm font-black text-white"><Plus className="h-4 w-4" />Conceder acesso</button>}</div>
    <div className="grid gap-3 sm:grid-cols-3"><Summary icon={<Briefcase />} value={employees.length} title="Funcionários" text="Fichas cadastrais do tenant" /><Summary icon={<Mail />} value={emailCount} title="Acessos por e-mail" text="Administradores e gerentes" /><Summary icon={<KeyRound />} value={pinCount} title="Acessos por PIN" text="Supervisor, caixa e atendente" /></div>
    <div className="inline-flex rounded-xl border border-dashem-border bg-dashem-surface p-1"><Tab active={view === 'ACCESS'} onClick={() => setView('ACCESS')}>Acessos</Tab><Tab active={view === 'EMPLOYEES'} onClick={() => setView('EMPLOYEES')}>Cadastro de funcionários</Tab></div>
    {error && <p className="rounded-xl border border-red-800/50 bg-red-950/40 p-4 text-sm font-bold text-red-300">{error}</p>}
    {view === 'ACCESS' ? <AccessTable members={members} loading={loading} saving={saving} canManage={canManage} changeStatus={changeStatus} resetPin={(member) => { setPinResetMember(member); setNewPin('') }} /> : <EmployeeTable employees={employees} stores={stores} loading={loading} canManage={canManage} edit={openEmployeeEdit} />}
    {!canManage && <p className="flex items-center gap-2 text-sm font-semibold text-dashem-muted"><UserRoundCog className="h-4 w-4" />Seu perfil permite consulta, mas não alteração da equipe.</p>}

    {formOpen && <Modal title="Conceder acesso" onClose={() => setFormOpen(false)}><div className="grid grid-cols-2 rounded-xl bg-dashem-bg p-1"><Tab active={mode === 'PIN'} onClick={() => setMode('PIN')}>Operação · PIN</Tab><Tab active={mode === 'EMAIL'} onClick={() => setMode('EMAIL')}>Gestão · e-mail</Tab></div><form onSubmit={submit} className="mt-5 space-y-4">{mode === 'EMAIL' ? <><Field label="Nome completo" value={emailForm.full_name} onChange={value => setEmailForm(current => ({ ...current, full_name: value }))} /><Field label="E-mail corporativo" type="email" value={emailForm.email} onChange={value => setEmailForm(current => ({ ...current, email: value }))} /><Select label="Função" value={emailForm.role} onChange={value => setEmailForm(current => ({ ...current, role: value }))} options={[["MANAGER","Gerente"],["ADMIN","Administrador"]]} /><Info>O convite por e-mail dá acesso à Gestão. Ao abrir o PDV, esse gestor continua autenticado e entra diretamente.</Info></> : <><div className="grid grid-cols-2 rounded-xl border border-dashem-border p-1"><Tab active={employeeSource === 'EXISTING'} onClick={() => setEmployeeSource('EXISTING')}>Buscar funcionário</Tab><Tab active={employeeSource === 'NEW'} onClick={() => setEmployeeSource('NEW')}>Novo cadastro</Tab></div>{employeeSource === 'EXISTING' ? <div className="space-y-4"><Field label="Buscar por nome ou matrícula" value={employeeSearch} onChange={setEmployeeSearch} icon={<Search className="h-4 w-4" />} /><Select label="Funcionário cadastrado" value={pinForm.employee_id} onChange={selectEmployee} options={availableEmployees.map(employee => [employee.id, `${employee.full_name} · ${employee.employee_number}`])} /></div> : <EmployeeFields value={employeeForm} onChange={setEmployeeForm} stores={stores} compact={false} />}<div className="grid gap-4 sm:grid-cols-2"><Select label="Função operacional" value={pinForm.role} onChange={value => setPinForm(current => ({ ...current, role: value as typeof pinForm.role }))} options={[["OPERATOR","Atendente"],["CASHIER","Caixa"],["SUPERVISOR","Supervisor"]]} /><Select label="Unidade do acesso" value={pinForm.store_id} onChange={value => setPinForm(current => ({ ...current, store_id: value, employee_id: '' }))} options={stores.map(store => [store.id, store.name])} /></div><Field label="Código de acesso do colaborador" value={pinForm.employee_code} onChange={value => setPinForm(current => ({ ...current, employee_code: value.replace(/[^A-Z0-9_-]/gi, '').toUpperCase().slice(0, 20) }))} /><div className="grid gap-4 sm:grid-cols-2"><Field label="PIN (4 a 8 números)" type="password" value={pinForm.pin} onChange={value => setPinForm(current => ({ ...current, pin: value.replace(/\D/g, '').slice(0, 8) }))} /><Field label="Confirmar PIN" type="password" value={pinForm.confirm_pin} onChange={value => setPinForm(current => ({ ...current, confirm_pin: value.replace(/\D/g, '').slice(0, 8) }))} /></div><Info>Use um PIN não repetido e não sequencial. A ficha do funcionário e sua credencial são registros separados e auditáveis.</Info></>}<button disabled={saving || mode === 'EMAIL' && (!emailForm.full_name || !emailForm.email.includes('@')) || mode === 'PIN' && (!selectedEmployeeValid || !pinForm.store_id || pinForm.employee_code.length < 3 || !pinValid)} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-white disabled:opacity-40">{saving ? 'Salvando...' : mode === 'PIN' ? 'Conceder acesso operacional' : 'Enviar convite de gestão'}</button></form></Modal>}
    {editingEmployee && <Modal title={`Ficha · ${editingEmployee.full_name}`} onClose={() => setEditingEmployee(null)}><form onSubmit={saveEmployee} className="mt-5 space-y-4"><EmployeeFields value={employeeForm} onChange={setEmployeeForm} stores={stores} compact={false} /><button disabled={saving || !employeeForm.full_name || !employeeForm.employee_number} className="h-12 w-full rounded-xl bg-dashem-red font-black text-white disabled:opacity-40">{saving ? 'Salvando...' : 'Salvar ficha cadastral'}</button></form></Modal>}
    {pinResetMember && <Modal title={`Novo PIN · ${pinResetMember.full_name}`} onClose={() => setPinResetMember(null)}><form onSubmit={resetPin} className="space-y-4"><Info>O PIN anterior deixará de funcionar imediatamente. Use um PIN não repetido e não sequencial.</Info><Field label="Novo PIN (4 a 8 números)" type="password" value={newPin} onChange={value => setNewPin(value.replace(/\D/g, '').slice(0, 8))} /><button disabled={saving || !strongPin(newPin)} className="h-12 w-full rounded-xl bg-dashem-red font-black text-white disabled:opacity-40">Redefinir PIN</button></form></Modal>}
  </div>
}

function AccessTable({ members, loading, saving, canManage, changeStatus, resetPin }: { members: api.TeamMember[]; loading: boolean; saving: boolean; canManage: boolean; changeStatus: (member: api.TeamMember, status: string) => Promise<void>; resetPin: (member: api.TeamMember) => void }) { return <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface">{loading ? <Loading /> : <div className="overflow-x-auto"><table className="w-full min-w-[820px] text-left"><thead className="border-b border-dashem-border bg-dashem-surface-elevated text-xs font-black uppercase text-dashem-muted"><tr><th className="p-4">Pessoa</th><th className="p-4">Entrada</th><th className="p-4">Função</th><th className="p-4">Unidade</th><th className="p-4">Estado</th><th className="p-4">Ações</th></tr></thead><tbody className="divide-y divide-dashem-border">{members.map(member => <tr key={member.membership_id}><td className="p-4"><p className="font-black text-white">{member.full_name}</p><p className="text-xs text-dashem-muted">{member.email || `Código ${member.employee_code}`}</p></td><td className="p-4"><AccessBadge mode={member.access_mode} /></td><td className="p-4 text-sm font-bold text-slate-200">{roleLabel[member.role] || member.role}</td><td className="p-4 text-sm text-slate-300">{member.store_name || 'Tenant inteiro'}</td><td className="p-4"><span className="rounded-full bg-dashem-bg px-2 py-1 text-xs font-black text-slate-300">{member.status === 'ACTIVE' ? 'Ativo' : member.status === 'SUSPENDED' ? 'Suspenso' : member.status}</span></td><td className="p-4"><div className="flex gap-2">{canManage && member.access_mode === 'PIN' && <Action onClick={() => resetPin(member)} disabled={saving} tone="violet"><RotateCcwKey className="h-4 w-4" />Novo PIN</Action>}{canManage && (member.status === 'ACTIVE' ? <Action onClick={() => void changeStatus(member, 'SUSPENDED')} disabled={saving} tone="amber"><Ban className="h-4 w-4" />Suspender</Action> : <Action onClick={() => void changeStatus(member, 'ACTIVE')} disabled={saving} tone="emerald"><ShieldCheck className="h-4 w-4" />Reativar</Action>)}</div></td></tr>)}</tbody></table>{members.length === 0 && <Empty text="Nenhum acesso concedido." />}</div>}</section> }

function EmployeeTable({ employees, stores, loading, canManage, edit }: { employees: api.Employee[]; stores: api.Store[]; loading: boolean; canManage: boolean; edit: (employee: api.Employee) => void }) { return <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface">{loading ? <Loading /> : <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left"><thead className="border-b border-dashem-border bg-dashem-surface-elevated text-xs font-black uppercase text-dashem-muted"><tr><th className="p-4">Funcionário</th><th className="p-4">Cargo / setor</th><th className="p-4">Lotação</th><th className="p-4">Contato</th><th className="p-4">Estado</th><th className="p-4">Ação</th></tr></thead><tbody className="divide-y divide-dashem-border">{employees.map(employee => <tr key={employee.id}><td className="p-4"><p className="font-black text-white">{employee.full_name}</p><p className="text-xs text-dashem-muted">Matrícula {employee.employee_number}{employee.tax_id ? ` · CPF final ${employee.tax_id.slice(-4)}` : ''}</p></td><td className="p-4 text-sm text-slate-300">{employee.job_title || 'Cargo pendente'}<p className="text-xs text-dashem-muted">{employee.department || 'Setor pendente'}</p></td><td className="p-4 text-sm text-slate-300">{stores.find(store => store.id === employee.home_store_id)?.name || 'Tenant inteiro'}</td><td className="p-4 text-sm text-slate-300">{employee.phone || employee.email || 'Não informado'}</td><td className="p-4 text-xs font-black text-slate-300">{employee.status === 'ACTIVE' ? 'Ativo' : employee.status}</td><td className="p-4">{canManage && <Action onClick={() => edit(employee)} tone="neutral"><Pencil className="h-4 w-4" />Editar ficha</Action>}</td></tr>)}</tbody></table>{employees.length === 0 && <Empty text="Nenhum funcionário cadastrado. Conceda um acesso e escolha Novo cadastro." />}</div>}</section> }

function EmployeeFields({ value, onChange, stores, compact }: { value: api.EmployeeInput; onChange: (value: api.EmployeeInput) => void; stores: api.Store[]; compact: boolean }) { const set = (key: keyof api.EmployeeInput, fieldValue: string) => onChange({ ...value, [key]: fieldValue }); return <div className="space-y-4"><div className="grid gap-4 sm:grid-cols-2"><Field label="Nome completo" value={value.full_name} onChange={v => set('full_name', v)} /><Field label="Nome preferido" value={value.preferred_name || ''} onChange={v => set('preferred_name', v)} required={false} /><Field label="Matrícula" value={value.employee_number} onChange={v => set('employee_number', v.toUpperCase())} /><Field label="CPF" value={value.tax_id || ''} onChange={v => set('tax_id', v.replace(/\D/g, '').slice(0, 11))} required={false} /></div><div className="grid gap-4 sm:grid-cols-4"><Field label="Cargo" value={value.job_title || ''} onChange={v => set('job_title', v)} required={false} /><Field label="Setor" value={value.department || ''} onChange={v => set('department', v)} required={false} /><Field label="Admissão" type="date" value={value.hire_date || ''} onChange={v => set('hire_date', v)} required={false} /><Select label="Situação" value={value.status} onChange={v => set('status', v)} options={[["ACTIVE","Ativo"],["ON_LEAVE","Afastado"],["INACTIVE","Inativo"],["TERMINATED","Desligado"]]} /></div><div className="grid gap-4 sm:grid-cols-3"><Select label="Lotação principal" value={value.home_store_id || ''} onChange={v => set('home_store_id', v)} options={stores.map(store => [store.id, store.name])} required={false} /><Field label="Telefone" value={value.phone || ''} onChange={v => set('phone', v)} required={false} /><Field label="E-mail de contato" type="email" value={value.email || ''} onChange={v => set('email', v)} required={false} /></div>{!compact && <><p className="border-t border-dashem-border pt-4 text-xs font-black uppercase tracking-wider text-dashem-muted">Endereço e emergência</p><div className="grid gap-4 sm:grid-cols-4"><Field label="CEP" value={value.postal_code || ''} onChange={v => set('postal_code', v.replace(/\D/g, '').slice(0, 8))} required={false} /><div className="sm:col-span-2"><Field label="Logradouro" value={value.street || ''} onChange={v => set('street', v)} required={false} /></div><Field label="Número" value={value.street_number || ''} onChange={v => set('street_number', v)} required={false} /><Field label="Complemento" value={value.address_complement || ''} onChange={v => set('address_complement', v)} required={false} /><Field label="Bairro" value={value.district || ''} onChange={v => set('district', v)} required={false} /><Field label="Cidade" value={value.city || ''} onChange={v => set('city', v)} required={false} /><Field label="UF" value={value.state || ''} onChange={v => set('state', v.toUpperCase().slice(0, 2))} required={false} /></div><div className="grid gap-4 sm:grid-cols-2"><Field label="Contato de emergência" value={value.emergency_contact_name || ''} onChange={v => set('emergency_contact_name', v)} required={false} /><Field label="Telefone de emergência" value={value.emergency_contact_phone || ''} onChange={v => set('emergency_contact_phone', v)} required={false} /></div><Field label="Observações administrativas" value={value.notes || ''} onChange={v => set('notes', v)} required={false} /></>}</div> }

function Summary({ icon, value, title, text }: { icon: React.ReactNode; value: number; title: string; text: string }) { return <div className="flex items-center gap-4 rounded-2xl border border-dashem-border bg-dashem-surface p-4"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-dashem-bg text-dashem-red">{icon}</div><div><p className="text-xl font-black text-white">{value}</p><p className="text-sm font-black text-slate-200">{title}</p><p className="text-xs text-dashem-muted">{text}</p></div></div> }
function Field({ label, value, onChange, type = 'text', required = true, icon }: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean; icon?: React.ReactNode }) { return <label className="block text-xs font-black uppercase text-dashem-muted">{label}<div className="mt-2 flex items-center rounded-xl border border-dashem-border bg-dashem-bg px-3 focus-within:border-dashem-red">{icon}<input required={required} type={type} value={value} onChange={event => onChange(event.target.value)} className="h-11 min-w-0 flex-1 bg-transparent px-2 text-sm font-bold normal-case text-white outline-none" /></div></label> }
function Select({ label, value, onChange, options, required = true }: { label: string; value: string; onChange: (value: string) => void; options: string[][]; required?: boolean }) { return <label className="block text-xs font-black uppercase text-dashem-muted">{label}<select required={required} value={value} onChange={event => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold normal-case text-white"><option value="">Selecione...</option>{options.map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label> }
function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) { return <button type="button" onClick={onClick} className={`h-10 rounded-lg px-4 text-xs font-black ${active ? 'bg-white text-slate-950' : 'text-dashem-muted'}`}>{children}</button> }
function Info({ children }: { children: React.ReactNode }) { return <p className="rounded-xl border border-sky-900/60 bg-sky-950/30 p-3 text-xs leading-5 text-sky-200">{children}</p> }
function AccessBadge({ mode }: { mode: AccessMode }) { return <span className={`rounded-full px-2 py-1 text-[10px] font-black ${mode === 'PIN' ? 'bg-violet-950 text-violet-300' : 'bg-sky-950 text-sky-300'}`}>{mode === 'PIN' ? 'CÓDIGO + PIN' : 'E-MAIL'}</span> }
function Action({ onClick, disabled = false, tone, children }: { onClick: () => void; disabled?: boolean; tone: 'violet' | 'amber' | 'emerald' | 'neutral'; children: React.ReactNode }) { const color = { violet: 'border-violet-800 text-violet-300', amber: 'border-amber-800 text-amber-300', emerald: 'border-emerald-800 text-emerald-300', neutral: 'border-dashem-border text-slate-300' }[tone]; return <button disabled={disabled} onClick={onClick} className={`flex items-center gap-1 rounded-lg border px-3 py-2 text-xs font-black ${color}`}>{children}</button> }
function Loading() { return <div className="flex min-h-48 items-center justify-center text-sm font-bold text-dashem-muted"><Loader2 className="mr-3 h-5 w-5 animate-spin" />Carregando equipe...</div> }
function Empty({ text }: { text: string }) { return <p className="p-10 text-center text-sm font-bold text-dashem-muted">{text}</p> }
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-3 sm:p-4"><section className="max-h-[94vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-dashem-border bg-dashem-surface p-4 shadow-2xl sm:rounded-3xl sm:p-6"><div className="flex items-center justify-between"><h3 className="text-xl font-black text-white">{title}</h3><button onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-xl border border-dashem-border text-dashem-muted"><X className="h-5 w-5" /></button></div>{children}</section></div> }
