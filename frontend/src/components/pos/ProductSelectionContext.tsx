import React, { createContext, useContext } from 'react'
import { usePos } from '../../context/PosContext'
import type { SalesContext, SellableProduct } from '../../services/api'

// Selection is shared; authority and the command belong to each journey.
export type ProductSelectionScope = Pick<ReturnType<typeof usePos>,
  'tenant' | 'store' | 'products' | 'categories' | 'permissions' | 'activeActivity' | 'showToast'> & {
  operationMode: SalesContext
  enabled: boolean
  actionLoading: boolean
  onPick: (product: SellableProduct) => Promise<boolean>
}

const SelectionContext = createContext<ProductSelectionScope | null>(null)
export const ProductSelectionProvider = SelectionContext.Provider
export function useProductSelection() {
  const value = useContext(SelectionContext)
  if (!value) throw new Error('Product selection requires an explicit journey scope')
  return value
}
