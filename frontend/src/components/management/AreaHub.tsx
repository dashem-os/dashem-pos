import React, { useEffect, useRef } from 'react'
import { LayoutGrid } from 'lucide-react'

export interface CardDoHub {
  id: string
  label: string
  descricao: string
}

/**
 * A grade de cards de uma área.
 *
 * O card inteiro é o alvo — um `button`, não um cartão com link dentro —
 * porque o contrato pede área acionável por teclado e por toque. Ícone, título
 * concreto e **uma** frase de tarefa: sem parágrafo, sem indicador decorativo e
 * sem contador que não venha de dado confiável.
 *
 * A grade vai de uma a três colunas conforme o espaço, e um card sozinho não é
 * esticado para preencher a tela: `grid-cols-3` deixa o item ocupar sua coluna.
 */
export const AreaHub: React.FC<{
  cards: CardDoHub[]
  icones?: Record<string, React.ComponentType<{ className?: string }>>
  focar?: string | null
  aoFocar?: () => void
  aoAbrir: (id: string) => void
}> = ({ cards, icones, focar, aoFocar, aoAbrir }) => {
  const paraFocar = useRef<HTMLButtonElement>(null)

  // Quem volta de um módulo volta para o card de onde saiu, não para o topo.
  useEffect(() => {
    if (!focar) return
    paraFocar.current?.focus()
    aoFocar?.()
  }, [aoFocar, focar])

  if (!cards.length) return null

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {cards.map((card) => {
        const Icone = icones?.[card.id] ?? LayoutGrid
        return (
          <button
            key={card.id}
            ref={card.id === focar ? paraFocar : undefined}
            onClick={() => aoAbrir(card.id)}
            className="flex h-full min-h-11 flex-col gap-2 rounded-2xl border border-dashem-border bg-dashem-surface p-5 text-left transition hover:border-brand/40 hover:bg-dashem-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-ink"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-dashem-surface-elevated text-brand-ink">
              <Icone className="h-5 w-5" />
            </span>
            <span className="text-base font-black text-dashem-strong">{card.label}</span>
            <span className="text-sm leading-6 text-dashem-muted">{card.descricao}</span>
          </button>
        )
      })}
    </div>
  )
}
