import React, { useEffect, useMemo, useState } from 'react'
import { Archive, Package, Plus, Search, ArrowUpDown, CheckCircle2, Star, AlertCircle, Layers, Store } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Modal } from '../common/Modal'
import * as api from '../../services/api'
import { Button } from '../common/Button'
import { DataTable } from '../common/DataTable'
import { formatCurrency } from '../../utils/format'
import { PendingMedia, ProductMediaPicker } from './ProductMediaPicker'

/** The product photo, falling back to the initial when a tenant has not set one. */
function ProductThumb({ name, imageUrl }: { name: string; imageUrl?: string | null }) {
  if (imageUrl) {
    return <img src={imageUrl} alt="" className="h-10 w-10 shrink-0 rounded-lg border border-dashem-border object-cover" />
  }
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-dashem-border bg-dashem-surface-elevated text-sm font-black text-dashem-muted">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  )
}

export const CatalogManager: React.FC = () => {
  const { tenant, store, products, prices, balances, createNewProduct, adjustStock, refreshData, actionLoading, activeActivity, showToast } = usePos()
  const mediaHeaders = useMemo(
    () => tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : null,
    [tenant?.id, store?.id],
  )
  const [searchQuery, setSearchQuery] = useState('')
  const [catalogItems, setCatalogItems] = useState<api.SellableProduct[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [isStockModalOpen, setIsStockModalOpen] = useState(false)
  const [selectedProductForStock, setSelectedProductForStock] = useState<string | null>(null)
  const [productToArchive, setProductToArchive] = useState<api.SellableProduct | null>(null)
  const [activeAssortments, setActiveAssortments] = useState<api.Assortment[]>([])
  const [publishAssortmentId, setPublishAssortmentId] = useState('')

  // New Product Form
  const [name, setName] = useState('')
  const [sku, setSku] = useState('')
  const [barcode, setBarcode] = useState('')
  const [pendingMedia, setPendingMedia] = useState<PendingMedia | null>(null)
  const [itemType, setItemType] = useState<'PRODUCT' | 'SERVICE'>('PRODUCT')
  const [priceInput, setPriceInput] = useState('')
  const [stockInput, setStockInput] = useState('')

  // Adjust Stock Form
  const [adjustQty, setAdjustQty] = useState('')
  const [adjustType, setAdjustType] = useState<'PURCHASE' | 'LOSS' | 'ADJUSTMENT'>('PURCHASE')
  const [adjustReason, setAdjustReason] = useState('Entrada de Mercadoria')
  const [minimumStock, setMinimumStock] = useState('')
  const [viewMode, setViewMode] = useState<'MASTER' | 'PROJECTION'>('MASTER')
  const [salesContext, setSalesContext] = useState<api.SalesContext>('COUNTER')
  const [contextError, setContextError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    if (!tenant || !store) return

    const timer = window.setTimeout(() => {
      setContextError(null)
      api.fetchSellableProducts(
        { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id },
        {
          sales_context: salesContext,
          master: viewMode === 'MASTER',
          page,
          pageSize: 25,
          search: searchQuery.trim() || undefined,
        }
      ).then((result) => {
        setCatalogItems(result.items)
        setTotal(result.total)
        setContextError(null)
      }).catch((err: unknown) => {
        setCatalogItems([])
        setTotal(0)
        setContextError(err instanceof Error ? err.message : 'Falha ao carregar catálogo.')
      })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [tenant, store, page, searchQuery, viewMode, salesContext, reloadKey])

  useEffect(() => {
    if (!isAddModalOpen || !mediaHeaders) return
    let alive = true
    void api.fetchAssortments(mediaHeaders, { status: 'ACTIVE', storeId: store?.id, pageSize: 100 })
      .then((result) => { if (alive) setActiveAssortments(result.items) })
      .catch(() => { if (alive) setActiveAssortments([]) })
    return () => { alive = false }
  }, [isAddModalOpen, mediaHeaders, store?.id])

  const openAddProduct = () => {
    setPublishAssortmentId('')
    setIsAddModalOpen(true)
  }

  const handleCreateProduct = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name || !sku || !priceInput) return

    const created = await createNewProduct(
      { name, sku, barcode: barcode || undefined, item_type: itemType },
      parseFloat(priceInput),
      itemType === 'PRODUCT' ? parseInt(stockInput || '0', 10) : 0
    )
    if (!created) return

    // The picture is attached after the product exists. A failure here leaves a
    // product without a photo, which is a state the catalogue already handles —
    // never a half-created product.
    if (created && pendingMedia && pendingMedia.kind !== 'CLEAR' && mediaHeaders) {
      try {
        await api.setProductMedia(mediaHeaders, created.id, pendingMedia.kind === 'LIBRARY'
          ? { library_asset_id: pendingMedia.library_asset_id }
          : {
              bucket_id: pendingMedia.bucket_id, object_path: pendingMedia.object_path,
              content_type: pendingMedia.content_type, size_bytes: pendingMedia.size_bytes,
              original_filename: pendingMedia.original_filename,
            })
      } catch (reason) {
        showToast('error', reason instanceof Error ? reason.message : 'Produto criado, mas a foto não foi vinculada.')
      }
    }

    if (publishAssortmentId && mediaHeaders) {
      const target = activeAssortments.find((assortment) => assortment.id === publishAssortmentId)
      if (target) {
        try {
          await api.linkAssortmentProducts(
            mediaHeaders, target.id, [created.id], target.version,
            `publish-new-product-${created.id}-${target.id}`,
          )
          showToast('success', `Produto publicado em “${target.name}” e disponível nos contextos desse sortimento.`)
        } catch (reason) {
          showToast('error', reason instanceof Error
            ? `Produto cadastrado, mas não foi publicado: ${reason.message}`
            : 'Produto cadastrado, mas não foi possível publicá-lo no sortimento.')
        }
      }
    } else {
      showToast('info', 'Produto cadastrado no acervo. Para aparecer no PDV, publique-o em um sortimento ativo.')
    }

    await refreshData()
    setReloadKey((key) => key + 1)

    setName('')
    setSku('')
    setBarcode('')
    setPendingMedia(null)
    setPriceInput('')
    setStockInput('')
    setIsAddModalOpen(false)
  }

  const handleAdjustStock = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedProductForStock || !adjustQty) return

    await adjustStock(selectedProductForStock, parseFloat(adjustQty), adjustType, adjustReason)
    if (tenant && store && minimumStock !== '') {
      await api.setMinimumStock(
        { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id },
        store.id,
        selectedProductForStock,
        parseFloat(minimumStock)
      )
    }
    setAdjustQty('')
    setMinimumStock('')
    setSelectedProductForStock(null)
    setIsStockModalOpen(false)
  }

  const handleQuickAccess = async (product: api.SellableProduct) => {
    if (!tenant || !store) return
    const headers = { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
    if (product.quick_position != null) {
      await api.removeQuickAccess(headers, product.id)
      setCatalogItems((items) => items.map((item) => item.id === product.id ? { ...item, quick_position: undefined } : item))
      return
    }
    const used = new Set(catalogItems.flatMap((item) => item.quick_position == null ? [] : [item.quick_position]))
    let position = 1
    while (used.has(position)) position += 1
    await api.setQuickAccess(headers, product.id, position)
    setCatalogItems((items) => items.map((item) => item.id === product.id ? { ...item, quick_position: position } : item))
  }

  const archiveProduct = async () => {
    if (!tenant || !store || !productToArchive) return
    const headers = { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
    await api.updateProduct(headers, productToArchive.id, { is_active: false, available_for_sale: false })
    setCatalogItems(items => items.filter(item => item.id !== productToArchive.id))
    setTotal(value => Math.max(0, value - 1))
    setProductToArchive(null)
    await refreshData()
  }

  return (
    <div className="space-y-6">
      {/* Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-black text-dashem-strong tracking-tight flex items-center space-x-2">
            <Package className="w-5 h-5 text-dashem-red" />
            <span>Produtos, preços e estoque</span>
          </h2>
          <p className="text-xs text-dashem-muted font-medium mt-0.5">
            Cadastre o que o negócio comercializa. A publicação no PDV é definida nos sortimentos.
          </p>
        </div>

        <button
          onClick={openAddProduct}
          className="h-11 px-5 rounded-2xl bg-dashem-red hover:bg-dashem-red-light text-brand-contrast text-xs font-black flex items-center justify-center space-x-2 transition-all shadow-md shadow-dashem-red/30 active:scale-95 shrink-0"
        >
          <Plus className="w-4 h-4" />
          <span>Cadastrar Novo Produto</span>
        </button>
      </div>

      <section className="grid gap-2 rounded-2xl border border-dashem-border bg-dashem-surface p-3 sm:grid-cols-3" aria-label="Como um produto chega ao PDV">
        <div className="flex items-start gap-3 rounded-xl bg-dashem-surface-elevated p-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-dashem-red text-xs font-black text-brand-contrast">1</span>
          <div><p className="text-xs font-black text-dashem-strong">Cadastre o produto</p><p className="mt-1 text-xs leading-5 text-dashem-muted">Nome, foto, preço e estoque pertencem ao acervo do negócio.</p></div>
        </div>
        <div className="flex items-start gap-3 rounded-xl bg-dashem-surface-elevated p-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-dashem-red text-xs font-black text-brand-contrast">2</span>
          <div><p className="text-xs font-black text-dashem-strong">Publique em um sortimento</p><p className="mt-1 text-xs leading-5 text-dashem-muted">Escolha em quais unidades e jornadas ele será vendido.</p></div>
        </div>
        <div className="flex items-start gap-3 rounded-xl bg-dashem-surface-elevated p-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-dashem-red text-xs font-black text-brand-contrast">3</span>
          <div><p className="text-xs font-black text-dashem-strong">Venda no PDV</p><p className="mt-1 text-xs leading-5 text-dashem-muted">O item aparece apenas nos contextos onde foi publicado.</p></div>
        </div>
      </section>

      {/* View Mode Switcher: Master Catalog vs Operational Projection */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-dashem-border pb-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { setViewMode('MASTER'); setPage(1); setContextError(null) }}
            className={`px-4 py-2 rounded-2xl text-xs font-black transition ${
              viewMode === 'MASTER'
                ? 'bg-dashem-red text-brand-contrast shadow-sm'
                : 'bg-dashem-surface border border-dashem-border text-dashem-muted hover:text-dashem-strong'
            }`}
          >
            Todos os produtos ({viewMode === 'MASTER' ? total : products.length})
          </button>
          <button
            type="button"
            onClick={() => { setViewMode('PROJECTION'); setPage(1) }}
            className={`px-4 py-2 rounded-2xl text-xs font-black transition ${
              viewMode === 'PROJECTION'
                ? 'bg-dashem-red text-brand-contrast shadow-sm'
                : 'bg-dashem-surface border border-dashem-border text-dashem-muted hover:text-dashem-strong'
            }`}
          >
            Publicados por contexto
          </button>
        </div>

        {viewMode === 'PROJECTION' && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-bold text-dashem-muted mr-1">Contexto de Venda:</span>
            {([
              { key: 'COUNTER', label: 'Balcão', operational: true },
              { key: 'TAKEAWAY', label: 'Retirada', operational: true },
              { key: 'TABLE', label: 'Mesa', operational: true },
              { key: 'DELIVERY', label: 'Delivery', operational: true },
              { key: 'ECOMMERCE', label: 'E-commerce', operational: false },
            ] as const).map((item) => {
              const active = salesContext === item.key
              return (
                <button
                  key={item.key}
                  type="button"
                  disabled={!item.operational}
                  onClick={() => { setSalesContext(item.key as api.SalesContext); setPage(1) }}
                  className={`px-3 py-1.5 rounded-xl text-xs font-bold transition ${
                    !item.operational
                      ? 'opacity-40 cursor-not-allowed bg-dashem-surface border border-dashem-border text-dashem-muted'
                      : active
                        ? 'bg-brand text-brand-contrast font-black shadow-sm'
                        : 'bg-dashem-surface border border-dashem-border text-dashem-muted hover:text-dashem-strong'
                  }`}
                  title={!item.operational ? 'Jornada não contratada' : undefined}
                >
                  {item.label}
                </button>
              )
            })}
          </div>
        )}
      </div>

      <p className="-mt-3 text-xs leading-5 text-dashem-muted">
        {viewMode === 'MASTER'
          ? 'Acervo completo deste tenant. Estar aqui não significa que o item já aparece no PDV.'
          : 'Prévia exata do que está publicado e pode ser vendido no contexto selecionado.'}
      </p>

      {/* Explicit Error Banner & Retry */}
      {contextError && (
        <div className="p-4 rounded-2xl bg-rose-50 border border-rose-200 flex items-center justify-between text-xs text-rose-700">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-700 shrink-0" />
            <span>{contextError}</span>
          </div>
          <button
            type="button"
            onClick={() => setReloadKey(k => k + 1)}
            className="px-3 py-1 rounded-xl bg-rose-50 hover:bg-rose-100 border border-rose-200 text-xs font-bold text-rose-700 transition"
          >
            Tentar novamente
          </button>
        </div>
      )}

      {/* Search Input */}
      <div className="relative">
        <Search className="w-4 h-4 text-dashem-muted absolute left-4 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => { setSearchQuery(e.target.value); setPage(1) }}
          placeholder="Buscar produto por nome, SKU ou código de barras..."
          className="w-full h-11 pl-11 pr-4 rounded-xl bg-dashem-surface border border-dashem-border text-dashem-strong text-xs font-medium focus:border-dashem-red outline-none"
        />
      </div>

      {/* Products: a real table on wide screens, one card per product on narrow. */}
      <div className="bg-dashem-surface border border-dashem-border rounded-2xl overflow-hidden shadow-sm md:p-0">
        <DataTable
          rows={catalogItems}
          rowKey={(prod) => prod.id}
          empty={<div className="p-8 text-center text-sm font-bold text-dashem-muted">Nenhum produto encontrado neste contexto.</div>}
          columns={[
            {
              key: 'name', header: 'Produto', primary: true,
              cell: (prod) => (
                <div className="flex items-center gap-3">
                  <ProductThumb name={prod.name} imageUrl={prod.image?.url || prod.image_url} />
                  <div className="min-w-0">
                    <span className="block font-bold text-dashem-strong">{prod.name}</span>
                    {prod.description && <span className="text-xs text-dashem-muted">{prod.description}</span>}
                  </div>
                </div>
              ),
            },
            {
              key: 'sku', header: 'SKU / EAN',
              cell: (prod) => (
                <div>
                  <span className="block font-mono text-dashem-strong">{prod.sku}</span>
                  {prod.barcode && <span className="text-xs text-dashem-muted">EAN: {prod.barcode}</span>}
                </div>
              ),
            },
            {
              key: 'type', header: 'Tipo',
              cell: (prod) => (
                <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-bold uppercase ${
                  prod.item_type === 'SERVICE'
                    ? 'bg-amber-50 text-amber-700 border border-amber-200'
                    : 'bg-dashem-surface-elevated text-dashem-muted border border-dashem-border'
                }`}>{prod.item_type === 'SERVICE' ? 'Serviço' : 'Produto'}</span>
              ),
            },
            {
              key: 'price', header: 'Preço de venda', align: 'right',
              cell: (prod) => <span className="font-black text-dashem-strong">{formatCurrency(Number(prod.sale_price))}</span>,
            },
            {
              key: 'stock', header: 'Atual / mínimo', align: 'right',
              cell: (prod) => prod.item_type === 'SERVICE'
                ? <span className="text-dashem-muted">—</span>
                : (
                  <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-bold ${
                    !prod.is_low_stock ? 'text-emerald-700 bg-emerald-50'
                      : Number(prod.quantity) > 0 ? 'text-amber-700 bg-amber-50'
                      : 'text-rose-700 bg-rose-50'
                  }`}>
                    {Number(prod.quantity)} / {Number(prod.minimum_stock)} {prod.unit.toLowerCase()}
                  </span>
                ),
            },
            {
              key: 'actions', header: 'Ações', actions: true, align: 'right',
              cell: (prod) => (
                <div className="inline-flex flex-wrap gap-2">
                  <Button variant="secondary" size="sm" icon={Archive} onClick={() => setProductToArchive(prod)}
                    title="Arquivar e retirar do PDV" className="border-amber-200 bg-amber-50 text-amber-700" aria-label="Arquivar" />
                  <Button variant="secondary" size="sm" onClick={() => handleQuickAccess(prod)}
                    title={prod.quick_position != null ? 'Remover do acesso rápido' : 'Adicionar ao acesso rápido'}
                    aria-label="Acesso rápido">
                    <Star className={`h-4 w-4 ${prod.quick_position != null ? 'fill-amber-400 text-amber-700' : 'text-dashem-muted'}`} />
                  </Button>
                  {prod.item_type !== 'SERVICE' && (
                    <Button variant="secondary" size="sm" icon={ArrowUpDown} onClick={() => {
                      setSelectedProductForStock(prod.id)
                      setMinimumStock(String(prod.minimum_stock))
                      setIsStockModalOpen(true)
                    }}>Ajustar</Button>
                  )}
                </div>
              ),
            },
          ]}
        />
      </div>

      <div className="flex items-center justify-between text-xs text-dashem-muted">
        <span>{total} item(ns) no catálogo</span>
        <div className="flex gap-2">
          <button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)} className="px-3 py-2 rounded-lg border border-dashem-border disabled:opacity-30">Anterior</button>
          <span className="px-3 py-2">Página {page}</span>
          <button type="button" disabled={page * 25 >= total} onClick={() => setPage((value) => value + 1)} className="px-3 py-2 rounded-lg border border-dashem-border disabled:opacity-30">Próxima</button>
        </div>
      </div>

      {/* Modal: Cadastrar Produto */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="Cadastrar Novo Produto"
        subtitle="Cadastre os dados e decida se o item já deve ser publicado no PDV"
        maxWidth="2xl"
      >
        <form onSubmit={handleCreateProduct} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-bold text-dashem-strong block">Nome do Produto / Serviço</label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex.: Hambúrguer artesanal, diária ou camiseta"
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-dashem-strong block">SKU / Código</label>
              <input
                type="text"
                required
                value={sku}
                onChange={(e) => setSku(e.target.value)}
                placeholder="Ex: CAB-25"
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-bold text-dashem-strong block">Código de Barras (EAN)</label>
              <input
                type="text"
                value={barcode}
                onChange={(e) => setBarcode(e.target.value)}
                placeholder="Ex: 789123456789"
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
              />
            </div>
          </div>

          {mediaHeaders && (
            <ProductMediaPicker
              headers={mediaHeaders}
              activity={activeActivity}
              onChange={setPendingMedia}
            />
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-dashem-strong block">Tipo</label>
              <select
                value={itemType}
                onChange={(e) => setItemType(e.target.value as any)}
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
              >
                <option value="PRODUCT">Produto Físico</option>
                <option value="SERVICE">Serviço / Mão de Obra</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-bold text-dashem-strong block">Preço de Venda (R$)</label>
              <input
                type="number"
                step="0.01"
                required
                value={priceInput}
                onChange={(e) => setPriceInput(e.target.value)}
                placeholder="Ex: 49.90"
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
              />
            </div>
          </div>

          {itemType === 'PRODUCT' && (
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-dashem-strong block">Estoque Inicial (unidades)</label>
              <input
                type="number"
                value={stockInput}
                onChange={(e) => setStockInput(e.target.value)}
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
              />
            </div>
          )}

          <section className="space-y-2 rounded-2xl border border-dashem-border bg-dashem-surface-elevated/40 p-4">
            <div className="flex items-start gap-2">
              <Layers className="mt-0.5 h-4 w-4 shrink-0 text-dashem-red" />
              <div>
                <h4 className="text-sm font-black text-dashem-strong">Publicação no PDV</h4>
                <p className="mt-1 text-xs leading-5 text-dashem-muted">
                  Produto é o cadastro. Sortimento define onde ele aparece e pode ser vendido.
                </p>
              </div>
            </div>
            <label className="block text-xs font-bold text-dashem-strong" htmlFor="new-product-assortment">Publicar agora em</label>
            <select
              id="new-product-assortment"
              value={publishAssortmentId}
              onChange={(event) => setPublishAssortmentId(event.target.value)}
              className="h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface px-3.5 text-xs font-semibold text-dashem-strong outline-none focus:border-dashem-red"
            >
              <option value="">Não publicar agora — manter somente em Todos os produtos</option>
              {activeAssortments.map((assortment) => (
                <option key={assortment.id} value={assortment.id}>
                  {assortment.name} · {assortment.scopes.map((scope) => ({ COUNTER: 'Balcão', TAKEAWAY: 'Retirada', TABLE: 'Mesa', DELIVERY: 'Delivery', ECOMMERCE: 'E-commerce' }[scope.sales_context])).filter(Boolean).join(', ') || 'sem contexto'}
                </option>
              ))}
            </select>
            {activeAssortments.length === 0 && (
              <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-800">
                <Store className="h-3.5 w-3.5" /> Crie primeiro um sortimento ativo para publicar este item no PDV.
              </p>
            )}
          </section>

          <div className="pt-3">
            <button
              type="submit"
              disabled={actionLoading}
              className="w-full h-12 rounded-2xl bg-dashem-red hover:bg-dashem-red-light text-brand-contrast text-xs font-black flex items-center justify-center space-x-2 transition-all shadow-lg active:scale-95 disabled:opacity-40"
            >
              <Plus className="w-4 h-4" />
              <span>{publishAssortmentId ? 'Cadastrar e publicar produto' : 'Cadastrar produto'}</span>
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Ajustar Estoque */}
      <Modal
        isOpen={isStockModalOpen}
        onClose={() => setIsStockModalOpen(false)}
        title="Ajustar Inventário de Estoque"
        subtitle="Registra movimentação de entrada ou baixa com auditoria"
      >
        <form onSubmit={handleAdjustStock} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-bold text-dashem-strong block">Tipo de Movimentação</label>
            <select
              value={adjustType}
              onChange={(e) => setAdjustType(e.target.value as any)}
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
            >
              <option value="PURCHASE">Entrada / Compra de Mercadoria</option>
              <option value="LOSS">Perda / Avaria / Vencimento</option>
              <option value="ADJUSTMENT">Ajuste de Balanço / Inventário</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-dashem-strong block">Quantidade</label>
            <input
              type="number"
              step="1"
              required
              value={adjustQty}
              onChange={(e) => setAdjustQty(e.target.value)}
              placeholder="Ex: 10"
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-dashem-strong block">Motivo / Observação</label>
            <input
              type="text"
              value={adjustReason}
              onChange={(e) => setAdjustReason(e.target.value)}
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-dashem-strong block">Estoque mínimo desta unidade</label>
            <input
              type="number"
              min="0"
              step="0.01"
              required
              value={minimumStock}
              onChange={(e) => setMinimumStock(e.target.value)}
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-semibold focus:border-dashem-red outline-none"
            />
          </div>

          <div className="pt-3">
            <button
              type="submit"
              disabled={actionLoading}
              className="w-full h-12 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-black flex items-center justify-center space-x-2 transition-all shadow-lg active:scale-95 disabled:opacity-40"
            >
              <CheckCircle2 className="w-4 h-4" />
              <span>Confirmar Ajuste de Estoque</span>
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={Boolean(productToArchive)} onClose={() => setProductToArchive(null)} title="Arquivar item do catálogo" subtitle="O item deixa o PDV sem apagar seu histórico."><div className="space-y-4"><p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-bold text-amber-700">{productToArchive?.name} será retirado da venda e do acesso rápido. Vendas, estoque e auditoria permanecem preservados.</p><div className="grid grid-cols-1 sm:grid-cols-2 gap-3"><button onClick={() => setProductToArchive(null)} className="h-11 rounded-xl border border-dashem-border font-black text-dashem-strong">Cancelar</button><button disabled={actionLoading} onClick={() => void archiveProduct()} className="h-11 rounded-xl bg-amber-600 font-black text-white disabled:opacity-40">Arquivar item</button></div></div></Modal>
    </div>
  )
}
