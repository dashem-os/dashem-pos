import React, { useEffect, useMemo, useState } from 'react'
import { ChefHat, KeyRound, Monitor, PauseCircle, PlugZap, Printer, RefreshCw, Router, ShieldX } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { useAuth } from '../../context/AuthContext'
import { Modal } from '../common/Modal'
import * as api from '../../services/api'
import { navigateTo } from '../../utils/navigation'

type DeviceKind = api.OperationalDevice['device_type']
const typeMeta: Record<DeviceKind, { label: string; icon: React.ComponentType<{ className?: string }>; description: string }> = {
  POS: { label: 'Frente de caixa', icon: Monitor, description: 'Terminal de venda vinculado a um caixa.' },
  KDS: { label: 'Terminal de produção', icon: ChefHat, description: 'Tela de cozinha, bar, copa ou expedição.' },
  PRINTER: { label: 'Impressora de comandas', icon: Printer, description: 'Destino de impressão referenciado por configuração segura.' },
}

export function DeviceManager() {
  const { tenant, store, operatorId, products, permissions, capabilities, showToast } = usePos()
  const { authorizeTerminal } = useAuth()
  const [devices, setDevices] = useState<api.OperationalDevice[]>([])
  const [registers, setRegisters] = useState<api.Register[]>([])
  const [points, setPoints] = useState<api.ProductionPoint[]>([])
  const [rules, setRules] = useState<api.ProductionRoutingRule[]>([])
  const [dialog, setDialog] = useState<'DEVICE' | 'RULE' | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ device_type: 'POS' as DeviceKind, code: '', name: '', point_type: 'KITCHEN' as api.ProductionPoint['point_type'], configuration_ref: '' })
  const [rule, setRule] = useState({ production_point_id: '', product_id: '', priority: '100' })
  const headers = useMemo<Record<string, string>>(() => tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : {} as Record<string, string>, [tenant, store])
  const canConfigure = permissions.includes('device.configure')
  const productionEnabled = Boolean(capabilities.kitchen_routing)
  const availableDeviceKinds: DeviceKind[] = productionEnabled ? ['POS', 'KDS', 'PRINTER'] : ['POS']

  const load = async () => {
    if (!store) return
    setLoading(true)
    try {
      const [nextDevices, nextRegisters] = await Promise.all([
        api.fetchOperationalDevices(headers), api.fetchRegisters(headers, store.id),
      ])
      setDevices(nextDevices); setRegisters(nextRegisters)
      if (productionEnabled) {
        const [nextPoints, nextRules] = await Promise.all([
          api.fetchProductionPoints(headers), api.fetchProductionRules(headers),
        ])
        setPoints(nextPoints); setRules(nextRules)
      } else {
        setPoints([]); setRules([])
      }
    } catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao carregar dispositivos.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [tenant?.id, store?.id, productionEnabled])

  const createDevice = async (event: React.FormEvent) => {
    event.preventDefault(); if (!store) return; setBusy(true)
    try {
      await api.createOperationalDevice(headers, {
        store_id: store.id, code: form.code, name: form.name, device_type: form.device_type,
        point_type: form.device_type === 'PRINTER' ? 'PRINTER' : form.device_type === 'KDS' ? form.point_type : undefined,
        configuration_ref: form.configuration_ref || undefined, actor_id: operatorId,
      })
      setForm({ device_type: 'POS', code: '', name: '', point_type: 'KITCHEN', configuration_ref: '' })
      setDialog(null); showToast('success', 'Dispositivo configurado e auditado.'); await load()
    } catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao configurar dispositivo.') }
    finally { setBusy(false) }
  }

  const updateStatus = async (device: api.OperationalDevice, status: api.OperationalDevice['status']) => {
    const reason = window.prompt(status === 'REVOKED' ? 'Motivo da revogação definitiva:' : status === 'PAUSED' ? 'Motivo da pausa:' : 'Motivo da reativação:')
    if (!reason || reason.trim().length < 3) return
    setBusy(true)
    try { await api.updateOperationalDevice(headers, device.id, { status, reason, actor_id: operatorId }); showToast('success', 'Estado do dispositivo atualizado.'); await load() }
    catch (value) { showToast('error', value instanceof Error ? value.message : 'Falha ao atualizar dispositivo.') }
    finally { setBusy(false) }
  }

  const authorizeThisBrowser = async (device: api.OperationalDevice) => {
    setBusy(true)
    try {
      const authorization = await api.authorizeOperationalTerminal(headers, device.id)
      authorizeTerminal(authorization.terminal_token)
      showToast('success', `${device.name} autorizado neste navegador.`)
      navigateTo('/pos')
    } catch (value) { showToast('error', value instanceof Error ? value.message : 'Falha ao autorizar este terminal.') }
    finally { setBusy(false) }
  }

  const createRule = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true)
    try {
      await api.createProductionRule(headers, crypto.randomUUID(), { production_point_id: rule.production_point_id, product_id: rule.product_id, priority: Number(rule.priority), actor_id: operatorId })
      setRule({ production_point_id: '', product_id: '', priority: '100' }); setDialog(null); showToast('success', 'Roteamento de produção criado.'); await load()
    } catch (value) { showToast('error', value instanceof Error ? value.message : 'Falha ao criar roteamento.') }
    finally { setBusy(false) }
  }

  const active = devices.filter((item) => item.status === 'ACTIVE').length
  const online = devices.filter((item) => item.last_seen_at && Date.now() - new Date(item.last_seen_at).getTime() < 90_000).length
  return <div className="space-y-6">
    <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6">
      <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end"><div><p className="text-[11px] font-black uppercase tracking-[.18em] text-sky-400">Infraestrutura da unidade</p><h1 className="mt-2 text-3xl font-black text-white">Terminais e dispositivos</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-dashem-muted">Autorize pontos de operação e acompanhe sua presença. Produção e impressão aparecem somente quando contratadas para esta unidade.</p></div><div className="flex gap-2"><button onClick={() => void load()} className="flex h-11 items-center gap-2 rounded-xl border border-dashem-border px-4 text-xs font-black"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Atualizar</button>{canConfigure && <button onClick={() => setDialog('DEVICE')} className="h-11 rounded-xl bg-dashem-red px-5 text-xs font-black text-white">Novo dispositivo</button>}</div></div>
      <div className="mt-6 grid gap-3 sm:grid-cols-3"><Metric label="Configurados" value={devices.length} hint={`${registers.length} caixas · ${points.length} pontos`} /><Metric label="Autorizados" value={active} hint={`${devices.length - active} pausados ou revogados`} /><Metric label="Presentes agora" value={online} hint="heartbeat nos últimos 90 segundos" /></div>
    </section>

    <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{devices.map((device) => { const meta = typeMeta[device.device_type]; const Icon = meta.icon; const isOnline = Boolean(device.last_seen_at && Date.now() - new Date(device.last_seen_at).getTime() < 90_000); return <article key={device.id} className="rounded-2xl border border-dashem-border bg-dashem-surface p-5"><div className="flex items-start justify-between"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-sky-950/60 text-sky-300"><Icon className="h-5 w-5" /></div><span className={`rounded-full px-2 py-1 text-[10px] font-black ${device.status === 'ACTIVE' ? 'bg-emerald-950/60 text-emerald-300' : device.status === 'PAUSED' ? 'bg-amber-950/60 text-amber-300' : 'bg-red-950/60 text-red-300'}`}>{device.status}</span></div><h3 className="mt-4 font-black text-white">{device.name}</h3><p className="mt-1 text-xs text-dashem-muted">{meta.label} · {device.code}</p><div className="mt-4 flex items-center gap-2 rounded-xl bg-dashem-bg p-3"><span className={`h-2.5 w-2.5 rounded-full ${isOnline ? 'bg-emerald-400' : 'bg-slate-600'}`} /><p className="text-xs font-bold text-slate-300">{isOnline ? 'Online agora' : device.last_seen_at ? `Último contato ${new Date(device.last_seen_at).toLocaleString('pt-BR')}` : 'Ainda não pareado'}</p></div>{canConfigure && device.device_type === 'POS' && device.status === 'ACTIVE' && <button disabled={busy} onClick={() => void authorizeThisBrowser(device)} className="mt-4 flex w-full items-center justify-center rounded-lg bg-rose-600 px-3 py-2.5 text-[11px] font-black text-white"><KeyRound className="mr-2 h-4 w-4" />Autorizar este navegador</button>}{canConfigure && device.status !== 'REVOKED' && <div className="mt-3 flex gap-2">{device.status === 'ACTIVE' ? <button disabled={busy} onClick={() => void updateStatus(device, 'PAUSED')} className="rounded-lg border border-amber-900 px-3 py-2 text-[11px] font-black text-amber-300"><PauseCircle className="mr-1 inline h-4 w-4" />Pausar</button> : <button disabled={busy} onClick={() => void updateStatus(device, 'ACTIVE')} className="rounded-lg border border-emerald-900 px-3 py-2 text-[11px] font-black text-emerald-300"><PlugZap className="mr-1 inline h-4 w-4" />Reativar</button>}<button disabled={busy} onClick={() => void updateStatus(device, 'REVOKED')} className="rounded-lg px-3 py-2 text-[11px] font-black text-red-300"><ShieldX className="mr-1 inline h-4 w-4" />Revogar</button></div>}</article> })}</section>
    {!loading && devices.length === 0 && <div className="rounded-3xl border border-dashed border-dashem-border p-12 text-center"><Router className="mx-auto h-10 w-10 text-slate-600" /><h3 className="mt-4 font-black text-white">Nenhum dispositivo configurado</h3><p className="mt-2 text-sm text-dashem-muted">Comece pelo caixa principal desta unidade.</p></div>}

    {productionEnabled && <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><p className="text-xs font-black uppercase tracking-[.16em] text-sky-400">Roteamento</p><h2 className="mt-1 text-xl font-black text-white">Produto → ponto de produção</h2><p className="mt-1 text-sm text-dashem-muted">Cada item segue uma regra persistida para cozinha, bar, copa ou impressão.</p></div>{canConfigure && <button onClick={() => setDialog('RULE')} disabled={!points.length || !products.length} className="h-10 rounded-xl border border-sky-800 px-4 text-xs font-black text-sky-300 disabled:opacity-40">Nova regra</button>}</div><div className="mt-5 divide-y divide-dashem-border rounded-2xl border border-dashem-border">{rules.map((item) => <div key={item.id} className="grid gap-2 p-4 text-sm md:grid-cols-[1fr_auto_1fr_auto] md:items-center"><span className="font-bold text-white">{products.find((product) => product.id === item.product_id)?.name || 'Produto não carregado'}</span><span className="text-dashem-muted">→</span><span className="font-bold text-sky-300">{points.find((point) => point.id === item.production_point_id)?.name || 'Ponto arquivado'}</span><span className="text-xs text-dashem-muted">prioridade {item.priority}</span></div>)}{rules.length === 0 && <p className="p-6 text-center text-sm font-bold text-dashem-muted">Nenhuma regra de roteamento configurada.</p>}</div></section>}

    <Modal isOpen={dialog === 'DEVICE'} onClose={() => setDialog(null)} title="Novo dispositivo" subtitle="Cria a estrutura operacional e seu vínculo auditável."><form onSubmit={createDevice} className="space-y-4"><label className="block text-xs font-black text-white">Tipo<div className={`mt-2 grid gap-2 ${availableDeviceKinds.length === 1 ? 'grid-cols-1' : 'grid-cols-3'}`}>{availableDeviceKinds.map((kind) => { const Icon = typeMeta[kind].icon; return <button type="button" key={kind} onClick={() => setForm({ ...form, device_type: kind })} className={`rounded-xl border p-3 text-center text-[11px] font-black ${form.device_type === kind ? 'border-dashem-red bg-red-950/30 text-white' : 'border-dashem-border text-dashem-muted'}`}><Icon className="mx-auto mb-2 h-5 w-5" />{typeMeta[kind].label}</button> })}</div></label><div className="grid grid-cols-2 gap-3"><Field label="Código" value={form.code} onChange={(value) => setForm({ ...form, code: value })} placeholder="CAIXA-01" /><Field label="Nome" value={form.name} onChange={(value) => setForm({ ...form, name: value })} placeholder="Caixa principal" /></div>{form.device_type === 'KDS' && <label className="block text-xs font-black text-white">Setor<select value={form.point_type} onChange={(event) => setForm({ ...form, point_type: event.target.value as api.ProductionPoint['point_type'] })} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-white"><option value="KITCHEN">Cozinha</option><option value="BAR">Bar</option><option value="PANTRY">Copa</option><option value="EXPEDITION">Expedição</option></select></label>}{form.device_type === 'PRINTER' && <Field label="Referência da configuração" value={form.configuration_ref} onChange={(value) => setForm({ ...form, configuration_ref: value })} placeholder="bridge://cozinha/impressora-01" />}<button disabled={busy || !form.code || !form.name || (form.device_type === 'PRINTER' && !form.configuration_ref)} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-white disabled:opacity-40">{busy ? 'Configurando...' : 'Configurar dispositivo'}</button></form></Modal>
    <Modal isOpen={dialog === 'RULE'} onClose={() => setDialog(null)} title="Nova regra de produção" subtitle="Direcione um produto real para um ponto ativo."><form onSubmit={createRule} className="space-y-4"><Select label="Produto" value={rule.product_id} onChange={(value) => setRule({ ...rule, product_id: value })} options={products.map((item) => ({ value: item.id, label: item.name }))} /><Select label="Ponto de produção" value={rule.production_point_id} onChange={(value) => setRule({ ...rule, production_point_id: value })} options={points.filter((item) => item.is_active).map((item) => ({ value: item.id, label: item.name }))} /><Field label="Prioridade" type="number" value={rule.priority} onChange={(value) => setRule({ ...rule, priority: value })} /><button disabled={busy || !rule.product_id || !rule.production_point_id} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-white disabled:opacity-40">Salvar roteamento</button></form></Modal>
  </div>
}

function Metric({ label, value, hint }: { label: string; value: number; hint: string }) { return <div className="rounded-2xl bg-dashem-bg p-4"><p className="text-xs font-black uppercase text-dashem-muted">{label}</p><p className="mt-2 text-2xl font-black text-white">{value}</p><p className="mt-1 text-xs text-slate-500">{hint}</p></div> }
function Field({ label, value, onChange, placeholder, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) { return <label className="block text-xs font-black text-white">{label}<input required type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-white outline-none focus:border-dashem-red" /></label> }
function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) { return <label className="block text-xs font-black text-white">{label}<select required value={value} onChange={(event) => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-white"><option value="">Selecione</option>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label> }
