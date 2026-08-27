export const onlyDigits = (value: string, max?: number) => {
  const normalized = value.replace(/\D/g, '')
  return typeof max === 'number' ? normalized.slice(0, max) : normalized
}

export const formatBrazilianPhone = (value: string) => {
  const number = onlyDigits(value, 11)
  if (number.length <= 2) return number ? `(${number}` : ''
  if (number.length <= 6) return `(${number.slice(0, 2)}) ${number.slice(2)}`
  if (number.length <= 10) return `(${number.slice(0, 2)}) ${number.slice(2, 6)}-${number.slice(6)}`
  return `(${number.slice(0, 2)}) ${number.slice(2, 7)}-${number.slice(7)}`
}

export const formatBrazilianPostalCode = (value: string) => {
  const number = onlyDigits(value, 8)
  return number.length > 5 ? `${number.slice(0, 5)}-${number.slice(5)}` : number
}

export const formatCpfCnpj = (value: string) => {
  const number = onlyDigits(value, 14)
  if (number.length <= 11) {
    return number
      .replace(/(\d{3})(\d)/, '$1.$2')
      .replace(/(\d{3})(\d)/, '$1.$2')
      .replace(/(\d{3})(\d{1,2})$/, '$1-$2')
  }
  return number
    .replace(/(\d{2})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1/$2')
    .replace(/(\d{4})(\d{1,2})$/, '$1-$2')
}

const allEqual = (value: string) => value.length > 0 && value === value[0].repeat(value.length)

export const isValidCpfCnpj = (value: string) => {
  const number = onlyDigits(value, 14)
  if (allEqual(number)) return false
  if (number.length === 11) {
    const digits = [...number].map(Number)
    const first = ((digits.slice(0, 9).reduce((sum, digit, index) => sum + digit * (10 - index), 0) * 10) % 11) % 10
    const second = ((digits.slice(0, 10).reduce((sum, digit, index) => sum + digit * (11 - index), 0) * 10) % 11) % 10
    return digits[9] === first && digits[10] === second
  }
  if (number.length === 14) {
    const calculate = (size: number) => {
      const weights = Array.from({ length: size }, (_, index) => {
        const position = size - index
        return position >= 9 ? position - 7 : position + 1
      })
      const total = [...number].slice(0, size).reduce((sum, digit, index) => sum + Number(digit) * weights[index], 0)
      const remainder = total % 11
      return remainder < 2 ? 0 : 11 - remainder
    }
    return Number(number[12]) === calculate(12) && Number(number[13]) === calculate(13)
  }
  return false
}

export type BrazilianAddress = {
  street: string
  district: string
  city: string
  state: string
  complement: string
}

export async function lookupBrazilianPostalCode(value: string): Promise<BrazilianAddress> {
  const postalCode = onlyDigits(value, 8)
  if (postalCode.length !== 8) throw new Error('Informe os 8 números do CEP.')
  const response = await fetch(`https://viacep.com.br/ws/${postalCode}/json/`)
  if (!response.ok) throw new Error('Não foi possível consultar o CEP agora.')
  const payload = await response.json() as { erro?: boolean; logradouro?: string; bairro?: string; localidade?: string; uf?: string; complemento?: string }
  if (payload.erro) throw new Error('CEP não encontrado.')
  return {
    street: payload.logradouro || '',
    district: payload.bairro || '',
    city: payload.localidade || '',
    state: payload.uf || '',
    complement: payload.complemento || '',
  }
}

