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
        return 'bg-state-success-strong/95 text-state-success-on-strong border-state-success shadow-xl'
      case 'error':
        return 'bg-state-danger-strong/95 text-state-danger-on-strong border-state-danger shadow-xl'
      case 'warning':
        return 'bg-state-warning-strong/95 text-state-warning-on-strong border-state-warning shadow-xl'
      default:
        return 'bg-state-info-strong/95 text-state-info-on-strong border-state-info shadow-xl'
    }
  }

  const getIcon = () => {
    switch (toast.type) {
      case 'success':
        return <CheckCircle2 className="w-5 h-5 text-state-success-accent shrink-0" />
      case 'error':
        return <AlertCircle className="w-5 h-5 text-state-danger-accent shrink-0" />
      case 'warning':
        return <AlertCircle className="w-5 h-5 text-state-warning-accent shrink-0" />
      default:
        return <Info className="w-5 h-5 text-state-info-accent shrink-0" />
    }
  }

  return (
    <div className="pointer-events-none fixed left-3 right-3 top-3 z-50 animate-in fade-in slide-in-from-top-3 duration-150 sm:left-auto sm:right-4 sm:top-4 sm:w-full sm:max-w-sm">
      <div className={`flex max-h-24 items-start gap-2 overflow-y-auto rounded-xl border px-3 py-2.5 backdrop-blur-sm ${getStyle()}`}>
        {getIcon()}
        <span className="min-w-0 break-words text-xs font-bold leading-4 sm:text-xs">{toast.text}</span>
      </div>
    </div>
  )
}
