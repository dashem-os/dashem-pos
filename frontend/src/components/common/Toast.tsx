import React from 'react'
import { CheckCircle2, AlertCircle, Info } from 'lucide-react'
import { ToastInfo } from '../../context/PosContext'

interface ToastProps {
  toast: ToastInfo | null
}

export const Toast: React.FC<ToastProps> = ({ toast }) => {
  if (!toast) return null

  const getStyle = () => {
    switch (toast.type) {
      case 'success':
        return 'bg-emerald-900/95 text-emerald-100 border-emerald-700 shadow-xl'
      case 'error':
        return 'bg-rose-900/95 text-rose-100 border-rose-700 shadow-xl'
      default:
        return 'bg-slate-900/95 text-slate-100 border-slate-700 shadow-xl'
    }
  }

  const getIcon = () => {
    switch (toast.type) {
      case 'success':
        return <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
      case 'error':
        return <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
      default:
        return <Info className="w-5 h-5 text-sky-400 shrink-0" />
    }
  }

  return (
    <div className="fixed top-4 right-4 z-50 max-w-md animate-in fade-in slide-in-from-top-3 duration-150 pointer-events-none">
      <div className={`px-4 py-3 rounded-2xl flex items-center space-x-3 border backdrop-blur-sm ${getStyle()}`}>
        {getIcon()}
        <span className="text-xs sm:text-sm font-bold leading-snug">{toast.text}</span>
      </div>
    </div>
  )
}
