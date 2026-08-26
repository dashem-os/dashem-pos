import React, { useEffect, useMemo, useState } from 'react'
import { Building2, Loader2, Monitor, Store as StoreIcon } from 'lucide-react'
import * as api from '../../services/api'
import { selectOnlyOption } from '../../domain/operationalRules'

export interface OperationalSelection {
  source?: 'MANAGEMENT' | 'OPERATIONAL_SESSION'
  tenantId: string
  storeId: string
  registerId?: string
  tenantName?: string
  tenantSlug?: string
  storeName?: string
  storeCode?: string
  registerName?: string
  registerCode?: string
  deviceId?: string
  deviceName?: string
}

export function OperationalContextGate({
  requireTerminal,
  children,
}: {
  requireTerminal: boolean
  children: (selection: OperationalSelection) => React.ReactNode
}) {
  const [tenants, setTenants] = useState<api.Tenant[]>([])
  const [stores, setStores] = useState<api.Store[]>([])
  const [registers, setRegisters] = useState<api.Register[]>([])
  const [tenantId, setTenantId] = useState('')
  const [storeId, setStoreId] = useState('')
  const [registerId, setRegisterId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api.fetchTenants().then((items) => {
      if (!active) return
      setTenants(items)
      const stored = sessionStorage.getItem('dashem.tenant_id')
      const authorizedStored = items.find((item) => item.id === stored)
      const only = selectOnlyOption(items)
      setTenantId(authorizedStored?.id ?? only?.id ?? '')
      setLoading(false)
    }).catch((reason) => {
      if (active) { setError(reason instanceof Error ? reason.message : 'Falha ao carregar tenants.'); setLoading(false) }
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!tenantId) { setStores([]); setStoreId(''); return }
    setLoading(true)
    api.fetchStores(tenantId).then((items) => {
      setStores(items)
      const stored = sessionStorage.getItem(`dashem.store_id.${tenantId}`)
      const authorizedStored = items.find((item) => item.id === stored)
      const only = selectOnlyOption(items)
      setStoreId(authorizedStored?.id ?? only?.id ?? '')
    }).catch((reason) => setError(reason instanceof Error ? reason.message : 'Falha ao carregar unidades.'))
      .finally(() => setLoading(false))
  }, [tenantId])

  useEffect(() => {
    if (!requireTerminal || !tenantId || !storeId) { setRegisters([]); setRegisterId(''); return }
    setLoading(true)
    const headers = { 'X-Tenant-ID': tenantId, 'X-Store-ID': storeId }
    api.fetchRegisters(headers, storeId).then((items) => {
      setRegisters(items)
      const stored = sessionStorage.getItem(`dashem.register_id.${storeId}`)
      const authorizedStored = items.find((item) => item.id === stored)
      const only = selectOnlyOption(items)
      setRegisterId(authorizedStored?.id ?? only?.id ?? '')
    }).catch((reason) => setError(reason instanceof Error ? reason.message : 'Falha ao carregar terminais.'))
      .finally(() => setLoading(false))
  }, [requireTerminal, tenantId, storeId])

  const ready = Boolean(tenantId && storeId && (!requireTerminal || registerId))
  const selection = useMemo(() => ready ? {
    source: 'MANAGEMENT' as const,
    tenantId, storeId, registerId: registerId || undefined,
    tenantName: tenants.find(item => item.id === tenantId)?.name,
    storeName: stores.find(item => item.id === storeId)?.name,
    registerName: registers.find(item => item.id === registerId)?.name,
  } : null, [ready, tenantId, storeId, registerId, tenants, stores, registers])

  if (loading && tenants.length === 0) return <ContextState label="Carregando contextos autorizados..." />
  if (error) return <ContextState label={error} error />
  if (selection) return <>{children(selection)}</>

  return <main className="flex min-h-screen items-center justify-center bg-[#07101f] p-6 text-slate-950"><section className="w-full max-w-xl rounded-3xl bg-white p-8 shadow-2xl"><p className="text-xs font-black uppercase tracking-[.18em] text-rose-600">Contexto operacional</p><h1 className="mt-2 text-2xl font-black">Escolha onde você vai operar</h1><p className="mt-2 text-sm leading-6 text-slate-500">Somente contextos autorizados são exibidos. A escolha fica nesta sessão e pode ser alterada ao sair.</p><div className="mt-7 space-y-4">{tenants.length > 1 && <SelectField icon={<Building2 />} label="Empresa" value={tenantId} onChange={(value) => { setTenantId(value); setStoreId(''); setRegisterId(''); sessionStorage.setItem('dashem.tenant_id', value) }} options={tenants.map((item) => ({ value: item.id, label: item.name }))} />}{tenantId && stores.length > 1 && <SelectField icon={<StoreIcon />} label="Unidade" value={storeId} onChange={(value) => { setStoreId(value); setRegisterId(''); sessionStorage.setItem(`dashem.store_id.${tenantId}`, value) }} options={stores.map((item) => ({ value: item.id, label: item.name }))} />}{requireTerminal && storeId && registers.length > 1 && <SelectField icon={<Monitor />} label="Terminal" value={registerId} onChange={(value) => { setRegisterId(value); sessionStorage.setItem(`dashem.register_id.${storeId}`, value) }} options={registers.map((item) => ({ value: item.id, label: item.name }))} />}{tenants.length === 0 && <Empty text="Nenhum tenant ativo foi autorizado para esta identidade." />}{tenantId && stores.length === 0 && !loading && <Empty text="Nenhuma unidade ativa está disponível para este tenant." />}{requireTerminal && storeId && registers.length === 0 && !loading && <Empty text="Nenhum terminal foi configurado nesta unidade. Solicite ao administrador do tenant." />}</div>{loading && <p className="mt-5 flex items-center gap-2 text-sm font-bold text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Atualizando opções...</p>}</section></main>
}

function SelectField({ icon, label, value, onChange, options }: { icon: React.ReactNode; label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) {
  return <label className="block text-sm font-black">{label}<div className="mt-2 flex items-center rounded-xl border border-slate-300 px-3 text-slate-400">{icon}<select value={value} onChange={(event) => onChange(event.target.value)} className="h-12 flex-1 bg-transparent px-3 font-bold text-slate-900 outline-none"><option value="">Selecione...</option>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div></label>
}

function Empty({ text }: { text: string }) { return <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-bold text-amber-800">{text}</p> }
function ContextState({ label, error = false }: { label: string; error?: boolean }) { return <div className={`flex min-h-screen items-center justify-center bg-[#07101f] p-6 text-sm font-bold ${error ? 'text-red-300' : 'text-slate-300'}`}>{!error && <Loader2 className="mr-3 h-5 w-5 animate-spin" />}{label}</div> }
