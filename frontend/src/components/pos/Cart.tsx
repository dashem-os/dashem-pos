import React, { useMemo } from 'react'
import { ShoppingBag } from 'lucide-react'
import { CartItem } from './CartItem'
import { usePos } from '../../context/PosContext'
import { groupCartItems } from '../../domain/cartGrouping'

export const Cart: React.FC = () => {
  const { currentSale } = usePos()
  const items = currentSale?.items || []
  const groups = useMemo(() => groupCartItems(items), [items])

  if (items.length === 0) {
    return (
      <div className="my-2 flex flex-1 flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50 p-6 text-center">
        <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-300 shadow-xs">
          <ShoppingBag className="h-6 w-6" />
        </div>
        <h4 className="text-sm font-bold text-slate-700">Nenhum item na venda</h4>
      </div>
    )
  }

  return (
    <div className="scrollbar-thin my-2 min-h-24 flex-1 space-y-2 overflow-y-auto pr-0.5">
      {groups.map((group) => (
        <CartItem key={group.key} group={group} />
      ))}
    </div>
  )
}
