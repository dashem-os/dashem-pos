import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { formatApiDateTime, millisecondsSince } from '../../utils/format'
import { Button } from '../common/Button'
import { DataTable } from '../common/DataTable'
import { Modal } from '../common/Modal'

type Snapshot = {
  providers: api.PaymentProviderConfiguration[]
  terminals: api.TefBridgeTerminal[]
  bindings: api.PaymentDeviceBinding[]
  registers: api.Register[]
  devices: api.OperationalDevice[]
}
type Dialog = 'provider' | 'bridge' | 'binding' | 'status' | null
const inputClass = 'mt-2 min-h-11 w-full min-w-0 rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 py-2 text-sm text-dashem-strong transition-colors focus:outline-none focus:ring-2 focus:ring-brand'
const statusLabel: Record<string, string> = {
  NOT_CONFIGURED: 'Não configurado', ACTIVE: 'Ativo', SUSPENDED: 'Suspenso',
  UNPAIRED: 'Aguardando pareamento', OFFLINE: 'Offline', ONLINE: 'Online', DEGRADED: 'Com falha',
  PAUSED: 'Pausado', REVOKED: 'Revogado',
}
const smartPosNotice = 'SmartPOS: somente cadastro. A execução de cobranças está indisponível até existir um adapter homologado.'

export function PaymentProviderManager() {
  const { tenant, store, permissions, capabilities } = usePos()
  if (!tenant || !store) return <Notice>Selecione uma unidade para consultar seus provedores.</Notice>
  if (!capabilities.tef || !permissions.includes('provider.read')) {
    return <Notice>Consulta de provedores indisponível para este acesso.</Notice>
  }
  // Changing the authority discards drafts, pairing secrets and in-flight reads.
  return <ProviderWorkspace key={`${tenant.id}:${store.id}:${permissions.join(',')}`} tenantId={tenant.id} storeId={store.id} />
}

function ProviderWorkspace({ tenantId, storeId }: { tenantId: string; storeId: string }) {
  const { permissions, showToast } = usePos()
  const canConfigure = permissions.includes('provider.configure')
  const canReadRegisters = permissions.includes('cash.read')
  const canReadDevices = permissions.includes('device.read')
  const headers = useMemo(() => ({ 'X-Tenant-ID': tenantId, 'X-Store-ID': storeId }), [tenantId, storeId])
  const [data, setData] = useState<Snapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dialog, setDialog] = useState<Dialog>(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [provider, setProvider] = useState({ provider_code: '', credentials_ref: '', timeout_seconds: '60' })
  const [bridge, setBridge] = useState({ register_id: '', provider_configuration_id: '', terminal_code: '' })
  const [binding, setBinding] = useState({ register_id: '', operational_device_id: '', provider_configuration_id: '', execution_mode: 'TEF_BRIDGE' as api.PaymentDeviceBinding['execution_mode'], tef_bridge_terminal_id: '', external_device_reference: '' })
  const [change, setChange] = useState<{ binding: api.PaymentDeviceBinding; status: api.PaymentDeviceBinding['status']; reason: string } | null>(null)
  const [paired, setPaired] = useState<Awaited<ReturnType<typeof api.pairTefBridgeTerminal>> | null>(null)
  const mounted = useRef(false)
  const submitting = useRef(false)
  const sequence = useRef(0)
  const request = useRef<{ payload: string; key: string } | null>(null)

  const load = useCallback(async () => {
    const version = ++sequence.current
    setLoading(true)
    try {
      const [providers, terminals, bindings, registers, devices] = await Promise.all([
        api.fetchPaymentProviderConfigurations(headers), api.fetchTefBridgeTerminals(headers), api.fetchPaymentDeviceBindings(headers),
        canReadRegisters ? api.fetchRegisters(headers, storeId) : Promise.resolve([]),
        canReadDevices ? api.fetchOperationalDevices(headers) : Promise.resolve([]),
      ])
      if (!mounted.current || version !== sequence.current) return
      const inScope = <T extends { tenant_id: string; store_id: string }>(rows: T[]) => rows.filter(row => row.tenant_id === tenantId && row.store_id === storeId)
      setData({ providers: inScope(providers), terminals: inScope(terminals), bindings: inScope(bindings), registers: inScope(registers), devices: inScope(devices) })
      setError('')
    } catch (reason) {
      if (mounted.current && version === sequence.current) setError(reason instanceof Error ? reason.message : 'Não foi possível carregar os provedores.')
    } finally {
      if (mounted.current && version === sequence.current) setLoading(false)
    }
  }, [headers, tenantId, storeId, canReadRegisters, canReadDevices])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => { mounted.current = false; sequence.current++ }
  }, [load])
  useEffect(() => {
    if (dialog) return
    const timer = window.setInterval(() => { if (!submitting.current) void load() }, 30_000)
    return () => window.clearInterval(timer)
  }, [dialog, load])

  const providers = data?.providers ?? []
  const terminals = data?.terminals ?? []
  const bindings = data?.bindings ?? []
  const registers = data?.registers ?? []
  const devices = data?.devices ?? []
  const activeRegisters = registers.filter(item => item.is_active)
  const activeProviders = providers.filter(item => item.status === 'ACTIVE')
  const availableDevices = devices.filter(item => item.device_type === 'POS' && item.status === 'ACTIVE'
    && activeRegisters.some(register => register.id === item.register_id)
    && !bindings.some(existing => existing.operational_device_id === item.id))
  const matchingTerminals = terminals.filter(item => item.register_id === binding.register_id && item.provider_configuration_id === binding.provider_configuration_id)
  const registerName = (id: string) => registers.find(item => item.id === id)?.name || 'Caixa sem identificação disponível'
  const providerName = (id: string) => providers.find(item => item.id === id)?.provider_code || 'Provedor indisponível'
  const disabled = busy || loading || Boolean(error) || !data

  const open = (next: Dialog) => {
    request.current = null
    setFormError(''); setPaired(null); setDialog(next)
  }
  const close = () => { if (!submitting.current) { setDialog(null); setPaired(null); setFormError('') } }
  const idempotencyKey = (payload: object) => {
    const serialized = JSON.stringify(payload)
    if (request.current?.payload !== serialized) request.current = { payload: serialized, key: crypto.randomUUID() }
    return request.current.key
  }
  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!canConfigure || submitting.current || paired) return
    submitting.current = true; setBusy(true); setFormError('')
    try {
      if (dialog === 'provider') {
        const payload = { store_id: storeId, provider_code: provider.provider_code.trim(), credentials_ref: provider.credentials_ref.trim(), timeout_seconds: Number(provider.timeout_seconds) }
        if (payload.provider_code.length < 2 || !payload.credentials_ref) throw new Error('Informe o código do provedor e a referência segura das credenciais.')
        await api.configurePaymentProvider(headers, idempotencyKey(payload), payload)
      } else if (dialog === 'bridge') {
        const payload = { store_id: storeId, ...bridge, terminal_code: bridge.terminal_code.trim() }
        if (payload.terminal_code.length < 2) throw new Error('Informe um código de terminal com pelo menos dois caracteres.')
        const result = await api.pairTefBridgeTerminal(headers, idempotencyKey(payload), payload)
        if (!mounted.current) return
        setPaired(result)
      } else if (dialog === 'binding') {
        const payload = {
          store_id: storeId, register_id: binding.register_id, operational_device_id: binding.operational_device_id,
          provider_configuration_id: binding.provider_configuration_id, execution_mode: binding.execution_mode,
          ...(binding.execution_mode === 'TEF_BRIDGE' ? { tef_bridge_terminal_id: binding.tef_bridge_terminal_id } : { external_device_reference: binding.external_device_reference.trim() }),
        }
        if (binding.execution_mode === 'SMARTPOS' && !binding.external_device_reference.trim()) throw new Error('Informe a referência real de pareamento da maquininha.')
        await api.createPaymentDeviceBinding(headers, idempotencyKey(payload), payload)
      } else if (dialog === 'status' && change) {
        if (change.reason.trim().length < 3) throw new Error('Informe um motivo com pelo menos três caracteres.')
        await api.updatePaymentDeviceBinding(headers, change.binding.id, { status: change.status, reason: change.reason.trim() })
      } else return
      if (!mounted.current) return
      if (dialog !== 'bridge') setDialog(null)
      setProvider(current => ({ ...current, credentials_ref: '' }))
      showToast('success', dialog === 'bridge' ? 'Código de pareamento gerado. Aguarde a conexão do bridge.' : 'Configuração salva.')
      await load()
    } catch (reason) {
      if (mounted.current) setFormError(reason instanceof Error ? reason.message : 'Não foi possível salvar. Tente novamente.')
    } finally {
      submitting.current = false
      if (mounted.current) setBusy(false)
    }
  }

  return <div className="min-w-0 space-y-6">
    <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-4 sm:p-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
        <div><h1 className="text-2xl font-black text-dashem-strong">Provedores de pagamento</h1>
          <p className="mt-2 max-w-2xl text-sm text-dashem-muted">Configure provedores, conecte o Dashem TEF Bridge e vincule maquininhas aos caixas desta unidade.</p></div>
        <Button variant="secondary" className="shrink-0 self-start whitespace-nowrap" icon={RefreshCw} loading={loading} disabled={busy} onClick={() => void load()}>Atualizar</Button>
      </div>
      <p className="mt-4 text-sm text-dashem-muted">{smartPosNotice}</p>
      {!canConfigure && <p className="mt-3 text-sm text-dashem-muted">Acesso somente para consulta. A configuração exige permissão de administração de provedores.</p>}
    </section>
    {error && <div role="alert" className="rounded-xl border border-dashem-border bg-dashem-surface p-4 text-sm text-dashem-strong">{error} Use Atualizar para tentar novamente. {data && 'Os dados abaixo são da última consulta concluída.'}</div>}
    {loading && !data && <p role="status" className="text-sm text-dashem-muted">Carregando configurações…</p>}
    {data && <>
      <Section title="Provedores" action={canConfigure && <Button disabled={disabled} onClick={() => { setProvider({ provider_code: '', credentials_ref: '', timeout_seconds: '60' }); open('provider') }}>Configurar provedor</Button>}>
        <DataTable rows={providers} rowKey={row => row.id} empty={<Notice>Nenhum provedor configurado nesta unidade.</Notice>} columns={[
          { key: 'provider', header: 'Provedor', primary: true, cell: row => <div className="break-all font-bold">{row.provider_code}<p className="mt-1 text-xs font-normal text-dashem-muted">Adapter {row.adapter_version}</p></div> },
          { key: 'status', header: 'Configuração', cell: row => <div>{statusLabel[row.status]}<p className="mt-1 text-xs text-dashem-muted">Tempo limite: {row.timeout_seconds}s</p></div> },
          { key: 'actions', header: 'Ações', actions: true, cell: row => canConfigure && <Button variant="secondary" disabled={disabled} onClick={() => { setProvider({ provider_code: row.provider_code, credentials_ref: '', timeout_seconds: String(row.timeout_seconds) }); open('provider') }}>Reconfigurar</Button> },
        ]} />
        <p className="text-xs text-dashem-muted">Cadastro ativo não comprova conexão, homologação ou aprovação de cobrança.</p>
      </Section>
      <Section title="Terminais de bridge" action={canConfigure && <Button disabled={disabled || !canReadRegisters || !activeRegisters.length || !activeProviders.length} onClick={() => { setBridge({ register_id: '', provider_configuration_id: '', terminal_code: '' }); open('bridge') }}>Parear bridge</Button>}>
        {canConfigure && (!canReadRegisters ? <Notice>A consulta de caixas precisa estar autorizada para parear um bridge.</Notice> : (!activeProviders.length || !activeRegisters.length) && <Notice>Configure um provedor ativo e um caixa ativo para iniciar o pareamento.</Notice>)}
        <DataTable rows={terminals} rowKey={row => row.id} empty={<Notice>Nenhum bridge configurado. A conexão TEF ainda não está disponível.</Notice>} columns={[
          { key: 'terminal', header: 'Terminal', primary: true, cell: row => <div className="break-words [overflow-wrap:anywhere]"><p className="font-bold">{row.terminal_code}</p><p className="mt-1 text-xs text-dashem-muted">{registerName(row.register_id)} · {providerName(row.provider_configuration_id)}</p></div> },
          { key: 'telemetry', header: 'Conexão e atividade', cell: row => <div className="break-words [overflow-wrap:anywhere]">
            <p className="font-bold">{statusLabel[row.status === 'ONLINE' && (millisecondsSince(row.last_heartbeat_at) ?? Infinity) > 90_000 ? 'OFFLINE' : row.status]}</p>
            <p className="mt-1 text-xs text-dashem-muted">Versão do bridge: {row.bridge_version || 'Ainda não informada'} · Protocolo {row.protocol_version}</p>
            <p className="mt-1 text-xs text-dashem-muted">Último contato: {formatApiDateTime(row.last_heartbeat_at)}</p>
            <p className="mt-1 text-xs text-dashem-muted">Última operação: {formatApiDateTime(row.last_operation_at)}</p>
            {(row.last_error_code || row.last_error_message) && <p className="mt-2 text-sm text-dashem-strong">{row.last_error_code} {row.last_error_message}</p>}
          </div> },
        ]} />
        <p className="text-xs text-dashem-muted">A conexão é confirmada pelo heartbeat do bridge. A consulta é atualizada a cada 30 segundos enquanto os diálogos estão fechados.</p>
      </Section>
      <Section title="Vínculos de maquininhas" action={canConfigure && <Button disabled={disabled || !canReadRegisters || !canReadDevices || !availableDevices.length || !activeProviders.length} onClick={() => { setBinding({ register_id: '', operational_device_id: '', provider_configuration_id: '', execution_mode: 'TEF_BRIDGE', tef_bridge_terminal_id: '', external_device_reference: '' }); open('binding') }}>Vincular maquininha</Button>}>
        {canConfigure && ((!canReadRegisters || !canReadDevices) ? <Notice>A consulta de caixas e dispositivos precisa estar autorizada para criar um vínculo.</Notice> : (!availableDevices.length || !activeProviders.length) && <Notice>Para criar um vínculo, é necessário um provedor ativo e um POS ativo, ligado a um caixa ativo e ainda sem vínculo de pagamento. Cadastre o POS em Terminais e dispositivos.</Notice>)}
        <DataTable rows={bindings} rowKey={row => row.id} empty={<Notice>Nenhuma maquininha vinculada nesta unidade.</Notice>} columns={[
          { key: 'device', header: 'POS e caixa', primary: true, cell: row => <div className="break-words [overflow-wrap:anywhere]"><p className="font-bold">{devices.find(item => item.id === row.operational_device_id)?.name || 'POS sem identificação disponível'}</p><p className="mt-1 text-xs text-dashem-muted">{registerName(row.register_id)} · {providerName(row.provider_configuration_id)}</p><p className="mt-2 text-sm">{row.execution_mode === 'SMARTPOS' ? 'SmartPOS · execução indisponível' : 'TEF Bridge'}</p>{row.external_device_reference && <p className="mt-1 text-xs text-dashem-muted">{row.external_device_reference}</p>}</div> },
          { key: 'status', header: 'Vínculo', cell: row => <div className="break-words [overflow-wrap:anywhere]"><p>{statusLabel[row.status]}</p>{row.paused_reason && <p className="mt-1 text-xs text-dashem-muted">{row.paused_reason}</p>}{row.status === 'REVOKED' && <p className="mt-1 text-xs text-dashem-muted">Não pode ser reativado.</p>}</div> },
          { key: 'actions', header: 'Ações', actions: true, cell: row => canConfigure && row.status !== 'REVOKED' && <div className="flex flex-wrap gap-2">
            <Button variant="secondary" disabled={disabled} onClick={() => { setChange({ binding: row, status: row.status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE', reason: '' }); open('status') }}>{row.status === 'ACTIVE' ? 'Pausar' : 'Reativar'}</Button>
            <Button variant="secondary" disabled={disabled} onClick={() => { setChange({ binding: row, status: 'REVOKED', reason: '' }); open('status') }}>Revogar</Button>
          </div> },
        ]} />
      </Section>
    </>}

    <Modal isOpen={dialog !== null} onClose={close} title={dialog === 'provider' ? 'Configurar provedor' : dialog === 'bridge' ? 'Parear terminal de bridge' : dialog === 'binding' ? 'Vincular maquininha' : `${change?.status === 'REVOKED' ? 'Revogar' : change?.status === 'PAUSED' ? 'Pausar' : 'Reativar'} vínculo`}>
      {paired ? <div className="space-y-4 text-sm text-dashem-strong">
        <p>Código gerado para {paired.terminal.terminal_code}. Informe estes dados no Dashem TEF Bridge para concluir a conexão.</p>
        <dl className="space-y-3"><PairingValue label="Unidade" value={storeId} /><PairingValue label="Empresa" value={tenantId} /><PairingValue label="Terminal" value={paired.terminal.id} /><PairingValue label="Código de pareamento" value={paired.pairing_code} /></dl>
        <p className="text-dashem-muted">Guarde o código em local seguro antes de fechar. Ele não será exibido na listagem. Gerar outro pareamento substitui este código.</p>
        <Button block onClick={close} disabled={busy}>Concluir</Button>
      </div> : <form onSubmit={save} className="space-y-4">
        <fieldset disabled={busy} className="min-w-0 space-y-4">
          {dialog === 'provider' && <>
            <Field label="Código do provedor" value={provider.provider_code} minLength={2} maxLength={80} onChange={value => setProvider({ ...provider, provider_code: value })} />
            <Field label="Referência segura das credenciais" value={provider.credentials_ref} maxLength={255} autoComplete="off" onChange={value => setProvider({ ...provider, credentials_ref: value })} />
            <p className="text-xs text-dashem-muted">Informe a referência fornecida na configuração segura da integração. Não cole senhas ou chaves de acesso. Reconfigurar o mesmo código substitui a referência anterior.</p>
            <Field label="Tempo limite em segundos" type="number" min={5} max={600} step={1} value={provider.timeout_seconds} onChange={value => setProvider({ ...provider, timeout_seconds: value })} />
          </>}
          {dialog === 'bridge' && <>
            <Select label="Caixa" value={bridge.register_id} options={activeRegisters.map(item => ({ value: item.id, label: `${item.name} · ${item.code}` }))} onChange={value => setBridge({ ...bridge, register_id: value })} />
            <Select label="Provedor" value={bridge.provider_configuration_id} options={activeProviders.map(item => ({ value: item.id, label: item.provider_code }))} onChange={value => setBridge({ ...bridge, provider_configuration_id: value })} />
            <Field label="Código do terminal" value={bridge.terminal_code} minLength={2} maxLength={80} onChange={value => setBridge({ ...bridge, terminal_code: value })} />
            {terminals.some(item => item.register_id === bridge.register_id) && <Notice>Este caixa já tem um bridge. O novo pareamento substitui o código anterior e a conexão ficará pendente até reconfigurar o bridge.</Notice>}
          </>}
          {dialog === 'binding' && <>
            <Select label="Caixa" value={binding.register_id} options={activeRegisters.filter(item => availableDevices.some(device => device.register_id === item.id)).map(item => ({ value: item.id, label: `${item.name} · ${item.code}` }))} onChange={value => setBinding({ ...binding, register_id: value, operational_device_id: '', tef_bridge_terminal_id: '' })} />
            <Select label="POS" value={binding.operational_device_id} options={availableDevices.filter(item => item.register_id === binding.register_id).map(item => ({ value: item.id, label: `${item.name} · ${item.code}` }))} onChange={value => setBinding({ ...binding, operational_device_id: value })} />
            <Select label="Provedor" value={binding.provider_configuration_id} options={activeProviders.map(item => ({ value: item.id, label: item.provider_code }))} onChange={value => setBinding({ ...binding, provider_configuration_id: value, tef_bridge_terminal_id: '' })} />
            <Select label="Modo de execução" value={binding.execution_mode} options={[{ value: 'TEF_BRIDGE', label: 'TEF Bridge' }, { value: 'SMARTPOS', label: 'SmartPOS · somente cadastro' }]} onChange={value => setBinding({ ...binding, execution_mode: value as api.PaymentDeviceBinding['execution_mode'], tef_bridge_terminal_id: '', external_device_reference: '' })} />
            {binding.execution_mode === 'TEF_BRIDGE' ? <><Select label="Terminal de bridge" value={binding.tef_bridge_terminal_id} options={matchingTerminals.map(item => ({ value: item.id, label: `${item.terminal_code} · ${statusLabel[item.status]}` }))} onChange={value => setBinding({ ...binding, tef_bridge_terminal_id: value })} />{!matchingTerminals.length && <Notice>Pareie um bridge com este caixa e provedor antes de criar o vínculo TEF.</Notice>}</> : <>
              <Notice>{smartPosNotice}</Notice>
              <Field label="Referência de pareamento da maquininha" value={binding.external_device_reference} maxLength={160} onChange={value => setBinding({ ...binding, external_device_reference: value })} />
            </>}
          </>}
          {dialog === 'status' && change && <>
            <p className="text-sm text-dashem-strong">{registerName(change.binding.register_id)} · {providerName(change.binding.provider_configuration_id)}</p>
            {change.status === 'REVOKED' && <Notice>A revogação é definitiva para este vínculo e impede sua reativação.</Notice>}
            <Field label="Motivo" value={change.reason} minLength={3} maxLength={500} onChange={value => setChange({ ...change, reason: value })} />
          </>}
        </fieldset>
        {formError && <p role="alert" className="text-sm text-dashem-strong">{formError}</p>}
        <div className="flex flex-wrap justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={close}>Cancelar</Button><Button type="submit" loading={busy}>{dialog === 'bridge' ? 'Gerar código de pareamento' : dialog === 'status' && change?.status === 'REVOKED' ? 'Confirmar revogação' : 'Salvar'}</Button></div>
      </form>}
    </Modal>
  </div>
}

function Section({ title, action, children }: { title: string; action: React.ReactNode; children: React.ReactNode }) {
  return <section className="min-w-0 space-y-4 rounded-3xl border border-dashem-border bg-dashem-surface p-4 sm:p-6"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><h2 className="text-xl font-black text-dashem-strong">{title}</h2>{action}</div>{children}</section>
}
function Notice({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl border border-dashem-border bg-dashem-surface-elevated p-4 text-sm text-dashem-strong">{children}</p>
}
function Field({ label, value, onChange, ...props }: Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange'> & { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="block text-sm font-bold text-dashem-strong">{label}<input {...props} required value={value} onChange={event => onChange(event.target.value)} className={inputClass} /></label>
}
function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) {
  const id = React.useId()
  return <div><label htmlFor={id} className="block text-sm font-bold text-dashem-strong">{label}</label><select id={id} required value={value} onChange={event => onChange(event.target.value)} className={inputClass}><option value="">Selecione</option>{options.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></div>
}
function PairingValue({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs font-bold text-dashem-muted">{label}</dt><dd className="mt-1 select-all break-all rounded-lg bg-dashem-surface-elevated p-3 font-mono text-sm text-dashem-strong">{value}</dd></div>
}
