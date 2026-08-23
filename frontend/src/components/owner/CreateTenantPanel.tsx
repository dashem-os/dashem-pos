import React, { useEffect, useMemo, useState } from 'react'
import { Building2, Loader2, MapPin, Plus, UserRound, X } from 'lucide-react'

import {
  fetchServicePlans,
  provisionPlatformTenant,
  ServicePlan,
  TenantCustomerType,
} from '../../services/api'


type FormState = {
  name: string
  legalName: string
  slug: string
  customerType: TenantCustomerType
  taxId: string
  stateRegistration: string
  municipalRegistration: string
  industry: string
  companyEmail: string
  companyPhone: string
  website: string
  contactName: string
  contactJobTitle: string
  contactEmail: string
  contactPhone: string
  storeName: string
  storeCode: string
  postalCode: string
  street: string
  streetNumber: string
  addressComplement: string
  district: string
  city: string
  state: string
  planId: string
}

const initialForm: FormState = {
  name: '', legalName: '', slug: '', customerType: 'TEST', taxId: '',
  stateRegistration: '', municipalRegistration: '', industry: '',
  companyEmail: '', companyPhone: '', website: '', contactName: '',
  contactJobTitle: '', contactEmail: '', contactPhone: '',
  storeName: 'Matriz', storeCode: 'MATRIZ', postalCode: '', street: '',
  streetNumber: '', addressComplement: '', district: '', city: '', state: '',
  planId: '',
}

function normalizeSlug(value: string) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
}

function digits(value: string, max: number) {
  return value.replace(/\D/g, '').slice(0, max)
}

function optional(value: string) {
  const normalized = value.trim()
  return normalized || undefined
}

const inputClass = 'mt-2 h-11 w-full rounded-xl border border-slate-300 px-3 font-semibold outline-none focus:border-rose-500 focus:ring-4 focus:ring-rose-100'

export function CreateTenantPanel({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const [form, setForm] = useState<FormState>(initialForm)
  const [slugTouched, setSlugTouched] = useState(false)
  const [plans, setPlans] = useState<ServicePlan[]>([])
  const [plansError, setPlansError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchServicePlans().then(setPlans).catch(err => {
      setPlansError(err instanceof Error ? err.message : 'Não foi possível carregar os planos.')
    })
  }, [])

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm(current => ({ ...current, [key]: value }))
  }

  const valid = useMemo(() => Boolean(
    form.name.trim().length >= 2
    && form.legalName.trim().length >= 2
    && form.slug.length >= 3
    && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(form.slug)
    && digits(form.taxId, 14).length === 14
    && form.industry.trim().length >= 2
    && form.companyPhone.trim().length >= 8
    && form.contactName.trim().length >= 2
    && (form.contactEmail.includes('@') || form.contactPhone.trim().length >= 8)
    && form.storeName.trim().length >= 2
    && form.storeCode.trim().length >= 2
    && digits(form.postalCode, 8).length === 8
    && form.street.trim().length >= 2
    && form.streetNumber.trim().length >= 1
    && form.district.trim().length >= 2
    && form.city.trim().length >= 2
    && form.state.length === 2
  ), [form])

  const changeTradeName = (value: string) => {
    setForm(current => ({
      ...current,
      name: value,
      slug: slugTouched ? current.slug : normalizeSlug(value),
    }))
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setLoading(true); setError(null)
    try {
      await provisionPlatformTenant({
        name: form.name.trim(), legal_name: form.legalName.trim(), slug: form.slug,
        customer_type: form.customerType, tax_id: form.taxId,
        state_registration: optional(form.stateRegistration),
        municipal_registration: optional(form.municipalRegistration),
        industry: form.industry.trim(), company_email: optional(form.companyEmail),
        company_phone: form.companyPhone.trim(), website: optional(form.website),
        contact_name: form.contactName.trim(), contact_job_title: optional(form.contactJobTitle),
        contact_email: optional(form.contactEmail), contact_phone: optional(form.contactPhone),
        first_store_name: form.storeName.trim(), first_store_code: form.storeCode.trim(),
        postal_code: form.postalCode, street: form.street.trim(),
        street_number: form.streetNumber.trim(), address_complement: optional(form.addressComplement),
        district: form.district.trim(), city: form.city.trim(), state: form.state,
        plan_id: form.planId || undefined,
      })
      await onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível cadastrar o cliente.')
      setLoading(false)
    }
  }

  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/55 backdrop-blur-sm">
    <button aria-label="Fechar criação" className="absolute inset-0" onClick={onClose} />
    <section className="relative flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl">
      <header className="flex items-start justify-between border-b border-slate-200 p-6 sm:p-8">
        <div><p className="text-xs font-black uppercase tracking-[.16em] text-rose-600">Cadastro mestre</p><h2 className="mt-2 text-2xl font-black tracking-tight">Novo cliente</h2><p className="mt-2 text-sm leading-6 text-slate-500">Cria a empresa, o contato principal, a matriz e o vínculo contratual em uma transação auditada.</p></div>
        <button type="button" onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500"><X className="h-5 w-5" /></button>
      </header>

      <form onSubmit={submit} className="flex flex-1 flex-col overflow-y-auto">
        <div className="space-y-8 p-6 sm:p-8">
          <fieldset>
            <legend className="flex items-center gap-2 font-black"><Building2 className="h-5 w-5 text-rose-600" />Empresa</legend>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-black">Nome fantasia<input autoFocus value={form.name} onChange={e => changeTradeName(e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Razão social<input value={form.legalName} onChange={e => set('legalName', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">CNPJ<input inputMode="numeric" value={form.taxId} onChange={e => set('taxId', digits(e.target.value, 14))} placeholder="Somente números" className={inputClass} /></label>
              <label className="text-sm font-black">Classificação<select value={form.customerType} onChange={e => set('customerType', e.target.value as TenantCustomerType)} className={inputClass}><option value="TEST">Teste</option><option value="PILOT">Piloto</option><option value="CUSTOMER">Cliente</option><option value="INTERNAL">Operação interna</option></select></label>
              <label className="text-sm font-black">Inscrição estadual<input value={form.stateRegistration} onChange={e => set('stateRegistration', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Inscrição municipal<input value={form.municipalRegistration} onChange={e => set('municipalRegistration', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black sm:col-span-2">Área de atuação<input value={form.industry} onChange={e => set('industry', e.target.value)} placeholder="Ex.: varejo de materiais elétricos" className={inputClass} /></label>
              <label className="text-sm font-black">Telefone da empresa<input value={form.companyPhone} onChange={e => set('companyPhone', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">E-mail da empresa<input type="email" value={form.companyEmail} onChange={e => set('companyEmail', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Site<input value={form.website} onChange={e => set('website', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Identificador técnico<input value={form.slug} onChange={e => { setSlugTouched(true); set('slug', normalizeSlug(e.target.value)) }} className={`${inputClass} font-mono`} /></label>
            </div>
          </fieldset>

          <fieldset className="border-t border-slate-200 pt-7">
            <legend className="flex items-center gap-2 font-black"><UserRound className="h-5 w-5 text-rose-600" />Responsável direto</legend>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-black">Nome completo<input value={form.contactName} onChange={e => set('contactName', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Cargo<input value={form.contactJobTitle} onChange={e => set('contactJobTitle', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">E-mail direto<input type="email" value={form.contactEmail} onChange={e => set('contactEmail', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Telefone direto<input value={form.contactPhone} onChange={e => set('contactPhone', e.target.value)} className={inputClass} /></label>
            </div>
          </fieldset>

          <fieldset className="border-t border-slate-200 pt-7">
            <legend className="flex items-center gap-2 font-black"><MapPin className="h-5 w-5 text-rose-600" />Matriz</legend>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-black">Nome da unidade<input value={form.storeName} onChange={e => set('storeName', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Código interno<input value={form.storeCode} onChange={e => set('storeCode', e.target.value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''))} className={`${inputClass} font-mono`} /></label>
              <label className="text-sm font-black">CEP<input inputMode="numeric" value={form.postalCode} onChange={e => set('postalCode', digits(e.target.value, 8))} className={inputClass} /></label>
              <label className="text-sm font-black">Logradouro<input value={form.street} onChange={e => set('street', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Número<input value={form.streetNumber} onChange={e => set('streetNumber', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Complemento<input value={form.addressComplement} onChange={e => set('addressComplement', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Bairro<input value={form.district} onChange={e => set('district', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">Cidade<input value={form.city} onChange={e => set('city', e.target.value)} className={inputClass} /></label>
              <label className="text-sm font-black">UF<input value={form.state} onChange={e => set('state', e.target.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 2))} className={inputClass} /></label>
              <label className="text-sm font-black">Plano<select value={form.planId} onChange={e => set('planId', e.target.value)} className={inputClass}><option value="">Ainda não definido</option>{plans.filter(plan => plan.is_active).map(plan => <option key={plan.id} value={plan.id}>{plan.name}</option>)}</select></label>
            </div>
            {plansError && <p className="mt-3 text-xs font-bold text-amber-700">{plansError}</p>}
            {!plansError && plans.length === 0 && <p className="mt-3 text-xs font-semibold text-slate-500">Nenhum plano cadastrado. O cliente poderá ser criado com contrato pendente, sem receber um plano fictício.</p>}
          </fieldset>

          {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}
        </div>
        <footer className="sticky bottom-0 mt-auto flex gap-3 border-t border-slate-200 bg-slate-50 p-6 sm:p-8">
          <button type="button" onClick={onClose} className="h-12 flex-1 rounded-xl border border-slate-300 bg-white font-black text-slate-600">Cancelar</button>
          <button disabled={!valid || loading} className="flex h-12 flex-[1.5] items-center justify-center gap-2 rounded-xl bg-rose-600 font-black text-white shadow-lg shadow-rose-600/20 disabled:opacity-40">{loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <><Plus className="h-5 w-5" />Cadastrar cliente</>}</button>
        </footer>
      </form>
    </section>
  </div>
}
