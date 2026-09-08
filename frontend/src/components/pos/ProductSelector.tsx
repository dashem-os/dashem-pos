import React from 'react'
import { usePos } from '../../context/PosContext'
import { ProductSearch } from './ProductSearch'
import { QuickProductGrid } from './QuickProductGrid'
import { ProductSelectionProvider } from './ProductSelectionContext'

export function ProductSelector() {
  return <div className="space-y-4"><ProductSearch /><QuickProductGrid /></div>
}

export function CounterProductSelector() {
  const pos = usePos()
  return <ProductSelectionProvider value={{
    tenant: pos.tenant, store: pos.store, products: pos.products, categories: pos.categories,
    permissions: pos.permissions, activeActivity: pos.activeActivity, showToast: pos.showToast,
    activities: pos.activities, contributions: pos.contributions,
    operationMode: pos.operationMode, actionLoading: pos.actionLoading,
    enabled: pos.permissions.includes('sale.create') && pos.connectionState === 'ONLINE' && pos.cashSession?.status === 'OPEN',
    onPick: product => pos.addItemToCart(product.id, 1),
  }}><ProductSelector key={`${pos.tenant?.id}/${pos.store?.id}/${pos.operationMode}/${pos.activeActivity}`} /></ProductSelectionProvider>
}
