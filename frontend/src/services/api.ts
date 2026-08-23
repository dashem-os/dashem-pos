import { API_BASE_URL, apiError, apiFetch as fetch } from './http'
export { setApiAccessTokenProvider } from './http'

export interface Tenant {
  id: string
  name: string
  slug: string
  status?: TenantLifecycleStatus
  created_at?: string
}

export interface Store {
  id: string
  tenant_id: string
  name: string
  code: string
  site_type?: string
  is_headquarters?: boolean
  legal_name?: string
  tax_id?: string
  state_registration?: string
  email?: string
  phone?: string
  postal_code?: string
  street?: string
  street_number?: string
  address_complement?: string
  district?: string
  city?: string
  state?: string
  country_code?: string
  is_active?: boolean
}

export interface Category {
  id: string
  tenant_id: string
  name: string
  slug: string
  parent_id?: string
  is_active: boolean
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
  image_url?: string
  unit: string
  is_active: boolean
  available_for_sale: boolean
  allows_multi_flavor: boolean
  production_destination?: string
}

export interface SellableProduct extends Omit<Product, 'tenant_id' | 'is_active'> {
  category_name?: string
  sale_price: number
  cost_price: number
  margin_percent: number
  quantity: number
  minimum_stock: number
  is_low_stock: boolean
  quick_position?: number
}

export interface SellableProductPage {
  items: SellableProduct[]
  total: number
  page: number
  page_size: number
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
  minimum_stock: number
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

export interface EffectiveAccess {
  capabilities: Record<string, { key: string; version: string; scope: string; configuration: Record<string, unknown>; inherited: boolean }>
  permissions: string[]
  context: { tenant_id: string; store_id?: string; membership_id?: string }
}

export interface TeamMember {
  membership_id: string
  user_id: string
  full_name: string
  email: string
  role: string
  status: string
  store_id?: string
  store_name?: string
}

export interface ManagementOverview {
  generated_at: string
  revenue_today: number
  revenue_30d: number
  sales_today: number
  sales_30d: number
  average_ticket_30d: number
  open_sales: number
  confirmed_receipts_30d: number
  active_cash_sessions: number
  products: number
  customers: number
  active_team_members: number
  daily_revenue: Array<{ date: string; revenue: number; sales: number }>
  alerts: string[]
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
  status: TenantLifecycleStatus
  created_at: string
  store_count: number
  customer_type: TenantCustomerType
  legal_name?: string
  tax_id?: string
  profile_complete: boolean
}

export type TenantLifecycleStatus = 'PROVISIONING' | 'TRIAL' | 'ACTIVE' | 'PAUSED' | 'SUSPENDED' | 'CANCELED' | 'ARCHIVED'
export type TenantCustomerType = 'TEST' | 'PILOT' | 'CUSTOMER' | 'INTERNAL'
export type SubscriptionStatus = 'PENDING' | 'TRIAL' | 'ACTIVE' | 'PAUSED' | 'CANCELED'

export interface TenantProfile {
  tenant_id: string
  customer_type: TenantCustomerType
  trade_name: string
  legal_name?: string
  tax_id?: string
  state_registration?: string
  municipal_registration?: string
  industry?: string
  company_email?: string
  company_phone?: string
  website?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface TenantContact {
  id: string
  tenant_id: string
  full_name: string
  job_title?: string
  email?: string
  phone?: string
  is_primary: boolean
  is_active: boolean
}

export interface ServicePlan {
  id: string
  code: string
  name: string
  description?: string
  is_active: boolean
  store_limit?: number
  user_limit?: number
  terminal_limit?: number
}

export interface TenantSubscription {
  tenant_id: string
  plan_id?: string
  status: SubscriptionStatus
  starts_at?: string
  trial_ends_at?: string
  ends_at?: string
}

export interface TenantCapability {
  id: string
  tenant_id: string
  key: string
  enabled: boolean
  status: string
  contract_limits: Record<string, unknown>
  configuration: Record<string, unknown>
}

export interface CapabilityCatalogItem {
  key: string
  name: string
  version: string
  scope: 'TENANT' | 'STORE' | 'TERMINAL'
  description: string
  requires: string[]
  enabled: boolean
  status: string
  contract_limits: Record<string, unknown>
}

export interface HealthComponent {
  key: string
  label: string
  status: 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY' | 'UNKNOWN' | 'NOT_CONFIGURED'
  latency_ms?: number
  details: Record<string, unknown>
}

export interface PlatformSystemHealth {
  checked_at: string
  status: 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY'
  components: HealthComponent[]
  totals: Record<string, number>
}

export interface TenantDailyMetric {
  date: string
  sales_count: number
  revenue: number
}

export interface TenantOperationalMetrics {
  tenant_id: string
  checked_at: string
  status: 'HEALTHY' | 'DEGRADED'
  stores_total: number
  stores_active: number
  users_total: number
  users_active: number
  users_invited: number
  users_suspended: number
  users_revoked: number
  registers_active: number
  cash_sessions_open: number
  products_total: number
  low_stock_items: number
  sales_today: number
  sales_30d: number
  revenue_today: number
  revenue_30d: number
  outbox_pending: number
  outbox_failed: number
  agent_runs_30d: number
  agent_failures_30d: number
  last_activity_at?: string
  daily: TenantDailyMetric[]
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

export interface PlatformTenantAccess {
  membership_id: string
  user_id: string
  email: string
  full_name: string
  role: string
  status: string
  store_id?: string
  store_name?: string
  created_at: string
}

export interface PlatformTenantDetail {
  tenant: PlatformTenantSummary
  profile?: TenantProfile
  contacts: TenantContact[]
  subscription?: TenantSubscription
  plan?: ServicePlan
  stores: Store[]
  accesses: PlatformTenantAccess[]
  capabilities: TenantCapability[]
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

export async function fetchEffectiveAccess(headers: Record<string, string>): Promise<EffectiveAccess> {
  const res = await fetch(`${API_BASE_URL}/api/v1/capabilities/effective`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível resolver capabilities e permissions efetivas.')
  return res.json()
}

export async function fetchTeam(headers: Record<string, string>): Promise<TeamMember[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/team`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar a equipe.')
  return res.json()
}

export async function inviteTeamMember(
  headers: Record<string, string>,
  input: { email: string; full_name: string; role: string; store_id?: string },
): Promise<TeamMember> {
  const res = await fetch(`${API_BASE_URL}/api/v1/team/invitations`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível convidar o membro da equipe.')
  return res.json()
}

export async function updateTeamMember(
  headers: Record<string, string>, membershipId: string,
  input: { role: string; status: string; store_id?: string; reason: string },
): Promise<TeamMember> {
  const res = await fetch(`${API_BASE_URL}/api/v1/team/${membershipId}`, {
    method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o acesso da equipe.')
  return res.json()
}

export async function fetchManagementOverview(headers: Record<string, string>): Promise<ManagementOverview> {
  const res = await fetch(`${API_BASE_URL}/api/v1/management/overview`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar os indicadores gerenciais.')
  return res.json()
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

export async function fetchPlatformHealth(): Promise<PlatformSystemHealth> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/health`)
  if (!res.ok) throw await apiError(res, 'Não foi possível verificar a saúde da plataforma.')
  return res.json()
}

export async function fetchTenantMetrics(tenantId: string): Promise<TenantOperationalMetrics> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/metrics`)
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar as métricas do cliente.')
  return res.json()
}

export async function provisionPlatformTenant(input: {
  name: string
  slug: string
  first_store_name: string
  first_store_code: string
  customer_type: TenantCustomerType
  legal_name?: string
  tax_id?: string
  state_registration?: string
  municipal_registration?: string
  industry?: string
  company_email?: string
  company_phone?: string
  website?: string
  contact_name?: string
  contact_job_title?: string
  contact_email?: string
  contact_phone?: string
  postal_code?: string
  street?: string
  street_number?: string
  address_complement?: string
  district?: string
  city?: string
  state?: string
  plan_id?: string
}): Promise<PlatformTenantProvisioned> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível criar o tenant.')
  return res.json()
}

export async function fetchServicePlans(): Promise<ServicePlan[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/plans`)
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar os planos.')
  return res.json()
}

export async function updatePlatformTenantLifecycle(
  tenantId: string,
  status: TenantLifecycleStatus,
  reason: string,
): Promise<Tenant> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/lifecycle`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, reason }),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível alterar o estado do cliente.')
  return res.json()
}

export async function updatePlatformTenantProfile(
  tenantId: string,
  input: Record<string, unknown>,
): Promise<TenantProfile> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/profile`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar a ficha do cliente.')
  return res.json()
}

export async function updateTenantSubscription(
  tenantId: string,
  planId: string | undefined,
  status: SubscriptionStatus,
): Promise<TenantSubscription> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/subscription`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan_id: planId, status }),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o plano do cliente.')
  return res.json()
}

export async function fetchTenantCapabilityCatalog(tenantId: string): Promise<CapabilityCatalogItem[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/capabilities`)
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar as capacidades contratáveis.')
  return res.json()
}

export async function updateTenantCapability(
  tenantId: string,
  capabilityKey: string,
  input: { enabled: boolean; contract_limits?: Record<string, unknown>; reason: string },
): Promise<CapabilityCatalogItem[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/capabilities/${capabilityKey}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar a capacidade do cliente.')
  return res.json()
}

export async function createPlatformStore(tenantId: string, input: Record<string, unknown>): Promise<Store> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/stores`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível criar a filial.')
  return res.json()
}

export async function updatePlatformStore(tenantId: string, storeId: string, input: Record<string, unknown>): Promise<Store> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/stores/${storeId}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar a unidade.')
  return res.json()
}

export async function fetchPlatformTenantDetail(tenantId: string): Promise<PlatformTenantDetail> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}`)
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar o tenant.')
  return res.json()
}

export async function invitePlatformTenantUser(tenantId: string, input: {
  email: string
  full_name: string
  role?: string
  store_id?: string
}): Promise<{ access: PlatformTenantAccess; delivery_status: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/invitations`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível enviar o convite.')
  return res.json()
}

export async function updatePlatformTenantAccess(tenantId: string, membershipId: string, input: {
  role: string
  status: string
  store_id?: string
  reason: string
}): Promise<PlatformTenantAccess> {
  const res = await fetch(`${API_BASE_URL}/api/v1/identity/platform/tenants/${tenantId}/accesses/${membershipId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível alterar o acesso.')
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

export async function fetchSellableProducts(
  headers: Record<string, string>,
  options: { page?: number; pageSize?: number; search?: string; categoryId?: string; quickAccess?: boolean } = {}
): Promise<SellableProductPage> {
  const params = new URLSearchParams({
    page: String(options.page || 1),
    page_size: String(options.pageSize || 50)
  })
  if (options.search) params.set('search', options.search)
  if (options.categoryId) params.set('category_id', options.categoryId)
  if (options.quickAccess) params.set('quick_access', 'true')
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/sellable-products?${params}`, { headers })
  if (!res.ok) throw new Error('Erro ao carregar catálogo operacional')
  return res.json()
}

export async function setQuickAccess(headers: Record<string, string>, productId: string, position: number): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/quick-access/${productId}`, {
    method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ position })
  })
  if (!res.ok) throw new Error('Erro ao salvar acesso rápido')
}

export async function removeQuickAccess(headers: Record<string, string>, productId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/quick-access/${productId}`, { method: 'DELETE', headers })
  if (!res.ok) throw new Error('Erro ao remover acesso rápido')
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

export async function setMinimumStock(
  headers: Record<string, string>, storeId: string, productId: string, minimumStock: number
): Promise<InventoryBalance> {
  const res = await fetch(`${API_BASE_URL}/api/v1/inventory/minimum`, {
    method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ store_id: storeId, product_id: productId, minimum_stock: minimumStock })
  })
  if (!res.ok) throw new Error('Erro ao definir estoque mínimo')
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
