import React, { useEffect, useRef, useState } from 'react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { ApiError } from '../../services/http'
import { Modal } from '../common/Modal'
import { ProductSelector } from '../pos/ProductSelector'
import { ProductSelectionProvider } from '../pos/ProductSelectionContext'

export function TableProductSelector({ session, order, onClose, onChanged }: {
  session: api.TableSession; order: api.Order; onClose: () => void; onChanged: () => Promise<void>
}) {
  const pos = usePos()
  const [products, setProducts] = useState<api.SellableProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [quantity, setQuantity] = useState('1')
  const [feedback, setFeedback] = useState('')
  const [retry, setRetry] = useState(0)
  const locked = useRef(false)
  const pending = useRef<{ product: string; quantity: number; key: string } | null>(null)
  const headers = { 'X-Tenant-ID': session.tenant_id, 'X-Store-ID': session.store_id }
  const allowed = pos.permissions.includes('table.session.update') && pos.connectionState === 'ONLINE' && order.status === 'OPEN'
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setProducts([])
    void (async () => {
      try {
        const items: api.SellableProduct[] = []
        let page = 1
        while (true) {
          const result = await api.fetchSellableProducts(headers, { sales_context: 'TABLE', activity: 'FOOD_SERVICE', page, pageSize: 100 })
          if (!active) return
          items.push(...result.items)
          if (!result.items.length || items.length >= result.total) break
          page++
        }
        setProducts(items)
      } catch { if (active) setError('Não foi possível carregar o cardápio da mesa. Tente novamente.') }
      finally { if (active) setLoading(false) }
    })()
    return () => { active = false }
  }, [session.tenant_id, session.store_id, retry])

  const pick = async (product: api.SellableProduct) => {
    const count = Number(quantity)
    if (locked.current || !allowed || !Number.isFinite(count) || count <= 0) return false
    if (pending.current && (pending.current.product !== product.id || pending.current.quantity !== count)) {
      setFeedback('Confirme o lançamento pendente repetindo o mesmo produto e quantidade antes de iniciar outro.')
      return false
    }
    locked.current = true; setBusy(true)
    pending.current ??= { product: product.id, quantity: count, key: crypto.randomUUID() }
    try {
      await api.addOrderItem(headers, order.id, pending.current.key, { product_id: product.id, quantity: count, actor_id: pos.operatorId })
      pending.current = null
      setFeedback(`${count} × ${product.name} lançado em ${order.notes || 'comanda selecionada'}.`)
      setQuantity('1')
      try { await onChanged() } catch { setFeedback('Item lançado. Não foi possível atualizar o resumo; atualize o atendimento antes de conferir o total.') }
      return true
    } catch (reason) {
      const rejected = reason instanceof ApiError && reason.status >= 400 && reason.status < 500 && reason.status !== 408
      if (rejected) pending.current = null
      setFeedback(`${reason instanceof Error ? reason.message : 'Falha no lançamento'}.${rejected ? ' Corrija a informação antes de tentar novamente.' : ' Repita o mesmo item para confirmar sem duplicar.'}`)
      return false
    } finally { locked.current = false; setBusy(false) }
  }
  return <Modal isOpen onClose={() => { if (!locked.current && !pending.current) onClose(); else setFeedback('Confirme o lançamento pendente antes de fechar.') }} maxWidth="2xl"
    title={`Adicionar · ${session.display_label}`} subtitle={`Destino: ${order.notes || 'Comanda'} · Mesa/Comanda · Alimentação`}>
    <div className="space-y-4">
      <label className="block text-sm font-bold">Quantidade por toque
        <input aria-label="Quantidade por toque" disabled={busy || Boolean(pending.current)} type="number" min="0.001" step="0.001" value={quantity} onChange={e => setQuantity(e.target.value)} className="ml-3 h-11 w-24 rounded-xl border border-slate-300 bg-white px-3 text-slate-900" />
      </label>
      {feedback && <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-900">{feedback}</p>}
      {loading ? <p role="status">Carregando cardápio da mesa…</p> : error ? <div role="alert"><p>{error}</p><button onClick={() => setRetry(value => value + 1)} className="min-h-11 rounded-xl border px-4">Tentar novamente</button></div> :
        <ProductSelectionProvider value={{ tenant: pos.tenant, store: pos.store, products, categories: pos.categories,
          permissions: pos.permissions, activeActivity: 'FOOD_SERVICE', showToast: pos.showToast,
          activities: pos.activities, contributions: pos.contributions,
          operationMode: 'TABLE', enabled: allowed, actionLoading: busy, onPick: pick }}><ProductSelector /></ProductSelectionProvider>}
    </div>
  </Modal>
}
