import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Ban, Building2, Check, CheckCircle2, Loader2, Pencil, Plus, Save, ShieldCheck, Users, WalletCards, X } from 'lucide-react'
import {
  BusinessNiche, CapabilityCatalogItem, fetchOwnerNiches, fetchPlatformTenantDetail, fetchServicePlans,
  fetchTenantCapabilityCatalog, OwnerNiche, PlatformTenantDetail, replacePlatformTenantAdministrator,
  PlatformTenantSummary, ServicePlan, SubscriptionStatus, TenantPhase, TenantType,
  updateOwnerTenantContract, updatePlatformTenantLifecycle, updatePlatformTenantProfile,
  updateSaasBillingAccount,
} from '../../services/api'
import { formatBrazilianPhone, formatBrazilianPostalCode, isValidCpfCnpj, lookupBrazilianPostalCode, onlyDigits } from '../../utils/brazil'

type Tab = 'summary' | 'registration' | 'billing' | 'contract' | 'administrator'
const nicheLabel: Record<BusinessNiche, string> = { FOOD_SERVICE: 'Food Service', RETAIL: 'Retail', BEAUTY_RESELLER: 'Beauty Reseller' }
const phaseLabel: Record<TenantPhase, string> = { TEST: 'Teste controlado', PILOT: 'Piloto', PRODUCTION: 'Produção' }
const statusLabel: Record<string, string> = { PENDING: 'Pendente', TRIAL: 'Avaliação', ACTIVE: 'Ativa', PAUSED: 'Pausada', CANCELED: 'Cancelada' }
const money = (value: number | string | undefined) => Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const inputClass = 'mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3 font-semibold outline-none focus:border-[#E12120] focus:ring-4 focus:ring-red-100'
const digits = (value: string, max = 14) => onlyDigits(value, max)

export function TenantWorkspace({ tenant, onBack, onManagePlans, onFinance, onChanged }: { tenant: PlatformTenantSummary; onBack: () => void; onManagePlans: () => void; onFinance: () => void; onChanged: () => void }) {
  const [tab, setTab] = useState<Tab>('summary')
  const [detail, setDetail] = useState<PlatformTenantDetail | null>(null)
  const [catalog, setCatalog] = useState<CapabilityCatalogItem[]>([])
  const [niches, setNiches] = useState<OwnerNiche[]>([])
  const [plans, setPlans] = useState<ServicePlan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [lifecycle, setLifecycle] = useState<'PAUSED' | 'ARCHIVED' | null>(null)
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { const [tenantDetail, capabilityRows, nicheRows, planRows] = await Promise.all([fetchPlatformTenantDetail(tenant.id), fetchTenantCapabilityCatalog(tenant.id), fetchOwnerNiches(), fetchServicePlans()]); setDetail(tenantDetail); setCatalog(capabilityRows); setNiches(nicheRows); setPlans(planRows.filter(item => item.is_active || item.id === tenantDetail.plan?.id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível carregar o cliente.') }
    finally { setLoading(false) }
  }, [tenant.id])
  useEffect(() => { load() }, [load])
  const changed = async () => {
    setNotice('Alterações salvas e confirmadas pelo servidor.')
    await load()
    onChanged()
  }
  if (loading || !detail) return <div className="p-20"><Loader2 className="mx-auto h-8 w-8 animate-spin text-[#E12120]" /></div>
  const limits = detail.contract?.limits ?? {}
  const admin = detail.accesses[0]
  return <div className="mx-auto max-w-[1500px] p-5 text-[#022444] sm:p-8">
    <button onClick={onBack} className="flex items-center gap-2 text-sm font-black text-slate-500"><ArrowLeft className="h-4 w-4" />Voltar para organizações</button>
    {error && <p className="mt-4 rounded-xl border border-[#ffbf00] bg-amber-50 p-4 text-sm font-bold text-[#6b4b00]">{error}</p>}
    {notice && <p className="mt-4 flex items-center gap-2 rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm font-bold text-emerald-800"><CheckCircle2 className="h-5 w-5" />{notice}</p>}
    <section className="mt-6 rounded-3xl bg-[#022444] p-7 text-white sm:p-9"><div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between"><div><div className="flex flex-wrap gap-2"><span className="rounded-full bg-white/10 px-3 py-1 text-xs font-black">{detail.profile?.tenant_type === 'INTERNAL' ? 'INTERNO' : 'CLIENTE'} · {phaseLabel[detail.profile?.lifecycle_phase || 'TEST']}</span>{detail.niches.map(niche => <span key={niche} className="rounded-full bg-emerald-400/15 px-3 py-1 text-xs font-black text-emerald-300">{nicheLabel[niche]}</span>)}{detail.niches.length === 0 && <span className="rounded-full bg-amber-400/15 px-3 py-1 text-xs font-black text-amber-300">Sem filtro de nicho</span>}</div><h2 className="mt-5 text-3xl font-black">{detail.tenant.name}</h2><p className="mt-2 text-slate-300">{detail.profile?.legal_name || 'Razão social ou nome civil não informado'} · {detail.profile?.tax_id || 'CPF/CNPJ pendente'}</p></div><div className="flex flex-wrap gap-3"><button onClick={() => setLifecycle('PAUSED')} className="flex h-11 items-center gap-2 rounded-xl bg-[#ffbf00] px-4 font-black text-[#022444]"><Ban className="h-4 w-4" />Pausar</button><button onClick={() => setLifecycle('ARCHIVED')} className="h-11 rounded-xl border border-red-300/50 px-4 font-black text-red-200">Arquivar</button></div></div></section>
    <nav className="mt-5 flex gap-2 overflow-x-auto border-b border-slate-200">{([['summary', 'Resumo contratual'], ['registration', 'Cadastro'], ['billing', 'Conta de cobrança'], ['contract', 'Contrato'], ['administrator', 'Administrador inicial']] as Array<[Tab, string]>).map(([key, label]) => <button key={key} onClick={() => { setTab(key); setNotice('') }} className={`shrink-0 border-b-2 px-4 py-4 text-sm font-black ${tab === key ? 'border-[#E12120] text-[#E12120]' : 'border-transparent text-slate-500'}`}>{label}</button>)}</nav>
    <div className="mt-7">
      {tab === 'summary' && !detail.subscription && <section className="mb-5 rounded-2xl border border-amber-300 bg-amber-50 p-5"><p className="text-xs font-black uppercase tracking-wider text-amber-800">Financeiro bloqueado</p><h3 className="mt-2 text-xl font-black">Esta organização ainda não possui assinatura SaaS</h3><p className="mt-2 text-sm text-slate-600">Crie um plano comercial e salve a primeira versão do contrato. Até lá, mensalidade e situação da assinatura não serão presumidas.</p><div className="mt-4 flex flex-wrap gap-2"><button onClick={onManagePlans} className="h-10 rounded-xl bg-[#022444] px-4 text-sm font-black text-white">Cadastrar plano</button><button onClick={() => setTab('contract')} className="h-10 rounded-xl border border-amber-300 bg-white px-4 text-sm font-black">Configurar contrato</button></div></section>}
      {tab === 'summary' && <div className="grid gap-5 lg:grid-cols-3"><Card icon={Building2} title="Contrato" value={detail.plan?.name || 'Sem plano'} hint={`${detail.niches.length ? detail.niches.map(item => nicheLabel[item]).join(' + ') : 'Sem filtro'} · versão ${detail.contract?.version ?? '—'}`} /><Card icon={WalletCards} title="Mensalidade SaaS" value={detail.subscription ? money(detail.subscription.monthly_amount) : 'Não configurada'} hint={detail.subscription ? `Vencimento contratual dia ${detail.subscription.billing_day || '—'} · assinatura ${detail.subscription.status}` : 'Salve a primeira versão do contrato'} /><Card icon={Users} title="Administrador" value={admin?.full_name || 'Pendente'} hint={admin?.email || 'Primeiro acesso ainda não entregue'} /><section className="rounded-2xl border border-slate-200 bg-white p-6 lg:col-span-3"><h3 className="text-lg font-black">Limites contratados</h3><div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Limit label="Usuários" value={limits.users} /><Limit label="Dispositivos" value={limits.devices} /><Limit label="Unidades" value={limits.units} /><Limit label="Storage" value={limits.storage_mb ? `${limits.storage_mb} MB` : undefined} /></div></section></div>}
      {tab === 'registration' && <RegistrationEditor detail={detail} onSaved={changed} />}
      {tab === 'billing' && <BillingAccountPanel detail={detail} onSaved={changed} />}
      {tab === 'contract' && <ContractEditor detail={detail} catalog={catalog} niches={niches} plans={plans} onManagePlans={onManagePlans} onFinance={onFinance} onSaved={changed} />}
      {tab === 'administrator' && <AdministratorPanel tenantId={tenant.id} admin={admin} onSaved={changed} />}
    </div>
    {lifecycle && <LifecycleModal status={lifecycle} onClose={() => setLifecycle(null)} onConfirm={async reason => { await updatePlatformTenantLifecycle(tenant.id, lifecycle, reason); setLifecycle(null); onBack(); onChanged() }} />}
  </div>
}

function BillingAccountPanel({ detail, onSaved }: { detail: PlatformTenantDetail; onSaved: () => Promise<void> }) {
  const account = detail.billing_account
  const primaryContact = detail.contacts.find(item => item.is_primary) || detail.contacts[0]
  const [editing, setEditing] = useState(!account)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({
    legal_name: account?.legal_name || detail.profile?.legal_name || '',
    tax_id: digits(account?.tax_id || detail.profile?.tax_id || ''),
    contact_name: account?.contact_name || primaryContact?.full_name || '',
    contact_email: account?.contact_email || primaryContact?.email || detail.profile?.company_email || '',
    contact_phone: digits(account?.contact_phone || primaryContact?.phone || '', 11),
    reason: 'Atualização da conta de cobrança solicitada pelo Owner.',
  })
  const set = (key: keyof typeof form, value: string) => setForm(current => ({ ...current, [key]: value }))
  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (saving) return
    if (!isValidCpfCnpj(form.tax_id)) { setError('Informe um CPF ou CNPJ válido.'); return }
    if (!form.contact_email.includes('@')) { setError('Informe um e-mail de cobrança válido.'); return }
    if (form.contact_phone && ![10, 11].includes(form.contact_phone.length)) { setError('Informe o DDD e o telefone de cobrança.'); return }
    setSaving(true); setError('')
    try {
      await updateSaasBillingAccount(detail.tenant.id, {
        legal_name: form.legal_name.trim(), tax_id: digits(form.tax_id),
        contact_name: form.contact_name.trim(), contact_email: form.contact_email.trim(),
        contact_phone: form.contact_phone || undefined, currency: 'BRL',
        expected_version: account?.version ?? 0, reason: form.reason.trim(),
      })
      await onSaved(); setEditing(false)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível salvar a conta de cobrança.') }
    finally { setSaving(false) }
  }
  if (!editing) return <div><div className="mb-5 flex justify-end"><button onClick={() => setEditing(true)} className="flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white"><Pencil className="h-4 w-4" />Editar conta de cobrança</button></div><InfoSection title="Conta de cobrança SaaS"><Info label="Razão social / nome civil" value={account?.legal_name} /><Info label="CPF ou CNPJ" value={account?.tax_id} /><Info label="Contato de cobrança" value={account?.contact_name} /><Info label="E-mail" value={account?.contact_email} /><Info label="Telefone" value={account?.contact_phone} /><Info label="Moeda contratual" value={account?.currency} /><Info label="Versão" value={account ? String(account.version) : undefined} /></InfoSection><p className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-semibold text-blue-900">Este cadastro pertence à cobrança da assinatura Dashem. Não contém faturamento, caixa, vendas ou lucro do tenant.</p></div>
  return <form onSubmit={save} className="rounded-2xl border border-slate-200 bg-white p-6"><div className="flex items-center justify-between"><div><h3 className="text-xl font-black">Editar conta de cobrança SaaS</h3><p className="mt-1 text-sm text-slate-500">Salvamento versionado, auditado e restrito ao Financeiro do Control.</p></div>{account && <button type="button" onClick={() => setEditing(false)} className="rounded-xl border border-slate-200 p-2"><X className="h-5 w-5" /></button>}</div>{error && <p className="mt-4 rounded-xl border border-[#ffbf00] bg-amber-50 p-3 text-sm font-bold text-[#6b4b00]">{error}</p>}<div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3"><TextField label="Razão social / nome civil" value={form.legal_name} onChange={value => set('legal_name', value)} /><TextField label="CPF ou CNPJ" value={form.tax_id} onChange={value => set('tax_id', digits(value))} /><TextField label="Contato de cobrança" value={form.contact_name} onChange={value => set('contact_name', value)} /><TextField label="E-mail de cobrança" type="email" value={form.contact_email} onChange={value => set('contact_email', value)} /><TextField label="Telefone de cobrança" value={formatBrazilianPhone(form.contact_phone)} onChange={value => set('contact_phone', digits(value, 11))} /><label className="text-sm font-black">Moeda contratual<input value="BRL" readOnly className={`${inputClass} bg-slate-100 text-slate-500`} /></label><div className="md:col-span-2 xl:col-span-3"><TextField label="Motivo da alteração" value={form.reason} onChange={value => set('reason', value)} /></div></div><button disabled={saving || form.legal_name.trim().length < 2 || form.contact_name.trim().length < 2 || form.reason.trim().length < 4} className="mt-6 flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white disabled:opacity-40">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{saving ? 'Salvando…' : 'Salvar nova versão'}</button></form>
}

function RegistrationEditor({ detail, onSaved }: { detail: PlatformTenantDetail; onSaved: () => Promise<void> }) {
  const profile = detail.profile
  const contact = detail.contacts.find(item => item.is_primary) || detail.contacts[0]
  const store = detail.stores.find(item => item.is_headquarters) || detail.stores[0]
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [registrationSection, setRegistrationSection] = useState<'company' | 'address'>('company')
  const [form, setForm] = useState({ name: detail.tenant.name, tenant_type: (profile?.tenant_type || 'CUSTOMER') as TenantType, lifecycle_phase: (profile?.lifecycle_phase || 'TEST') as TenantPhase, legal_name: profile?.legal_name || '', tax_id: digits(profile?.tax_id || ''), company_email: profile?.company_email || '', company_phone: digits(profile?.company_phone || '', 11), contact_name: contact?.full_name || '', contact_job_title: contact?.job_title || '', contact_email: contact?.email || '', contact_phone: digits(contact?.phone || '', 11), store_name: store?.name || 'Matriz', store_code: store?.code || 'MATRIZ', postal_code: digits(store?.postal_code || '', 8), street: store?.street || '', street_number: store?.street_number || '', address_complement: store?.address_complement || '', district: store?.district || '', city: store?.city || '', state: store?.state || '' })
  const set = (key: keyof typeof form, value: string) => setForm(current => ({ ...current, [key]: value }))
  const setPostalCode = async (value: string) => {
    const postalCode = digits(value, 8)
    set('postal_code', postalCode)
    if (postalCode.length !== 8) return
    try {
      const address = await lookupBrazilianPostalCode(postalCode)
      setForm(current => ({ ...current, street: address.street, district: address.district, city: address.city, state: address.state, address_complement: current.address_complement || address.complement }))
      setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'CEP não encontrado.') }
  }
  const save = async () => {
    if (saving) return
    if (form.tax_id && !isValidCpfCnpj(form.tax_id)) { setError('Informe um CPF ou CNPJ válido.'); return }
    if (form.company_phone && ![10, 11].includes(form.company_phone.length)) { setError('Informe o DDD e o telefone da empresa.'); return }
    setSaving(true); setError('')
    try {
      await updatePlatformTenantProfile(detail.tenant.id, { ...form, tax_id: digits(form.tax_id), state: form.state.toUpperCase().slice(0, 2), industry: profile?.industry || null, state_registration: profile?.state_registration || null, municipal_registration: profile?.municipal_registration || null, website: profile?.website || null, notes: profile?.notes || null })
      await onSaved(); setEditing(false)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível salvar o cadastro.') }
    finally { setSaving(false) }
  }
  if (!editing) return <div><div className="mb-5 flex justify-end"><button onClick={() => setEditing(true)} className="flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white"><Pencil className="h-4 w-4" />Editar cadastro</button></div><div className="grid gap-5 lg:grid-cols-2"><InfoSection title="Empresa"><Info label="Nome fantasia" value={profile?.trade_name} /><Info label="Razão social / nome civil" value={profile?.legal_name} /><Info label="CPF ou CNPJ" value={profile?.tax_id} /><Info label="Tipo" value={profile?.tenant_type === 'INTERNAL' ? 'Operação interna' : 'Cliente'} /><Info label="Fase" value={phaseLabel[profile?.lifecycle_phase || 'TEST']} /><Info label="E-mail" value={profile?.company_email} /><Info label="Telefone" value={profile?.company_phone} /></InfoSection><InfoSection title="Responsável contratual"><Info label="Nome" value={contact?.full_name} /><Info label="Cargo" value={contact?.job_title} /><Info label="E-mail" value={contact?.email} /><Info label="Telefone" value={contact?.phone} /></InfoSection><InfoSection title="Matriz cadastral"><Info label="Unidade" value={store?.name} /><Info label="Endereço" value={[store?.street, store?.street_number, store?.district, store?.city, store?.state].filter(Boolean).join(', ')} /></InfoSection></div></div>
  return <section className="rounded-2xl border border-slate-200 bg-white p-6"><div className="flex items-center justify-between"><div><h3 className="text-xl font-black">Editar cadastro</h3><p className="mt-1 text-sm text-slate-500">CPF e CNPJ são validados no servidor antes da gravação.</p></div><button onClick={() => setEditing(false)} className="rounded-xl border border-slate-200 p-2"><X className="h-5 w-5" /></button></div>{error && <p className="mt-4 rounded-xl border border-[#ffbf00] bg-amber-50 p-3 text-sm font-bold">{error}</p>}<nav className="mt-5 flex flex-wrap gap-2 rounded-xl bg-slate-100 p-2"><button type="button" onClick={() => setRegistrationSection('company')} className={`rounded-lg px-4 py-2 text-sm font-black ${registrationSection === 'company' ? 'bg-[#022444] text-white' : 'text-slate-500'}`}>Empresa e responsável</button><button type="button" onClick={() => setRegistrationSection('address')} className={`rounded-lg px-4 py-2 text-sm font-black ${registrationSection === 'address' ? 'bg-[#022444] text-white' : 'text-slate-500'}`}>Endereço da matriz</button></nav>{registrationSection === 'company' ? <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3"><TextField label="Nome fantasia" value={form.name} onChange={value => set('name', value)} /><TextField label="Razão social / nome civil" value={form.legal_name} onChange={value => set('legal_name', value)} /><TextField label="CPF ou CNPJ" value={form.tax_id} onChange={value => set('tax_id', digits(value))} /><Select label="Tipo de tenant" value={form.tenant_type} onChange={value => set('tenant_type', value)} options={[["CUSTOMER", "Cliente"], ["INTERNAL", "Operação interna"]]} /><Select label="Fase" value={form.lifecycle_phase} onChange={value => set('lifecycle_phase', value)} options={[["TEST", "Teste controlado"], ["PILOT", "Piloto"], ["PRODUCTION", "Produção"]]} /><TextField label="Telefone da empresa" value={formatBrazilianPhone(form.company_phone)} onChange={value => set('company_phone', digits(value, 11))} /><TextField label="E-mail da empresa" value={form.company_email} onChange={value => set('company_email', value)} /><TextField label="Responsável contratual" value={form.contact_name} onChange={value => set('contact_name', value)} /><TextField label="Cargo" value={form.contact_job_title} onChange={value => set('contact_job_title', value)} /><TextField label="E-mail do responsável" value={form.contact_email} onChange={value => set('contact_email', value)} /><TextField label="Telefone do responsável" value={formatBrazilianPhone(form.contact_phone)} onChange={value => set('contact_phone', digits(value, 11))} /></div> : <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3"><TextField label="Nome da matriz" value={form.store_name} onChange={value => set('store_name', value)} /><TextField label="Código da matriz" value={form.store_code} onChange={value => set('store_code', value.toUpperCase())} /><TextField label="CEP" value={formatBrazilianPostalCode(form.postal_code)} onChange={setPostalCode} /><TextField label="Logradouro" value={form.street} onChange={value => set('street', value)} /><TextField label="Número" value={form.street_number} onChange={value => set('street_number', value)} /><TextField label="Complemento" value={form.address_complement} onChange={value => set('address_complement', value)} /><TextField label="Bairro" value={form.district} onChange={value => set('district', value)} /><TextField label="Cidade" value={form.city} onChange={value => set('city', value)} /><TextField label="UF" value={form.state} onChange={value => set('state', value)} /></div>}<button onClick={save} disabled={saving} className="mt-6 flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white disabled:opacity-40">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{saving ? 'Salvando…' : 'Salvar cadastro'}</button>{error && <p className="mt-3 text-sm font-bold text-[#8a6100]">O cadastro não foi salvo. {error}</p>}</section>
}

function ContractEditor({ detail, catalog, niches, plans, onManagePlans, onFinance, onSaved }: { detail: PlatformTenantDetail; catalog: CapabilityCatalogItem[]; niches: OwnerNiche[]; plans: ServicePlan[]; onManagePlans: () => void; onFinance: () => void; onSaved: () => Promise<void> }) {
  const limits = detail.contract?.limits || {}
  const primaryContact = detail.contacts.find(item => item.is_primary) || detail.contacts[0]
  const contractualAdmin = detail.accesses[0]
  const savedBilling = (limits.billing || {}) as {
    contact_name?: string; email?: string; phone?: string; monthly_amount?: number | string
    gross_monthly_amount?: number | string; billing_day?: number; discount_type?: 'PERCENTAGE' | 'FIXED'
    discount_value?: number | string; discount_reason_code?: string; discount_reason?: string
    discount_starts_on?: string; discount_ends_on?: string; discount_review_on?: string
  }
  const billing = {
    contact_name: detail.billing_account?.contact_name || savedBilling.contact_name || primaryContact?.full_name || contractualAdmin?.full_name || '',
    email: detail.billing_account?.contact_email || savedBilling.email || primaryContact?.email || detail.profile?.company_email || contractualAdmin?.email || '',
    phone: detail.billing_account?.contact_phone || savedBilling.phone || primaryContact?.phone || detail.profile?.company_phone || '',
    monthly_amount: savedBilling.gross_monthly_amount ?? detail.subscription?.gross_monthly_amount ?? savedBilling.monthly_amount ?? detail.subscription?.monthly_amount ?? 0,
    billing_day: savedBilling.billing_day ?? detail.subscription?.billing_day ?? 1,
  }
  const [editing, setEditing] = useState(!detail.contract)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [contractSection, setContractSection] = useState<'billing' | 'models' | 'capabilities' | 'limits'>('billing')
  const [planId, setPlanId] = useState(detail.plan?.id || '')
  const [selectedNiches, setSelectedNiches] = useState<BusinessNiche[]>(detail.niches || [])
  const [keys, setKeys] = useState(catalog.filter(item => item.enabled).map(item => item.key))
  const [users, setUsers] = useState(String(limits.users ?? 1)); const [devices, setDevices] = useState(String(limits.devices ?? 1)); const [units, setUnits] = useState(String(limits.units ?? 1)); const [storage, setStorage] = useState(String(limits.storage_mb ?? 128))
  const [contactName, setContactName] = useState(billing.contact_name || ''); const [email, setEmail] = useState(billing.email || ''); const [phone, setPhone] = useState(billing.phone || '')
  const [amount, setAmount] = useState(String(billing.monthly_amount || detail.subscription?.monthly_amount || 0)); const [billingDay, setBillingDay] = useState(String(billing.billing_day || detail.subscription?.billing_day || 1)); const [subscriptionStatus, setSubscriptionStatus] = useState<SubscriptionStatus>(detail.subscription?.status || 'PENDING'); const [nextDueDate, setNextDueDate] = useState(detail.subscription?.next_due_date || ''); const [reason, setReason] = useState('Atualização comercial solicitada pelo Owner.')
  const [discountType, setDiscountType] = useState<'NONE' | 'PERCENTAGE' | 'FIXED'>(detail.subscription?.discount_type || savedBilling.discount_type || 'NONE')
  const [discountValue, setDiscountValue] = useState(String(detail.subscription?.discount_value || savedBilling.discount_value || 0))
  const [discountReasonCode, setDiscountReasonCode] = useState(detail.subscription?.discount_reason_code || savedBilling.discount_reason_code || 'LAUNCH_PROMOTION')
  const [discountReason, setDiscountReason] = useState(detail.subscription?.discount_reason || savedBilling.discount_reason || 'Condição comercial autorizada pelo Owner.')
  const [discountStartsOn, setDiscountStartsOn] = useState(detail.subscription?.discount_starts_on || savedBilling.discount_starts_on || '')
  const [discountEndsOn, setDiscountEndsOn] = useState(detail.subscription?.discount_ends_on || savedBilling.discount_ends_on || '')
  const [discountReviewOn, setDiscountReviewOn] = useState(detail.subscription?.discount_review_on || savedBilling.discount_review_on || '')
  const suggested = useMemo(() => new Set(niches.filter(item => selectedNiches.includes(item.key)).flatMap(item => [...item.required_capabilities, ...item.allowed_addons].map(capability => capability.key))), [niches, selectedNiches])
  const selectedPlan = plans.find(item => item.id === planId)
  const grossAmount = Math.max(0, Number(String(amount).replace(',', '.')) || 0)
  const discountInput = Math.max(0, Number(String(discountValue).replace(',', '.')) || 0)
  const previewDiscount = discountType === 'PERCENTAGE'
    ? Math.min(grossAmount, grossAmount * discountInput / 100)
    : discountType === 'FIXED' ? Math.min(grossAmount, discountInput) : 0
  const previewNet = Math.max(0, grossAmount - previewDiscount)
  const selectablePlans = plans.filter(item => item.is_active || item.id === planId)
  const toggleNiche = (key: BusinessNiche) => setSelectedNiches(current => current.includes(key) ? current.filter(item => item !== key) : [...current, key])
  const toggleCapability = (key: string) => setKeys(current => current.includes(key) ? current.filter(item => item !== key) : [...current, key])
  const selectPlan = (value: string) => {
    setPlanId(value)
    const plan = plans.find(item => item.id === value)
    if (!plan) return
    setAmount(String(plan.monthly_price))
    setKeys(plan.capability_keys || [])
  }
  const save = async () => {
    if (saving) return
    if (!planId) { setError('Selecione um plano para salvar o contrato.'); return }
    const quotas = { users: Number(users), devices: Number(devices), units: Number(units), storage_mb: Number(storage) }
    if ([users, devices, units, storage].some(value => value === '') || Object.values(quotas).some(value => !Number.isInteger(value) || value < 1) || quotas.storage_mb < 128) {
      setError('Informe limites inteiros válidos. O storage mínimo é 128 MB.')
      return
    }
    if (!contactName.trim() || !email.trim()) {
      setError('Complete o contato e o e-mail de cobrança na seção Plano e cobrança antes de salvar.')
      return
    }
    const dueDay = Number(billingDay)
    if (!Number.isInteger(dueDay) || dueDay < 1 || dueDay > 28) { setError('O dia de vencimento deve ficar entre 1 e 28.'); return }
    if (discountType === 'PERCENTAGE' && (discountInput <= 0 || discountInput > 100)) { setError('O desconto percentual deve ficar entre 0,01% e 100%.'); return }
    if (discountType === 'FIXED' && (discountInput <= 0 || discountInput > grossAmount)) { setError('O desconto fixo deve ser positivo e não pode superar o valor-base.'); return }
    if (discountType !== 'NONE' && discountReason.trim().length < 4) { setError('Registre a justificativa do desconto.'); return }
    if (previewNet === 0 && !discountEndsOn && !discountReviewOn) { setError('Desconto de 100% exige uma data de encerramento ou revisão.'); return }
    setSaving(true)
    setError('')
    try {
      await updateOwnerTenantContract(detail.tenant.id, {
        plan_id: planId, niches: selectedNiches, capability_keys: keys, quotas,
        billing: {
          contact_name: contactName.trim(), email: email.trim(), phone: phone || undefined,
          monthly_amount: grossAmount, billing_day: dueDay,
          discount: discountType === 'NONE' ? undefined : {
            type: discountType, value: discountInput, reason_code: discountReasonCode,
            reason: discountReason.trim(), starts_on: discountStartsOn || undefined,
            ends_on: discountEndsOn || undefined, review_on: discountReviewOn || undefined,
          },
        },
        subscription_status: subscriptionStatus,
        next_due_date: nextDueDate || undefined,
        expected_contract_version: detail.contract?.version ?? 0,
        expected_billing_account_version: detail.billing_account?.version ?? 0,
        reason,
      })
      await onSaved()
      setEditing(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível salvar o contrato.')
    } finally { setSaving(false) }
  }
  if (!editing) return <div><div className="mb-5 flex justify-end"><button onClick={() => setEditing(true)} className="flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white"><Pencil className="h-4 w-4" />Editar contrato</button></div><div className="space-y-5"><section className="rounded-2xl border border-slate-200 bg-white p-6"><div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4"><Info label="Plano" value={detail.plan?.name} /><Info label="Valor bruto" value={money(detail.subscription?.gross_monthly_amount)} /><Info label="Desconto" value={money(detail.subscription?.discount_amount)} /><Info label="Mensalidade líquida" value={money(detail.subscription?.monthly_amount)} /><Info label="Vencimento contratual" value={detail.subscription?.billing_day ? `Dia ${detail.subscription.billing_day}` : undefined} /><Info label="Conta de cobrança" value={detail.billing_account?.contact_email} /></div><div className="mt-5 flex flex-col gap-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm font-semibold text-blue-900 sm:flex-row sm:items-center sm:justify-between"><p>Faturas, recebimentos e inadimplência são fatos persistidos e ficam disponíveis no Financeiro SaaS.</p><button onClick={onFinance} className="h-9 shrink-0 rounded-lg border border-blue-300 bg-white px-3 text-xs font-black">Abrir Financeiro SaaS</button></div></section><section className="rounded-2xl border border-slate-200 bg-white p-6"><h3 className="text-lg font-black">Atividades e capabilities contratadas</h3><p className="mt-2 text-sm text-slate-500">{detail.niches.length ? detail.niches.map(item => nicheLabel[item]).join(' + ') : 'Sem filtro de nicho'}</p><div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{catalog.filter(item => item.enabled).map(item => <article key={item.key} className="rounded-xl border border-emerald-200 bg-emerald-50 p-4"><div className="flex justify-between gap-3"><h4 className="font-black">{item.name}</h4><CheckCircle2 className="h-5 w-5 text-emerald-600" /></div><p className="mt-2 text-sm text-slate-600">{item.description}</p></article>)}</div></section></div></div>
  if (plans.length === 0) return <section className="rounded-2xl border border-amber-300 bg-amber-50 p-6"><p className="text-xs font-black uppercase tracking-wider text-amber-800">Contrato ainda não configurável</p><h3 className="mt-2 text-xl font-black">Cadastre um plano comercial ativo</h3><p className="mt-2 max-w-2xl text-sm text-slate-600">O plano é a referência obrigatória para mensalidade, limites e assinatura. Depois do cadastro, volte a esta organização para salvar a primeira versão do contrato.</p><button onClick={onManagePlans} className="mt-5 h-11 rounded-xl bg-[#022444] px-5 text-sm font-black text-white">Ir para Planos comerciais</button></section>
  return <div className="space-y-6">
    <div className="flex items-center justify-between"><div><h3 className="text-xl font-black">Editar contrato e mensalidade</h3><p className="mt-1 text-sm text-slate-500">Cada salvamento cria uma nova versão auditada.</p></div>{detail.contract && <button onClick={() => setEditing(false)} className="rounded-xl border border-slate-200 p-2"><X className="h-5 w-5" /></button>}</div>
    <nav className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-2">{([['billing', 'Plano e cobrança'], ['models', 'Modelos de negócio'], ['capabilities', 'Capabilities'], ['limits', 'Limites']] as Array<[typeof contractSection, string]>).map(([key, label]) => <button type="button" key={key} onClick={() => setContractSection(key)} className={`rounded-xl px-4 py-3 text-sm font-black ${contractSection === key ? 'bg-[#022444] text-white' : 'text-slate-500 hover:bg-slate-100'}`}>{label}</button>)}</nav>
    {error && <p className="rounded-xl border border-[#ffbf00] bg-amber-50 p-4 text-sm font-bold">{error}</p>}
    {contractSection === 'billing' && <section className="rounded-2xl border border-slate-200 bg-white p-6">
      <h4 className="font-black">Plano e cobrança SaaS</h4>
      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Select label="Plano" value={planId} onChange={selectPlan} options={[["", "Selecione"], ...plans.map(plan => [plan.id, `${plan.name} · ${money(plan.monthly_price)}`] as [string, string])]} />
        <TextField label="Valor-base contratado (R$)" value={amount} onChange={setAmount} />
        <NumberInput label="Dia de vencimento" value={billingDay} min={1} max={28} onChange={setBillingDay} />
        <TextField label="Próxima cobrança contratual prevista" type="date" value={nextDueDate} onChange={setNextDueDate} />
        <Select label="Assinatura" value={subscriptionStatus} onChange={value => setSubscriptionStatus(value as SubscriptionStatus)} options={[["PENDING", "Pendente"], ["TRIAL", "Avaliação"], ["ACTIVE", "Ativa"], ["PAUSED", "Pausada"], ["CANCELED", "Cancelada"]]} />
        <TextField label="Contato de cobrança" value={contactName} onChange={setContactName} />
        <TextField label="E-mail de cobrança" value={email} onChange={setEmail} />
        <TextField label="Telefone de cobrança" value={formatBrazilianPhone(phone)} onChange={value => setPhone(onlyDigits(value, 11))} />
      </div>
      <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center"><div><h5 className="font-black">Desconto contratual</h5><p className="text-sm text-slate-500">Aplicado pelo Owner sem alterar o preço de tabela do plano.</p></div><Select label="Tipo" value={discountType} onChange={value => setDiscountType(value as typeof discountType)} options={[["NONE", "Sem desconto"], ["FIXED", "Valor fixo"], ["PERCENTAGE", "Percentual"]]} /></div>
        {discountType !== 'NONE' && <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <TextField label={discountType === 'PERCENTAGE' ? 'Desconto (%)' : 'Desconto (R$)'} value={discountValue} onChange={setDiscountValue} />
          <Select label="Motivo" value={discountReasonCode} onChange={setDiscountReasonCode} options={[["INTERNAL_CONTROLLED_TEST", "Teste interno controlado"], ["COMMERCIAL_PILOT", "Piloto comercial"], ["LAUNCH_PROMOTION", "Promoção de lançamento"], ["PARTNERSHIP", "Parceria"], ["RETENTION", "Retenção"], ["COMMERCIAL_NEGOTIATION", "Negociação comercial"], ["SERVICE_COMPENSATION", "Compensação de serviço"]]} />
          <TextField label="Início" type="date" value={discountStartsOn} onChange={setDiscountStartsOn} />
          <TextField label="Encerramento" type="date" value={discountEndsOn} onChange={setDiscountEndsOn} />
          <div className="md:col-span-2 xl:col-span-3"><TextField label="Justificativa auditável" value={discountReason} onChange={setDiscountReason} /></div>
          <TextField label="Revisar em" type="date" value={discountReviewOn} onChange={setDiscountReviewOn} />
        </div>}
        <div className="mt-4 grid gap-3 sm:grid-cols-3"><Info label="Valor bruto" value={money(grossAmount)} /><Info label="Desconto" value={money(previewDiscount)} /><Info label="Valor líquido da fatura" value={money(previewNet)} /></div>
        {previewNet === 0 && <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm font-bold text-amber-900">A fatura será emitida sem valor a pagar; ela não será marcada como recebida.</p>}
      </div>
      <div className="mt-4 flex flex-col gap-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm font-semibold text-blue-900 sm:flex-row sm:items-center sm:justify-between"><p>Este contrato define as fontes da cobrança. Faturas, recebimentos e inadimplência são administrados no Financeiro SaaS.</p><button onClick={onFinance} className="h-9 shrink-0 rounded-lg border border-blue-300 bg-white px-3 text-xs font-black">Abrir Financeiro SaaS</button></div>
    </section>}
    {contractSection === 'models' && <section className="rounded-2xl border border-slate-200 bg-white p-6"><h4 className="font-black">Definir segmentos do negócio</h4><p className="mt-1 text-sm text-slate-500">Defina um ou mais segmentos contratados. Combinações híbridas são permitidas e podem ser alteradas.</p><div className="mt-5 grid gap-3 md:grid-cols-3">{niches.map(niche => <button key={niche.key} onClick={() => toggleNiche(niche.key)} className={`rounded-xl border-2 p-4 text-left ${selectedNiches.includes(niche.key) ? 'border-[#E12120] bg-red-50' : 'border-slate-200'}`}><div className="flex justify-between gap-3"><span className="font-black">{niche.name}</span>{selectedNiches.includes(niche.key) && <Check className="h-5 w-5 text-[#E12120]" />}</div><p className="mt-2 text-sm text-slate-500">{niche.description}</p></button>)}</div></section>}
    {contractSection === 'capabilities' && <section className="rounded-2xl border border-slate-200 bg-white p-6"><h4 className="font-black">Capabilities contratadas</h4><p className="mt-1 text-sm text-slate-500">Âmbar indica sugestão; verde indica contratação efetiva.</p><div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{catalog.map(item => <button key={item.key} onClick={() => toggleCapability(item.key)} className={`rounded-xl border-2 p-4 text-left ${keys.includes(item.key) ? 'border-emerald-400 bg-emerald-50' : suggested.has(item.key) ? 'border-[#ffbf00] bg-amber-50' : 'border-slate-200'}`}><div className="flex justify-between gap-3"><span className="font-black">{item.name}</span>{keys.includes(item.key) && <Check className="h-5 w-5 text-emerald-600" />}</div><p className="mt-2 text-sm text-slate-500">{item.description}</p></button>)}</div></section>}
    {contractSection === 'limits' && <section className="rounded-2xl border border-slate-200 bg-white p-6"><h4 className="font-black">Limites contratados</h4><div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><NumberInput label="Usuários" value={users} max={selectedPlan?.user_limit} onChange={setUsers} /><NumberInput label="Dispositivos" value={devices} max={selectedPlan?.terminal_limit} onChange={setDevices} /><NumberInput label="Unidades" value={units} max={selectedPlan?.store_limit} onChange={setUnits} /><NumberInput label="Storage (MB)" value={storage} min={128} max={selectedPlan?.storage_limit_mb} onChange={setStorage} /></div></section>}
    <TextField label="Motivo da alteração" value={reason} onChange={setReason} />
    <button onClick={save} disabled={saving} className="flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white disabled:opacity-40">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{saving ? 'Salvando…' : 'Salvar nova versão'}</button>
    {error && <p className="text-sm font-bold text-[#8a6100]">A alteração não foi salva. {error}</p>}
  </div>
}

function AdministratorPanel({ tenantId, admin, onSaved }: { tenantId: string; admin: PlatformTenantDetail['accesses'][number] | undefined; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState({ full_name: admin?.full_name || '', email: admin?.email || '', reason: 'Alteração solicitada pelo cliente ao Owner.' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (saving) return
    setSaving(true); setError('')
    try {
      await replacePlatformTenantAdministrator(tenantId, { ...form, current_membership_id: admin?.membership_id })
      await onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível atualizar o administrador.') }
    finally { setSaving(false) }
  }
  return <section className="rounded-2xl border border-slate-200 bg-white p-6"><h3 className="text-xl font-black">Administrador contratual</h3><p className="mt-2 text-sm text-slate-500">O Owner pode corrigir ou substituir este acesso mediante solicitação do cliente. A equipe operacional continua sob responsabilidade do tenant.</p>{admin && <div className="mt-5 rounded-xl bg-emerald-50 p-4 text-sm"><strong>Acesso atual:</strong> {admin.full_name} · {admin.email} · {admin.status}</div>}<form onSubmit={submit} className="mt-6 grid gap-4 sm:grid-cols-2"><TextField label="Nome" value={form.full_name} onChange={value => setForm(current => ({ ...current, full_name: value }))} /><TextField label="E-mail administrativo" type="email" value={form.email} onChange={value => setForm(current => ({ ...current, email: value }))} /><div className="sm:col-span-2"><TextField label="Motivo da alteração" value={form.reason} onChange={value => setForm(current => ({ ...current, reason: value }))} /></div>{error && <p className="rounded-xl border border-[#ffbf00] bg-amber-50 p-3 text-sm font-bold text-[#6b4b00] sm:col-span-2">A alteração não foi salva. {error}</p>}<button disabled={saving || !form.email.includes('@') || form.full_name.trim().length < 2 || form.reason.trim().length < 4} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white disabled:opacity-40 sm:col-span-2 sm:w-fit">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}{saving ? 'Salvando…' : admin ? 'Salvar ou substituir administrador' : 'Entregar primeiro acesso'}</button></form></section>
}
function Card({ icon: Icon, title, value, hint }: { icon: React.ComponentType<{ className?: string }>; title: string; value: string; hint: string }) { return <article className="rounded-2xl border border-slate-200 bg-white p-6"><Icon className="h-6 w-6 text-[#E12120]" /><p className="mt-4 text-xs font-black uppercase text-slate-400">{title}</p><p className="mt-2 text-xl font-black">{value}</p><p className="mt-2 text-sm text-slate-500">{hint}</p></article> }
function Limit({ label, value }: { label: string; value: unknown }) { return <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs font-black uppercase text-slate-400">{label === 'Storage' ? 'Storage · sem medição' : label}</p><p className="mt-2 text-2xl font-black">{value === undefined ? '—' : String(value)}</p></div> }
function InfoSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="rounded-2xl border border-slate-200 bg-white p-6"><h3 className="border-b border-slate-100 pb-4 text-lg font-black">{title}</h3><div className="mt-5 grid gap-5 sm:grid-cols-2">{children}</div></section> }
function Info({ label, value }: { label: string; value?: string | null }) { return <div><p className="text-xs font-black uppercase text-slate-400">{label}</p><p className="mt-2 font-semibold">{value || 'Não informado'}</p></div> }
function TextField({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) { return <label className="text-sm font-black">{label}<input type={type} value={value} onChange={event => onChange(event.target.value)} className={inputClass} /></label> }
function NumberInput({ label, value, onChange, min = 1, max }: { label: string; value: string; onChange: (value: string) => void; min?: number; max?: number }) { return <label className="text-sm font-black">{label === 'Storage (MB)' ? 'Storage (MB) — contratual, sem medição' : label}<input type="text" inputMode="numeric" value={value} onChange={event => onChange(onlyDigits(event.target.value).replace(/^0+(?=\d)/, ''))} className={inputClass} />{max && <span className="mt-1 block text-xs text-slate-400">Teto do plano: {max}</span>}{min > 1 && <span className="mt-1 block text-xs text-slate-400">Mínimo: {min}</span>}</label> }
function Select({ label, value, options, onChange }: { label: string; value: string; options: Array<[string, string]>; onChange: (value: string) => void }) { return <label className="text-sm font-black">{label}<select value={value} onChange={event => onChange(event.target.value)} className={inputClass}>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label> }
function LifecycleModal({ status, onClose, onConfirm }: { status: 'PAUSED' | 'ARCHIVED'; onClose: () => void; onConfirm: (reason: string) => Promise<void> }) { const [reason, setReason] = useState(''); const [saving, setSaving] = useState(false); const [error, setError] = useState(''); const submit = async (event: React.FormEvent) => { event.preventDefault(); setSaving(true); try { await onConfirm(reason) } catch (cause) { setError(cause instanceof Error ? cause.message : 'Não foi possível concluir.'); setSaving(false) } }; return <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#022444]/60 p-4"><button className="absolute inset-0" onClick={onClose} /><form onSubmit={submit} className="relative w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"><h2 className="text-xl font-black">{status === 'PAUSED' ? 'Pausar' : 'Arquivar'} cliente</h2><p className="mt-2 text-sm text-slate-500">A ação preserva contrato, cadastro e auditoria.</p><TextField label="Motivo" value={reason} onChange={setReason} />{error && <p className="mt-3 text-sm font-bold text-red-700">{error}</p>}<div className="mt-6 flex gap-3"><button type="button" onClick={onClose} className="h-11 flex-1 rounded-xl border border-slate-300 font-black">Cancelar</button><button disabled={saving || reason.trim().length < 3} className="h-11 flex-1 rounded-xl bg-[#E12120] font-black text-white disabled:opacity-40">Confirmar</button></div></form></div> }
