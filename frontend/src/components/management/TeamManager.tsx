import React, { useEffect, useMemo, useState } from 'react'
import { Ban, Briefcase, KeyRound, Loader2, Mail, Pencil, Plus, RefreshCw as RotateCcwKey, Search, ShieldCheck, UserRoundCog, X } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { DataTable } from '../common/DataTable'

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
  const [pinForm, setPinForm] = useState({ employee_id: '', role: 'OPERATOR' as 'SUPERVISOR' | 'CASHIER' | 'OPERATOR', store_id: '', employee_code: '' })
  const [editingAccess, setEditingAccess] = useState<api.TeamMember | null>(null)
  const [accessForm, setAccessForm] = useState({ role: '', store_id: '', reason: '' })
  const [activationMember, setActivationMember] = useState<api.TeamMember | null>(null)
  const [activationDelivery, setActivationDelivery] = useState<api.TeamMember | null>(null)
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
        const created = await api.createOperationalMember(headers, {
          employee_id: employeeId, role: pinForm.role, store_id: pinForm.store_id,
          employee_code: pinForm.employee_code,
        })
        setActivationDelivery(created)
        setPinForm(current => ({ ...current, employee_id: '', employee_code: '' }))
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

  const startEditAccess = (member: api.TeamMember) => {
    setAccessForm({ role: member.role, store_id: member.store_id || '', reason: '' })
    setEditingAccess(member)
  }

  /**
   * Function and unit of an existing access are correctable. The endpoint that
   * suspends an access already carries them; until now the interface only ever
   * sent them back unchanged, so a wrong role could not be fixed.
   */
  const saveAccess = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!editingAccess) return
    setSaving(true); setError(null)
    try {
      await api.updateTeamMember(headers, editingAccess.membership_id, {
        role: accessForm.role,
        status: editingAccess.status,
        store_id: accessForm.store_id || undefined,
        reason: accessForm.reason.trim(),
      })
      setEditingAccess(null)
      await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao alterar o acesso.') }
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

  const issueActivation = async () => {
    if (!activationMember) return
    setSaving(true); setError(null)
    try {
      const issued = await api.issueOperationalPinActivation(headers, activationMember.membership_id, {
        reason: 'Nova ativação solicitada pela administração do tenant',
      })
      setActivationMember(null); setActivationDelivery(issued); await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao emitir ativação.') }
    finally { setSaving(false) }
  }

  const selectedEmployeeValid = employeeSource === 'EXISTING' ? Boolean(pinForm.employee_id) : Boolean(employeeForm.full_name && employeeForm.employee_number)
  const emailCount = members.filter(member => member.access_mode === 'EMAIL').length
  const pinCount = members.filter(member => member.access_mode === 'PIN').length

  return <div className="space-y-5">
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><p className="text-xs font-black uppercase tracking-[.16em] text-dashem-red">Administração do tenant</p><h2 className="mt-1 text-2xl font-black text-dashem-strong">Equipe e identidades</h2><p className="mt-1 max-w-3xl text-sm text-dashem-muted">O cadastro do funcionário existe antes do acesso. Gestores entram por e-mail; equipe operacional assume o turno com código e PIN.</p></div>{canManage && <button onClick={() => setFormOpen(true)} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-dashem-red px-5 text-sm font-black text-brand-contrast"><Plus className="h-4 w-4" />Conceder acesso</button>}</div>
    <div className="grid gap-3 sm:grid-cols-3"><Summary icon={<Briefcase />} value={employees.length} title="Funcionários" text="Fichas cadastrais do tenant" /><Summary icon={<Mail />} value={emailCount} title="Acessos por e-mail" text="Administradores e gerentes" /><Summary icon={<KeyRound />} value={pinCount} title="Acessos operacionais" text="Código, PIN, função e unidade" /></div>
    <div className="inline-flex rounded-xl border border-dashem-border bg-dashem-surface p-1"><Tab active={view === 'ACCESS'} onClick={() => setView('ACCESS')}>Acessos</Tab><Tab active={view === 'EMPLOYEES'} onClick={() => setView('EMPLOYEES')}>Cadastro de funcionários</Tab></div>
    {error && <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
    {view === 'ACCESS' ? <AccessTable members={members} loading={loading} saving={saving} canManage={canManage} changeStatus={changeStatus} issueActivation={setActivationMember} editAccess={startEditAccess} /> : <EmployeeTable employees={employees} stores={stores} loading={loading} canManage={canManage} edit={openEmployeeEdit} />}
    {!canManage && <p className="flex items-center gap-2 text-sm font-semibold text-dashem-muted"><UserRoundCog className="h-4 w-4" />Seu perfil permite consulta, mas não alteração da equipe.</p>}

    {editingAccess && <Modal title="Editar acesso" onClose={() => setEditingAccess(null)}>
      <p className="text-sm leading-6 text-dashem-muted">{editingAccess.full_name} · {editingAccess.access_mode === 'PIN' ? `código ${editingAccess.employee_code}` : editingAccess.email}</p>
      <form onSubmit={saveAccess} className="mt-5 space-y-4">
        <Select
          label="Função"
          value={accessForm.role}
          onChange={value => setAccessForm(current => ({ ...current, role: value }))}
          options={editingAccess.access_mode === 'PIN'
            ? [["OPERATOR", "Atendente"], ["CASHIER", "Caixa"], ["SUPERVISOR", "Supervisor"]]
            : [["MANAGER", "Gerente"], ["ADMIN", "Administrador"]]}
        />
        {editingAccess.access_mode === 'PIN' && <Select
          label="Unidade do acesso"
          value={accessForm.store_id}
          onChange={value => setAccessForm(current => ({ ...current, store_id: value }))}
          options={stores.map(store => [store.id, store.name])}
        />}
        <Field label="Motivo da alteração" value={accessForm.reason} onChange={value => setAccessForm(current => ({ ...current, reason: value }))} />
        <Info>A função define o que a pessoa pode fazer na operação. Atendente não abre nem fecha caixa; Caixa e Supervisor abrem e fecham. A alteração é auditada e derruba sessões que dependiam da autoridade anterior.</Info>
        <button disabled={saving || !accessForm.role || accessForm.reason.trim().length < 4} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">
          {saving ? 'Salvando...' : 'Salvar acesso'}
        </button>
      </form>
    </Modal>}

    {formOpen && <Modal title="Conceder acesso" onClose={() => setFormOpen(false)}><div className="grid grid-cols-2 rounded-xl bg-dashem-bg p-1"><Tab active={mode === 'PIN'} onClick={() => setMode('PIN')}>Operação · código + PIN</Tab><Tab active={mode === 'EMAIL'} onClick={() => setMode('EMAIL')}>Gestão · e-mail</Tab></div><form onSubmit={submit} className="mt-5 space-y-4">{mode === 'EMAIL' ? <><Field label="Nome completo" value={emailForm.full_name} onChange={value => setEmailForm(current => ({ ...current, full_name: value }))} /><Field label="E-mail corporativo" type="email" value={emailForm.email} onChange={value => setEmailForm(current => ({ ...current, email: value }))} /><Select label="Função" value={emailForm.role} onChange={value => setEmailForm(current => ({ ...current, role: value }))} options={[["MANAGER","Gerente"],["ADMIN","Administrador"]]} /><Info>O convite por e-mail dá acesso à Gestão. A operação continua exigindo a identificação pessoal do colaborador em um terminal autorizado.</Info></> : <><div className="grid grid-cols-2 rounded-xl border border-dashem-border p-1"><Tab active={employeeSource === 'EXISTING'} onClick={() => setEmployeeSource('EXISTING')}>Buscar funcionário</Tab><Tab active={employeeSource === 'NEW'} onClick={() => setEmployeeSource('NEW')}>Novo cadastro</Tab></div>{employeeSource === 'EXISTING' ? <div className="space-y-4"><Field label="Buscar por nome ou matrícula" value={employeeSearch} onChange={setEmployeeSearch} icon={<Search className="h-4 w-4" />} /><Select label="Funcionário cadastrado" value={pinForm.employee_id} onChange={selectEmployee} options={availableEmployees.map(employee => [employee.id, `${employee.full_name} · ${employee.employee_number}`])} /></div> : <EmployeeFields value={employeeForm} onChange={setEmployeeForm} stores={stores} compact={false} />}<div className="grid gap-4 sm:grid-cols-2"><Select label="Função operacional" value={pinForm.role} onChange={value => setPinForm(current => ({ ...current, role: value as typeof pinForm.role }))} options={[["OPERATOR","Atendente"],["CASHIER","Caixa"],["SUPERVISOR","Supervisor"]]} /><Select label="Unidade do acesso" value={pinForm.store_id} onChange={value => setPinForm(current => ({ ...current, store_id: value, employee_id: '' }))} options={stores.map(store => [store.id, store.name])} /></div><Field label="Código de acesso do colaborador" value={pinForm.employee_code} onChange={value => setPinForm(current => ({ ...current, employee_code: value.replace(/[^A-Z0-9_-]/gi, '').toUpperCase().slice(0, 20) }))} /><Info>A Gestão define código, função e unidade. O colaborador recebe um código de ativação temporário e cria o próprio PIN no terminal autorizado; o gestor nunca vê esse PIN.</Info></>}<button disabled={saving || mode === 'EMAIL' && (!emailForm.full_name || !emailForm.email.includes('@')) || mode === 'PIN' && (!selectedEmployeeValid || !pinForm.store_id || pinForm.employee_code.length < 3)} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">{saving ? 'Salvando...' : mode === 'PIN' ? 'Conceder e emitir ativação' : 'Enviar convite de gestão'}</button></form></Modal>}
    {editingEmployee && <Modal title={`Ficha · ${editingEmployee.full_name}`} onClose={() => setEditingEmployee(null)}><form onSubmit={saveEmployee} className="mt-5 space-y-4"><EmployeeFields value={employeeForm} onChange={setEmployeeForm} stores={stores} compact={false} /><button disabled={saving || !employeeForm.full_name || !employeeForm.employee_number} className="h-12 w-full rounded-xl bg-dashem-red font-black text-brand-contrast disabled:opacity-40">{saving ? 'Salvando...' : 'Salvar ficha cadastral'}</button></form></Modal>}
    {activationMember && <Modal title={`Nova ativação · ${activationMember.full_name}`} onClose={() => setActivationMember(null)}><div className="mt-5 space-y-4"><Info>As sessões atuais serão revogadas e o PIN anterior deixará de funcionar. A Gestão receberá somente um código temporário; o novo PIN será criado pelo colaborador.</Info><button disabled={saving} onClick={() => void issueActivation()} className="h-12 w-full rounded-xl bg-dashem-red font-black text-brand-contrast disabled:opacity-40">{saving ? 'Emitindo...' : 'Revogar PIN e emitir ativação'}</button></div></Modal>}
    {activationDelivery?.activation_code && <Modal title="Código de ativação temporário" onClose={() => setActivationDelivery(null)}><div className="mt-5 space-y-4"><Info>Entregue este código ao colaborador. Ele aparece somente agora, expira em 24 horas e serve uma única vez para que o próprio colaborador defina o PIN.</Info><div className="rounded-2xl border border-dashem-border bg-dashem-bg p-6 text-center"><p className="text-xs font-black uppercase tracking-wider text-dashem-muted">{activationDelivery.full_name} · {activationDelivery.employee_code}</p><p className="mt-3 font-mono text-4xl font-black tracking-[.22em] text-dashem-strong">{activationDelivery.activation_code}</p></div><button onClick={() => setActivationDelivery(null)} className="h-12 w-full rounded-xl bg-brand font-black text-brand-contrast">Código entregue</button></div></Modal>}
  </div>
}

function AccessTable({ members, loading, saving, canManage, changeStatus, issueActivation, editAccess }: { members: api.TeamMember[]; loading: boolean; saving: boolean; canManage: boolean; changeStatus: (member: api.TeamMember, status: string) => Promise<void>; issueActivation: (member: api.TeamMember) => void; editAccess: (member: api.TeamMember) => void }) { return <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface">{loading ? <Loading /> : <DataTable
  rows={members}
  rowKey={(member) => member.membership_id}
  empty={<Empty text="Nenhum acesso concedido." />}
  columns={[
    { key: 'person', header: 'Pessoa', primary: true, cell: (member) => <div><p className="font-black text-dashem-strong">{member.full_name}</p><p className="text-xs text-dashem-muted">{member.email || `Código ${member.employee_code}`}</p></div> },
    { key: 'entry', header: 'Entrada', cell: (member) => <AccessBadge mode={member.access_mode} /> },
    { key: 'role', header: 'Função', cell: (member) => <span className="text-sm font-bold text-dashem-muted">{roleLabel[member.role] || member.role}</span> },
    { key: 'store', header: 'Unidade', cell: (member) => <span className="text-sm text-dashem-muted">{member.store_name || 'Tenant inteiro'}</span> },
    { key: 'state', header: 'Estado', cell: (member) => <span className="rounded-full bg-dashem-bg px-2 py-1 text-xs font-black text-dashem-muted">{member.status !== 'ACTIVE' ? (member.status === 'SUSPENDED' ? 'Suspenso' : member.status) : member.credential_state === 'PENDING_ACTIVATION' ? 'Aguardando ativação' : 'Ativo'}</span> },
    { key: 'actions', header: 'Ações', actions: true, cell: (member) => <div className="flex flex-wrap gap-2">{canManage && <Action onClick={() => editAccess(member)} tone="neutral"><Pencil className="h-4 w-4" />Editar acesso</Action>}{canManage && member.access_mode === 'PIN' && <Action onClick={() => issueActivation(member)} disabled={saving} tone="violet"><RotateCcwKey className="h-4 w-4" />Nova ativação</Action>}{canManage && (member.status === 'ACTIVE' ? <Action onClick={() => void changeStatus(member, 'SUSPENDED')} disabled={saving} tone="amber"><Ban className="h-4 w-4" />Suspender</Action> : <Action onClick={() => void changeStatus(member, 'ACTIVE')} disabled={saving} tone="emerald"><ShieldCheck className="h-4 w-4" />Reativar</Action>)}</div> },
  ]}
/>}</section> }

function EmployeeTable({ employees, stores, loading, canManage, edit }: { employees: api.Employee[]; stores: api.Store[]; loading: boolean; canManage: boolean; edit: (employee: api.Employee) => void }) { return <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface">{loading ? <Loading /> : <DataTable
  rows={employees}
  rowKey={(employee) => employee.id}
  empty={<Empty text="Nenhum funcionário cadastrado. Conceda um acesso e escolha Novo cadastro." />}
  columns={[
    { key: 'person', header: 'Funcionário', primary: true, cell: (employee) => <div><p className="font-black text-dashem-strong">{employee.full_name}</p><p className="text-xs text-dashem-muted">Matrícula {employee.employee_number}{employee.tax_id ? ` · CPF final ${employee.tax_id.slice(-4)}` : ''}</p></div> },
    { key: 'job', header: 'Cargo / setor', cell: (employee) => <div className="text-sm text-dashem-muted">{employee.job_title || 'Cargo pendente'}<p className="text-xs text-dashem-muted">{employee.department || 'Setor pendente'}</p></div> },
    { key: 'store', header: 'Lotação', cell: (employee) => <span className="text-sm text-dashem-muted">{stores.find(store => store.id === employee.home_store_id)?.name || 'Tenant inteiro'}</span> },
    { key: 'contact', header: 'Contato', cell: (employee) => <span className="text-sm text-dashem-muted">{employee.phone || employee.email || 'Não informado'}</span> },
    { key: 'state', header: 'Estado', cell: (employee) => <span className="text-xs font-black text-dashem-muted">{employee.status === 'ACTIVE' ? 'Ativo' : employee.status}</span> },
    { key: 'action', header: 'Ação', actions: true, cell: (employee) => canManage ? <Action onClick={() => edit(employee)} tone="neutral"><Pencil className="h-4 w-4" />Editar ficha</Action> : null },
  ]}
/>}</section> }

function EmployeeFields({ value, onChange, stores, compact }: { value: api.EmployeeInput; onChange: (value: api.EmployeeInput) => void; stores: api.Store[]; compact: boolean }) { const set = (key: keyof api.EmployeeInput, fieldValue: string) => onChange({ ...value, [key]: fieldValue }); return <div className="space-y-4"><div className="grid gap-4 sm:grid-cols-2"><Field label="Nome completo" value={value.full_name} onChange={v => set('full_name', v)} /><Field label="Nome preferido" value={value.preferred_name || ''} onChange={v => set('preferred_name', v)} required={false} /><Field label="Matrícula" value={value.employee_number} onChange={v => set('employee_number', v.toUpperCase())} /><Field label="CPF" value={value.tax_id || ''} onChange={v => set('tax_id', v.replace(/\D/g, '').slice(0, 11))} required={false} /></div><div className="grid gap-4 sm:grid-cols-4"><Field label="Cargo" value={value.job_title || ''} onChange={v => set('job_title', v)} required={false} /><Field label="Setor" value={value.department || ''} onChange={v => set('department', v)} required={false} /><Field label="Admissão" type="date" value={value.hire_date || ''} onChange={v => set('hire_date', v)} required={false} /><Select label="Situação" value={value.status} onChange={v => set('status', v)} options={[["ACTIVE","Ativo"],["ON_LEAVE","Afastado"],["INACTIVE","Inativo"],["TERMINATED","Desligado"]]} /></div><div className="grid gap-4 sm:grid-cols-3"><Select label="Lotação principal" value={value.home_store_id || ''} onChange={v => set('home_store_id', v)} options={stores.map(store => [store.id, store.name])} required={false} /><Field label="Telefone" value={value.phone || ''} onChange={v => set('phone', v)} required={false} /><Field label="E-mail de contato" type="email" value={value.email || ''} onChange={v => set('email', v)} required={false} /></div>{!compact && <><p className="border-t border-dashem-border pt-4 text-xs font-black uppercase tracking-wider text-dashem-muted">Endereço e emergência</p><div className="grid gap-4 sm:grid-cols-4"><Field label="CEP" value={value.postal_code || ''} onChange={v => set('postal_code', v.replace(/\D/g, '').slice(0, 8))} required={false} /><div className="sm:col-span-2"><Field label="Logradouro" value={value.street || ''} onChange={v => set('street', v)} required={false} /></div><Field label="Número" value={value.street_number || ''} onChange={v => set('street_number', v)} required={false} /><Field label="Complemento" value={value.address_complement || ''} onChange={v => set('address_complement', v)} required={false} /><Field label="Bairro" value={value.district || ''} onChange={v => set('district', v)} required={false} /><Field label="Cidade" value={value.city || ''} onChange={v => set('city', v)} required={false} /><Field label="UF" value={value.state || ''} onChange={v => set('state', v.toUpperCase().slice(0, 2))} required={false} /></div><div className="grid gap-4 sm:grid-cols-2"><Field label="Contato de emergência" value={value.emergency_contact_name || ''} onChange={v => set('emergency_contact_name', v)} required={false} /><Field label="Telefone de emergência" value={value.emergency_contact_phone || ''} onChange={v => set('emergency_contact_phone', v)} required={false} /></div><Field label="Observações administrativas" value={value.notes || ''} onChange={v => set('notes', v)} required={false} /></>}</div> }

function Summary({ icon, value, title, text }: { icon: React.ReactNode; value: number; title: string; text: string }) { return <div className="flex items-center gap-4 rounded-2xl border border-dashem-border bg-dashem-surface p-4"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-dashem-bg text-dashem-red">{icon}</div><div><p className="text-xl font-black text-dashem-strong">{value}</p><p className="text-sm font-black text-dashem-muted">{title}</p><p className="text-xs text-dashem-muted">{text}</p></div></div> }
function Field({ label, value, onChange, type = 'text', required = true, icon }: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean; icon?: React.ReactNode }) { return <label className="block text-xs font-black uppercase text-dashem-muted">{label}<div className="mt-2 flex items-center rounded-xl border border-dashem-border bg-dashem-bg px-3 focus-within:border-dashem-red">{icon}<input required={required} type={type} value={value} onChange={event => onChange(event.target.value)} className="h-11 min-w-0 flex-1 bg-transparent px-2 text-sm font-bold normal-case text-dashem-strong outline-none" /></div></label> }
function Select({ label, value, onChange, options, required = true }: { label: string; value: string; onChange: (value: string) => void; options: string[][]; required?: boolean }) { return <label className="block text-xs font-black uppercase text-dashem-muted">{label}<select required={required} value={value} onChange={event => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold normal-case text-dashem-strong"><option value="">Selecione...</option>{options.map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label> }
function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) { return <button type="button" onClick={onClick} className={`h-10 rounded-lg px-4 text-xs font-black ${active ? 'bg-brand text-brand-contrast' : 'text-dashem-muted'}`}>{children}</button> }
function Info({ children }: { children: React.ReactNode }) { return <p className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs leading-5 text-sky-700">{children}</p> }
function AccessBadge({ mode }: { mode: AccessMode }) { return <span className={`rounded-full px-2 py-1 text-xs font-black ${mode === 'PIN' ? 'bg-violet-50 text-violet-700' : 'bg-sky-50 text-sky-700'}`}>{mode === 'PIN' ? 'CÓDIGO + PIN' : 'E-MAIL'}</span> }
function Action({ onClick, disabled = false, tone, children }: { onClick: () => void; disabled?: boolean; tone: 'violet' | 'amber' | 'emerald' | 'neutral'; children: React.ReactNode }) { const color = { violet: 'border-violet-200 text-violet-700', amber: 'border-amber-200 text-amber-700', emerald: 'border-emerald-200 text-emerald-700', neutral: 'border-dashem-border text-dashem-muted' }[tone]; return <button disabled={disabled} onClick={onClick} className={`flex items-center gap-1 rounded-lg border px-3 py-2 text-xs font-black ${color}`}>{children}</button> }
function Loading() { return <div className="flex min-h-48 items-center justify-center text-sm font-bold text-dashem-muted"><Loader2 className="mr-3 h-5 w-5 animate-spin" />Carregando equipe...</div> }
function Empty({ text }: { text: string }) { return <p className="p-10 text-center text-sm font-bold text-dashem-muted">{text}</p> }
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-3 sm:p-4"><section className="max-h-[94vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-dashem-border bg-dashem-surface p-4 shadow-2xl sm:rounded-3xl sm:p-6"><div className="flex items-center justify-between"><h3 className="text-xl font-black text-dashem-strong">{title}</h3><button onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-xl border border-dashem-border text-dashem-muted"><X className="h-5 w-5" /></button></div>{children}</section></div> }
