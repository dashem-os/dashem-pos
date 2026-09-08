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
  positive: 'border-state-success-border bg-state-success-soft text-state-success',
  warning: 'border-state-warning-border bg-state-warning-soft text-state-warning',
  critical: 'border-state-danger-border bg-state-danger-soft text-state-danger',
  info: 'border-state-info-border bg-state-info-soft text-state-info',
}

export const Badge: React.FC<BadgeProps> = ({ tone = 'neutral', icon: Icon, children, className = '' }) => (
  <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold ${TONES[tone]} ${className}`}>
    {Icon && <Icon className="h-3.5 w-3.5" />}
    {children}
  </span>
)
