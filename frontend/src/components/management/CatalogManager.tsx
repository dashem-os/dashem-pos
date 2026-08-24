import React, { useEffect, useState } from 'react'
import { Archive, Package, Plus, Search, ArrowUpDown, CheckCircle2, Star } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Modal } from '../common/Modal'
import * as api from '../../services/api'

export const CatalogManager: React.FC = () => {
  const { tenant, store, products, createNewProduct, adjustStock, refreshData, actionLoading } = usePos()
  const [searchQuery, setSearchQuery] = useState('')
  const [catalogItems, setCatalogItems] = useState<api.SellableProduct[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [isStockModalOpen, setIsStockModalOpen] = useState(false)
  const [selectedProductForStock, setSelectedProductForStock] = useState<string | null>(null)
  const [productToArchive, setProductToArchive] = useState<api.SellableProduct | null>(null)

  // New Product Form
  const [name, setName] = useState('')
  const [sku, setSku] = useState('')
  const [barcode, setBarcode] = useState('')
  const [itemType, setItemType] = useState<'PRODUCT' | 'SERVICE'>('PRODUCT')
  const [priceInput, setPriceInput] = useState('')
  const [stockInput, setStockInput] = useState('')

  // Adjust Stock Form
  const [adjustQty, setAdjustQty] = useState('')
  const [adjustType, setAdjustType] = useState<'PURCHASE' | 'LOSS' | 'ADJUSTMENT'>('PURCHASE')
  const [adjustReason, setAdjustReason] = useState('Entrada de Mercadoria')
  const [minimumStock, setMinimumStock] = useState('')

  useEffect(() => {
    if (!tenant || !store) return
    const timer = window.setTimeout(() => {
      api.fetchSellableProducts(
        { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id },
        { page, pageSize: 25, search: searchQuery.trim() || undefined }
      ).then((result) => {
        setCatalogItems(result.items)
        setTotal(result.total)
      }).catch(() => {
        setCatalogItems([])
        setTotal(0)
      })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [tenant, store, page, searchQuery, products])

  const handleCreateProduct = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name || !sku || !priceInput) return

    await createNewProduct(
      { name, sku, barcode: barcode || undefined, item_type: itemType },
      parseFloat(priceInput),
      itemType === 'PRODUCT' ? parseInt(stockInput || '0', 10) : 0
    )

    setName('')
    setSku('')
    setBarcode('')
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
          <h2 className="text-xl font-black text-white tracking-tight flex items-center space-x-2">
            <Package className="w-5 h-5 text-dashem-red" />
            <span>Catálogo de Produtos & Estoque</span>
          </h2>
          <p className="text-xs text-dashem-muted font-medium mt-0.5">
            Gerenciamento de produtos, serviços, preços de venda e saldos de inventário.
          </p>
        </div>

        <button
          onClick={() => setIsAddModalOpen(true)}
          className="h-11 px-5 rounded-2xl bg-dashem-red hover:bg-dashem-red-light text-white text-xs font-black flex items-center justify-center space-x-2 transition-all shadow-md shadow-dashem-red/30 active:scale-95 shrink-0"
        >
          <Plus className="w-4 h-4" />
          <span>Cadastrar Novo Produto</span>
        </button>
      </div>

      {/* Search Input */}
      <div className="relative">
        <Search className="w-4 h-4 text-dashem-muted absolute left-4 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => { setSearchQuery(e.target.value); setPage(1) }}
          placeholder="Buscar produto por nome, SKU ou código de barras..."
          className="w-full h-11 pl-11 pr-4 rounded-xl bg-dashem-surface border border-dashem-border text-white text-xs font-medium focus:border-dashem-red outline-none"
        />
      </div>

      {/* Products Table */}
      <div className="bg-dashem-surface border border-dashem-border rounded-3xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-dashem-surface-elevated text-dashem-muted font-extrabold uppercase tracking-wider text-[10px] border-b border-dashem-border">
              <tr>
                <th className="px-5 py-3.5">Produto / Descrição</th>
                <th className="px-4 py-3.5">SKU / EAN</th>
                <th className="px-4 py-3.5">Tipo</th>
                <th className="px-4 py-3.5 text-right">Preço de Venda</th>
                <th className="px-4 py-3.5 text-right">Atual / Mínimo</th>
                <th className="px-5 py-3.5 text-center">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dashem-border/50 font-medium">
              {catalogItems.map((prod) => {
                const price = Number(prod.sale_price)
                const stock = Number(prod.quantity)
                const isService = prod.item_type === 'SERVICE'

                return (
                  <tr key={prod.id} className="hover:bg-dashem-surface-elevated/40 transition-colors">
                    <td className="px-5 py-3.5">
                      <span className="font-bold text-white block">{prod.name}</span>
                      {prod.description && <span className="text-[11px] text-dashem-muted">{prod.description}</span>}
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="font-mono text-white block">{prod.sku}</span>
                      {prod.barcode && <span className="text-[10px] text-dashem-muted">EAN: {prod.barcode}</span>}
                    </td>
                    <td className="px-4 py-3.5">
                      <span
                        className={`px-2 py-0.5 rounded-md font-bold text-[10px] uppercase ${
                          isService ? 'bg-amber-950/60 text-amber-300 border border-amber-800/40' : 'bg-dashem-surface-elevated text-slate-300'
                        }`}
                      >
                        {prod.item_type}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <span className="font-black text-white text-sm">R$ {price.toFixed(2)}</span>
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      {isService ? (
                        <span className="text-dashem-muted text-[11px]">—</span>
                      ) : (
                        <span
                          className={`font-bold px-2 py-0.5 rounded-md text-[11px] ${
                            !prod.is_low_stock
                              ? 'text-emerald-400 bg-emerald-950/40'
                              : stock > 0
                              ? 'text-amber-400 bg-amber-950/40'
                              : 'text-rose-400 bg-rose-950/40'
                          }`}
                        >
                          {stock} / {Number(prod.minimum_stock)} {prod.unit.toLowerCase()}
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3.5 text-center">
                      <div className="inline-flex gap-2">
                        <button type="button" onClick={() => setProductToArchive(prod)} title="Arquivar e retirar do PDV" className="rounded-lg border border-amber-900 bg-amber-950/30 p-2 text-amber-300"><Archive className="h-3.5 w-3.5" /></button>
                        <button
                          type="button"
                          onClick={() => handleQuickAccess(prod)}
                          title={prod.quick_position != null ? 'Remover do acesso rápido' : 'Adicionar ao acesso rápido'}
                          className="p-2 rounded-lg bg-dashem-surface-elevated border border-dashem-border"
                        >
                          <Star className={`w-3.5 h-3.5 ${prod.quick_position != null ? 'fill-amber-400 text-amber-400' : 'text-dashem-muted'}`} />
                        </button>
                        {!isService && (
                        <button
                          onClick={() => {
                            setSelectedProductForStock(prod.id)
                            setMinimumStock(String(prod.minimum_stock))
                            setIsStockModalOpen(true)
                          }}
                          className="px-3 py-1.5 rounded-lg bg-dashem-surface-elevated hover:bg-dashem-border text-white text-[11px] font-bold transition-all border border-dashem-border inline-flex items-center space-x-1"
                        >
                          <ArrowUpDown className="w-3.5 h-3.5 text-dashem-red" />
                          <span>Ajustar</span>
                        </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
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
        subtitle="Adiciona um novo item ao catálogo e define o preço"
      >
        <form onSubmit={handleCreateProduct} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-bold text-white block">Nome do Produto / Serviço</label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex.: Hambúrguer artesanal, diária ou camiseta"
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-white block">SKU / Código</label>
              <input
                type="text"
                required
                value={sku}
                onChange={(e) => setSku(e.target.value)}
                placeholder="Ex: CAB-25"
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-bold text-white block">Código de Barras (EAN)</label>
              <input
                type="text"
                value={barcode}
                onChange={(e) => setBarcode(e.target.value)}
                placeholder="Ex: 789123456789"
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-white block">Tipo</label>
              <select
                value={itemType}
                onChange={(e) => setItemType(e.target.value as any)}
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
              >
                <option value="PRODUCT">Produto Físico</option>
                <option value="SERVICE">Serviço / Mão de Obra</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-bold text-white block">Preço de Venda (R$)</label>
              <input
                type="number"
                step="0.01"
                required
                value={priceInput}
                onChange={(e) => setPriceInput(e.target.value)}
                placeholder="Ex: 49.90"
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
              />
            </div>
          </div>

          {itemType === 'PRODUCT' && (
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-white block">Estoque Inicial (unidades)</label>
              <input
                type="number"
                value={stockInput}
                onChange={(e) => setStockInput(e.target.value)}
                className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
              />
            </div>
          )}

          <div className="pt-3">
            <button
              type="submit"
              disabled={actionLoading}
              className="w-full h-12 rounded-2xl bg-dashem-red hover:bg-dashem-red-light text-white text-xs font-black flex items-center justify-center space-x-2 transition-all shadow-lg active:scale-95 disabled:opacity-40"
            >
              <Plus className="w-4 h-4" />
              <span>Salvar Produto no Catálogo</span>
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
            <label className="text-xs font-bold text-white block">Tipo de Movimentação</label>
            <select
              value={adjustType}
              onChange={(e) => setAdjustType(e.target.value as any)}
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
            >
              <option value="PURCHASE">Entrada / Compra de Mercadoria</option>
              <option value="LOSS">Perda / Avaria / Vencimento</option>
              <option value="ADJUSTMENT">Ajuste de Balanço / Inventário</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-white block">Quantidade</label>
            <input
              type="number"
              step="1"
              required
              value={adjustQty}
              onChange={(e) => setAdjustQty(e.target.value)}
              placeholder="Ex: 10"
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-white block">Motivo / Observação</label>
            <input
              type="text"
              value={adjustReason}
              onChange={(e) => setAdjustReason(e.target.value)}
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-white block">Estoque mínimo desta unidade</label>
            <input
              type="number"
              min="0"
              step="0.01"
              required
              value={minimumStock}
              onChange={(e) => setMinimumStock(e.target.value)}
              className="w-full h-11 px-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-white text-xs font-semibold focus:border-dashem-red outline-none"
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

      <Modal isOpen={Boolean(productToArchive)} onClose={() => setProductToArchive(null)} title="Arquivar item do catálogo" subtitle="O item deixa o PDV sem apagar seu histórico."><div className="space-y-4"><p className="rounded-xl border border-amber-900/50 bg-amber-950/30 p-4 text-sm font-bold text-amber-200">{productToArchive?.name} será retirado da venda e do acesso rápido. Vendas, estoque e auditoria permanecem preservados.</p><div className="grid grid-cols-2 gap-3"><button onClick={() => setProductToArchive(null)} className="h-11 rounded-xl border border-dashem-border font-black text-white">Cancelar</button><button disabled={actionLoading} onClick={() => void archiveProduct()} className="h-11 rounded-xl bg-amber-600 font-black text-white disabled:opacity-40">Arquivar item</button></div></div></Modal>
    </div>
  )
}
