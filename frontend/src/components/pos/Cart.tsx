import React from 'react'
import { ShoppingBag } from 'lucide-react'
import { CartItem } from './CartItem'
import { usePos } from '../../context/PosContext'

export const Cart: React.FC = () => {
  const { currentSale } = usePos()
  const items = currentSale?.items || []

  if (items.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center bg-slate-50 border-2 border-dashed border-slate-200 rounded-2xl my-2">
        <div className="w-12 h-12 rounded-2xl bg-white border border-slate-200 flex items-center justify-center text-slate-300 mb-2 shadow-xs">
          <ShoppingBag className="w-6 h-6" />
        </div>
        <h4 className="text-sm font-bold text-slate-700">Nenhum item na venda</h4>
        <p className="text-xs text-slate-400 max-w-[200px] mt-0.5">
          Bipe o código de barras ou toque em um produto no catálogo.
        </p>
      </div>
    )
  }

  return (
    <div className="min-h-24 flex-1 overflow-y-auto pr-0.5 space-y-2 my-2 scrollbar-thin">
      {items.map((item, index) => (
        <CartItem key={item.id} item={item} index={index} />
      ))}
    </div>
  )
}
