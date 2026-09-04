/**
 * Brazilian Portuguese Formatting Utilities for POS and Retail
 */

export const PRODUCT_TIME_OFFSET = 'UTC−03:00'

const UTC_MINUS_THREE_MS = 3 * 60 * 60 * 1000
const ISO_WITH_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/i
const productDateTimeFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZone: 'UTC',
})

/**
 * Formats an instant using the product's fixed UTC−03:00 display rule.
 * Offset-less backend timestamps are legacy UTC values, not browser-local time.
 */
export function formatProductDateTime(value: string | number | Date | undefined | null): string {
  if (value === undefined || value === null || value === '') return '—'
  const normalized = typeof value === 'string' && !ISO_WITH_OFFSET.test(value.trim())
    ? `${value.trim()}Z`
    : value
  const instant = normalized instanceof Date ? normalized : new Date(normalized)
  if (Number.isNaN(instant.getTime())) return '—'
  return `${productDateTimeFormatter.format(new Date(instant.getTime() - UTC_MINUS_THREE_MS))} (${PRODUCT_TIME_OFFSET})`
}

export function formatCurrency(value: number | string | undefined | null): string {
  const num = typeof value === 'string' ? parseFloat(value) : (value || 0)
  if (isNaN(num)) return 'R$ 0,00'
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(num)
}

export function formatQuantity(value: number | string | undefined | null): string {
  const num = typeof value === 'string' ? parseFloat(value) : (value || 0)
  if (isNaN(num)) return '0'
  // If whole integer, show integer without decimals
  if (Math.floor(num) === num) {
    return num.toString()
  }
  // Otherwise format with up to 3 decimals with comma
  return new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 3
  }).format(num)
}

export function formatStock(value: number | string | undefined | null, unit: string = 'un'): string {
  const num = typeof value === 'string' ? parseFloat(value) : (value || 0)
  if (isNaN(num) || num <= 0) return 'Sem estoque'
  return `${formatQuantity(num)} ${unit}`
}

/**
 * Progressive BRL entry: digits fill from the cents up, so typing 1, 0, 0, 0
 * reads 0,01 → 0,10 → 1,00 → 10,00. Anything that is not a digit is ignored,
 * which keeps backspace working through the comma and the thousand separators
 * instead of leaving a zero the person cannot erase.
 */
export function maskCurrencyInput(raw: string): string {
  const digits = raw.replace(/\D/g, '').replace(/^0+(?=\d)/, '')
  if (!digits) return ''
  const cents = digits.padStart(3, '0')
  const whole = cents.slice(0, -2)
  const fraction = cents.slice(-2)
  return `${Number(whole).toLocaleString('pt-BR')},${fraction}`
}

/** The numeric value behind a masked BRL string. */
export function parseCurrencyInput(masked: string): number {
  const digits = masked.replace(/\D/g, '')
  return digits ? Number(digits) / 100 : 0
}

/**
 * A timestamp coming from the API, read as the UTC instant it is.
 *
 * The backend stores and serializes naive UTC — `2026-09-04T00:48:00`, with no
 * offset — and `new Date` on a string without an offset is parsed as *local*
 * time. Every server timestamp rendered that way was therefore shifted by the
 * browser's offset: a fifteen minute lock announced itself three hours away, a
 * terminal seen a second ago never counted as online, and a due date falling in
 * the small hours of UTC showed the day before.
 *
 * Only fields the server produced go through here. A value the person typed
 * into the browser is already local and must not be reinterpreted.
 */
export function parseApiDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value)
  const parsed = new Date(hasZone ? value : `${value}Z`)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

/** Milliseconds elapsed since a server timestamp, or null when there is none. */
export function millisecondsSince(value: string | null | undefined): number | null {
  const parsed = parseApiDate(value)
  return parsed ? Date.now() - parsed.getTime() : null
}

/**
 * A server timestamp rendered for a Brazilian reader. Absent or unparseable
 * values print the fallback instead of "Invalid Date".
 */
export function formatApiDateTime(
  value: string | null | undefined,
  style: 'datetime' | 'date' | 'time' = 'datetime',
  fallback = '—',
): string {
  const parsed = parseApiDate(value)
  if (!parsed) return fallback
  if (style === 'date') return parsed.toLocaleDateString('pt-BR')
  if (style === 'time') return parsed.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  return parsed.toLocaleString('pt-BR')
}
