import React from 'react'
import { Loader2 } from 'lucide-react'

export interface EmptyStateProps {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  /** Say what the operator can do next, not why the query returned nothing. */
  description?: string
  action?: React.ReactNode
  tone?: 'neutral' | 'positive' | 'warning'
  className?: string
}

const TONES = {
  neutral: 'border-dashem-border bg-dashem-surface-elevated text-dashem-muted',
  positive: 'border-state-success-border bg-state-success-soft text-state-success',
  warning: 'border-state-warning-border bg-state-warning-soft text-state-warning',
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon: Icon, title, description, action, tone = 'neutral', className = '',
}) => (
  <div className={`flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-6 py-10 text-center ${TONES[tone]} ${className}`}>
    {Icon && <Icon className="h-7 w-7 opacity-70" />}
    <p className="text-sm font-black text-dashem-strong">{title}</p>
    {description && <p className="max-w-md text-xs leading-5">{description}</p>}
    {action && <div className="mt-2">{action}</div>}
  </div>
)

export const LoadingState: React.FC<{ text?: string; className?: string }> = ({
  text = 'Carregando...', className = '',
}) => (
  <div className={`flex min-h-56 items-center justify-center gap-3 rounded-2xl border border-dashem-border bg-dashem-surface text-sm font-bold text-dashem-muted ${className}`}>
    <Loader2 className="h-5 w-5 animate-spin" />{text}
  </div>
)

export const ErrorState: React.FC<{ text: string; action?: React.ReactNode; className?: string }> = ({
  text, action, className = '',
}) => (
  <div className={`flex min-h-56 flex-col items-center justify-center gap-3 rounded-2xl border border-state-danger-border bg-state-danger-soft px-6 text-center text-sm font-bold text-state-danger ${className}`}>
    {text}{action}
  </div>
)

/** Placeholder block for content that is still loading, sized by the caller. */
export const Skeleton: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`animate-pulse rounded-xl bg-dashem-surface-elevated ${className}`} />
)
