import React, { ReactNode, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title: string
  subtitle?: string
  children: ReactNode
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl'
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  maxWidth = 'md'
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const getMaxWidthClass = () => {
    switch (maxWidth) {
      case 'sm':
        return 'max-w-sm'
      case 'lg':
        return 'max-w-lg'
      case 'xl':
        return 'max-w-xl'
      case '2xl':
        return 'max-w-2xl'
      default:
        return 'max-w-md'
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-150"
      // Clicking the backdrop dismisses, the same way Escape and the X do.
      onClick={(event) => { if (event.target === event.currentTarget) onClose() }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${getMaxWidthClass()} bg-white border border-slate-200 rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[calc(100dvh-2rem)] animate-in zoom-in-95 transition-[opacity,transform] duration-150 text-slate-900`}
      >
        {/* Modal Header */}
        <div className="flex shrink-0 items-center justify-between gap-3 px-4 sm:px-6 py-4 border-b border-slate-100 bg-slate-50/50">
          <div>
            <h3 className="text-base sm:text-lg font-black text-slate-900 tracking-tight">{title}</h3>
            {subtitle && <p className="text-xs text-slate-500 font-medium mt-0.5">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Fechar janela"
            className="shrink-0 w-11 h-11 rounded-xl flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Content */}
        <div className="min-h-0 p-4 sm:p-6 overflow-y-auto overscroll-contain flex-1">{children}</div>
      </div>
    </div>, document.body
  )
}
