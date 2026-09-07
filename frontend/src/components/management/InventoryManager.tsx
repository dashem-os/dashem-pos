import React, { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowDownToLine, Boxes, ClipboardCheck, History, PackageCheck, Scale, Search } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Modal } from '../common/Modal'
import { DataTable } from '../common/DataTable'
import * as api from '../../services/api'
import { formatApiDateTime } from '../../utils/format'
import { ApiError } from '../../services/http'
import { DEFAULT_STOCK_REASONS, countPreview, reasonForMovement, type StockMovementType } from '../../domain/stockMovements'

export function InventoryManager() {
  const { tenant, store, operatorId, products, adjustStock, permissions, showToast, refreshData } = usePos()
  const [movements, setMovements] = useState<api.InventoryMovement[]>([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<api.SellableProduct | null>(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ quantity: '', movement_type: 'PURCHASE', reason: DEFAULT_STOCK_REASONS.PURCHASE, minimum_stock: '' })
  const headers = useMemo<Record<string, string>>(() => tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : {} as Record<string, string>, [tenant, store])
  const canAdjust = permissions.includes('inventory.adjust')
  const canCount = permissions.includes('inventory.count')
  // Diferença lançada à mão passa por cima da conferência da prateleira. Quem
  // não tem essa autoridade não vê a ação — e a rota recusa de qualquer forma.
  const canAdjustTechnically = permissions.includes('inventory.adjust.technical')
  const [technical, setTechnical] = useState<api.SellableProduct | null>(null)
  const [technicalForm, setTechnicalForm] = useState({ difference: '', reason: '' })
  const submitTechnical = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!technical || !store || technicalForm.difference === '') return
    setBusy(true)
    try {
      await api.adjustStockTechnically(headers, {
        store_id: store.id, product_id: technical.id, actor_id: operatorId,
        difference: Number(technicalForm.difference), reason: technicalForm.reason,
      })
      await refreshData(); await load()
      setTechnical(null); setTechnicalForm({ difference: '', reason: '' })
      showToast('success', 'Ajuste técnico registrado no histórico do estoque.')
    } catch (reason) {
      showToast('error', reason instanceof Error ? reason.message : 'Não foi possível lançar o ajuste.')
    } finally { setBusy(false) }
  }
  // A contagem carrega o saldo e a versão que a pessoa tinha à vista quando foi
  // olhar a prateleira. É essa versão que o servidor confere ao confirmar.
  const [counting, setCounting] = useState<api.SellableProduct | null>(null)
  const [counted, setCounted] = useState('')
  const [countBase, setCountBase] = useState<api.InventoryBalance | null>(null)
  const [countConflict, setCountConflict] = useState<string>('')
  // Depois de um conflito, confirmar de novo exige um ato deliberado. Sem isto,
  // um clique reenviaria o número contado antes da movimentação contra a versão
  // recém-lida — que é exatamente a aceitação silenciosa que a versão existe
  // para impedir. O número digitado permanece; o que falta é a pessoa dizer que
  // voltou à prateleira.
  const [recounted, setRecounted] = useState(false)
  const openCount = async (item: api.SellableProduct) => {
    if (!store) return
    setCounting(item); setCounted(''); setCountConflict(''); setRecounted(false)
    setCountBase(await api.fetchInventoryBalance(headers, store.id, item.id))
  }
  const submitCount = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!counting || !store || counted === '') return
    setBusy(true)
    try {
      await api.countStock(headers, `count-${counting.id}-${crypto.randomUUID()}`, {
        store_id: store.id, product_id: counting.id, actor_id: operatorId,
        counted_quantity: Number(counted),
        expected_version: countBase?.version ?? 0,
      })
      await refreshData(); await load()
      setCounting(null); setCounted(''); setCountConflict(''); setRecounted(false)
      showToast('success', 'Conferência registrada.')
    } catch (reason) {
      // Conflito não é erro da pessoa: o estoque andou enquanto ela contava. O
      // que ela digitou permanece, o saldo é relido, e ela decide se confirma o
      // mesmo número ou conta de novo. Nunca aceitamos por cima com a versão
      // nova — isso apagaria do estoque a venda que entrou no meio.
      if (reason instanceof ApiError && reason.status === 409) {
        setCountConflict(reason.message)
        setRecounted(false)
        setCountBase(await api.fetchInventoryBalance(headers, store.id, counting.id))
      } else {
        showToast('error', reason instanceof Error ? reason.message : 'Não foi possível registrar a contagem.')
      }
    } finally { setBusy(false) }
  }
  const load = () => store ? api.fetchInventoryMovements(headers, store.id).then(setMovements).catch(() => setMovements([])) : Promise.resolve()
  useEffect(() => { void load() }, [tenant?.id, store?.id])
  const physical = products.filter((item) => item.item_type === 'PRODUCT' && item.name.toLocaleLowerCase('pt-BR').includes(search.toLocaleLowerCase('pt-BR')))
  const low = physical.filter((item) => item.is_low_stock).length
  const totalUnits = physical.reduce((sum, item) => sum + Number(item.quantity), 0)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); if (!selected || !store) return; setBusy(true)
    try {
      await adjustStock(selected.id, Number(form.quantity), form.movement_type, form.reason)
      if (form.minimum_stock !== '') await api.setMinimumStock(headers, store.id, selected.id, Number(form.minimum_stock))
      await refreshData(); await load(); setSelected(null); showToast('success', 'Movimentação registrada no histórico do estoque.')
    } catch { /* o aviso de falha já foi dado por quem chamou a API; aqui só não seguimos adiante */ }
    finally { setBusy(false) }
  }
  return <div className="space-y-6"><section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6"><p className="text-[11px] font-black uppercase tracking-[.18em] text-emerald-700">Controle de mercadorias</p><h1 className="mt-2 text-3xl font-black text-dashem-strong">Estoque por unidade</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-dashem-muted">Saldos, mínimos e entradas são fatos persistidos. Ajustes exigem motivo e ficam no histórico.</p><div className="mt-6 grid gap-3 sm:grid-cols-3"><Metric label="Produtos controlados" value={physical.length} icon={Boxes} /><Metric label="Unidades em saldo" value={totalUnits} icon={PackageCheck} /><Metric label="Atenção necessária" value={low} icon={AlertTriangle} attention={low > 0} /></div></section><div className="relative"><Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-dashem-muted" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por produto ou SKU..." className="h-12 w-full rounded-xl border border-dashem-border bg-dashem-surface pl-11 pr-4 text-sm text-dashem-strong outline-none focus:border-emerald-600" /></div><section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface"><DataTable rows={physical} rowKey={(item) => item.id} empty={<p className="p-8 text-center text-sm font-bold text-dashem-muted">Nenhuma mercadoria controlada nesta unidade.</p>} columns={[ { key: "name", header: "Mercadoria", primary: true, cell: (item) => <div><p className="font-black text-dashem-strong">{item.name}</p><p className="text-xs text-dashem-muted">{item.sku}</p></div> }, { key: "qty", header: "Saldo", cell: (item) => <span className="font-black text-dashem-strong">{Number(item.quantity)} {item.unit}</span> }, { key: "min", header: "Mínimo", cell: (item) => <span className="text-dashem-muted">{Number(item.minimum_stock)} {item.unit}</span> }, { key: "state", header: "Situação", cell: (item) => <span className={`rounded-full px-2 py-1 text-xs font-black ${item.is_low_stock ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>{item.is_low_stock ? "Repor" : "Regular"}</span> }, { key: "action", header: "Ação", actions: true, align: "right", cell: (item) => <div className="flex flex-wrap justify-end gap-2">{canCount ? <button onClick={() => { void openCount(item) }} className="inline-flex min-h-11 items-center rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-strong"><ClipboardCheck className="mr-1 inline h-4 w-4 text-emerald-700" />Contar estoque</button> : null}{canAdjust ? <button onClick={() => { setSelected(item); setForm({ quantity: "", movement_type: "PURCHASE", reason: DEFAULT_STOCK_REASONS.PURCHASE, minimum_stock: String(item.minimum_stock) }) }} className="inline-flex min-h-11 items-center rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-strong"><ArrowDownToLine className="mr-1 inline h-4 w-4 text-emerald-700" />Movimentar</button> : null}{canAdjustTechnically ? <button onClick={() => { setTechnical(item); setTechnicalForm({ difference: '', reason: '' }) }} className="inline-flex min-h-11 items-center rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-strong"><Scale className="mr-1 inline h-4 w-4 text-amber-700" />Ajuste técnico</button> : null}</div> }, ]} /></section><section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5"><div className="flex items-center gap-2"><History className="h-5 w-5 text-emerald-700" /><h2 className="font-black text-dashem-strong">Movimentações recentes</h2></div><div className="mt-4 divide-y divide-dashem-border">{movements.slice(0, 12).map((item) => <div key={item.id} className="grid gap-1 py-3 text-xs sm:grid-cols-[1fr_auto_auto]"><span className="font-bold text-dashem-strong">{products.find((product) => product.id === item.product_id)?.name || item.product_id.slice(0, 8)}</span><span className="text-dashem-muted">{item.movement_type} · {Number(item.quantity)}</span><span className="text-dashem-muted">{formatApiDateTime(item.created_at)}</span></div>)}{movements.length === 0 && <p className="py-6 text-center text-sm text-dashem-muted">Nenhuma movimentação registrada.</p>}</div></section><Modal isOpen={Boolean(technical)} onClose={() => setTechnical(null)} title={`Ajuste técnico de ${technical?.name || ''}`} subtitle="Diferença lançada à mão, quando a contagem não resolve."><form onSubmit={submitTechnical} className="space-y-4"><div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs font-bold text-amber-900">Esta operação não passa pela conferência da prateleira. Prefira <b>Contar estoque</b> sempre que a mercadoria puder ser conferida.</div><Field label="Diferença (use sinal negativo para retirar)" type="number" value={technicalForm.difference} onChange={(value) => setTechnicalForm({ ...technicalForm, difference: value })} /><Field label="Motivo" value={technicalForm.reason} onChange={(value) => setTechnicalForm({ ...technicalForm, reason: value })} /><button disabled={busy || technicalForm.difference === '' || technicalForm.reason.trim().length < 3} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">{busy ? 'Registrando...' : 'Lançar ajuste técnico'}</button></form></Modal><Modal isOpen={Boolean(counting)} onClose={() => setCounting(null)} title={`Contar ${counting?.name || ''}`} subtitle="Informe quanto você encontrou na prateleira. A diferença é calculada aqui."><form onSubmit={submitCount} className="space-y-4"><div className="rounded-xl border border-dashem-border bg-dashem-surface-elevated p-3 text-xs text-dashem-muted"><p>Saldo registrado agora: <b className="text-dashem-strong">{Number(countBase?.quantity ?? 0)} {counting?.unit}</b></p>{counted !== '' && <p className="mt-1 text-dashem-strong">{countPreview(Number(counted), Number(countBase?.quantity ?? 0), counting?.unit || 'un')}</p>}</div><Field label="Quantidade encontrada" type="number" value={counted} onChange={setCounted} />{countConflict && <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs font-bold text-amber-900">{countConflict}<span className="mt-1 block font-medium">O saldo acima já foi relido. O número que você digitou continua aqui, mas ele foi contado antes desta movimentação.</span><label className="mt-3 flex items-center gap-2 font-black"><input type="checkbox" checked={recounted} onChange={(event) => setRecounted(event.target.checked)} className="h-4 w-4" />Voltei à prateleira e confirmo a quantidade acima</label></div>}<button disabled={busy || counted === '' || (Boolean(countConflict) && !recounted)} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">{busy ? 'Registrando...' : 'Confirmar contagem'}</button></form></Modal><Modal isOpen={Boolean(selected)} onClose={() => setSelected(null)} title={`Movimentar ${selected?.name || ''}`} subtitle="Informe a quantidade e o motivo operacional."><form onSubmit={submit} className="space-y-4"><label className="block text-xs font-black text-dashem-strong">Tipo<select value={form.movement_type} onChange={(event) => setForm({ ...form, movement_type: event.target.value, reason: reasonForMovement(form.reason, event.target.value as StockMovementType) })} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong"><option value="PURCHASE">Entrada / compra</option><option value="LOSS">Perda</option><option value="RETURN">Devolução</option><option value="ADJUSTMENT">Ajuste inventariado</option></select></label><Field label="Quantidade" type="number" value={form.quantity} onChange={(value) => setForm({ ...form, quantity: value })} /><Field label="Estoque mínimo" type="number" value={form.minimum_stock} onChange={(value) => setForm({ ...form, minimum_stock: value })} /><Field label="Motivo" value={form.reason} onChange={(value) => setForm({ ...form, reason: value })} /><button disabled={busy || !form.quantity || form.reason.length < 3} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">{busy ? 'Registrando...' : 'Registrar movimentação'}</button></form></Modal></div>
}

function Metric({ label, value, icon: Icon, attention = false }: { label: string; value: number; icon: React.ComponentType<{ className?: string }>; attention?: boolean }) { return <div className="flex items-center gap-4 rounded-2xl bg-dashem-bg p-4"><div className={`flex h-10 w-10 items-center justify-center rounded-xl ${attention ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}><Icon className="h-5 w-5" /></div><div><p className="text-2xl font-black text-dashem-strong">{value}</p><p className="text-xs font-bold text-dashem-muted">{label}</p></div></div> }
function Field({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) { return <label className="block text-xs font-black text-dashem-strong">{label}<input required type={type} step={type === 'number' ? '0.001' : undefined} value={value} onChange={(event) => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong outline-none focus:border-dashem-red" /></label> }
