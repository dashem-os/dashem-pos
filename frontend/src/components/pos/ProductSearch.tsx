import React, { useState, useRef, useEffect } from 'react'
import { Search, Barcode, X, CornerDownLeft, CheckCircle2, ChevronRight } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { SellableProduct } from '../../services/api'
import * as api from '../../services/api'
import { formatCurrency, formatStock } from '../../utils/format'

export const ProductSearch: React.FC = () => {
  const { tenant, store, prices, balances, addItemToCart, showToast, actionLoading, cashSession } = usePos()
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SellableProduct[]>([])
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const isCashOpen = cashSession?.status === 'OPEN'

  // Web Audio subtle scanner beep feedback
  const playBeep = () => {
    try {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      if (!AudioCtx) return
      const ctx = new AudioCtx()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(1800, ctx.currentTime)
      gain.gain.setValueAtTime(0.15, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.08)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start()
      osc.stop(ctx.currentTime + 0.08)
    } catch {
      // Audio might be muted or blocked by browser policy
    }
  }

  // Continuous auto-focus for fast barcode scanning operation
  useEffect(() => {
    if (isCashOpen) {
      inputRef.current?.focus()
    }
  }, [isCashOpen])

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSelectProduct = async (product: SellableProduct) => {
    playBeep()
    const ok = await addItemToCart(product.id, 1)
    if (ok) {
      setQuery('')
      setSearchResults([])
      setIsDropdownOpen(false)
      inputRef.current?.focus()
    }
  }

  const handleScanOrSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const clean = query.trim()
    if (!clean || !isCashOpen || actionLoading) return

    if (!tenant || !store) return
    const result = await api.fetchSellableProducts(
      { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id },
      { search: clean, pageSize: 20 }
    ).catch(() => null)
    const matches = result?.items || []

    // 1. Exact match by Barcode (EAN)
    const exactBarcode = matches.find((p) => p.barcode && p.barcode.toLowerCase() === clean.toLowerCase())
    if (exactBarcode) {
      await handleSelectProduct(exactBarcode)
      return
    }

    // 2. Exact match by SKU
    const exactSku = matches.find((p) => p.sku.toLowerCase() === clean.toLowerCase())
    if (exactSku) {
      await handleSelectProduct(exactSku)
      return
    }

    // 3. Match by partial query
    const matched = matches

    if (matched.length === 1) {
      await handleSelectProduct(matched[0])
      return
    }

    if (matched.length > 1) {
      // CRITICAL FIX: NEVER pick arbitrarily! Open selection dropdown for operator
      setSearchResults(matched)
      setIsDropdownOpen(true)
      return
    }

    showToast('error', `Produto com código/termo '${clean}' não localizado!`)
    setQuery('')
    inputRef.current?.focus()
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <form onSubmit={handleScanOrSubmit} className="relative w-full">
        <div className="relative flex items-center bg-white rounded-2xl border-2 border-slate-200 focus-within:border-rose-600 focus-within:ring-4 focus-within:ring-rose-500/10 shadow-sm transition-all h-14">
          <div className="pl-4 pr-2 text-slate-400 flex items-center space-x-2 shrink-0">
            <Barcode className="w-6 h-6 text-rose-600" />
            <Search className="w-4 h-4 text-slate-400" />
          </div>

          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              if (isDropdownOpen) setIsDropdownOpen(false)
            }}
            placeholder="Escanear código de barras (Enter) ou digitar SKU / nome..."
            disabled={!isCashOpen || actionLoading}
            className="w-full h-full pr-24 bg-transparent text-slate-900 placeholder:text-slate-400 font-semibold text-sm sm:text-base outline-none disabled:opacity-50"
          />

          <div className="absolute right-3 flex items-center space-x-1.5 shrink-0">
            {query && (
              <button
                type="button"
                onClick={() => {
                  setQuery('')
                  setSearchResults([])
                  setIsDropdownOpen(false)
                  inputRef.current?.focus()
                }}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
                title="Limpar busca"
              >
                <X className="w-4 h-4" />
              </button>
            )}

            <div className="hidden sm:flex items-center space-x-1 px-2 py-1 rounded-lg bg-slate-100 text-slate-500 text-[11px] font-bold border border-slate-200 pointer-events-none">
              <CornerDownLeft className="w-3 h-3 text-slate-400" />
              <span>Enter</span>
            </div>
          </div>
        </div>
      </form>

      {/* Multiple Partial Matches Dropdown (Operator Picks - No Arbitrary Selection) */}
      {isDropdownOpen && searchResults.length > 1 && (
        <div className="absolute top-16 left-0 right-0 z-40 bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
          <div className="px-4 py-2 bg-slate-50 border-b border-slate-100 flex items-center justify-between text-xs font-bold text-slate-500">
            <span>{searchResults.length} produtos encontrados para "{query}"</span>
            <span>Toque para selecionar</span>
          </div>

          <div className="max-h-64 overflow-y-auto divide-y divide-slate-100">
            {searchResults.map((product) => {
              const price = prices[product.id] || 0
              const stock = balances[product.id] || 0
              return (
                <button
                  key={product.id}
                  type="button"
                  onClick={() => handleSelectProduct(product)}
                  className="w-full px-4 py-3 flex items-center justify-between hover:bg-rose-50 text-left transition-colors group"
                >
                  <div className="min-w-0 flex-1 pr-3">
                    <h4 className="text-sm font-bold text-slate-900 group-hover:text-rose-600 truncate">
                      {product.name}
                    </h4>
                    <div className="flex items-center space-x-2 text-xs text-slate-400 mt-0.5">
                      <span className="font-mono">{product.sku}</span>
                      <span>•</span>
                      <span>Estoque: {formatStock(stock)}</span>
                    </div>
                  </div>

                  <div className="flex items-center space-x-3 shrink-0">
                    <span className="text-sm font-black text-slate-900">
                      {formatCurrency(price)}
                    </span>
                    <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-rose-600" />
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
