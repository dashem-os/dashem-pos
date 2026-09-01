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
