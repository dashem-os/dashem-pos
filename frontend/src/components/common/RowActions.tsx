import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { MoreHorizontal } from 'lucide-react'

/**
 * Ações raras saem da fila das diárias.
 *
 * Uma linha com cinco botões iguais obriga a pessoa a ler todos para achar o
 * que ela faz todo dia. Aqui as frequentes ficam visíveis e as demais entram
 * neste menu — que continua sendo teclado, foco e leitor de tela, e não esconde
 * nada: o rótulo diz que há mais ações.
 *
 * O painel é posicionado em coordenadas de viewport porque tabelas rolam na
 * horizontal, e um ancestral que rola recorta qualquer coisa absoluta dentro
 * dele. O menu ficaria cortado exatamente nas telas em que ele é mais útil.
 */
export interface RowActionsProps {
  label?: string
  children: React.ReactNode
}

export const RowActions: React.FC<RowActionsProps> = ({ label = 'Mais ações', children }) => {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ top: 0, left: 0 })

  useLayoutEffect(() => {
    if (!open || !trigger.current) return
    const anchor = trigger.current.getBoundingClientRect()
    const height = panel.current?.offsetHeight ?? 0
    const width = panel.current?.offsetWidth ?? 224
    // Abre para baixo; se não couber, abre para cima. Nunca sai pela esquerda.
    const below = anchor.bottom + 6
    const top = below + height > window.innerHeight ? Math.max(8, anchor.top - height - 6) : below
    setPosition({ top, left: Math.max(8, Math.min(anchor.right - width, window.innerWidth - width - 8)) })
  }, [open])

  useEffect(() => {
    if (!open) return
    const outside = (event: MouseEvent) => {
      if (panel.current?.contains(event.target as Node)) return
      if (trigger.current?.contains(event.target as Node)) return
      setOpen(false)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() }
    }
    // Rolar com o menu aberto o deixaria flutuando longe do botão que o abriu.
    const dismiss = () => setOpen(false)
    document.addEventListener('mousedown', outside)
    document.addEventListener('keydown', key)
    window.addEventListener('scroll', dismiss, true)
    window.addEventListener('resize', dismiss)
    return () => {
      document.removeEventListener('mousedown', outside)
      document.removeEventListener('keydown', key)
      window.removeEventListener('scroll', dismiss, true)
      window.removeEventListener('resize', dismiss)
    }
  }, [open])

  return (
    <>
      <button
        ref={trigger} type="button" aria-haspopup="menu" aria-expanded={open} aria-label={label} title={label}
        onClick={() => setOpen((was) => !was)}
        className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-dashem-border bg-dashem-surface text-dashem-muted hover:text-dashem-strong focus-visible:ring-2 focus-visible:ring-dashem-red"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open && (
        <div
          ref={panel} role="menu" aria-label={label}
          style={{ top: position.top, left: position.left }}
          onClick={() => setOpen(false)}
          className="fixed z-50 w-56 rounded-2xl border border-dashem-border bg-dashem-surface p-1.5 shadow-xl"
        >
          {children}
        </div>
      )}
    </>
  )
}

export interface RowActionProps {
  icon?: React.ComponentType<{ className?: string }>
  onClick: () => void
  tone?: 'neutral' | 'critical'
  children: React.ReactNode
}

export const RowAction: React.FC<RowActionProps> = ({ icon: Icon, onClick, tone = 'neutral', children }) => (
  <button
    type="button" role="menuitem" onClick={onClick}
    className={`flex min-h-11 w-full items-center gap-2.5 rounded-xl px-3 text-left text-xs font-black hover:bg-dashem-surface-elevated focus-visible:ring-2 focus-visible:ring-dashem-red ${
      tone === 'critical' ? 'text-state-danger' : 'text-dashem-strong'
    }`}
  >
    {Icon && <Icon className="h-4 w-4 shrink-0" />}
    <span>{children}</span>
  </button>
)
