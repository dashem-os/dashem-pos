import React, { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Building2, Loader2, LogOut, Monitor, Store as StoreIcon } from 'lucide-react'
import * as api from '../../services/api'
import { useAuth } from '../../context/AuthContext'
import { selectOnlyOption } from '../../domain/operationalRules'
import { navigateTo } from '../../utils/navigation'

export interface OperationalSelection {
  source?: 'MANAGEMENT' | 'OPERATIONAL_SESSION'
  operatorId?: string
  operatorName?: string
  operatorRole?: 'SUPERVISOR' | 'CASHIER' | 'OPERATOR'
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
  const { signOut } = useAuth()
  // Set by the management console when it opens an operational surface for
  // validation, which is also what makes the return route legitimate.
  const managementAccess = new URLSearchParams(window.location.search).get('access') === 'management'
  const [tenants, setTenants] = useState<api.Tenant[]>([])
  const [stores, setStores] = useState<api.Store[]>([])
  const [registers, setRegisters] = useState<api.Register[]>([])
  const [tenantId, setTenantId] = useState('')
  const [storeId, setStoreId] = useState('')
  const [registerId, setRegisterId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [terminalName, setTerminalName] = useState('Caixa 01')
  const [terminalCode, setTerminalCode] = useState('CAIXA-01')
  const [provisioning, setProvisioning] = useState(false)
  const [provisionError, setProvisionError] = useState<string | null>(null)

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

  /**
   * Creates the first terminal of the unit after the manager confirms it. The
   * backend provisions terminal and register in the same transaction and writes
   * the audit trail; the cash session stays closed, so opening it remains an
   * explicit act with its own value and record.
   */
  const provisionFirstTerminal = async () => {
    if (!tenantId || !storeId || provisioning) return
    setProvisioning(true)
    setProvisionError(null)
    try {
      const headers = { 'X-Tenant-ID': tenantId, 'X-Store-ID': storeId }
      const device = await api.createOperationalDevice(headers, {
        store_id: storeId,
        code: terminalCode.trim().toUpperCase(),
        name: terminalName.trim(),
        device_type: 'POS',
      })
      const items = await api.fetchRegisters(headers, storeId)
      setRegisters(items)
      const created = device.register_id ?? selectOnlyOption(items)?.id ?? ''
      if (created) sessionStorage.setItem(`dashem.register_id.${storeId}`, created)
      setRegisterId(created)
    } catch (reason) {
      setProvisionError(reason instanceof Error ? reason.message : 'Não foi possível criar o terminal.')
    } finally {
      setProvisioning(false)
    }
  }

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

  return <main className="flex min-h-screen items-center justify-center bg-[#07101f] p-6 text-white"><section className="w-full max-w-xl rounded-3xl bg-white p-8 text-slate-900 shadow-2xl"><p className="text-xs font-black uppercase tracking-[.18em] text-brand-ink">Contexto operacional</p><h1 className="mt-2 text-2xl font-black">Escolha onde você vai operar</h1><p className="mt-2 text-sm leading-6 text-slate-500">Somente contextos autorizados são exibidos. A escolha fica nesta sessão e pode ser alterada ao sair.</p><div className="mt-7 space-y-4">{tenants.length > 1 && <SelectField icon={<Building2 />} label="Empresa" value={tenantId} onChange={(value) => { setTenantId(value); setStoreId(''); setRegisterId(''); sessionStorage.setItem('dashem.tenant_id', value) }} options={tenants.map((item) => ({ value: item.id, label: item.name }))} />}{tenantId && stores.length > 1 && <SelectField icon={<StoreIcon />} label="Unidade" value={storeId} onChange={(value) => { setStoreId(value); setRegisterId(''); sessionStorage.setItem(`dashem.store_id.${tenantId}`, value) }} options={stores.map((item) => ({ value: item.id, label: item.name }))} />}{requireTerminal && storeId && registers.length > 1 && <SelectField icon={<Monitor />} label="Terminal" value={registerId} onChange={(value) => { setRegisterId(value); sessionStorage.setItem(`dashem.register_id.${storeId}`, value) }} options={registers.map((item) => ({ value: item.id, label: item.name }))} />}{tenants.length === 0 && <Empty text="Nenhum tenant ativo foi autorizado para esta identidade." />}{tenantId && stores.length === 0 && !loading && <Empty text="Nenhuma unidade ativa está disponível para este tenant." />}{requireTerminal && storeId && registers.length === 0 && !loading && (managementAccess ? <FirstTerminal name={terminalName} code={terminalCode} onName={setTerminalName} onCode={setTerminalCode} onConfirm={provisionFirstTerminal} busy={provisioning} error={provisionError} /> : <Empty text="Nenhum terminal foi configurado nesta unidade. Solicite ao administrador do tenant." />)}</div>{loading && <p className="mt-5 flex items-center gap-2 text-sm font-bold text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Atualizando opções...</p>}<GateExit managementAccess={managementAccess} onSignOut={signOut} /></section></main>
}

function SelectField({ icon, label, value, onChange, options }: { icon: React.ReactNode; label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) {
  return <label className="block text-sm font-black">{label}<div className="mt-2 flex items-center rounded-xl border border-slate-300 px-3 text-slate-400">{icon}<select value={value} onChange={(event) => onChange(event.target.value)} className="h-12 flex-1 bg-transparent px-3 font-bold text-slate-900 outline-none"><option value="">Selecione...</option>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div></label>
}

function Empty({ text, action }: { text: string; action?: { label: string; onClick: () => void } }) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
      <p className="text-sm font-bold text-amber-800">{text}</p>
      {action && (
        <button type="button" onClick={action.onClick} className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-xl bg-slate-950 px-4 text-sm font-black text-white">
          {action.label}
        </button>
      )}
    </div>
  )
}

/**
 * A unit with no terminal cannot sell: the cash session and the sale bind to a
 * register. Rather than dead-ending the manager, the gate offers to create the
 * first one, stating plainly what will happen and letting the name be changed
 * before confirming. Nothing is created silently.
 */
function FirstTerminal({ name, code, onName, onCode, onConfirm, busy, error }: {
  name: string
  code: string
  onName: (value: string) => void
  onCode: (value: string) => void
  onConfirm: () => void
  busy: boolean
  error: string | null
}) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
      <p className="text-sm font-bold text-amber-900">Nenhum terminal foi configurado nesta unidade.</p>
      <p className="mt-2 text-sm leading-6 text-amber-800">
        Ao confirmar, o sistema cria este terminal e o caixa vinculado a ele, e registra a ação na auditoria.
        O caixa continua fechado: a abertura permanece um ato seu, com valor informado.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block text-xs font-black uppercase tracking-wide text-amber-900">Nome do terminal
          <input value={name} onChange={(event) => onName(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-amber-300 bg-white px-3 text-sm font-bold text-slate-900 outline-none focus:border-brand-ink" />
        </label>
        <label className="block text-xs font-black uppercase tracking-wide text-amber-900">Código
          <input value={code} onChange={(event) => onCode(event.target.value.toUpperCase())} className="mt-2 h-11 w-full rounded-xl border border-amber-300 bg-white px-3 font-mono text-sm font-bold text-slate-900 outline-none focus:border-brand-ink" />
        </label>
      </div>
      {error && <p className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-800">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onConfirm} disabled={busy || name.trim().length < 2 || code.trim().length < 2}
          className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-slate-950 px-4 text-sm font-black text-white disabled:opacity-40">
          {busy ? 'Criando terminal...' : 'Criar terminal e abrir o PDV'}
        </button>
        <button type="button" onClick={() => navigateTo('/manage?module=devices')}
          className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-amber-300 px-4 text-sm font-black text-amber-900">
          Configurar em Terminais e dispositivos
        </button>
      </div>
    </div>
  )
}

/**
 * This gate covers the whole screen and blocks the surface behind it. Without an
 * exit it becomes a trap: the copy above promises the choice can be changed on
 * the way out, so the way out has to exist.
 */
function GateExit({ managementAccess, onSignOut }: { managementAccess: boolean; onSignOut: () => void }) {
  return (
    <div className="mt-7 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-5">
      {managementAccess && (
        <button type="button" onClick={() => navigateTo('/manage')} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-slate-300 px-4 text-sm font-black text-slate-700">
          <ArrowLeft className="h-4 w-4" />Voltar à Gestão
        </button>
      )}
      <button type="button" onClick={onSignOut} className="inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-bold text-slate-500 hover:text-slate-800">
        <LogOut className="h-4 w-4" />Sair
      </button>
    </div>
  )
}
function ContextState({ label, error = false }: { label: string; error?: boolean }) { return <div className={`flex min-h-screen items-center justify-center bg-[#07101f] p-6 text-sm font-bold ${error ? 'text-red-300' : 'text-slate-300'}`}>{!error && <Loader2 className="mr-3 h-5 w-5 animate-spin" />}{label}</div> }
