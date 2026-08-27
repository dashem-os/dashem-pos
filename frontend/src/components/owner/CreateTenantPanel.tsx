import React, { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Building2, Check, Loader2, Plus, ShieldCheck, X } from 'lucide-react'

import {
  BusinessNiche, fetchOwnerNiches, fetchServicePlans, OwnerNiche,
  provisionPlatformTenant, ServicePlan, TenantCustomerType,
} from '../../services/api'

type FormState = {
  name: string; legalName: string; slug: string; customerType: TenantCustomerType; taxId: string
  companyEmail: string; companyPhone: string; contactName: string; contactEmail: string; contactPhone: string
  billingName: string; billingEmail: string; billingPhone: string
  storeName: string; storeCode: string; postalCode: string; street: string; streetNumber: string; district: string; city: string; state: string
  niche: BusinessNiche | ''; planId: string; addonKeys: string[]
  users: number; devices: number; units: number; storageMb: number
  adminName: string; adminEmail: string
}

const steps = ['Cadastro', 'Nicho', 'Plano', 'Capabilities', 'Limites', 'Administrador']
const inputClass = 'mt-2 h-11 w-full rounded-xl border border-slate-300 bg-white px-3 font-semibold outline-none focus:border-rose-500 focus:ring-4 focus:ring-rose-100'
const initialForm: FormState = {
  name: '', legalName: '', slug: '', customerType: 'PILOT', taxId: '', companyEmail: '', companyPhone: '',
  contactName: '', contactEmail: '', contactPhone: '', billingName: '', billingEmail: '', billingPhone: '',
  storeName: 'Matriz', storeCode: 'MATRIZ', postalCode: '', street: '', streetNumber: '', district: '', city: '', state: '',
  niche: '', planId: '', addonKeys: [], users: 2, devices: 1, units: 1, storageMb: 1024,
  adminName: '', adminEmail: '',
}

function normalizeSlug(value: string) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
}
function digits(value: string, max: number) { return value.replace(/\D/g, '').slice(0, max) }
function Field({ label, value, onChange, type = 'text', inputMode }: { label: string; value: string; onChange: (value: string) => void; type?: string; inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode'] }) {
  return <label className="text-sm font-black text-slate-800">{label}<input type={type} inputMode={inputMode} value={value} onChange={event => onChange(event.target.value)} className={inputClass} /></label>
}

export function CreateTenantPanel({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [form, setForm] = useState<FormState>(initialForm)
  const [step, setStep] = useState(0)
  const [niches, setNiches] = useState<OwnerNiche[]>([])
  const [plans, setPlans] = useState<ServicePlan[]>([])
  const [loadingCatalog, setLoadingCatalog] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [slugTouched, setSlugTouched] = useState(false)
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm(current => ({ ...current, [key]: value }))

  useEffect(() => {
    Promise.all([fetchOwnerNiches(), fetchServicePlans()])
      .then(([nicheRows, planRows]) => { setNiches(nicheRows); setPlans(planRows.filter(item => item.is_active)) })
      .catch(reason => setError(reason instanceof Error ? reason.message : 'Não foi possível carregar o contrato comercial.'))
      .finally(() => setLoadingCatalog(false))
  }, [])

  const selectedNiche = niches.find(item => item.key === form.niche)
  const selectedPlan = plans.find(item => item.id === form.planId)
  const validStep = useMemo(() => {
    if (step === 0) return Boolean(
      form.name.trim().length >= 2 && form.legalName.trim().length >= 2 && form.slug.length >= 3 && digits(form.taxId, 14).length === 14
      && form.companyPhone.trim().length >= 8 && form.contactName.trim().length >= 2 && form.contactEmail.includes('@')
      && form.billingName.trim().length >= 2 && form.billingEmail.includes('@') && form.storeName.trim().length >= 2
      && digits(form.postalCode, 8).length === 8 && form.street.trim().length >= 2 && form.streetNumber.trim()
      && form.district.trim().length >= 2 && form.city.trim().length >= 2 && form.state.length === 2
    )
    if (step === 1) return Boolean(form.niche)
    if (step === 2) return Boolean(form.planId)
    if (step === 3) return Boolean(selectedNiche)
    if (step === 4) return form.users > 0 && form.devices > 0 && form.units > 0 && form.storageMb >= 128
      && (!selectedPlan?.user_limit || form.users <= selectedPlan.user_limit)
      && (!selectedPlan?.terminal_limit || form.devices <= selectedPlan.terminal_limit)
      && (!selectedPlan?.store_limit || form.units <= selectedPlan.store_limit)
      && (!selectedPlan?.storage_limit_mb || form.storageMb <= selectedPlan.storage_limit_mb)
    return form.adminName.trim().length >= 2 && form.adminEmail.includes('@')
  }, [form, selectedNiche, selectedPlan, step])

  const selectPlan = (plan: ServicePlan) => setForm(current => ({
    ...current, planId: plan.id,
    users: Math.min(current.users, plan.user_limit ?? current.users),
    devices: Math.min(current.devices, plan.terminal_limit ?? current.devices),
    units: Math.min(current.units, plan.store_limit ?? current.units),
    storageMb: Math.min(current.storageMb, plan.storage_limit_mb ?? current.storageMb),
  }))
  const selectNiche = (niche: BusinessNiche) => setForm(current => ({ ...current, niche, addonKeys: [] }))
  const toggleAddon = (key: string) => setForm(current => ({ ...current, addonKeys: current.addonKeys.includes(key) ? current.addonKeys.filter(item => item !== key) : [...current.addonKeys, key] }))

  const submit = async () => {
    if (!validStep || !form.niche || !selectedNiche) return
    setSaving(true); setError(null)
    try {
      await provisionPlatformTenant({
        name: form.name.trim(), legal_name: form.legalName.trim(), slug: form.slug,
        customer_type: form.customerType, tax_id: form.taxId, industry: form.niche,
        company_email: form.companyEmail.trim() || undefined, company_phone: form.companyPhone.trim(),
        contact_name: form.contactName.trim(), contact_email: form.contactEmail.trim(), contact_phone: form.contactPhone.trim() || undefined,
        first_store_name: form.storeName.trim(), first_store_code: form.storeCode,
        postal_code: form.postalCode, street: form.street.trim(), street_number: form.streetNumber.trim(),
        district: form.district.trim(), city: form.city.trim(), state: form.state,
        niche: form.niche, plan_id: form.planId, addon_keys: form.addonKeys,
        quotas: { users: form.users, devices: form.devices, units: form.units, storage_mb: form.storageMb },
        billing: { contact_name: form.billingName.trim(), email: form.billingEmail.trim(), phone: form.billingPhone.trim() || undefined },
        initial_admin: { full_name: form.adminName.trim(), email: form.adminEmail.trim() },
      })
      await onCreated()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível provisionar o cliente.')
      setSaving(false)
    }
  }

  return <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-slate-950/65 p-0 backdrop-blur-sm sm:p-5">
    <button aria-label="Fechar" className="absolute inset-0" onClick={onClose} />
    <section className="relative flex h-full w-full max-w-6xl flex-col overflow-hidden bg-white shadow-2xl sm:h-[calc(100vh-2.5rem)] sm:rounded-3xl">
      <header className="flex items-start justify-between border-b border-slate-200 px-5 py-4 sm:px-8">
        <div><p className="text-xs font-black uppercase tracking-[.16em] text-rose-600">OWNER-P0 · PROVISIONAMENTO</p><h2 className="mt-1 text-2xl font-black">Novo cliente SaaS</h2><p className="mt-1 text-sm text-slate-500">Um único fluxo cria cadastro, contrato, entitlements e primeiro administrador.</p></div>
        <button onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500"><X className="h-5 w-5" /></button>
      </header>
      <ol className="flex gap-2 overflow-x-auto border-b border-slate-200 px-5 py-3 sm:px-8">
        {steps.map((label, index) => <li key={label} className={`flex shrink-0 items-center gap-2 rounded-full px-3 py-2 text-xs font-black ${index === step ? 'bg-slate-950 text-white' : index < step ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{index < step ? <Check className="h-3.5 w-3.5" /> : index + 1}{label}</li>)}
      </ol>
      <div className="flex-1 overflow-y-auto p-5 sm:p-8">
        {loadingCatalog ? <Loader2 className="mx-auto mt-24 h-8 w-8 animate-spin text-rose-600" /> : <>
          {step === 0 && <div className="space-y-7">
            <Section title="Empresa e contrato"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Field label="Nome fantasia" value={form.name} onChange={value => setForm(current => ({ ...current, name: value, slug: slugTouched ? current.slug : normalizeSlug(value) }))} />
              <Field label="Razão social" value={form.legalName} onChange={value => set('legalName', value)} />
              <Field label="CNPJ" value={form.taxId} inputMode="numeric" onChange={value => set('taxId', digits(value, 14))} />
              <label className="text-sm font-black">Ciclo<select value={form.customerType} onChange={event => set('customerType', event.target.value as TenantCustomerType)} className={inputClass}><option value="PILOT">Piloto</option><option value="CUSTOMER">Cliente</option><option value="TEST">Teste controlado</option><option value="INTERNAL">Operação interna</option></select></label>
              <Field label="Telefone da empresa" value={form.companyPhone} onChange={value => set('companyPhone', value)} />
              <Field label="E-mail da empresa" value={form.companyEmail} type="email" onChange={value => set('companyEmail', value)} />
              <Field label="Identificador técnico" value={form.slug} onChange={value => { setSlugTouched(true); set('slug', normalizeSlug(value)) }} />
            </div></Section>
            <Section title="Responsável e cobrança"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <Field label="Responsável contratual" value={form.contactName} onChange={value => set('contactName', value)} />
              <Field label="E-mail do responsável" value={form.contactEmail} type="email" onChange={value => set('contactEmail', value)} />
              <Field label="Telefone do responsável" value={form.contactPhone} onChange={value => set('contactPhone', value)} />
              <Field label="Contato de cobrança" value={form.billingName} onChange={value => set('billingName', value)} />
              <Field label="E-mail de cobrança" value={form.billingEmail} type="email" onChange={value => set('billingEmail', value)} />
              <Field label="Telefone de cobrança" value={form.billingPhone} onChange={value => set('billingPhone', value)} />
            </div></Section>
            <Section title="Matriz"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Field label="Nome da unidade" value={form.storeName} onChange={value => set('storeName', value)} /><Field label="Código" value={form.storeCode} onChange={value => set('storeCode', value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''))} />
              <Field label="CEP" value={form.postalCode} inputMode="numeric" onChange={value => set('postalCode', digits(value, 8))} /><Field label="Logradouro" value={form.street} onChange={value => set('street', value)} />
              <Field label="Número" value={form.streetNumber} onChange={value => set('streetNumber', value)} /><Field label="Bairro" value={form.district} onChange={value => set('district', value)} />
              <Field label="Cidade" value={form.city} onChange={value => set('city', value)} /><Field label="UF" value={form.state} onChange={value => set('state', value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 2))} />
            </div></Section>
          </div>}
          {step === 1 && <ChoiceGrid>{niches.map(niche => <ChoiceCard key={niche.key} selected={form.niche === niche.key} title={niche.name} description={niche.description} onClick={() => selectNiche(niche.key)} footer={`${niche.required_capabilities.length} capabilities base · ${niche.allowed_addons.length} add-ons possíveis`} />)}</ChoiceGrid>}
          {step === 2 && <ChoiceGrid>{plans.map(plan => <ChoiceCard key={plan.id} selected={form.planId === plan.id} title={plan.name} description={plan.description || 'Plano comercial ativo'} onClick={() => selectPlan(plan)} footer={`${plan.user_limit ?? '∞'} usuários · ${plan.terminal_limit ?? '∞'} dispositivos · ${plan.store_limit ?? '∞'} unidades · ${plan.storage_limit_mb ?? '∞'} MB`} />)}</ChoiceGrid>}
          {step === 3 && selectedNiche && <div className="space-y-7"><Section title="Incluído pelo nicho"><CapabilityGrid capabilities={selectedNiche.required_capabilities} selected={() => true} disabled onToggle={() => undefined} /></Section><Section title="Add-ons permitidos"><CapabilityGrid capabilities={selectedNiche.allowed_addons} selected={key => form.addonKeys.includes(key)} onToggle={toggleAddon} /></Section></div>}
          {step === 4 && <div><h3 className="text-xl font-black">Limites efetivamente contratados</h3><p className="mt-2 text-sm text-slate-500">Os valores não podem exceder o plano. Estes limites serão persistidos no contrato do tenant.</p><div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><NumberField label="Usuários" value={form.users} max={selectedPlan?.user_limit} onChange={value => set('users', value)} /><NumberField label="Dispositivos" value={form.devices} max={selectedPlan?.terminal_limit} onChange={value => set('devices', value)} /><NumberField label="Unidades" value={form.units} max={selectedPlan?.store_limit} onChange={value => set('units', value)} /><NumberField label="Storage (MB)" value={form.storageMb} max={selectedPlan?.storage_limit_mb} min={128} onChange={value => set('storageMb', value)} /></div></div>}
          {step === 5 && <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]"><Section title="Primeiro administrador"><div className="grid gap-4"><Field label="Nome completo" value={form.adminName} onChange={value => set('adminName', value)} /><Field label="E-mail de acesso" value={form.adminEmail} type="email" onChange={value => set('adminEmail', value)} /><p className="rounded-xl bg-blue-50 p-4 text-sm font-semibold text-blue-900">O Owner entrega somente este acesso administrativo. Operadores, caixas, garçons e supervisores serão geridos pelo cliente no Dashem Gestão.</p></div></Section><section className="rounded-2xl bg-slate-950 p-6 text-white"><div className="flex items-center gap-3"><ShieldCheck className="h-6 w-6 text-emerald-400" /><h3 className="text-xl font-black">Contrato pronto para provisionar</h3></div><dl className="mt-6 space-y-3 text-sm"><Summary label="Cliente" value={form.name} /><Summary label="Nicho" value={selectedNiche?.name || ''} /><Summary label="Plano" value={selectedPlan?.name || ''} /><Summary label="Capabilities" value={`${(selectedNiche?.required_capabilities.length ?? 0) + form.addonKeys.length} efetivamente contratadas`} /><Summary label="Limites" value={`${form.users} usuários · ${form.devices} dispositivos · ${form.units} unidades · ${form.storageMb} MB`} /><Summary label="Administrador" value={form.adminEmail} /></dl></section></div>}
        </>}
        {error && <p role="alert" className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
      </div>
      <footer className="flex items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-5 py-4 sm:px-8"><button type="button" onClick={() => step === 0 ? onClose() : setStep(value => value - 1)} className="flex h-11 items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 font-black text-slate-600"><ArrowLeft className="h-4 w-4" />{step === 0 ? 'Cancelar' : 'Voltar'}</button>{step < steps.length - 1 ? <button disabled={!validStep || loadingCatalog} onClick={() => setStep(value => value + 1)} className="flex h-11 items-center gap-2 rounded-xl bg-slate-950 px-6 font-black text-white disabled:opacity-35">Continuar<ArrowRight className="h-4 w-4" /></button> : <button disabled={!validStep || saving} onClick={submit} className="flex h-11 items-center gap-2 rounded-xl bg-rose-600 px-6 font-black text-white disabled:opacity-35">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Provisionar tenant</button>}</footer>
    </section>
  </div>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section><h3 className="flex items-center gap-2 border-b border-slate-200 pb-3 text-lg font-black"><Building2 className="h-5 w-5 text-rose-600" />{title}</h3><div className="mt-5">{children}</div></section> }
function ChoiceGrid({ children }: { children: React.ReactNode }) { return <div><h3 className="text-xl font-black">Escolha exatamente uma opção</h3><div className="mt-6 grid gap-4 lg:grid-cols-3">{children}</div></div> }
function ChoiceCard({ selected, title, description, footer, onClick }: { selected: boolean; title: string; description: string; footer: string; onClick: () => void }) { return <button onClick={onClick} className={`rounded-2xl border-2 p-6 text-left transition ${selected ? 'border-rose-500 bg-rose-50 shadow-lg shadow-rose-100' : 'border-slate-200 hover:border-slate-400'}`}><div className="flex items-center justify-between"><h4 className="text-xl font-black">{title}</h4>{selected && <span className="rounded-full bg-rose-600 p-1 text-white"><Check className="h-4 w-4" /></span>}</div><p className="mt-3 min-h-16 text-sm leading-6 text-slate-600">{description}</p><p className="mt-4 border-t border-current/10 pt-4 text-xs font-black text-slate-500">{footer}</p></button> }
function CapabilityGrid({ capabilities, selected, disabled = false, onToggle }: { capabilities: OwnerNiche['required_capabilities']; selected: (key: string) => boolean; disabled?: boolean; onToggle: (key: string) => void }) { return <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{capabilities.map(capability => <button key={capability.key} type="button" disabled={disabled} onClick={() => onToggle(capability.key)} className={`rounded-xl border p-4 text-left ${selected(capability.key) ? 'border-emerald-300 bg-emerald-50' : 'border-slate-200 bg-white'}`}><div className="flex items-start justify-between gap-3"><p className="font-black">{capability.name}</p><span className={`mt-0.5 flex h-5 w-5 items-center justify-center rounded ${selected(capability.key) ? 'bg-emerald-600 text-white' : 'border border-slate-300'}`}>{selected(capability.key) && <Check className="h-3.5 w-3.5" />}</span></div><p className="mt-2 text-sm text-slate-600">{capability.description}</p></button>)}</div> }
function NumberField({ label, value, max, min = 1, onChange }: { label: string; value: number; max?: number; min?: number; onChange: (value: number) => void }) { return <label className="rounded-2xl border border-slate-200 bg-white p-5 text-sm font-black">{label}<input type="number" min={min} max={max} value={value} onChange={event => onChange(Number(event.target.value))} className={`${inputClass} text-xl`} /><span className="mt-2 block text-xs font-semibold text-slate-500">Máximo do plano: {max ?? 'sem teto definido'}</span></label> }
function Summary({ label, value }: { label: string; value: string }) { return <div className="flex items-start justify-between gap-6 border-b border-white/10 pb-3"><dt className="text-slate-400">{label}</dt><dd className="text-right font-black">{value}</dd></div> }
