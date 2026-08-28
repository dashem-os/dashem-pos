import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Building2, Check, Loader2, Plus, ShieldCheck, X } from 'lucide-react'
import {
  BusinessNiche, fetchOwnerCapabilityCatalog, fetchOwnerNiches, fetchServicePlans,
  OwnerNiche, OwnerNicheCapability, provisionPlatformTenant, ServicePlan,
  TenantPhase, TenantType,
} from '../../services/api'
import { formatBrazilianPhone, formatBrazilianPostalCode, lookupBrazilianPostalCode, onlyDigits } from '../../utils/brazil'

type FormState = {
  name: string; legalName: string; slug: string; tenantType: TenantType; phase: TenantPhase; taxId: string
  companyPhone: string; companyEmail: string; contactName: string; contactEmail: string; contactPhone: string
  billingName: string; billingEmail: string; billingPhone: string; monthlyAmount: string; billingDay: string
  storeName: string; storeCode: string; postalCode: string; street: string; streetNumber: string
  complement: string; district: string; city: string; state: string
  niches: BusinessNiche[]; planId: string; capabilityKeys: string[]
  users: string; devices: string; units: string; storageMb: string
  adminName: string; adminEmail: string
}

const steps = ['Cadastro', 'Modelos de negócio', 'Plano', 'Capabilities', 'Limites', 'Administrador']
const initialForm: FormState = {
  name: '', legalName: '', slug: '', tenantType: 'CUSTOMER', phase: 'PILOT', taxId: '',
  companyPhone: '', companyEmail: '', contactName: '', contactEmail: '', contactPhone: '',
  billingName: '', billingEmail: '', billingPhone: '', monthlyAmount: '0,00', billingDay: '1',
  storeName: 'Matriz', storeCode: 'MATRIZ', postalCode: '', street: '', streetNumber: '',
  complement: '', district: '', city: '', state: '', niches: [], planId: '', capabilityKeys: [],
  users: '2', devices: '1', units: '1', storageMb: '1024', adminName: '', adminEmail: '',
}
const inputClass = 'mt-2 h-11 w-full rounded-xl border bg-white px-3 font-semibold outline-none transition focus:ring-4'
const digits = (value: string, max = 14) => onlyDigits(value, max)
const normalizeSlug = (value: string) => value.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80)
const moneyNumber = (value: string) => Number(value.replace(/\./g, '').replace(',', '.')) || 0
const nicheLabel: Record<BusinessNiche, string> = { FOOD_SERVICE: 'Food Service', RETAIL: 'Retail', BEAUTY_RESELLER: 'Beauty Reseller' }

function validCpf(value: string) {
  if (value.length !== 11 || /^(\d)\1+$/.test(value)) return false
  const calc = (size: number) => { const sum = value.slice(0, size).split('').reduce((total, digit, index) => total + Number(digit) * (size + 1 - index), 0); const rest = (sum * 10) % 11; return rest === 10 ? 0 : rest }
  return calc(9) === Number(value[9]) && calc(10) === Number(value[10])
}
function validCnpj(value: string) {
  if (value.length !== 14 || /^(\d)\1+$/.test(value)) return false
  const numbers = value.split('').map(Number)
  for (const size of [12, 13]) { const weights = [...Array(size - 8).keys()].map(index => size - 7 - index).concat([9, 8, 7, 6, 5, 4, 3, 2]); const total = numbers.slice(0, size).reduce((sum, number, index) => sum + number * weights[index], 0); const rest = total % 11; if (numbers[size] !== (rest < 2 ? 0 : 11 - rest)) return false }
  return true
}
const validTaxId = (value: string) => value.length === 11 ? validCpf(value) : value.length === 14 && validCnpj(value)
const formatTaxId = (value: string) => value.length <= 11
  ? value.replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d{1,2})$/, '$1-$2')
  : value.replace(/(\d{2})(\d)/, '$1.$2').replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d)/, '$1/$2').replace(/(\d{4})(\d{1,2})$/, '$1-$2')

export function CreateTenantPanel({ onClose, onCreated, onManagePlans }: { onClose: () => void; onCreated: () => void; onManagePlans: () => void }) {
  const [form, setForm] = useState<FormState>(initialForm)
  const [step, setStep] = useState(0)
  const [niches, setNiches] = useState<OwnerNiche[]>([])
  const [plans, setPlans] = useState<ServicePlan[]>([])
  const [capabilities, setCapabilities] = useState<OwnerNicheCapability[]>([])
  const [loadingCatalog, setLoadingCatalog] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [slugTouched, setSlugTouched] = useState(false)

  useEffect(() => {
    Promise.all([fetchOwnerNiches(), fetchServicePlans(), fetchOwnerCapabilityCatalog()])
      .then(([nicheRows, planRows, capabilityRows]) => { setNiches(nicheRows); setPlans(planRows.filter(item => item.is_active)); setCapabilities(capabilityRows) })
      .catch(reason => setError(reason instanceof Error ? reason.message : 'Não foi possível carregar o contrato.'))
      .finally(() => setLoadingCatalog(false))
  }, [])

  const selectedPlan = plans.find(item => item.id === form.planId)
  const suggestedKeys = useMemo(() => new Set(niches.filter(niche => form.niches.includes(niche.key)).flatMap(niche => [...niche.required_capabilities, ...niche.allowed_addons].map(item => item.key))), [form.niches, niches])
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => { setForm(current => ({ ...current, [key]: value })); setFieldErrors(current => { const next = { ...current }; delete next[key]; return next }) }
  const setPostalCode = async (value: string) => {
    const postalCode = digits(value, 8)
    set('postalCode', postalCode)
    if (postalCode.length !== 8) return
    try {
      const address = await lookupBrazilianPostalCode(postalCode)
      setForm(current => ({ ...current, street: address.street, district: address.district, city: address.city, state: address.state, complement: current.complement || address.complement }))
      setError('')
    } catch (reason) { setFieldErrors(current => ({ ...current, postalCode: reason instanceof Error ? reason.message : 'CEP não encontrado.' })) }
  }

  const errorsForStep = () => {
    const required: Record<string, string> = {}
    if (step === 0) {
      if (form.name.trim().length < 2) required.name = 'Informe o nome fantasia.'
      if (form.legalName.trim().length < 2) required.legalName = form.taxId.length === 11 ? 'Informe o nome civil.' : 'Informe a razão social.'
      if (!validTaxId(form.taxId)) required.taxId = 'Informe um CPF ou CNPJ válido.'
      if (form.slug.length < 3) required.slug = 'Informe um identificador técnico.'
      if (form.companyPhone.trim().length < 8) required.companyPhone = 'Informe o telefone da empresa.'
      if (form.contactName.trim().length < 2) required.contactName = 'Informe o responsável contratual.'
      if (!form.contactEmail.includes('@')) required.contactEmail = 'Informe um e-mail válido.'
      if (form.billingName.trim().length < 2) required.billingName = 'Informe o contato de cobrança.'
      if (!form.billingEmail.includes('@')) required.billingEmail = 'Informe o e-mail de cobrança.'
      if (form.storeName.trim().length < 2) required.storeName = 'Informe o nome da matriz.'
      if (digits(form.postalCode, 8).length !== 8) required.postalCode = 'Informe um CEP válido.'
      if (form.street.trim().length < 2) required.street = 'Informe o logradouro.'
      if (!form.streetNumber.trim()) required.streetNumber = 'Informe o número.'
      if (form.district.trim().length < 2) required.district = 'Informe o bairro.'
      if (form.city.trim().length < 2) required.city = 'Informe a cidade.'
      if (form.state.length !== 2) required.state = 'Informe a UF.'
    }
    if (step === 2 && !form.planId) required.planId = 'Selecione um plano.'
    if (step === 4) {
      if (!form.users || Number(form.users) < 1 || (selectedPlan?.user_limit && Number(form.users) > selectedPlan.user_limit)) required.users = 'Revise o limite de usuários.'
      if (!form.devices || Number(form.devices) < 1 || (selectedPlan?.terminal_limit && Number(form.devices) > selectedPlan.terminal_limit)) required.devices = 'Revise o limite de dispositivos.'
      if (!form.units || Number(form.units) < 1 || (selectedPlan?.store_limit && Number(form.units) > selectedPlan.store_limit)) required.units = 'Revise o limite de unidades.'
      if (!form.storageMb || Number(form.storageMb) < 128 || (selectedPlan?.storage_limit_mb && Number(form.storageMb) > selectedPlan.storage_limit_mb)) required.storageMb = 'Revise o limite de storage.'
    }
    if (step === 5) { if (form.adminName.trim().length < 2) required.adminName = 'Informe o nome do administrador.'; if (!form.adminEmail.includes('@')) required.adminEmail = 'Informe um e-mail válido.' }
    return required
  }
  const advance = () => {
    if (step === 1 && plans.length === 0) { onManagePlans(); return }
    const errors = errorsForStep()
    if (Object.keys(errors).length) { setFieldErrors(errors); setError('Revise os campos destacados para continuar.'); const first = document.getElementById(`owner-${Object.keys(errors)[0]}`); first?.scrollIntoView({ behavior: 'smooth', block: 'center' }); first?.focus(); return }
    setError(''); setFieldErrors({}); setStep(value => value + 1)
  }
  const toggleNiche = (key: BusinessNiche) => setForm(current => ({
    ...current,
    niches: current.niches.includes(key)
      ? current.niches.filter(item => item !== key)
      : [...current.niches, key],
  }))
  const toggleCapability = (key: string) => set('capabilityKeys', form.capabilityKeys.includes(key) ? form.capabilityKeys.filter(item => item !== key) : [...form.capabilityKeys, key])
  const selectPlan = (plan: ServicePlan) => setForm(current => ({ ...current, planId: plan.id, monthlyAmount: Number(plan.monthly_price || 0).toFixed(2).replace('.', ','), users: String(Math.min(Number(current.users || 1), plan.user_limit ?? Number(current.users || 1))), devices: String(Math.min(Number(current.devices || 1), plan.terminal_limit ?? Number(current.devices || 1))), units: String(Math.min(Number(current.units || 1), plan.store_limit ?? Number(current.units || 1))), storageMb: String(Math.min(Number(current.storageMb || 128), plan.storage_limit_mb ?? Number(current.storageMb || 128))) }))
  const submit = async () => {
    const errors = errorsForStep(); if (Object.keys(errors).length) { setFieldErrors(errors); setError('Revise os campos destacados para provisionar.'); return }
    setSaving(true); setError('')
    try {
      await provisionPlatformTenant({
        name: form.name.trim(), slug: form.slug, first_store_name: form.storeName.trim(), first_store_code: form.storeCode.trim().toUpperCase(),
        tenant_type: form.tenantType, lifecycle_phase: form.phase, legal_name: form.legalName.trim(), tax_id: form.taxId,
        company_email: form.companyEmail.trim() || undefined, company_phone: form.companyPhone.trim(), contact_name: form.contactName.trim(),
        contact_email: form.contactEmail.trim(), contact_phone: form.contactPhone.trim() || undefined, postal_code: form.postalCode,
        street: form.street.trim(), street_number: form.streetNumber.trim(), address_complement: form.complement.trim() || undefined,
        district: form.district.trim(), city: form.city.trim(), state: form.state, plan_id: form.planId, niches: form.niches,
        quotas: { users: Number(form.users), devices: Number(form.devices), units: Number(form.units), storage_mb: Number(form.storageMb) }, capability_keys: form.capabilityKeys,
        billing: { contact_name: form.billingName.trim(), email: form.billingEmail.trim(), phone: form.billingPhone.trim() || undefined, monthly_amount: moneyNumber(form.monthlyAmount), billing_day: Number(form.billingDay) },
        initial_admin: { full_name: form.adminName.trim(), email: form.adminEmail.trim() },
      })
      onCreated()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível provisionar o tenant.') } finally { setSaving(false) }
  }

  return <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-[#022444]/70 p-0 backdrop-blur-sm sm:p-5">
    <button className="absolute inset-0" onClick={onClose} aria-label="Fechar" />
    <section className="relative flex h-full w-full max-w-[1450px] flex-col overflow-hidden bg-white text-[#022444] shadow-2xl sm:h-[calc(100vh-2.5rem)] sm:rounded-3xl">
      <header className="flex items-start justify-between border-b border-slate-200 px-5 py-5 sm:px-8"><div><p className="text-xs font-black uppercase tracking-[.16em] text-[#E12120]">OWNER · PROVISIONAMENTO</p><h2 className="mt-1 text-2xl font-black">Novo cliente SaaS</h2><p className="mt-1 text-sm text-slate-500">Cadastro, contrato, sugestões e administrador em um fluxo revisável.</p></div><button onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500"><X /></button></header>
      <ol className="flex gap-2 overflow-x-auto border-b border-slate-200 px-5 py-3 sm:px-8">{steps.map((label, index) => <li key={label} className={`flex shrink-0 items-center gap-2 rounded-full px-4 py-2 text-xs font-black ${index === step ? 'bg-[#022444] text-white' : index < step ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{index < step && <Check className="h-3.5 w-3.5" />}{label}</li>)}</ol>
      <div className="flex-1 overflow-y-auto p-5 sm:p-8">{loadingCatalog ? <Loader2 className="mx-auto mt-24 h-8 w-8 animate-spin text-[#E12120]" /> : <>
        {error && <p className="mb-5 rounded-xl border border-[#ffbf00] bg-amber-50 p-4 text-sm font-bold text-[#6b4b00]">{error}</p>}
        {step === 0 && <div className="space-y-7"><Section title="Empresa e contrato"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Field id="name" label="Nome fantasia" value={form.name} error={fieldErrors.name} onChange={value => { set('name', value); if (!slugTouched) setForm(current => ({ ...current, name: value, slug: normalizeSlug(value) })) }} />
          <Field id="legalName" label={form.taxId.length === 11 ? 'Nome civil' : 'Razão social / nome civil'} value={form.legalName} error={fieldErrors.legalName} onChange={value => set('legalName', value)} />
          <Field id="taxId" label={form.taxId.length === 11 ? 'CPF' : form.taxId.length === 14 ? 'CNPJ' : 'CPF ou CNPJ'} value={formatTaxId(form.taxId)} error={fieldErrors.taxId} inputMode="numeric" onChange={value => set('taxId', digits(value))} />
          <SelectField label="Tipo de tenant" value={form.tenantType} onChange={value => set('tenantType', value as TenantType)} options={[["CUSTOMER", "Cliente"], ["INTERNAL", "Operação interna"]]} />
          <SelectField label="Fase" value={form.phase} onChange={value => set('phase', value as TenantPhase)} options={[["TEST", "Teste controlado"], ["PILOT", "Piloto"], ["PRODUCTION", "Produção"]]} />
          <Field id="companyPhone" label="Telefone da empresa" value={formatBrazilianPhone(form.companyPhone)} error={fieldErrors.companyPhone} inputMode="tel" onChange={value => set('companyPhone', digits(value, 11))} />
          <Field id="companyEmail" label="E-mail da empresa" value={form.companyEmail} type="email" onChange={value => set('companyEmail', value)} />
          <Field id="slug" label="Identificador técnico" value={form.slug} error={fieldErrors.slug} onChange={value => { setSlugTouched(true); set('slug', normalizeSlug(value)) }} />
        </div></Section><Section title="Responsável e cobrança"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Field id="contactName" label="Responsável contratual" value={form.contactName} error={fieldErrors.contactName} onChange={value => set('contactName', value)} /><Field id="contactEmail" label="E-mail do responsável" value={form.contactEmail} error={fieldErrors.contactEmail} type="email" onChange={value => set('contactEmail', value)} /><Field id="contactPhone" label="Telefone do responsável" value={formatBrazilianPhone(form.contactPhone)} inputMode="tel" onChange={value => set('contactPhone', digits(value, 11))} />
          <Field id="billingName" label="Contato de cobrança" value={form.billingName} error={fieldErrors.billingName} onChange={value => set('billingName', value)} /><Field id="billingEmail" label="E-mail de cobrança" value={form.billingEmail} error={fieldErrors.billingEmail} type="email" onChange={value => set('billingEmail', value)} /><Field id="billingPhone" label="Telefone de cobrança" value={formatBrazilianPhone(form.billingPhone)} inputMode="tel" onChange={value => set('billingPhone', digits(value, 11))} />
          <Field id="monthlyAmount" label="Mensalidade negociada (R$)" value={form.monthlyAmount} inputMode="decimal" onChange={value => set('monthlyAmount', value)} /><NumberField id="billingDay" label="Dia de vencimento" value={form.billingDay} min={1} max={28} onChange={value => set('billingDay', value)} />
        </div></Section><Section title="Matriz"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Field id="storeName" label="Nome da unidade" value={form.storeName} error={fieldErrors.storeName} onChange={value => set('storeName', value)} /><Field id="storeCode" label="Código" value={form.storeCode} onChange={value => set('storeCode', value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''))} /><Field id="postalCode" label="CEP" value={formatBrazilianPostalCode(form.postalCode)} error={fieldErrors.postalCode} inputMode="numeric" onChange={setPostalCode} /><Field id="street" label="Logradouro" value={form.street} error={fieldErrors.street} onChange={value => set('street', value)} />
          <Field id="streetNumber" label="Número" value={form.streetNumber} error={fieldErrors.streetNumber} onChange={value => set('streetNumber', value)} /><Field id="complement" label="Complemento" value={form.complement} onChange={value => set('complement', value)} /><Field id="district" label="Bairro" value={form.district} error={fieldErrors.district} onChange={value => set('district', value)} /><Field id="city" label="Cidade" value={form.city} error={fieldErrors.city} onChange={value => set('city', value)} /><Field id="state" label="UF" value={form.state} error={fieldErrors.state} onChange={value => set('state', value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 2))} />
        </div></Section></div>}
        {step === 1 && <div><h3 className="text-xl font-black">Definir segmentos do negócio</h3><p className="mt-2 max-w-3xl text-sm text-slate-500">Selecione nenhum, um ou vários modelos contratuais. Combinações híbridas são permitidas e podem ser alteradas depois.</p><ChoiceGrid>{niches.map(niche => <ChoiceCard key={niche.key} selected={form.niches.includes(niche.key)} title={niche.name} description={niche.description} onClick={() => toggleNiche(niche.key)} footer={`${niche.required_capabilities.length} capabilities compatíveis`} />)}</ChoiceGrid></div>}
        {step === 2 && <div><h3 className="text-xl font-black">Plano comercial</h3><ChoiceGrid>{plans.map(plan => <ChoiceCard key={plan.id} selected={form.planId === plan.id} invalid={Boolean(fieldErrors.planId)} title={plan.name} description={plan.description || 'Plano comercial ativo'} onClick={() => { selectPlan(plan); setFieldErrors({}) }} footer={`R$ ${Number(plan.monthly_price || 0).toFixed(2).replace('.', ',')} · ${plan.user_limit ?? '∞'} usuários · ${plan.terminal_limit ?? '∞'} dispositivos`} />)}</ChoiceGrid></div>}
        {step === 3 && <div><h3 className="text-xl font-black">Prévia de capabilities</h3><p className="mt-2 text-sm text-slate-500">As capabilities compatíveis aparecem destacadas, mas todo o catálogo continua disponível para contratação.</p><div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{capabilities.map(capability => <button key={capability.key} type="button" onClick={() => toggleCapability(capability.key)} className={`rounded-xl border-2 p-4 text-left transition ${form.capabilityKeys.includes(capability.key) ? 'border-emerald-400 bg-emerald-50' : suggestedKeys.has(capability.key) ? 'border-[#ffbf00] bg-amber-50' : 'border-slate-200 bg-white'}`}><div className="flex items-start justify-between gap-3"><p className="font-black">{capability.name}</p>{form.capabilityKeys.includes(capability.key) && <span className="rounded-full bg-emerald-600 p-1 text-white"><Check className="h-3.5 w-3.5" /></span>}</div><p className="mt-2 text-sm text-slate-600">{capability.description}</p><p className="mt-3 text-xs font-black uppercase text-slate-400">{suggestedKeys.has(capability.key) ? 'Compatível com os modelos' : 'Catálogo geral'}</p></button>)}</div></div>}
        {step === 4 && <div><h3 className="text-xl font-black">Limites contratados</h3><p className="mt-2 text-sm text-slate-500">Ajuste dentro do teto do plano. Estes valores poderão ser editados depois.</p><div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><NumberField id="users" label="Usuários" value={form.users} error={fieldErrors.users} max={selectedPlan?.user_limit} onChange={value => set('users', value)} /><NumberField id="devices" label="Dispositivos" value={form.devices} error={fieldErrors.devices} max={selectedPlan?.terminal_limit} onChange={value => set('devices', value)} /><NumberField id="units" label="Unidades" value={form.units} error={fieldErrors.units} max={selectedPlan?.store_limit} onChange={value => set('units', value)} /><NumberField id="storageMb" label="Storage (MB)" value={form.storageMb} error={fieldErrors.storageMb} max={selectedPlan?.storage_limit_mb} min={128} onChange={value => set('storageMb', value)} /></div></div>}
        {step === 5 && <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]"><Section title="Primeiro administrador"><div className="grid gap-4"><Field id="adminName" label="Nome completo" value={form.adminName} error={fieldErrors.adminName} onChange={value => set('adminName', value)} /><Field id="adminEmail" label="E-mail de acesso" value={form.adminEmail} error={fieldErrors.adminEmail} type="email" onChange={value => set('adminEmail', value)} /><p className="rounded-xl bg-blue-50 p-4 text-sm font-semibold text-blue-900">O Owner entrega somente o acesso administrativo. A equipe operacional será gerida pelo cliente.</p></div></Section><section className="rounded-2xl bg-[#022444] p-6 text-white"><div className="flex items-center gap-3"><ShieldCheck className="h-6 w-6 text-emerald-400" /><h3 className="text-xl font-black">Prévia do contrato</h3></div><dl className="mt-6 space-y-3 text-sm"><Summary label="Cliente" value={form.name} /><Summary label="Tipo e fase" value={`${form.tenantType === 'CUSTOMER' ? 'Cliente' : 'Interno'} · ${form.phase}`} /><Summary label="Modelos de negócio" value={form.niches.length ? form.niches.map(item => nicheLabel[item]).join(' + ') : 'Sem filtro de nicho'} /><Summary label="Plano" value={selectedPlan?.name || ''} /><Summary label="Capabilities" value={`${form.capabilityKeys.length} selecionadas`} /><Summary label="Mensalidade" value={`R$ ${form.monthlyAmount} · dia ${form.billingDay}`} /></dl></section></div>}
      </>}</div>
      <footer className="flex items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-5 py-4 sm:px-8"><button type="button" onClick={() => step === 0 ? onClose() : setStep(value => value - 1)} className="flex h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 font-black text-slate-600"><ArrowLeft className="h-4 w-4" />{step === 0 ? 'Cancelar' : 'Voltar'}</button>{step < steps.length - 1 ? <button onClick={advance} disabled={loadingCatalog} className="flex h-11 items-center gap-2 rounded-xl bg-[#022444] px-6 font-black text-white disabled:opacity-35">Continuar<ArrowRight className="h-4 w-4" /></button> : <button disabled={saving} onClick={submit} className="flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-6 font-black text-white disabled:opacity-35">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}{saving ? 'Provisionando…' : 'Provisionar tenant'}</button>}</footer>
    </section>
  </div>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section><h3 className="flex items-center gap-2 border-b border-slate-200 pb-3 text-lg font-black"><Building2 className="h-5 w-5 text-[#E12120]" />{title}</h3><div className="mt-5">{children}</div></section> }
function ChoiceGrid({ children }: { children: React.ReactNode }) { return <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{children}</div> }
function ChoiceCard({ selected, invalid, title, description, footer, onClick }: { selected: boolean; invalid?: boolean; title: string; description: string; footer: string; onClick: () => void }) { return <button type="button" onClick={onClick} className={`rounded-2xl border-2 p-6 text-left transition ${selected ? 'border-[#E12120] bg-red-50 shadow-lg shadow-red-100' : invalid ? 'border-[#ffbf00] bg-amber-50' : 'border-slate-200 hover:border-slate-400'}`}><div className="flex items-center justify-between"><h4 className="text-xl font-black">{title}</h4>{selected && <span className="rounded-full bg-[#E12120] p-1 text-white"><Check className="h-4 w-4" /></span>}</div><p className="mt-3 min-h-16 text-sm leading-6 text-slate-600">{description}</p><p className="mt-4 border-t border-current/10 pt-4 text-xs font-black text-slate-500">{footer}</p></button> }
function Field({ id, label, value, onChange, type = 'text', inputMode, error }: { id: string; label: string; value: string; onChange: (value: string) => void; type?: string; inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode']; error?: string }) { return <label className="text-sm font-black">{label}<input id={`owner-${id}`} type={type} inputMode={inputMode} value={value} onChange={event => onChange(event.target.value)} className={`${inputClass} ${error ? 'border-[#ffbf00] focus:border-[#ffbf00] focus:ring-amber-100' : 'border-slate-300 focus:border-[#E12120] focus:ring-red-100'}`} />{error && <span className="mt-1 block text-xs font-bold text-[#8a6100]">{error}</span>}</label> }
function SelectField({ label, value, options, onChange }: { label: string; value: string; options: Array<[string, string]>; onChange: (value: string) => void }) { return <label className="text-sm font-black">{label}<select value={value} onChange={event => onChange(event.target.value)} className={`${inputClass} border-slate-300 focus:border-[#E12120] focus:ring-red-100`}>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label> }
function NumberField({ id, label, value, onChange, min = 1, max, error }: { id: string; label: string; value: string; onChange: (value: string) => void; min?: number; max?: number; error?: string }) { return <label className="text-sm font-black">{label}<input id={`owner-${id}`} type="text" inputMode="numeric" value={value} onChange={event => onChange(digits(event.target.value).replace(/^0+(?=\d)/, ''))} className={`${inputClass} ${error ? 'border-[#ffbf00] focus:border-[#ffbf00] focus:ring-amber-100' : 'border-slate-300 focus:border-[#E12120] focus:ring-red-100'}`} />{max && <span className="mt-1 block text-xs text-slate-400">Teto do plano: {max}</span>}{min > 1 && <span className="mt-1 block text-xs text-slate-400">Mínimo: {min}</span>}{error && <span className="mt-1 block text-xs font-bold text-[#8a6100]">{error}</span>}</label> }
function Summary({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4 border-b border-white/10 pb-3"><dt className="text-slate-400">{label}</dt><dd className="text-right font-black">{value || '—'}</dd></div> }
