import React from 'react'

type Accent = 'neutral' | 'brand' | 'positive' | 'warning' | 'critical'

export interface StatCardProps {
  label: string
  value: string
  /** Secondary line under the value: period, count, or comparison. */
  meta?: string
  icon?: React.ComponentType<{ className?: string }>
  accent?: Accent
  onClick?: () => void
}

const ACCENTS: Record<Accent, string> = {
  neutral: 'text-dashem-muted',
  brand: 'text-brand-ink',
  positive: 'text-emerald-600',
  warning: 'text-amber-600',
  critical: 'text-red-600',
}

/**
 * Single KPI tile. The value is the largest element so a dashboard row reads as
 * a set of numbers first and labels second.
 */
export const StatCard: React.FC<StatCardProps> = ({ label, value, meta, icon: Icon, accent = 'neutral', onClick }) => {
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-black uppercase tracking-wide text-dashem-muted">{label}</p>
        {Icon && <Icon className={`h-5 w-5 shrink-0 ${ACCENTS[accent]}`} />}
      </div>
      <p className="mt-3 text-2xl font-black tracking-tight text-dashem-strong">{value}</p>
      {meta && <p className="mt-1 text-xs text-dashem-muted">{meta}</p>}
    </>
  )
  const shell = 'rounded-2xl border border-dashem-border bg-dashem-surface p-5 text-left'
  return onClick
    ? <button type="button" onClick={onClick} className={`${shell} transition hover:border-brand/40 hover:bg-dashem-surface-elevated`}>{body}</button>
    : <article className={shell}>{body}</article>
}
