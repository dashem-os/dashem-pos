import React, { useId } from 'react'

const CONTROL = `min-h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface px-3 text-sm
  font-semibold text-dashem-strong placeholder:font-normal placeholder:text-dashem-muted
  transition focus:border-brand-ink disabled:cursor-not-allowed disabled:opacity-60`

export interface FieldProps {
  label: string
  /** Guidance shown before the user types; errors replace it. */
  hint?: string
  error?: string
  required?: boolean
  className?: string
  children: (controlProps: { id: string; className: string; 'aria-invalid': boolean }) => React.ReactNode
}

/**
 * Label + control + hint/error, so every form in the product aligns the same way.
 * The control is supplied by the caller to keep input, select and textarea supported.
 */
export const Field: React.FC<FieldProps> = ({ label, hint, error, required, className = '', children }) => {
  const id = useId()
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={id} className="text-xs font-black uppercase tracking-wide text-dashem-muted">
        {label}{required && <span className="ml-1 text-brand-ink">*</span>}
      </label>
      {children({ id, className: `${CONTROL} ${error ? 'border-red-400' : ''}`, 'aria-invalid': Boolean(error) })}
      {error
        ? <p className="text-xs font-bold text-red-600">{error}</p>
        : hint ? <p className="text-xs text-dashem-muted">{hint}</p> : null}
    </div>
  )
}

export const Input: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({ className = '', ...rest }) => (
  <input className={`${CONTROL} ${className}`} {...rest} />
)

export const Select: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({ className = '', children, ...rest }) => (
  <select className={`${CONTROL} ${className}`} {...rest}>{children}</select>
)

export const Textarea: React.FC<React.TextareaHTMLAttributes<HTMLTextAreaElement>> = ({ className = '', ...rest }) => (
  <textarea className={`${CONTROL} py-2.5 ${className}`} {...rest} />
)
