import React, { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Loader2, Pencil, Plus, Save, WalletCards, X } from 'lucide-react'

import {
  createServicePlan,
  fetchServicePlans,
  ServicePlan,
  ServicePlanInput,
  updateServicePlan,
} from '../../services/api'

type PlanForm = {
  code: string
  name: string
  description: string
  monthlyPrice: string
  units: string
  users: string
  devices: string
  storage: string
  isActive: boolean
}

const emptyForm: PlanForm = {
  code: '', name: '', description: '', monthlyPrice: '0,00',
  units: '', users: '', devices: '', storage: '', isActive: true,
}
const inputClass = 'mt-2 h-11 w-full rounded-xl border bg-white px-3 font-semibold outline-none transition focus:ring-4'
const integer = (value: string) => {
  const clean = value.replace(/\D/g, '').replace(/^0+(?=\d)/, '')
  return clean
}
const money = (value: number) => Number(value || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const moneyNumber = (value: string) => Number(value.replace(/\./g, '').replace(',', '.')) || 0
const optionalPositive = (value: string) => value ? Number(value) : undefined

export function ServicePlansView() {
  const [plans, setPlans] = useState<ServicePlan[]>([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | 'new' | null>(null)
  const [form, setForm] = useState<PlanForm>(emptyForm)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try { setPlans(await fetchServicePlans()); setError('') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível carregar os planos comerciais.') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const set = <K extends keyof PlanForm>(key: K, value: PlanForm[K]) => {
    setForm(current => ({ ...current, [key]: value }))
    setFieldErrors(current => { const next = { ...current }; delete next[key]; return next })
  }
  const startNew = () => { setEditingId('new'); setForm(emptyForm); setError(''); setNotice(''); setFieldErrors({}) }
  const startEdit = (plan: ServicePlan) => {
    setEditingId(plan.id)
    setForm({
      code: plan.code, name: plan.name, description: plan.description || '',
      monthlyPrice: Number(plan.monthly_price || 0).toFixed(2).replace('.', ','),
      units: plan.store_limit?.toString() || '', users: plan.user_limit?.toString() || '',
      devices: plan.terminal_limit?.toString() || '', storage: plan.storage_limit_mb?.toString() || '',
      isActive: plan.is_active,
    })
    setError(''); setNotice(''); setFieldErrors({})
  }
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (saving) return
    const errors: Record<string, string> = {}
    if (!/^[A-Z0-9_-]{2,60}$/.test(form.code.trim().toUpperCase())) errors.code = 'Use ao menos dois caracteres: letras, números, _ ou -.'
    if (form.name.trim().length < 2) errors.name = 'Informe o nome do plano.'
    if (moneyNumber(form.monthlyPrice) < 0) errors.monthlyPrice = 'Informe um valor igual ou maior que zero.'
    for (const [key, value, minimum] of [
      ['units', form.units, 1], ['users', form.users, 1], ['devices', form.devices, 1], ['storage', form.storage, 128],
    ] as Array<[string, string, number]>) if (value && Number(value) < minimum) errors[key] = `Informe no mínimo ${minimum} ou deixe sem limite.`
    if (Object.keys(errors).length) { setFieldErrors(errors); setError('Revise os campos destacados.'); return }
    const input: ServicePlanInput = {
      code: form.code.trim().toUpperCase(), name: form.name.trim(),
      description: form.description.trim() || undefined, monthly_price: moneyNumber(form.monthlyPrice),
      store_limit: optionalPositive(form.units), user_limit: optionalPositive(form.users),
      terminal_limit: optionalPositive(form.devices), storage_limit_mb: optionalPositive(form.storage),
    }
    setSaving(true); setError(''); setNotice('')
    try {
      if (editingId === 'new') await createServicePlan(input)
      else if (editingId) await updateServicePlan(editingId, { ...input, is_active: form.isActive })
      await load()
      setEditingId(null)
      setNotice(editingId === 'new' ? 'Plano comercial criado e disponível para contratação.' : 'Plano comercial atualizado e confirmado pelo servidor.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Não foi possível salvar o plano comercial.') }
    finally { setSaving(false) }
  }

  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-black uppercase tracking-wider text-[#E12120]">Catálogo comercial</p><h2 className="mt-2 text-3xl font-black">Planos comerciais</h2><p className="mt-2 max-w-3xl text-slate-500">Defina a oferta, o preço-base e os tetos de contratação. A mensalidade negociada continua sendo definida no contrato de cada cliente.</p></div><button onClick={startNew} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-[#E12120] px-5 text-sm font-black text-white"><Plus className="h-4 w-4" />Novo plano</button></div>
    {error && <p className="mt-5 rounded-xl border border-[#ffbf00] bg-amber-50 p-4 text-sm font-bold text-[#6b4b00]">{error}</p>}
    {notice && <p className="mt-5 flex items-center gap-2 rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm font-bold text-emerald-800"><CheckCircle2 className="h-5 w-5" />{notice}</p>}
    {editingId && <form onSubmit={submit} className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><div className="flex items-start justify-between"><div><h3 className="text-xl font-black">{editingId === 'new' ? 'Cadastrar plano' : 'Editar plano'}</h3><p className="mt-1 text-sm text-slate-500">Campos de limite vazios significam que o plano não impõe teto nessa dimensão.</p></div><button type="button" onClick={() => setEditingId(null)} className="rounded-xl border border-slate-200 p-2"><X className="h-5 w-5" /></button></div><div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4"><Field label="Código" value={form.code} error={fieldErrors.code} onChange={value => set('code', value.toUpperCase().replace(/[^A-Z0-9_-]/g, ''))} /><Field label="Nome do plano" value={form.name} error={fieldErrors.name} onChange={value => set('name', value)} /><Field label="Preço-base mensal (R$)" value={form.monthlyPrice} error={fieldErrors.monthlyPrice} inputMode="decimal" onChange={value => set('monthlyPrice', value.replace(/[^\d,.]/g, ''))} /><label className="text-sm font-black">Situação<button type="button" disabled={editingId === 'new'} onClick={() => set('isActive', !form.isActive)} className={`mt-2 flex h-11 w-full items-center justify-center rounded-xl border font-black disabled:cursor-not-allowed ${form.isActive ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-slate-300 bg-slate-100 text-slate-500'}`}>{editingId === 'new' ? 'Ativo ao cadastrar' : form.isActive ? 'Ativo' : 'Inativo'}</button></label><div className="md:col-span-2 xl:col-span-4"><Field label="Descrição comercial" value={form.description} onChange={value => set('description', value)} /></div><Field label="Unidades" value={form.units} error={fieldErrors.units} inputMode="numeric" placeholder="Sem limite" onChange={value => set('units', integer(value))} /><Field label="Usuários" value={form.users} error={fieldErrors.users} inputMode="numeric" placeholder="Sem limite" onChange={value => set('users', integer(value))} /><Field label="Dispositivos" value={form.devices} error={fieldErrors.devices} inputMode="numeric" placeholder="Sem limite" onChange={value => set('devices', integer(value))} /><Field label="Storage (MB)" value={form.storage} error={fieldErrors.storage} inputMode="numeric" placeholder="Sem limite" onChange={value => set('storage', integer(value))} /></div><button disabled={saving} className="mt-6 flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white disabled:opacity-40">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{saving ? 'Salvando…' : editingId === 'new' ? 'Cadastrar plano' : 'Salvar plano'}</button></form>}
    <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{loading ? <div className="col-span-full py-20"><Loader2 className="mx-auto h-8 w-8 animate-spin text-[#E12120]" /></div> : plans.map(plan => <article key={plan.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-3"><div className="rounded-xl bg-slate-100 p-2.5"><WalletCards className="h-5 w-5" /></div><span className={`rounded-full px-3 py-1 text-xs font-black ${plan.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{plan.is_active ? 'ATIVO' : 'INATIVO'}</span></div><p className="mt-4 text-xs font-black uppercase tracking-wider text-slate-400">{plan.code}</p><h3 className="mt-1 text-xl font-black">{plan.name}</h3><p className="mt-2 min-h-10 text-sm text-slate-500">{plan.description || 'Sem descrição comercial.'}</p><p className="mt-4 text-2xl font-black">{money(plan.monthly_price)}<span className="text-xs text-slate-400"> / mês</span></p><div className="mt-4 grid grid-cols-2 gap-2 text-xs font-bold text-slate-500"><span>{plan.store_limit ?? '∞'} unidades</span><span>{plan.user_limit ?? '∞'} usuários</span><span>{plan.terminal_limit ?? '∞'} dispositivos</span><span>{plan.storage_limit_mb ? `${plan.storage_limit_mb} MB` : '∞ storage'}</span></div><button onClick={() => startEdit(plan)} className="mt-5 flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-slate-300 text-sm font-black"><Pencil className="h-4 w-4" />Editar plano</button></article>)}{!loading && plans.length === 0 && <div className="col-span-full rounded-2xl border border-[#ffbf00] bg-amber-50 p-8 text-center"><WalletCards className="mx-auto h-9 w-9 text-[#8a6100]" /><h3 className="mt-4 text-xl font-black">Nenhum plano comercial cadastrado</h3><p className="mt-2 text-sm text-slate-600">Cadastre o primeiro plano para liberar a contratação e o provisionamento de clientes.</p><button onClick={startNew} className="mt-5 inline-flex h-11 items-center gap-2 rounded-xl bg-[#E12120] px-5 font-black text-white"><Plus className="h-4 w-4" />Cadastrar primeiro plano</button></div>}</section>
  </div>
}

function Field({ label, value, onChange, error, inputMode, placeholder }: { label: string; value: string; onChange: (value: string) => void; error?: string; inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode']; placeholder?: string }) {
  return <label className="text-sm font-black">{label}<input value={value} inputMode={inputMode} placeholder={placeholder} onChange={event => onChange(event.target.value)} className={`${inputClass} ${error ? 'border-[#ffbf00] focus:border-[#ffbf00] focus:ring-amber-100' : 'border-slate-300 focus:border-[#E12120] focus:ring-red-100'}`} />{error && <span className="mt-1 block text-xs font-bold text-[#8a6100]">{error}</span>}</label>
}
