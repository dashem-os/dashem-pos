import React, { useState, useMemo } from 'react'
import { Package, Plus, Star } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { formatCurrency, formatStock } from '../../utils/format'
import { ProductShowcase } from './ProductShowcase'

export const QuickProductGrid: React.FC = () => {
  const { products, categories, prices, balances, addItemToCart, actionLoading, permissions, connectionState, cashSession } = usePos()
  // A sale needs an open till, the same rule the search field already applied.
  // The grid only got away without it because it was never drawn on a closed
  // till — until managerial validation started reaching this screen.
  const canSell = permissions.includes('sale.create') && connectionState === 'ONLINE' && cashSession?.status === 'OPEN'
  const [activeTab, setActiveTab] = useState<string>('ALL')

  // Per-member, per-store quick access persisted by the backend.
  const favoriteProducts = useMemo(() => {
    return products.filter((product) => product.quick_position != null)
  }, [products])

  const filteredProducts = useMemo(() => {
    if (activeTab === 'FAVORITES') return favoriteProducts
    if (activeTab === 'ALL') return products
    return products.filter((p) => p.category_id === activeTab)
  }, [products, favoriteProducts, activeTab])

  if (products.length === 0) {
    return (
      <div className="w-full py-12 px-6 flex flex-col items-center justify-center bg-white border border-slate-200 rounded-2xl text-center shadow-sm">
        <Package className="w-10 h-10 text-slate-300 mb-3" />
        <h3 className="text-base font-bold text-slate-800">Catálogo de Produtos Vazio</h3>
        <p className="text-xs text-slate-500 max-w-sm mt-1 mb-4">
          Nenhum produto cadastrado. Cadastre ou importe o catálogo real no Dashem Gestão.
        </p>
      </div>
    )
  }

  return (
    <div className="w-full flex flex-col space-y-3">
      {/* What the house sells, first: the unit's window and the person's own
          band, before the alphabetical catalogue. Search below is for the long
          tail that does not earn a place on the first screen. */}
      <ProductShowcase onPick={(product) => void addItemToCart(product.id)} disabled={!canSell} />

      {/* Navigation Pills: Acesso Rápido, Todos, and Real Categories */}
      <div className="flex items-center space-x-2 overflow-x-auto pb-1 scrollbar-none select-none">
        {/* Acesso Rápido (Favoritos) Tab */}
        <button
          type="button"
          onClick={() => setActiveTab('FAVORITES')}
          className={`min-h-11 px-4 rounded-xl text-xs font-bold whitespace-nowrap transition-all border flex items-center space-x-1.5 ${
            activeTab === 'FAVORITES'
              ? 'bg-brand text-brand-contrast border-brand shadow-sm'
              : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
          }`}
        >
          <Star className={`w-3.5 h-3.5 ${activeTab === 'FAVORITES' ? 'text-amber-300 fill-amber-300' : 'text-slate-400'}`} />
          <span>Acesso Rápido ({favoriteProducts.length})</span>
        </button>

        {/* Todos Tab */}
        <button
          type="button"
          onClick={() => setActiveTab('ALL')}
          className={`min-h-11 px-4 rounded-xl text-xs font-bold whitespace-nowrap transition-all border ${
            activeTab === 'ALL'
              ? 'bg-brand text-brand-contrast border-brand shadow-sm'
              : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
          }`}
        >
          Todos ({products.length})
        </button>

        {/* Only categories present in the projection: the tenant may hold
            categories from another contracted activity, and an empty chip for
            "Perfumaria" inside a food service counter is exactly the mixture
            the activity scope exists to prevent. */}
        {categories.filter((cat) => products.some((p) => p.category_id === cat.id)).map((cat) => {
          const count = products.filter((p) => p.category_id === cat.id).length
          const isSelected = activeTab === cat.id
          return (
            <button
              key={cat.id}
              type="button"
              onClick={() => setActiveTab(cat.id)}
              className={`min-h-11 px-4 rounded-xl text-xs font-bold whitespace-nowrap transition-all border ${
                isSelected
                  ? 'bg-brand text-brand-contrast border-brand shadow-sm'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
            >
              {cat.name} ({count})
            </button>
          )
        })}
      </div>

      {/* Touch Grid of Product Cards */}
      <div className="grid grid-cols-1 min-[420px]:grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-4" aria-label="Produtos disponíveis para venda">
        {filteredProducts.map((product) => {
          const price = prices[product.id] ?? 0
          const stock = balances[product.id] ?? 0
          const isService = product.item_type === 'SERVICE'
          const catName = product.category_name || (isService ? 'Serviço' : 'Sem categoria')

          return (
            <button
              key={product.id}
              onClick={() => addItemToCart(product.id, 1)}
              disabled={actionLoading || !canSell}
              className="group relative flex min-h-[148px] flex-col justify-between rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-all hover:border-rose-400 hover:shadow-md active:scale-[0.98] select-none sm:min-h-[160px] sm:p-5"
            >
              {/* Header: Category & Stock */}
              <div className="flex items-center justify-between w-full mb-1">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider truncate max-w-[110px]">
                  {catName}
                </span>

                {!isService && (
                  <span
                    className={`text-xs font-bold px-2 py-0.5 rounded-md shrink-0 ${
                      !product.is_low_stock
                        ? 'bg-slate-100 text-slate-600'
                        : stock > 0
                        ? 'bg-amber-50 text-amber-700 border border-amber-200'
                        : 'bg-rose-50 text-rose-700 border border-rose-200'
                    }`}
                  >
                    {formatStock(stock)}
                  </span>
                )}
              </div>

              {/* Every card reserves the same photo area, so a catalogue with
                  partial photography still lines up in the grid. */}
              {(product.image?.url || product.image_url) ? (
                <img
                  src={product.image?.url || product.image_url}
                  alt=""
                  loading="lazy"
                  className="mt-2 h-20 w-full rounded-xl border border-slate-100 object-cover"
                />
              ) : (
                <div className="mt-2 flex h-20 w-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-xl font-black text-slate-300">
                  {product.name.trim().charAt(0).toUpperCase()}
                </div>
              )}

              {/* Title & SKU */}
              <div className="my-1 flex-1">
                <h4 className="text-sm font-bold leading-snug text-slate-900 transition-colors line-clamp-3 group-hover:text-rose-600 sm:text-base">
                  {product.name}
                </h4>
                <span className="text-xs font-mono text-slate-400 mt-0.5 block">{product.sku}</span>
              </div>

              {/* Price & Add Icon */}
              <div className="flex items-end justify-between w-full pt-1.5 border-t border-slate-100 mt-1">
                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block leading-none">Preço</span>
                  <span className="text-sm sm:text-base font-black text-slate-900">
                    {formatCurrency(price)}
                  </span>
                </div>
                <div className="w-8 h-8 rounded-xl bg-slate-100 group-hover:bg-rose-600 group-hover:text-white text-slate-500 flex items-center justify-center transition-colors">
                  <Plus className="w-4 h-4" />
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
