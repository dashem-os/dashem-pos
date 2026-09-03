import React from 'react'

type Tone = 'neutral' | 'brand' | 'positive' | 'warning' | 'critical' | 'info'

export interface BadgeProps {
  tone?: Tone
  icon?: React.ComponentType<{ className?: string }>
  children: React.ReactNode
  className?: string
}

const TONES: Record<Tone, string> = {
  neutral: 'border-dashem-border bg-dashem-surface-elevated text-dashem-muted',
  brand: 'border-brand/30 bg-brand-soft text-brand-ink',
  positive: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  warning: 'border-amber-200 bg-amber-50 text-amber-700',
  critical: 'border-red-200 bg-red-50 text-red-700',
  info: 'border-sky-200 bg-sky-50 text-sky-700',
}

export const Badge: React.FC<BadgeProps> = ({ tone = 'neutral', icon: Icon, children, className = '' }) => (
  <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold ${TONES[tone]} ${className}`}>
    {Icon && <Icon className="h-3.5 w-3.5" />}
    {children}
  </span>
)
