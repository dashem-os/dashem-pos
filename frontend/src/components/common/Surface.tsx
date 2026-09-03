import React from 'react'

export interface CardProps extends React.HTMLAttributes<HTMLElement> {
  as?: 'section' | 'article' | 'div'
  /** `plain` sits on the page, `raised` separates from a busy background. */
  tone?: 'plain' | 'raised' | 'muted'
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

const TONES = {
  plain: 'border border-dashem-border bg-dashem-surface',
  raised: 'border border-dashem-border bg-dashem-surface shadow-sm',
  muted: 'border border-dashem-border bg-dashem-surface-elevated',
}

const PADDINGS = { none: '', sm: 'p-4', md: 'p-5', lg: 'p-6' }

export const Card: React.FC<CardProps> = ({
  as: Tag = 'section', tone = 'plain', padding = 'md', className = '', children, ...rest
}) => (
  <Tag className={`rounded-2xl ${TONES[tone]} ${PADDINGS[padding]} ${className}`} {...rest}>
    {children}
  </Tag>
)

export interface SectionHeaderProps {
  /** Small uppercase line above the title, for context or category. */
  eyebrow?: string
  title: string
  description?: string
  /** Actions rendered on the trailing edge; wraps below the title on narrow screens. */
  actions?: React.ReactNode
  className?: string
}

export const SectionHeader: React.FC<SectionHeaderProps> = ({ eyebrow, title, description, actions, className = '' }) => (
  <div className={`flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between ${className}`}>
    <div className="min-w-0">
      {eyebrow && <p className="text-[11px] font-extrabold uppercase tracking-[.16em] text-brand-ink">{eyebrow}</p>}
      <h2 className="mt-1 text-lg font-black tracking-tight text-dashem-strong">{title}</h2>
      {description && <p className="mt-1 text-sm leading-5 text-dashem-muted">{description}</p>}
    </div>
    {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
  </div>
)
