import React from 'react'
import { Loader2 } from 'lucide-react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'soft'
type Size = 'sm' | 'md' | 'lg'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  /** Renders a spinner and blocks interaction without collapsing the layout. */
  loading?: boolean
  icon?: React.ComponentType<{ className?: string }>
  iconRight?: React.ComponentType<{ className?: string }>
  block?: boolean
}

const VARIANTS: Record<Variant, string> = {
  // text-brand-contrast (not text-white) keeps the amber BEAUTY identity readable.
  primary: 'bg-brand text-brand-contrast shadow-sm hover:bg-brand-strong active:bg-brand-strong',
  secondary: 'border border-dashem-border bg-dashem-surface text-dashem-strong hover:bg-dashem-surface-elevated',
  ghost: 'text-dashem-muted hover:bg-dashem-surface-elevated hover:text-dashem-strong',
  danger: 'bg-red-600 text-white shadow-sm hover:bg-red-700',
  soft: 'bg-brand-soft text-brand-ink hover:bg-brand-soft/70',
}

// md is the default because 44px is the smallest comfortable touch target on a
// counter tablet; sm exists only for dense desktop-only toolbars.
const SIZES: Record<Size, string> = {
  sm: 'min-h-9 gap-1.5 rounded-lg px-3 text-xs',
  md: 'min-h-11 gap-2 rounded-xl px-4 text-sm',
  lg: 'min-h-14 gap-2.5 rounded-2xl px-6 text-base',
}

const ICON_SIZES: Record<Size, string> = { sm: 'h-3.5 w-3.5', md: 'h-4 w-4', lg: 'h-5 w-5' }

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary', size = 'md', loading = false, icon: Icon, iconRight: IconRight,
  block = false, className = '', children, disabled, type = 'button', ...rest
}) => {
  const iconClass = `${ICON_SIZES[size]} shrink-0`
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex max-w-full items-center justify-center font-bold tracking-tight transition
        disabled:cursor-not-allowed disabled:opacity-50
        ${VARIANTS[variant]} ${SIZES[size]} ${block ? 'w-full' : ''} ${className}`}
      {...rest}
    >
      {loading ? <Loader2 className={`${iconClass} animate-spin`} /> : Icon ? <Icon className={iconClass} /> : null}
      {children}
      {IconRight && !loading ? <IconRight className={iconClass} /> : null}
    </button>
  )
}
