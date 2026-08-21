const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8002'

let accessTokenProvider: () => Promise<string | null> = async () => null

export function setApiAccessTokenProvider(provider: () => Promise<string | null>) {
  accessTokenProvider = provider
}

const nativeFetch = globalThis.fetch.bind(globalThis)
const fetch: typeof globalThis.fetch = async (input, init = {}) => {
  const token = await accessTokenProvider()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return nativeFetch(input, { ...init, headers })
}

export interface Tenant {
  id: string
  name: string
  slug: string
  status?: 'PROVISIONING' | 'TRIAL' | 'ACTIVE' | 'SUSPENDED' | 'CANCELED'
  created_at?: string
}

export interface Store {
  id: string
  tenant_id: string
  name: string
  code: string
}

export interface Category {
  id: string
  tenant_id: string
  name: string
  slug: string
}

export interface Product {
  id: string
  tenant_id: string
  name: string
  sku: string
  barcode?: string
  description?: string
  category_id?: string
  item_type: 'PRODUCT' | 'SERVICE'
  tracks_inventory: boolean
  requires_fulfillment: boolean
}

export interface ProductPrice {
  id: string
  tenant_id: string
  store_id?: string
  product_id: string
  sale_price: number
  cost_price: number
}

export interface InventoryBalance {
  id: string
  tenant_id: string
  store_id: string
  product_id: string
  quantity: number
}

export interface InventoryMovement {
  id: string
  tenant_id: string
  store_id: string
  product_id: string
  actor_id: string
  movement_type: 'PURCHASE' | 'SALE' | 'LOSS' | 'RETURN' | 'ADJUSTMENT'
  quantity: number
  reason?: string
  created_at: string
}

export interface SaleItem {
  id: string
  tenant_id: string
  sale_id: string
  product_id: string
  product_name: string
  sku: string
  item_type_snapshot: string
  tracks_inventory_snapshot: boolean
  requires_fulfillment_snapshot: boolean
  unit_price: number
  quantity: number
  discount_amount: number
  gross_total: number
  net_total: number
  created_at: string
}

export interface Sale {
  id: string
  tenant_id: string
  store_id: string
  customer_id?: string
  seller_id?: string
  status: 'DRAFT' | 'CHECKOUT' | 'AWAITING_PAYMENT' | 'PAID' | 'COMPLETED' | 'CANCELED'
  discount_type?: 'PERCENTAGE' | 'FIXED'
  requested_discount: number
  approved_discount: number
  gross_total: number
  discount_total: number
  net_total: number
  notes?: string
  created_at: string
  updated_at: string
  items: SaleItem[]
}

export interface Register {
  id: string
  tenant_id: string
  store_id: string
  name: string
  code: string
}

export interface CashSession {
  id: string
  tenant_id: string
  store_id: string
  register_id: string
  operator_id: string
  status: 'OPEN' | 'CLOSED'
  opening_balance: number
  closing_balance?: number
  expected_balance?: number
  variance?: number
  opened_at: string
  closed_at?: string
}

export interface CashMovement {
  id: string
  tenant_id: string
  store_id: string
  cash_session_id: string
  actor_id: string
  movement_type: 'OPENING' | 'SALE_PAYMENT' | 'BLEED' | 'REINFORCEMENT' | 'CLOSING'
  amount: number
  notes?: string
  created_at: string
}

export interface Payment {
  id: string
  tenant_id: string
  store_id: string
  sale_id: string
  cash_session_id?: string
  method: 'CASH' | 'PIX' | 'CREDIT_CARD' | 'DEBIT_CARD' | 'STORE_CREDIT'
  status: 'PENDING' | 'CONFIRMED' | 'FAILED' | 'REFUNDED'
  amount: number
  tendered_amount?: number
  change_amount?: number
  transaction_ref?: string
  created_at: string
  confirmed_at?: string
}

export interface FiscalDocument {
  id: string
  tenant_id: string
  store_id: string
  sale_id: string
  document_type: 'NFCE' | 'NFE' | 'SAT' | 'NONE'
  status: 'NOT_REQUIRED' | 'PENDING' | 'AUTHORIZED' | 'REJECTED' | 'CONTINGENCY' | 'CANCELED'
  access_key?: string
  document_number?: number
  xml_content?: string
  pdf_url?: string
  rejection_code?: string
  rejection_reason?: string
  issued_at?: string
  canceled_at?: string
}

export interface ApiHealth {
  status: string
  service: string
  timestamp: string
}

export interface AuthMe {
  mode: 'authenticated' | 'local-bypass'
  user: { id: string; email: string; full_name: string; is_active: boolean } | null
  platform_role?: string
  assurance_level?: string
  auth_provider?: string
  password_setup_required?: boolean
  mfa_required?: boolean
  onboarding_completed?: boolean
  memberships?: Array<{
    id: string
    tenant_id: string
    store_id?: string
    role: string
    status: string
  }>
}

export interface PlatformTenantSummary {
  id: string
  name: string
  slug: string
  status: 'PROVISIONING' | 'TRIAL' | 'ACTIVE' | 'SUSPENDED' | 'CANCELED'
  created_at: string
  store_count: number
}

export interface PlatformOverview {
  tenant_count: number
  trial_count: number
  active_count: number
  lead_count: number
  tenants: PlatformTenantSummary[]
}

export interface PlatformTenantProvisioned {
  tenant: Tenant
  first_store: Store
}

export interface PaymentConfirmResponse {
  payment: Payment
  sale_status: Sale['status']
  already_confirmed: boolean
}

export interface FiscalIssueResponse {
  fiscal_document: FiscalDocument
  sale_status: Sale['status']
  already_processed: boolean
}

// ----------------------------------------------------------------------
// SYSTEM & IDENTITY ENDPOINTS
// ----------------------------------------------------------------------

export async function fetchHealth(): Promise<ApiHealth> {
  const res = await fetch(`${API_BASE_URL}/health`)
  if (!res.ok) throw new Error('API Offline')
  return res.json()
}

export async function fetchMe(): Promise<AuthMe> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/me`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || 'Usuário não provisionado no Dashem POS')
  }
  return res.json()
}

async function apiError(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => ({}))
  const detail = typeof body.detail === 'string' ? body.detail : fallback
  return new Error(detail)
}

export async function completePasswordSetup(): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/me/password-setup-complete`, {
    method: 'POST',
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível concluir a configuração da senha.')
}

export async function completeOwnerOnboarding(): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/me/onboarding-complete`, {
    method: 'POST',
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível concluir o primeiro acesso.')
}

export async function fetchPlatformOverview(): Promise<PlatformOverview> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/overview`)
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar o Console Owner.')
  return res.json()
}

export async function provisionPlatformTenant(input: {
  name: string
  slug: string
  first_store_name: string
  first_store_code: string
}): Promise<PlatformTenantProvisioned> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível criar o tenant.')
  return res.json()
}

export async function fetchTenants(): Promise<Tenant[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/tenants`)
  if (!res.ok) return []
  return res.json()
}

export async function createTenant(name: string, slug: string): Promise<Tenant> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/tenants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, slug })
  })
  if (!res.ok) throw new Error('Erro ao criar tenant')
  return res.json()
}

export async function fetchStores(tenantId?: string): Promise<Store[]> {
  const url = tenantId ? `${API_BASE_URL}/api/v1/identity/stores?tenant_id=${tenantId}` : `${API_BASE_URL}/api/v1/identity/stores`
  const res = await fetch(url)
  if (!res.ok) return []
  return res.json()
}

export async function createStore(tenantId: string, name: string, code: string): Promise<Store> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/stores`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tenant_id: tenantId, name, code })
  })
  if (!res.ok) throw new Error('Erro ao criar loja')
  return res.json()
}

// ----------------------------------------------------------------------
// CATALOG & INVENTORY ENDPOINTS
// ----------------------------------------------------------------------

export async function fetchProducts(headers: Record<string, string>, search?: string): Promise<Product[]> {
  const url = search ? `${API_BASE_URL}/api/v1/catalog/products?search=${encodeURIComponent(search)}` : `${API_BASE_URL}/api/v1/catalog/products`
  const res = await fetch(url, { headers })
  if (!res.ok) return []
  return res.json()
}

export async function createProduct(
  headers: Record<string, string>,
  product: { name: string; sku: string; barcode?: string; description?: string; category_id?: string; item_type?: 'PRODUCT' | 'SERVICE'; tracks_inventory?: boolean; requires_fulfillment?: boolean }
): Promise<Product> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/products`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(product)
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao criar produto')
  }
  return res.json()
}

export async function setProductPrice(
  headers: Record<string, string>,
  productId: string,
  storeId: string,
  salePrice: number,
  costPrice: number = 0
): Promise<ProductPrice> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/prices`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_id: productId, store_id: storeId, sale_price: salePrice, cost_price: costPrice })
  })
  if (!res.ok) throw new Error('Erro ao definir preço')
  return res.json()
}

export async function fetchCategories(headers: Record<string, string>): Promise<Category[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/categories`, { headers })
  if (!res.ok) return []
  return res.json()
}

export async function createCategory(headers: Record<string, string>, name: string, slug: string): Promise<Category> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/categories`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, slug })
  })
  if (!res.ok) throw new Error('Erro ao criar categoria')
  return res.json()
}

export async function fetchProductPrices(headers: Record<string, string>, storeId?: string, productId?: string): Promise<ProductPrice[]> {
  let url = `${API_BASE_URL}/api/v1/catalog/prices`
  const params = new URLSearchParams()
  if (storeId) params.append('store_id', storeId)
  if (productId) params.append('product_id', productId)
  if (params.toString()) url += `?${params.toString()}`

  const res = await fetch(url, { headers })
  if (!res.ok) return []
  return res.json()
}

export async function fetchInventoryBalance(headers: Record<string, string>, storeId: string, productId: string): Promise<InventoryBalance | null> {
  const res = await fetch(`${API_BASE_URL}/api/v1/inventory/balance?store_id=${storeId}&product_id=${productId}`, { headers })
  if (!res.ok) return null
  return res.json()
}


export async function adjustInventory(
  headers: Record<string, string>,
  data: { store_id: string; product_id: string; actor_id: string; movement_type: string; quantity: number; reason?: string }
): Promise<{ movement: InventoryMovement | null; balance: InventoryBalance; movement_created: boolean }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/inventory/adjust`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  if (!res.ok) throw new Error('Erro ao ajustar estoque')
  return res.json()
}

export async function fetchInventoryMovements(headers: Record<string, string>, storeId?: string, productId?: string): Promise<InventoryMovement[]> {
  let url = `${API_BASE_URL}/api/v1/inventory/movements`
  const params = new URLSearchParams()
  if (storeId) params.append('store_id', storeId)
  if (productId) params.append('product_id', productId)
  if (params.toString()) url += `?${params.toString()}`

  const res = await fetch(url, { headers })
  if (!res.ok) return []
  return res.json()
}

// ----------------------------------------------------------------------
// SALES & CART ENDPOINTS
// ----------------------------------------------------------------------

export async function fetchSales(headers: Record<string, string>, storeId?: string, status?: Sale['status']): Promise<Sale[]> {
  let url = `${API_BASE_URL}/api/v1/sales`
  const params = new URLSearchParams()
  if (storeId) params.append('store_id', storeId)
  if (status) params.append('status', status)
  if (params.toString()) url += `?${params.toString()}`

  const res = await fetch(url, { headers })
  if (!res.ok) return []
  return res.json()
}

export async function getSale(headers: Record<string, string>, saleId: string): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/${saleId}`, { headers })
  if (!res.ok) throw new Error('Venda não encontrada')
  return res.json()
}

export async function createSale(headers: Record<string, string>, storeId: string, customerId?: string, notes?: string): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_id: storeId, customer_id: customerId, notes })
  })
  if (!res.ok) throw new Error('Erro ao criar venda')
  return res.json()
}

export async function addItemToSale(
  headers: Record<string, string>,
  saleId: string,
  productId: string,
  quantity: number = 1,
  requestedDiscount: number = 0
): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/${saleId}/items`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_id: productId, quantity, requested_discount: requestedDiscount })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao adicionar item')
  }
  // Retrieve the complete refreshed Sale with updated items and totals
  return getSale(headers, saleId)
}

export async function updateSaleItem(
  headers: Record<string, string>,
  saleId: string,
  itemId: string,
  quantity: number,
  requestedDiscount?: number
): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/${saleId}/items/${itemId}`, {
    method: 'PATCH',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ quantity, requested_discount: requestedDiscount })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao atualizar quantidade do item')
  }
  return getSale(headers, saleId)
}

export async function deleteSaleItem(headers: Record<string, string>, saleId: string, itemId: string): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/${saleId}/items/${itemId}`, {
    method: 'DELETE',
    headers
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao remover item da venda')
  }
  return res.json()
}

export async function applySaleDiscount(
  headers: Record<string, string>,
  saleId: string,
  discountType: 'FIXED' | 'PERCENTAGE',
  value: number
): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/${saleId}/discount`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ discount_type: discountType, value })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao aplicar desconto')
  }
  return res.json()
}

export async function cancelSale(headers: Record<string, string>, saleId: string, actorId?: string, reason?: string): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/${saleId}/cancel`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, reason })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao cancelar venda')
  }
  return res.json()
}

export async function checkoutSale(
  headers: Record<string, string>,
  saleId: string,
  actorId: string,
  requestedDiscount: number = 0,
  discountType?: 'PERCENTAGE' | 'FIXED'
): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/${saleId}/checkout`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, requested_discount: requestedDiscount, discount_type: discountType })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro no checkout da venda')
  }
  return res.json()
}

// ----------------------------------------------------------------------
// CASH SESSION ENDPOINTS
// ----------------------------------------------------------------------

export async function fetchRegisters(headers: Record<string, string>, storeId?: string): Promise<Register[]> {
  const url = storeId ? `${API_BASE_URL}/api/v1/cash/registers?store_id=${storeId}` : `${API_BASE_URL}/api/v1/cash/registers`
  const res = await fetch(url, { headers })
  if (!res.ok) return []
  return res.json()
}

export async function createRegister(headers: Record<string, string>, storeId: string, name: string, code: string): Promise<Register> {
  const res = await fetch(`${API_BASE_URL}/api/v1/cash/registers`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_id: storeId, name, code })
  })
  if (!res.ok) throw new Error('Erro ao criar terminal de caixa')
  return res.json()
}

export async function fetchActiveCashSession(headers: Record<string, string>, storeId?: string, registerId?: string): Promise<CashSession | null> {
  const params = new URLSearchParams()
  if (storeId) params.append('store_id', storeId)
  if (registerId) params.append('register_id', registerId)
  const url = `${API_BASE_URL}/api/v1/cash/sessions/active?${params.toString()}`

  const res = await fetch(url, { headers })
  if (!res.ok) return null
  return res.json()
}

export async function fetchCashSessions(headers: Record<string, string>, storeId?: string, status?: 'OPEN' | 'CLOSED'): Promise<CashSession[]> {
  let url = `${API_BASE_URL}/api/v1/cash/sessions`
  const params = new URLSearchParams()
  if (storeId) params.append('store_id', storeId)
  if (status) params.append('status', status)
  if (params.toString()) url += `?${params.toString()}`

  const res = await fetch(url, { headers })
  if (!res.ok) return []
  return res.json()
}

export async function openCashSession(
  headers: Record<string, string>,
  storeId: string,
  registerId: string,
  operatorId: string,
  openingBalance: number
): Promise<CashSession> {
  const res = await fetch(`${API_BASE_URL}/api/v1/cash/sessions/open`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_id: storeId, register_id: registerId, operator_id: operatorId, opening_balance: openingBalance })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao abrir caixa')
  }
  return res.json()
}

export async function closeCashSession(headers: Record<string, string>, sessionId: string, operatorId: string, closingBalance: number): Promise<CashSession> {
  const res = await fetch(`${API_BASE_URL}/api/v1/cash/sessions/${sessionId}/close`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ operator_id: operatorId, closing_balance: closingBalance })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao fechar caixa')
  }
  return res.json()
}

export async function addCashMovement(
  headers: Record<string, string>,
  sessionId: string,
  actorId: string,
  movementType: 'BLEED' | 'REINFORCEMENT',
  amount: number,
  notes?: string
): Promise<CashMovement> {
  const res = await fetch(`${API_BASE_URL}/api/v1/cash/sessions/${sessionId}/movements`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, movement_type: movementType, amount, notes })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao registrar movimentação de caixa')
  }
  return res.json()
}

export async function fetchCashMovements(headers: Record<string, string>, sessionId: string): Promise<CashMovement[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/cash/sessions/${sessionId}/movements`, { headers })
  if (!res.ok) return []
  return res.json()
}

// ----------------------------------------------------------------------
// PAYMENT ENDPOINTS
// ----------------------------------------------------------------------

export async function fetchSalePayments(headers: Record<string, string>, saleId: string): Promise<Payment[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/payments?sale_id=${saleId}`, { headers })
  if (!res.ok) return []
  return res.json()
}

export async function createPayment(
  headers: Record<string, string>,
  saleId: string,
  method: Payment['method'],
  amount: number,
  cashSessionId?: string,
  tenderedAmount?: number
): Promise<Payment> {
  const res = await fetch(`${API_BASE_URL}/api/v1/payments`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ sale_id: saleId, method, amount, cash_session_id: cashSessionId, tendered_amount: tenderedAmount })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao adicionar pagamento')
  }
  return res.json()
}

export async function confirmPayment(
  headers: Record<string, string>,
  paymentId: string,
  actorId: string,
  idempotencyKey?: string
): Promise<PaymentConfirmResponse> {
  const reqHeaders: Record<string, string> = { ...headers, 'Content-Type': 'application/json' }
  if (idempotencyKey) reqHeaders['Idempotency-Key'] = idempotencyKey

  const res = await fetch(`${API_BASE_URL}/api/v1/payments/${paymentId}/confirm`, {
    method: 'POST',
    headers: reqHeaders,
    body: JSON.stringify({ actor_id: actorId })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao confirmar pagamento')
  }
  return res.json()
}

// ----------------------------------------------------------------------
// FISCAL ENDPOINTS
// ----------------------------------------------------------------------

export async function issueFiscalDocument(
  headers: Record<string, string>,
  saleId: string,
  actorId: string,
  documentType: 'NFCE' | 'NFE' | 'SAT' | 'NONE' = 'NFCE',
  simulateStatus?: string
): Promise<FiscalIssueResponse> {
  const res = await fetch(`${API_BASE_URL}/api/v1/fiscal/documents/issue`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ sale_id: saleId, actor_id: actorId, document_type: documentType, simulate_status: simulateStatus })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao emitir documento fiscal')
  }
  return res.json()
}

export async function cancelFiscalDocument(
  headers: Record<string, string>,
  fiscalDocumentId: string,
  actorId: string,
  reason: string
): Promise<FiscalDocument> {
  const res = await fetch(`${API_BASE_URL}/api/v1/fiscal/documents/${fiscalDocumentId}/cancel`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, reason })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Erro ao cancelar documento fiscal')
  }
  return res.json()
}

export async function getFiscalDocument(headers: Record<string, string>, fiscalDocumentId: string): Promise<FiscalDocument> {
  const res = await fetch(`${API_BASE_URL}/api/v1/fiscal/documents/${fiscalDocumentId}`, { headers })
  if (!res.ok) throw new Error('Documento fiscal não encontrado')
  return res.json()
}

// ----------------------------------------------------------------------
// IDEMPOTENT DEVELOPMENT SEED HELPER
// ----------------------------------------------------------------------

export async function seedDevEnvironment(operatorId: string): Promise<{ tenant: Tenant; store: Store; register: Register; cashSession: CashSession }> {
  // Check if any tenant exists
  const tenants = await fetchTenants()
  let tenant = tenants[0]
  if (!tenant) {
    tenant = await createTenant('Dashem Retail Store', 'dashem-retail-01')
  }

  // Check if store exists
  const stores = await fetchStores(tenant.id)
  let store = stores[0]
  if (!store) {
    store = await createStore(tenant.id, 'Loja Matriz Centro', 'MC-01')
  }

  const hdrs = { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }

  // Check register
  const registers = await fetchRegisters(hdrs, store.id)
  let register = registers[0]
  if (!register) {
    register = await createRegister(hdrs, store.id, 'Caixa Principal 01', 'CX-01')
  }

  // Check active cash session
  let activeSession = await fetchActiveCashSession(hdrs, store.id, register.id)
  if (!activeSession) {
    activeSession = await openCashSession(hdrs, store.id, register.id, operatorId, 100.0)
  }

  // Seed default categories & products if catalog is empty
  const prods = await fetchProducts(hdrs)
  if (prods.length === 0) {
    // 1. Create Real Categories
    const existingCats = await fetchCategories(hdrs)
    const catMap: Record<string, string> = {}
    for (const c of existingCats) {
      catMap[c.name] = c.id
    }

    const categoriesToSeed = [
      { name: 'Elétrica', slug: 'eletrica' },
      { name: 'Iluminação', slug: 'iluminacao' },
      { name: 'Acessórios', slug: 'acessorios' },
      { name: 'Ferramentas', slug: 'ferramentas' }
    ]

    for (const c of categoriesToSeed) {
      if (!catMap[c.name]) {
        const createdCat = await createCategory(hdrs, c.name, c.slug).catch(() => null)
        if (createdCat) catMap[c.name] = createdCat.id
      }
    }

    // 2. Create Products linked to Category ID
    const initialItems = [
      { name: 'Cabo Flexível 2.5mm (Rolo 100m)', sku: 'CAB-25M', barcode: '7891000000014', price: 89.90, type: 'PRODUCT' as const, qty: 25, category: 'Elétrica' },
      { name: 'Disjuntor Bipolar 32A DIN Curva C', sku: 'DISJ-32A', barcode: '7891000000021', price: 44.50, type: 'PRODUCT' as const, qty: 18, category: 'Elétrica' },
      { name: 'Lâmpada LED Bulbo 12W Bivolt E27', sku: 'LAMP-12W', barcode: '7891000000038', price: 14.90, type: 'PRODUCT' as const, qty: 50, category: 'Iluminação' },
      { name: 'Plafon LED Sobrepor 18W Quadrado', sku: 'PLAF-18W', barcode: '7891000000045', price: 38.00, type: 'PRODUCT' as const, qty: 14, category: 'Iluminação' },
      { name: 'Tomada Dupla 20A com Placa 4x2', sku: 'TOM-20A', barcode: '7891000000052', price: 22.90, type: 'PRODUCT' as const, qty: 40, category: 'Elétrica' },
      { name: 'Fita Isolante 3M Imperial 20m', sku: 'FITA-20M', barcode: '7891000000069', price: 11.50, type: 'PRODUCT' as const, qty: 60, category: 'Acessórios' },
      { name: 'Refletor LED 50W IP65 Branco Frio', sku: 'REFL-50W', barcode: '7891000000076', price: 68.00, type: 'PRODUCT' as const, qty: 12, category: 'Iluminação' },
      { name: 'Fita LED 5050 5m Branco Quente', sku: 'FLED-5M', barcode: '7891000000083', price: 49.90, type: 'PRODUCT' as const, qty: 15, category: 'Iluminação' },
      { name: 'Canaleta 20x10mm com Fita Dupla Face 2m', sku: 'CAN-2010', barcode: '7891000000090', price: 8.50, type: 'PRODUCT' as const, qty: 35, category: 'Acessórios' },
      { name: 'Interruptor Paralelo Simples com Placa', sku: 'INT-PAR', barcode: '7891000000106', price: 16.90, type: 'PRODUCT' as const, qty: 28, category: 'Elétrica' },
      { name: 'Chave de Teste Digital 12-250V', sku: 'CHAV-TEST', barcode: '7891000000113', price: 28.00, type: 'PRODUCT' as const, qty: 20, category: 'Ferramentas' },
      { name: 'Alicate Decapador e Crimpador Automático', sku: 'ALIC-DEC', barcode: '7891000000120', price: 75.00, type: 'PRODUCT' as const, qty: 8, category: 'Ferramentas' }
    ]

    for (const item of initialItems) {
      const created = await createProduct(hdrs, {
        name: item.name,
        sku: item.sku,
        barcode: item.barcode,
        description: item.category,
        category_id: catMap[item.category] || undefined,
        item_type: item.type
      })
      await setProductPrice(hdrs, created.id, store.id, item.price)
      if (item.type === 'PRODUCT' && item.qty > 0) {
        await adjustInventory(hdrs, {
          store_id: store.id,
          product_id: created.id,
          actor_id: operatorId,
          movement_type: 'PURCHASE',
          quantity: item.qty,
          reason: 'Carga Inicial Estoque Dev'
        })
      }
    }
  }

  return { tenant, store, register, cashSession: activeSession }
}
