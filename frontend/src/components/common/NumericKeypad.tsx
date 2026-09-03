import React from 'react'
import { Delete } from 'lucide-react'

export interface NumericKeypadProps {
  onDigit: (digit: string) => void
  onBackspace: () => void
  /** Required when `leadingKey` is 'clear'. */
  onClear?: () => void
  /** Key rendered to the left of zero: a decimal separator or a clear action. */
  leadingKey?: 'decimal' | 'clear' | 'none'
  disabled?: boolean
  className?: string
}

const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

// 48px keys: the operator hits these repeatedly, often on a counter tablet.
const KEY = `flex min-h-12 items-center justify-center rounded-xl border border-dashem-border
  text-lg font-black transition active:scale-95 disabled:opacity-40`
const DIGIT_KEY = `${KEY} bg-dashem-surface text-dashem-strong shadow-xs hover:bg-dashem-surface-elevated`
const ACTION_KEY = `${KEY} bg-dashem-surface-elevated text-dashem-muted text-sm hover:bg-dashem-border/60`

/**
 * Touch numeric keypad shared by the quantity and discount flows.
 */
export const NumericKeypad: React.FC<NumericKeypadProps> = ({
  onDigit, onBackspace, onClear, leadingKey = 'none', disabled = false, className = '',
}) => (
  <div className={`grid grid-cols-3 gap-1.5 ${className}`}>
    {DIGITS.map((digit) => (
      <button key={digit} type="button" disabled={disabled} onClick={() => onDigit(digit)} className={DIGIT_KEY}>
        {digit}
      </button>
    ))}

    {leadingKey === 'decimal' && (
      <button type="button" disabled={disabled} onClick={() => onDigit('.')} className={DIGIT_KEY}>.</button>
    )}
    {leadingKey === 'clear' && (
      <button type="button" disabled={disabled} onClick={onClear} className={`${ACTION_KEY} text-brand-ink`}>Limpar</button>
    )}
    {leadingKey === 'none' && <span />}

    <button type="button" disabled={disabled} onClick={() => onDigit('0')} className={DIGIT_KEY}>0</button>

    <button type="button" disabled={disabled} onClick={onBackspace} className={ACTION_KEY} aria-label="Apagar último dígito">
      <Delete className="h-5 w-5" />
    </button>
  </div>
)
