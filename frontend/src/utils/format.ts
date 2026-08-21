/**
 * Brazilian Portuguese Formatting Utilities for POS and Retail
 */

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
