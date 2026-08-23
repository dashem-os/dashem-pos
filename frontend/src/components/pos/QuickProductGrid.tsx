import React, { useState, useMemo } from 'react'
import { Package, Plus, Star } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { formatCurrency, formatStock } from '../../utils/format'

export const QuickProductGrid: React.FC = () => {
  const { products, categories, prices, balances, addItemToCart, actionLoading, permissions, connectionState } = usePos()
  const canSell = permissions.includes('sale.create') && connectionState === 'ONLINE'
  const [activeTab, setActiveTab] = useState<string>('FAVORITES')

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
      {/* Navigation Pills: Acesso Rápido, Todos, and Real Categories */}
      <div className="flex items-center space-x-2 overflow-x-auto pb-1 scrollbar-none select-none">
        {/* Acesso Rápido (Favoritos) Tab */}
        <button
          type="button"
          onClick={() => setActiveTab('FAVORITES')}
          className={`h-9 px-4 rounded-xl text-xs font-bold whitespace-nowrap transition-all border flex items-center space-x-1.5 ${
            activeTab === 'FAVORITES'
              ? 'bg-rose-600 text-white border-rose-600 shadow-sm'
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
          className={`h-9 px-4 rounded-xl text-xs font-bold whitespace-nowrap transition-all border ${
            activeTab === 'ALL'
              ? 'bg-rose-600 text-white border-rose-600 shadow-sm'
              : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
          }`}
        >
          Todos ({products.length})
        </button>

        {/* Real Categories from Backend */}
        {categories.map((cat) => {
          const count = products.filter((p) => p.category_id === cat.id).length
          const isSelected = activeTab === cat.id
          return (
            <button
              key={cat.id}
              type="button"
              onClick={() => setActiveTab(cat.id)}
              className={`h-9 px-4 rounded-xl text-xs font-bold whitespace-nowrap transition-all border ${
                isSelected
                  ? 'bg-rose-600 text-white border-rose-600 shadow-sm'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
            >
              {cat.name} ({count})
            </button>
          )
        })}
      </div>

      {/* Touch Grid of Product Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4 gap-2.5 sm:gap-3">
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
              className="group relative flex flex-col justify-between p-3 sm:p-3.5 rounded-2xl bg-white border border-slate-200 hover:border-rose-400 hover:shadow-md active:scale-[0.98] transition-all text-left min-h-[120px] shadow-sm select-none"
            >
              {/* Header: Category & Stock */}
              <div className="flex items-center justify-between w-full mb-1">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider truncate max-w-[110px]">
                  {catName}
                </span>

                {!isService && (
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-md shrink-0 ${
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

              {/* Title & SKU */}
              <div className="my-1 flex-1">
                <h4 className="text-xs sm:text-sm font-bold text-slate-900 leading-snug line-clamp-2 group-hover:text-rose-600 transition-colors">
                  {product.name}
                </h4>
                <span className="text-[11px] font-mono text-slate-400 mt-0.5 block">{product.sku}</span>
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
