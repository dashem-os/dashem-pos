import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, ChevronLeft, ChevronRight, GripVertical, LayoutGrid, Star, X } from 'lucide-react'

import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { formatCurrency } from '../../utils/format'

/**
 * The two bands of the operation's first screen.
 *
 * "Meus atalhos" belongs to the person and only exists while their operational
 * session does. "Vitrine da unidade" belongs to the store and keeps the same
 * positions for everyone, which is what makes muscle memory possible across a
 * shift change — so a product that appears in someone's band is NOT removed
 * from the window. De-duplicating would shift the arrangement under whoever
 * personalised it, which is the exact thing the separate band avoids.
 *
 * Reordering happens only in an explicit mode. On a touch screen a drag that is
 * always live cannot be told apart from a scroll or from the tap that sells,
 * and the tap that sells is the one that must never be ambiguous.
 */

type Mode = 'OFF' | 'STORE' | 'PERSONAL'

interface Props {
  onPick: (product: api.SellableProduct) => void
  disabled?: boolean
}

export const ProductShowcase: React.FC<Props> = ({ onPick, disabled }) => {
  const { products, tenant, store, permissions, operationMode, activeActivity, showToast } = usePos()

  const [layout, setLayout] = useState<api.StoreCatalogLayout | null>(null)
  const [personal, setPersonal] = useState<string[]>([])
  const [mode, setMode] = useState<Mode>('OFF')
  const [draft, setDraft] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const canManage = permissions.includes('catalog.layout.manage')
  const canPersonalize = permissions.includes('catalog.layout.personalize')

  const headers = useMemo(
    () => (tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : null),
    [tenant, store],
  )
  const scope = useMemo(
    () => ({ sales_context: operationMode, business_activity: activeActivity || undefined }),
    [operationMode, activeActivity],
  )

  const byId = useMemo(() => new Map(products.map((product) => [product.id, product])), [products])

  const load = useCallback(async () => {
    if (!headers) return
    const [nextLayout, nextPersonal] = await Promise.all([
      api.fetchStoreLayout(headers, scope.sales_context, scope.business_activity).catch(() => null),
      api.fetchQuickAccess(headers, scope.sales_context, scope.business_activity).catch(() => []),
    ])
    setLayout(nextLayout)
    setPersonal(nextPersonal.map((entry) => entry.product_id))
  }, [headers, scope.sales_context, scope.business_activity])

  useEffect(() => { void load() }, [load])

  // An arrangement never renders a product the catalogue no longer offers: a
  // dead button on the first screen is worse than an absent one.
  const visible = useCallback((ids: string[]) => ids.filter((id) => byId.has(id)), [byId])
  const storeIds = useMemo(() => visible(layout?.product_ids ?? []), [layout, visible])
  const personalIds = useMemo(() => visible(personal), [personal, visible])

  const startEditing = (next: Mode) => {
    setDraft(next === 'STORE' ? storeIds : personalIds)
    setMode(next)
  }

  const move = (from: number, to: number) => {
    if (to < 0 || to >= draft.length) return
    const next = [...draft]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    setDraft(next)
  }

  const save = async () => {
    if (!headers) return
    setBusy(true)
    try {
      if (mode === 'STORE') {
        const saved = await api.reorderStoreLayout(headers, {
          product_ids: draft, expected_version: layout?.version ?? 0, ...scope,
        })
        setLayout(saved)
        showToast('success', 'Vitrine da unidade atualizada.')
      } else {
        const saved = await api.reorderQuickAccess(headers, { product_ids: draft, ...scope })
        setPersonal(saved.map((entry) => entry.product_id))
        showToast('success', 'Seus atalhos foram salvos.')
      }
      setMode('OFF')
    } catch (reason) {
      // A 409 means someone else arranged the same window while this one was
      // open. Reloading is the honest answer: the person sees what is there now
      // instead of overwriting a colleague.
      showToast('error', reason instanceof Error ? reason.message : 'Não foi possível salvar a ordem.')
      await load()
    } finally {
      setBusy(false)
    }
  }

  const Card: React.FC<{ product: api.SellableProduct }> = ({ product }) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onPick(product)}
      className="group flex min-h-[132px] w-36 shrink-0 flex-col justify-between rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm transition-all hover:border-rose-400 hover:shadow-md active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
    >
      {(product.image?.url || product.image_url) ? (
        <img src={product.image?.url || product.image_url} alt="" loading="lazy" className="h-16 w-full rounded-xl border border-slate-100 object-cover" />
      ) : (
        <div className="flex h-16 w-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-lg font-black text-slate-300">
          {product.name.charAt(0).toUpperCase()}
        </div>
      )}
      <p className="mt-2 line-clamp-2 text-xs font-bold text-slate-800">{product.name}</p>
      <p className="text-sm font-black text-slate-900">{formatCurrency(Number(product.sale_price))}</p>
    </button>
  )

  const Editable: React.FC<{ id: string; index: number }> = ({ id, index }) => {
    const product = byId.get(id)
    if (!product) return null
    return (
      <div
        draggable
        onDragStart={(event) => event.dataTransfer.setData('text/plain', String(index))}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          move(Number(event.dataTransfer.getData('text/plain')), index)
        }}
        className="flex w-36 shrink-0 flex-col rounded-2xl border-2 border-dashed border-rose-300 bg-rose-50/40 p-3"
      >
        <div className="flex items-center justify-between text-rose-700">
          <GripVertical className="h-4 w-4 cursor-grab" />
          <span className="text-[10px] font-black">{index + 1}</span>
        </div>
        <p className="mt-1 line-clamp-2 text-xs font-bold text-slate-800">{product.name}</p>
        {/* Dragging is for a mouse. These move the item on any screen, which is
            the only thing that reliably works under a finger. */}
        <div className="mt-2 flex items-center justify-between">
          <button type="button" aria-label={`Mover ${product.name} para trás`} onClick={() => move(index, index - 1)}
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-rose-200 bg-white text-rose-700 disabled:opacity-30"
            disabled={index === 0}>
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button type="button" aria-label={`Mover ${product.name} para frente`} onClick={() => move(index, index + 1)}
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-rose-200 bg-white text-rose-700 disabled:opacity-30"
            disabled={index === draft.length - 1}>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    )
  }

  const Band: React.FC<{ title: string; icon: React.ReactNode; ids: string[]; editing: boolean; empty: string }> = ({
    title, icon, ids, editing, empty,
  }) => (
    <section className="mb-5">
      <div className="mb-2 flex items-center gap-2">
        {icon}
        <h3 className="text-xs font-black uppercase tracking-wider text-slate-500">{title}</h3>
      </div>
      {ids.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-xs text-slate-500">{empty}</p>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {ids.map((id, index) =>
            editing
              ? <Editable key={id} id={id} index={index} />
              : byId.has(id) && <Card key={id} product={byId.get(id)!} />,
          )}
        </div>
      )}
    </section>
  )

  return (
    <div>
      {mode !== 'OFF' && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-3">
          <p className="text-xs font-black text-rose-900">
            {mode === 'STORE' ? 'Personalizando a vitrine da unidade' : 'Personalizando seus atalhos'} · arraste ou use as setas
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={() => setMode('OFF')} disabled={busy}
              className="flex h-10 items-center gap-1 rounded-xl border border-slate-300 bg-white px-3 text-xs font-black text-slate-600">
              <X className="h-4 w-4" />Cancelar
            </button>
            <button type="button" onClick={() => void save()} disabled={busy}
              className="flex h-10 items-center gap-1 rounded-xl bg-rose-600 px-4 text-xs font-black text-white disabled:opacity-40">
              <Check className="h-4 w-4" />Salvar ordem
            </button>
          </div>
        </div>
      )}

      {(personalIds.length > 0 || mode === 'PERSONAL') && (
        <Band
          title="Meus atalhos"
          icon={<Star className="h-4 w-4 text-amber-500" />}
          ids={mode === 'PERSONAL' ? draft : personalIds}
          editing={mode === 'PERSONAL'}
          empty="Você ainda não fixou atalhos. Eles aparecem só para você, enquanto seu turno estiver aberto."
        />
      )}

      <Band
        title="Vitrine da unidade"
        icon={<LayoutGrid className="h-4 w-4 text-rose-600" />}
        ids={mode === 'STORE' ? draft : storeIds}
        editing={mode === 'STORE'}
        empty="A vitrine desta unidade ainda não foi montada. A gerência define os itens que aparecem primeiro."
      />

      {mode === 'OFF' && (
        <div className="flex flex-wrap gap-2">
          {canPersonalize && (
            <button type="button" onClick={() => startEditing('PERSONAL')}
              className="h-10 rounded-xl border border-slate-300 bg-white px-3 text-xs font-black text-slate-600">
              Personalizar meus atalhos
            </button>
          )}
          {canManage && (
            <button type="button" onClick={() => startEditing('STORE')}
              className="h-10 rounded-xl border border-rose-200 bg-white px-3 text-xs font-black text-rose-700">
              Personalizar vitrine da unidade
            </button>
          )}
        </div>
      )}
    </div>
  )
}
