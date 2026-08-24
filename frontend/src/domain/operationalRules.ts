export type ShellRoute = '/login' | '/operate' | '/owner' | '/manage' | '/pos' | '/tables' | '/kds'

const PLATFORM_ROLES = new Set(['PLATFORM_OWNER', 'PLATFORM_ADMIN'])

export function authenticatedHome(platformRole?: string | null, canManage = false): ShellRoute {
  if (platformRole && PLATFORM_ROLES.has(platformRole)) return '/owner'
  return canManage ? '/manage' : '/pos'
}

export function normalizeAuthenticatedRoute(
  pathname: string,
  platformRole?: string | null,
  canManage = false,
  canUseKds = false,
): ShellRoute {
  const home = authenticatedHome(platformRole, canManage)
  if (home === '/owner') return '/owner'
  if (pathname === '/manage') return canManage ? '/manage' : '/pos'
  if (pathname === '/kds') return canUseKds ? '/kds' : '/pos'
  if (pathname === '/tables') return '/tables'
  if (pathname === '/pos') return '/pos'
  return home
}

export function selectOnlyOption<T>(options: readonly T[]): T | null {
  return options.length === 1 ? options[0] : null
}

export type SaleStatus = 'DRAFT' | 'CHECKOUT' | 'AWAITING_PAYMENT' | 'PAID' | 'COMPLETED' | 'CANCELED'

export function saleNeedsCreation(status?: SaleStatus | null): boolean {
  return !status || status === 'PAID' || status === 'COMPLETED' || status === 'CANCELED'
}

export function canOperateCart(cashStatus?: 'OPEN' | 'CLOSED' | null): boolean {
  return cashStatus === 'OPEN'
}

export interface PaymentProgress {
  totalPaid: number
  remaining: number
  change: number
  settled: boolean
}

export function paymentProgress(
  netTotal: number,
  confirmedAmounts: readonly number[],
  tenderedAmount = 0,
  amountBeingPaid = 0,
): PaymentProgress {
  const totalPaid = confirmedAmounts.reduce((total, amount) => total + Number(amount), 0)
  const remaining = Math.max(0, Number(netTotal) - totalPaid)
  const change = Math.max(0, Number(tenderedAmount) - Number(amountBeingPaid))
  return { totalPaid, remaining, change, settled: remaining === 0 }
}

export type CashMovementType = 'OPENING' | 'SALE_PAYMENT' | 'BLEED' | 'REINFORCEMENT' | 'CLOSING'

export function expectedCashBalance(
  openingBalance: number,
  movements: ReadonlyArray<{ movement_type: CashMovementType; amount: number }>,
): number {
  return movements.reduce((balance, movement) => {
    if (movement.movement_type === 'SALE_PAYMENT' || movement.movement_type === 'REINFORCEMENT') {
      return balance + Number(movement.amount)
    }
    if (movement.movement_type === 'BLEED') return balance - Number(movement.amount)
    return balance
  }, Number(openingBalance))
}
