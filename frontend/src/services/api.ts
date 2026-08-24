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

export interface Customer {
  id: string
  tenant_id: string
  name: string
  cpf_cnpj?: string
  phone?: string
  email?: string
  created_at: string
}

export interface Receivable {
  id: string
  tenant_id: string
  store_id: string
  customer_id: string
  negotiation_id?: string
  sale_id?: string
  agreement_id?: string
  agreement_installment_number?: number
  origin_receivable_id?: string
  status: 'OPEN' | 'PARTIALLY_PAID' | 'PAID' | 'OVERDUE' | 'REVERSED' | 'RENEGOTIATED'
  principal_amount: number
  paid_amount: number
  balance: number
  issued_at: string
  due_at: string
  version: number
  reversed_at?: string
}

export interface CreditPolicyProjection {
  policy: {
    id: string
    customer_id: string
    status: 'ACTIVE' | 'BLOCKED'
    credit_limit: number
    terms_days: number
    allow_overdue: boolean
    version: number
    updated_at: string
  }
  exposure: number
  available: number
}

export interface ReceivableReceipt {
  id: string
  customer_id: string
  status: 'PENDING' | 'CONFIRMED' | 'FAILED' | 'REVERSED'
  method: string
  amount: number
  reason: string
  confirmed_at?: string
  created_at: string
}

export interface ReceivableAgreement {
  id: string
  customer_id: string
  status: 'ACTIVE' | 'COMPLETED' | 'DEFAULTED' | 'CANCELED'
  original_principal: number
  agreement_total: number
  installment_count: number
  reason: string
  created_at: string
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
  register_id?: string
  customer_id?: string
  seller_id?: string
  operation_mode: 'COUNTER' | 'TAKEAWAY'
  operator_action_count: number
  last_activity_at: string
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

export interface OrderItem {
  id: string
  tenant_id: string
  order_id: string
  product_id: string
  product_name: string
  sku: string
  unit_snapshot: string
  unit_price: number
  quantity: number
  modifier_snapshot: Array<Record<string, unknown>>
  notes?: string
  production_destination?: string
  production_state: 'NOT_REQUIRED' | 'PENDING' | 'IN_PREPARATION' | 'READY' | 'DELIVERED' | 'CANCELED'
  production_version: number
  status: 'ACTIVE' | 'CANCELED'
  added_by: string
  canceled_by?: string
  cancellation_reason?: string
  canceled_at?: string
  created_at: string
  updated_at: string
}

export interface Order {
  id: string
  tenant_id: string
  store_id: string
  register_id?: string
  customer_id?: string
  table_id?: string
  table_session_id?: string
  sale_id?: string
  channel_id?: string
  origin: 'POS' | 'API' | 'SALES_CHANNEL'
  fulfillment: 'COUNTER' | 'TAKEAWAY' | 'DINE_IN' | 'DELIVERY'
  status: 'OPEN' | 'SUBMITTED' | 'CLOSED' | 'CANCELED'
  idempotency_key: string
  external_reference?: string
  opened_by: string
  notes?: string
  created_at: string
  updated_at: string
  items: OrderItem[]
}

export interface ServiceTable {
  id: string
  tenant_id: string
  store_id: string
  code: string
  name: string
  capacity: number
  area_id?: string
  area?: string
  sort_order: number
  blocking_reason?: string
  status: 'AVAILABLE' | 'OCCUPIED' | 'RESERVED' | 'BLOCKED'
  version: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ServiceTableProjection extends ServiceTable {
  active_session_id?: string
  active_session_status?: TableSession['status']
  active_session_label?: string
  order_count: number
  item_count: number
  consolidated_total: number
  active_reservation?: TableReservation
}

export interface ServiceArea {
  id: string
  tenant_id: string
  store_id: string
  code: string
  name: string
  kind: 'INTERNAL' | 'EXTERNAL' | 'COUNTER' | 'TAKEAWAY' | 'FLEXIBLE'
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface TableReservation {
  id: string
  tenant_id: string
  store_id: string
  service_table_id: string
  customer_name: string
  customer_phone?: string
  party_size: number
  reserved_for: string
  duration_minutes: number
  notes?: string
  status: 'BOOKED' | 'SEATED' | 'COMPLETED' | 'CANCELED' | 'NO_SHOW'
  created_by: string
  created_at: string
  updated_at: string
}

export interface TableSessionEvent {
  id: string
  tenant_id: string
  table_session_id: string
  event_type: string
  actor_id: string
  from_status?: string
  to_status?: string
  reason?: string
  payload: Record<string, unknown>
  created_at: string
}

export interface TableSession {
  id: string
  tenant_id: string
  store_id: string
  service_table_id?: string
  kind: 'TABLE' | 'INDIVIDUAL_TAB'
  status: 'OPEN' | 'IN_SERVICE' | 'PARTIALLY_PAID' | 'CLOSING' | 'CLOSED' | 'CANCELED'
  display_label: string
  customer_id?: string
  attendant_id: string
  opened_by: string
  closed_by?: string
  close_reason?: string
  version: number
  opened_at: string
  updated_at: string
  closed_at?: string
  service_table?: ServiceTable
  orders: Order[]
  events: TableSessionEvent[]
  order_count: number
  active_item_count: number
  consolidated_total: number
}

export interface TableSessionSummary {
  id: string
  service_table_id?: string
  kind: TableSession['kind']
  status: TableSession['status']
  display_label: string
  version: number
  opened_at: string
  updated_at: string
  order_count: number
  item_count: number
  consolidated_total: number
}

export interface TransferRecord {
  id: string; transfer_type: 'ITEM' | 'SESSION_MERGE'; source_session_id: string; destination_session_id: string
  source_order_item_id?: string; derived_order_item_id?: string; quantity?: number; unit_price_snapshot?: number
  source_version_before: number; destination_version_before: number; reason: string
  production_compensation_required: boolean; created_at: string
}

export type CheckoutNegotiationStatus = 'OPEN' | 'PARTIALLY_COVERED' | 'COVERED' | 'INVALIDATED' | 'FINALIZED' | 'CANCELED'
export type PaymentIntentStatus = 'PENDING' | 'PROCESSING' | 'CONFIRMED' | 'FAILED' | 'CANCELED'
export type NegotiationPaymentMethod = 'CASH' | 'PIX' | 'CREDIT_CARD' | 'DEBIT_CARD' | 'STORE_CREDIT'

export interface NegotiationPaymentIntent {
  id: string
  method: NegotiationPaymentMethod
  status: PaymentIntentStatus
  amount: number
  tendered_amount?: number
  change_amount: number
  provider: string
  failure_code?: string
  failure_reason?: string
  created_at: string
  confirmed_at?: string
  failed_at?: string
}

export interface CheckoutNegotiation {
  id: string
  tenant_id: string
  store_id: string
  table_session_id?: string
  sale_id?: string
  status: CheckoutNegotiationStatus
  subtotal: number
  discount_total: number
  surcharge_total: number
  tax_total: number
  total_due: number
  confirmed_amount: number
  processing_amount: number
  failed_amount: number
  remaining_amount: number
  source_version: number
  version: number
  created_at: string
  updated_at: string
  finalized_at?: string
  orders: Array<{ id: string; order_id: string; amount_snapshot: number }>
  intents: NegotiationPaymentIntent[]
  allocations: Array<{ id: string; payment_intent_id: string; order_id?: string; order_item_id?: string; amount: number }>
}

export interface PaymentProviderConfiguration {
  id: string
  tenant_id: string
  store_id: string
  provider_code: string
  adapter_version: string
  status: 'NOT_CONFIGURED' | 'ACTIVE' | 'SUSPENDED'
  timeout_seconds: number
  created_at: string
  updated_at: string
}

export interface TefBridgeTerminal {
  id: string
  tenant_id: string
  store_id: string
  register_id: string
  provider_configuration_id: string
  terminal_code: string
  bridge_version?: string
  protocol_version: string
  status: 'UNPAIRED' | 'OFFLINE' | 'ONLINE' | 'DEGRADED'
  last_heartbeat_at?: string
  last_operation_at?: string
  last_error_code?: string
  last_error_message?: string
}

export interface ProviderTransaction {
  id: string
  payment_intent_id: string
  provider_code: string
  status: 'CREATED' | 'PROCESSING' | 'CONFIRMED' | 'FAILED' | 'CANCELED' | 'UNKNOWN' | 'REFUNDED'
  external_transaction_id?: string
  nsu?: string
  authorization_code?: string
  acquirer?: string
  card_brand?: string
  correlation_id: string
  sanitized_payload: Record<string, unknown>
  failure_code?: string
  failure_reason?: string
}

export interface MerchantConnection {
  id: string
  tenant_id: string
  store_id: string
  channel_id: string
  provider_code: string
  adapter_version: string
  merchant_external_id: string
  status: 'NOT_CONNECTED' | 'VALIDATING' | 'CONNECTED' | 'DEGRADED' | 'SUSPENDED'
  last_validated_at?: string
  last_event_at?: string
  last_error_code?: string
  last_error_message?: string
  created_at: string
  updated_at: string
}

export interface ChannelInboxEvent {
  id: string
  merchant_connection_id: string
  provider_event_id: string
  external_order_id: string
  event_type: string
  status: 'RECEIVED' | 'NORMALIZED' | 'PROCESSED' | 'QUARANTINED' | 'DUPLICATE'
  order_id?: string
  quarantine_code?: string
  quarantine_reason?: string
  received_at: string
  acknowledged_at?: string
  processed_at?: string
}

export interface ChannelCatalogOffer { id:string; merchant_connection_id:string; product_id:string; price:number; available:boolean; stock_quantity?:number; desired_version:number; published_version:number; last_publication_status:'PENDING'|'SUCCEEDED'|'FAILED'; updated_at:string }
export interface ChannelPublicationBatch { id:string; merchant_connection_id:string; status:'PENDING'|'PROCESSING'|'PARTIAL'|'SUCCEEDED'|'FAILED'; created_at:string; updated_at:string }
export interface MarketplaceSettlement { id:string; merchant_connection_id:string; provider_document_ref:string; external_order_id?:string; order_id?:string; competence_date:string; gross_amount:number; commission_amount:number; fee_amount:number; promotion_amount:number; adjustment_amount:number; expected_net_amount:number; paid_amount:number; status:'PENDING'|'PARTIAL'|'PAID'|'DIVERGENT'; updated_at:string }

export interface ProductionPoint {
  id: string
  tenant_id: string
  store_id: string
  code: string
  name: string
  point_type: 'KITCHEN' | 'BAR' | 'PANTRY' | 'EXPEDITION' | 'PRINTER'
  is_active: boolean
  printer_configuration_ref?: string
  created_at: string
  updated_at: string
}

export interface ProductionRoutingRule {
  id: string
  tenant_id: string
  store_id: string
  production_point_id: string
  product_id?: string
  modifier_id?: string
  fulfillment?: Order['fulfillment']
  priority: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface OperationalDevice {
  id: string
  tenant_id: string
  store_id: string
  code: string
  name: string
  device_type: 'POS' | 'KDS' | 'PRINTER'
  status: 'ACTIVE' | 'PAUSED' | 'REVOKED'
  register_id?: string
  production_point_id?: string
  configuration_ref?: string
  authorization_version: number
  authorized_at?: string
  authorized_by?: string
  authorization_expires_at?: string
  last_seen_at?: string
  created_at: string
  updated_at: string
}

export interface ProductionTicketItem {
  id: string
  order_item_id: string
  item_version: number
  operation: 'CREATE' | 'UPDATE' | 'CANCEL'
  quantity: number
  product_name_snapshot: string
  modifier_snapshot: Array<Record<string, unknown>>
  notes_snapshot?: string
  created_at: string
}

export interface ProductionTicketProjection {
  ticket: {
    id: string
    tenant_id: string
    store_id: string
    order_id: string
    production_point_id: string
    status: 'NEW' | 'ACCEPTED' | 'PREPARING' | 'READY' | 'DELIVERED' | 'CANCELED'
    priority: number
    version: number
    created_at: string
    updated_at: string
  }
  point: ProductionPoint
  items: ProductionTicketItem[]
}

export interface Register {
  id: string
  tenant_id: string
  store_id: string
  name: string
  code: string
  is_active: boolean
}

export interface CashSession {
  id: string
  tenant_id: string
  store_id: string
  register_id: string
  operator_id: string
  status: 'OPEN' | 'CLOSING' | 'CLOSED'
  opening_balance: number
  closing_balance?: number
  expected_balance?: number
  variance?: number
  version: number
  blind_count: boolean
  divergence_reason?: string
  opened_at: string
  closed_at?: string
}

export interface CashMovement {
  id: string
  tenant_id: string
  store_id: string
  cash_session_id: string
  actor_id: string
  movement_type: 'OPENING' | 'SALE_PAYMENT' | 'RECEIVABLE_PAYMENT' | 'BLEED' | 'REINFORCEMENT' | 'REFUND' | 'CLOSING'
  amount: number
  notes?: string
  source_type?: string
  source_id?: string
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
  attempt_count: number
  last_attempt_at?: string
}

export interface FinancialReconciliation {
  id: string
  tenant_id: string
  store_id: string
  sale_id: string
  negotiation_id?: string
  fiscal_document_id?: string
  cash_session_id?: string
  expected_amount: number
  payment_total: number
  receivable_total: number
  provider_reported_total?: number
  difference: number
  status: 'MATCHED' | 'DIFFERENCE'
  provider?: string
  provider_reference?: string
  version: number
  checked_at: string
}

export interface ApiHealth {
  status: string
  service: string
  timestamp: string
}

export interface EffectiveAccess {
  capabilities: Record<string, { key: string; version: string; scope: string; configuration: Record<string, unknown>; inherited: boolean }>
  permissions: string[]
  contributions: Array<{
    id: string
    capability_key?: string
    surface: 'MANAGEMENT_NAV' | 'HEALTH' | 'REPORTING' | string
    contribution_key: string
    label: string
    group_key?: string
    route?: string
    permission_key?: string
    implementation_key: string
    sort_order: number
    metadata_json: Record<string, unknown>
  }>
  profile?: { key: string; version: string }
  context: { tenant_id: string; store_id?: string; membership_id?: string }
}

export interface TeamMember {
  membership_id: string
  user_id: string
  full_name: string
  email?: string
  access_mode: 'EMAIL' | 'PIN'
  employee_code?: string
  employee_id?: string
  role: string
  status: string
  store_id?: string
  store_name?: string
}

export type EmployeeStatus = 'ACTIVE' | 'ON_LEAVE' | 'INACTIVE' | 'TERMINATED'

export interface Employee {
  id: string
  tenant_id: string
  user_id?: string
  employee_number: string
  full_name: string
  preferred_name?: string
  tax_id?: string
  email?: string
  phone?: string
  job_title?: string
  department?: string
  hire_date?: string
  home_store_id?: string
  postal_code?: string
  street?: string
  street_number?: string
  address_complement?: string
  district?: string
  city?: string
  state?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  status: EmployeeStatus
  notes?: string
  created_at: string
  updated_at: string
}

export type EmployeeInput = Omit<Employee, 'id' | 'tenant_id' | 'user_id' | 'created_at' | 'updated_at'>

export interface ManagementOverview {
  generated_at: string
  projection_lag_seconds: number
  projection_version: number
  source_watermark?: string
  revenue_today: number
  revenue_30d: number
  sales_today: number
  sales_30d: number
  average_ticket_30d: number
  open_sales: number
  confirmed_receipts_30d: number
  refunds_30d: number
  receivables_issued_30d: number
  receivables_settled_30d: number
  marketplace_settled_30d: number
  table_sessions_closed_30d: number
  table_average_minutes_30d: number
  production_tickets_30d: number
  production_average_minutes_30d: number
  transfers_30d: number
  stockout_products: number
  active_cash_sessions: number
  products: number
  customers: number
  active_team_members: number
  daily_revenue: Array<{ date: string; revenue: number; sales: number }>
  alerts: string[]
  formulas: Record<string, string>
}

export interface BiDrilldown {
  metric: string
  competence_date: string
  total: number
  offset: number
  limit: number
  items: Array<{ source_type: string; source_id: string; occurred_at: string; amount: number }>
}

export interface AuthMe {
  mode: 'authenticated' | 'local-bypass'
  user: { id: string; email?: string; full_name: string; is_active: boolean } | null
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
  status: 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY' | 'UNKNOWN' | 'NOT_CONFIGURED' | 'UNINSTRUMENTED'
  latency_ms?: number
  details: Record<string, unknown>
}

export interface PlatformSystemHealth {
  checked_at: string
  status: 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY'
  components: HealthComponent[]
  totals: Record<string, number>
}

export interface ControlLead {
  id: string
  company_name: string
  contact_name: string
  email?: string
  phone?: string
  source?: string
  status: 'NEW' | 'QUALIFIED' | 'ONBOARDING' | 'CONVERTED' | 'LOST'
  converted_tenant_id?: string
  created_at: string
}

export interface ControlHealthComponent {
  key: string
  label: string
  status: string
  last_seen_at?: string
  age_seconds?: number
  details: Record<string, unknown>
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

export async function fetchEmployees(headers: Record<string, string>): Promise<Employee[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/team/employees`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar os funcionários.')
  return res.json()
}

export async function createEmployee(headers: Record<string, string>, input: EmployeeInput): Promise<Employee> {
  const res = await fetch(`${API_BASE_URL}/api/v1/team/employees`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível cadastrar o funcionário.')
  return res.json()
}

export async function updateEmployee(headers: Record<string, string>, employeeId: string, input: EmployeeInput): Promise<Employee> {
  const res = await fetch(`${API_BASE_URL}/api/v1/team/employees/${employeeId}`, {
    method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o funcionário.')
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

export async function createOperationalMember(
  headers: Record<string, string>,
  input: { employee_id: string; role: 'SUPERVISOR' | 'CASHIER' | 'OPERATOR'; store_id: string; employee_code: string; pin: string },
): Promise<TeamMember> {
  const res = await fetch(`${API_BASE_URL}/api/v1/team/operational`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível cadastrar o acesso por PIN.')
  return res.json()
}

export async function resetOperationalPin(
  headers: Record<string, string>, membershipId: string, input: { pin: string; reason: string },
): Promise<TeamMember> {
  const res = await fetch(`${API_BASE_URL}/api/v1/team/${membershipId}/pin`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível redefinir o PIN.')
  return res.json()
}

export interface OperationalSession {
  access_token: string
  token_type: string
  expires_at: string
  user_id: string
  membership_id: string
  full_name: string
  role: 'SUPERVISOR' | 'CASHIER' | 'OPERATOR'
  store_id: string
  register_id?: string
}

export interface TerminalAuthorizationContext {
  device_id: string
  device_name: string
  tenant_id: string
  tenant_name: string
  store_id: string
  store_name: string
  register_id: string
  register_name: string
}

export interface TerminalAuthorization extends TerminalAuthorizationContext {
  terminal_token: string
  expires_at: string
}

export async function authorizeOperationalTerminal(
  headers: Record<string, string>, deviceId: string,
): Promise<TerminalAuthorization> {
  const res = await fetch(`${API_BASE_URL}/api/v1/operational-access/terminals/${deviceId}/authorize`, {
    method: 'POST', headers,
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível autorizar este terminal.')
  return res.json()
}

export async function resolveOperationalTerminal(terminalToken: string): Promise<TerminalAuthorizationContext> {
  const res = await fetch(`${API_BASE_URL}/api/v1/operational-access/terminal/status`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ terminal_token: terminalToken }),
  })
  if (!res.ok) throw await apiError(res, 'Este terminal precisa ser autorizado por um gestor.')
  return res.json()
}

export async function loginOperationalTerminal(
  terminalToken: string, input: { employee_code: string; pin: string },
): Promise<OperationalSession> {
  const res = await fetch(`${API_BASE_URL}/api/v1/operational-access/terminal/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ terminal_token: terminalToken, ...input }),
  })
  if (!res.ok) throw await apiError(res, 'Código ou PIN inválido para este terminal.')
  return res.json()
}

export async function endOperationalSession(accessToken: string): Promise<void> {
  const claims = JSON.parse(atob(accessToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))) as {
    tenant_id: string; store_id: string
  }
  const res = await fetch(`${API_BASE_URL}/api/v1/operational-access/session/end`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
      'X-Tenant-ID': claims.tenant_id,
      'X-Store-ID': claims.store_id,
    },
    body: JSON.stringify({ reason: 'Encerramento voluntário do turno' }),
  })
  if (!res.ok && res.status !== 409) throw await apiError(res, 'Não foi possível encerrar o turno operacional.')
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

export async function fetchManagementOverview(
  headers: Record<string, string>, filters: { days?: number; register_id?: string; operator_id?: string; channel?: string } = {}
): Promise<ManagementOverview> {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, String(value)) })
  let url = `${API_BASE_URL}/api/v1/management/overview`
  if (params.toString()) url += `?${params.toString()}`
  const res = await fetch(url, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar os indicadores gerenciais.')
  return res.json()
}

export async function refreshBiProjection(
  headers: Record<string, string>, actorId: string, startDate?: string, endDate?: string
): Promise<{ projected_at: string; version: number }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/management/bi/refresh`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, start_date: startDate, end_date: endDate })
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar a projeção gerencial.')
  return res.json()
}

export async function fetchBiDrilldown(
  headers: Record<string, string>, metric: string, competenceDate: string, offset = 0, limit = 50
): Promise<BiDrilldown> {
  const params = new URLSearchParams({ metric, competence_date: competenceDate, offset: String(offset), limit: String(limit) })
  const res = await fetch(`${API_BASE_URL}/api/v1/management/bi/drilldown?${params.toString()}`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível rastrear as fontes desta métrica.')
  return res.json()
}

export async function fetchCustomers(headers: Record<string, string>): Promise<Customer[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/customers`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar os clientes.')
  return res.json()
}

export async function createCustomer(
  headers: Record<string, string>, input: { name: string; cpf_cnpj?: string; phone?: string; email?: string },
): Promise<Customer> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/customers`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível cadastrar o cliente.')
  return res.json()
}

export async function updateCustomer(
  headers: Record<string, string>, customerId: string,
  input: { name?: string; cpf_cnpj?: string; phone?: string; email?: string },
): Promise<Customer> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/customers/${customerId}`, {
    method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o cliente.')
  return res.json()
}

export async function fetchReceivables(headers: Record<string, string>): Promise<Receivable[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/receivables`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar as contas a receber.')
  return res.json()
}

export async function fetchCreditPolicy(headers: Record<string, string>, customerId: string): Promise<CreditPolicyProjection> {
  const res = await fetch(`${API_BASE_URL}/api/v1/receivables/customers/${customerId}/policy`, { headers })
  if (!res.ok) throw await apiError(res, 'Política de crédito ainda não configurada.')
  return res.json()
}

export async function saveCreditPolicy(
  headers: Record<string, string>, customerId: string,
  input: { credit_limit: number; terms_days: number; allow_overdue: boolean; status: 'ACTIVE' | 'BLOCKED'; expected_version?: number },
): Promise<CreditPolicyProjection> {
  const res = await fetch(`${API_BASE_URL}/api/v1/receivables/customers/${customerId}/policy`, {
    method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível salvar a política de crédito.')
  return res.json()
}

export async function settleReceivables(
  headers: Record<string, string>, input: {
    allocations: Array<{ receivable_id: string; expected_version: number; principal_amount: number; interest_amount?: number; fine_amount?: number; discount_amount?: number; abatement_amount?: number }>
    method: 'CASH' | 'PIX' | 'CREDIT_CARD' | 'DEBIT_CARD'; cash_session_id?: string; provider_reference?: string; reason: string
  },
): Promise<ReceivableReceipt> {
  const res = await fetch(`${API_BASE_URL}/api/v1/receivables/settlements`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível confirmar o recebimento.')
  return res.json()
}

export async function createReceivableAgreement(
  headers: Record<string, string>, input: {
    receivable_ids: string[]; installment_count: number; first_due_at: string; interval_days: number;
    interest_amount: number; fine_amount: number; discount_amount: number; reason: string
  },
): Promise<ReceivableAgreement> {
  const res = await fetch(`${API_BASE_URL}/api/v1/receivables/agreements`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify(input),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível criar o acordo.')
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

export async function fetchControlLeads(): Promise<ControlLead[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/control/leads`)
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar o funil comercial.')
  return res.json()
}

export async function fetchControlHealth(): Promise<{ checked_at: string; components: ControlHealthComponent[] }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/control/health/components`)
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar a instrumentação do Control.')
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

export async function updateCategory(headers: Record<string, string>, categoryId: string, data: { name?: string; slug?: string; parent_id?: string; is_active?: boolean }): Promise<Category> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/categories/${categoryId}`, { method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar a categoria.')
  return res.json()
}

export async function updateProduct(
  headers: Record<string, string>, productId: string,
  data: { name?: string; sku?: string; barcode?: string; category_id?: string; is_active?: boolean; available_for_sale?: boolean },
): Promise<Product> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/products/${productId}`, {
    method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o produto.')
  return res.json()
}

export async function archiveCategory(headers: Record<string, string>, categoryId: string): Promise<Category> {
  const res = await fetch(`${API_BASE_URL}/api/v1/catalog/categories/${categoryId}`, { method: 'DELETE', headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível arquivar a categoria.')
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

export async function createSale(
  headers: Record<string, string>, storeId: string, registerId?: string,
  sellerId?: string, operationMode: 'COUNTER' | 'TAKEAWAY' = 'COUNTER',
  customerId?: string, notes?: string
): Promise<Sale> {
  const res = await fetch(`${API_BASE_URL}/api/v1/sales`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      store_id: storeId, register_id: registerId, seller_id: sellerId,
      operation_mode: operationMode, customer_id: customerId, notes
    })
  })
  if (!res.ok) throw new Error('Erro ao criar venda')
  return res.json()
}

export async function fetchActiveSale(
  headers: Record<string, string>, storeId: string, registerId: string, sellerId: string
): Promise<Sale | null> {
  const params = new URLSearchParams({ store_id: storeId, register_id: registerId, seller_id: sellerId })
  const res = await fetch(`${API_BASE_URL}/api/v1/sales/active?${params}`, { headers })
  if (!res.ok) throw new Error('Erro ao recuperar operação em andamento')
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
// ORDER AGGREGATE ENDPOINTS
// ----------------------------------------------------------------------

export async function createOrder(
  headers: Record<string, string>, idempotencyKey: string,
  data: {
    store_id: string; register_id?: string; customer_id?: string; table_id?: string; table_session_id?: string;
    sale_id?: string; channel_id?: string; origin?: Order['origin'];
    fulfillment?: Order['fulfillment']; external_reference?: string; actor_id?: string; notes?: string
  }
): Promise<Order> {
  const res = await fetch(`${API_BASE_URL}/api/v1/orders`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(data)
  })
  if (!res.ok) throw new Error('Erro ao abrir pedido')
  return res.json()
}

// ----------------------------------------------------------------------
// TABLE SERVICE & TABS
// ----------------------------------------------------------------------

export async function fetchServiceTables(headers: Record<string, string>): Promise<ServiceTableProjection[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar mesas e comandas.')
  return res.json()
}

export async function createServiceTable(
  headers: Record<string, string>, idempotencyKey: string,
  data: { store_id: string; code: string; name: string; capacity: number; area?: string; area_id?: string; sort_order?: number; actor_id?: string },
): Promise<ServiceTable> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível cadastrar a mesa.')
  return res.json()
}

export async function fetchServiceAreas(headers: Record<string, string>): Promise<ServiceArea[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/areas`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar os ambientes.')
  return res.json()
}

export async function createServiceArea(headers: Record<string, string>, data: {
  store_id: string; code: string; name: string; kind: ServiceArea['kind']; sort_order?: number; actor_id?: string
}): Promise<ServiceArea> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/areas`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível cadastrar o ambiente.')
  return res.json()
}

export async function updateServiceArea(headers: Record<string, string>, areaId: string, data: {
  name?: string; kind?: ServiceArea['kind']; sort_order?: number; is_active?: boolean; reason: string; actor_id?: string
}): Promise<ServiceArea> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/areas/${areaId}`, { method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o ambiente.')
  return res.json()
}

export async function updateServiceTable(headers: Record<string, string>, tableId: string, data: {
  expected_version: number; name?: string; capacity?: number; area_id?: string; sort_order?: number; is_active?: boolean; reason: string; actor_id?: string
}): Promise<ServiceTable> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/${tableId}`, { method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível configurar a mesa.')
  return res.json()
}

export async function setServiceTableState(headers: Record<string, string>, tableId: string, data: {
  expected_version: number; target: 'AVAILABLE' | 'BLOCKED'; reason: string; actor_id?: string
}): Promise<ServiceTable> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/${tableId}/state`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível alterar a situação da mesa.')
  return res.json()
}

export async function fetchTableReservations(headers: Record<string, string>): Promise<TableReservation[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/reservations`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar as reservas.')
  return res.json()
}

export async function createTableReservation(headers: Record<string, string>, tableId: string, idempotencyKey: string, data: {
  customer_name: string; customer_phone?: string; party_size: number; reserved_for: string; duration_minutes: number; notes?: string; actor_id?: string
}): Promise<TableReservation> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/${tableId}/reservations`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível registrar a reserva.')
  return res.json()
}

export async function transitionTableReservation(headers: Record<string, string>, reservationId: string, data: {
  target: 'CANCELED' | 'NO_SHOW'; reason: string; actor_id?: string
}): Promise<TableReservation> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/reservations/${reservationId}/transition`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar a reserva.')
  return res.json()
}

export async function openTableSession(
  headers: Record<string, string>, idempotencyKey: string,
  data: { store_id: string; service_table_id?: string; display_label?: string; customer_id?: string; reservation_id?: string; attendant_id?: string; actor_id?: string },
): Promise<TableSession> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/sessions`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível abrir a mesa ou comanda.')
  return res.json()
}

export async function getTableSession(headers: Record<string, string>, sessionId: string): Promise<TableSession> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/sessions/${sessionId}`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível recuperar a sessão de atendimento.')
  return res.json()
}

export async function fetchActiveTableSessions(headers: Record<string, string>): Promise<TableSessionSummary[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/sessions`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar as comandas ativas.')
  return res.json()
}

export async function transferOrderItem(headers: Record<string, string>, idempotencyKey: string, data: {
  source_session_id: string; destination_session_id: string; order_item_id: string; quantity: number
  expected_source_version: number; expected_destination_version: number; reason: string; actor_id: string
}): Promise<TransferRecord> {
  const res=await fetch(`${API_BASE_URL}/api/v1/transfers/items`,{method:'POST',headers:{...headers,'Content-Type':'application/json','Idempotency-Key':idempotencyKey},body:JSON.stringify(data)})
  if(!res.ok)throw await apiError(res,'Não foi possível transferir o item.')
  return res.json()
}

export async function addTableSessionOrder(
  headers: Record<string, string>, sessionId: string, idempotencyKey: string,
  data: { display_reference?: string; customer_id?: string; actor_id?: string },
): Promise<Order> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/sessions/${sessionId}/orders`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível abrir outra comanda.')
  return res.json()
}

export async function closeEmptyTableSession(
  headers: Record<string, string>, sessionId: string, idempotencyKey: string,
  data: { expected_version: number; reason: string; actor_id?: string },
): Promise<TableSession> {
  const res = await fetch(`${API_BASE_URL}/api/v1/tables/sessions/${sessionId}/close`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível encerrar a sessão.')
  return res.json()
}

// ----------------------------------------------------------------------
// CHECKOUT NEGOTIATION & PAYMENT ORCHESTRATOR
// ----------------------------------------------------------------------

export async function openCheckoutNegotiation(
  headers: Record<string, string>, idempotencyKey: string,
  data: { store_id: string; table_session_id?: string; order_ids?: string[]; actor_id?: string },
): Promise<CheckoutNegotiation> {
  const res = await fetch(`${API_BASE_URL}/api/v1/negotiations`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível abrir a negociação da conta.')
  return res.json()
}

export async function getCheckoutNegotiation(headers: Record<string, string>, negotiationId: string): Promise<CheckoutNegotiation> {
  const res = await fetch(`${API_BASE_URL}/api/v1/negotiations/${negotiationId}`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar a negociação.')
  return res.json()
}

export async function createNegotiationPaymentIntent(
  headers: Record<string, string>, negotiationId: string, idempotencyKey: string,
  data: { method: NegotiationPaymentMethod; amount: number; cash_session_id?: string; tendered_amount?: number; allocations?: Array<{ amount: number; order_id?: string; order_item_id?: string }>; actor_id?: string },
): Promise<CheckoutNegotiation> {
  const res = await fetch(`${API_BASE_URL}/api/v1/negotiations/${negotiationId}/intents`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível registrar a parcela.')
  return res.json()
}

export async function confirmNegotiationPaymentIntent(
  headers: Record<string, string>, intentId: string, idempotencyKey: string, actorId?: string,
): Promise<CheckoutNegotiation> {
  const res = await fetch(`${API_BASE_URL}/api/v1/negotiations/intents/${intentId}/confirm`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ actor_id: actorId }),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível confirmar a parcela.')
  return res.json()
}

export async function finalizeCheckoutNegotiation(
  headers: Record<string, string>, negotiationId: string, idempotencyKey: string, expectedVersion: number, actorId?: string,
): Promise<CheckoutNegotiation> {
  const res = await fetch(`${API_BASE_URL}/api/v1/negotiations/${negotiationId}/finalize`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ expected_version: expectedVersion, actor_id: actorId }),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível finalizar a conta.')
  return res.json()
}

export async function fetchPaymentProviderConfigurations(headers: Record<string, string>): Promise<PaymentProviderConfiguration[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/providers/configurations`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível consultar os providers.')
  return res.json()
}

export async function fetchTefBridgeTerminals(headers: Record<string, string>, registerId?: string): Promise<TefBridgeTerminal[]> {
  const suffix = registerId ? `?register_id=${registerId}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/providers/bridge/terminals${suffix}`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível consultar o Dashem TEF Bridge.')
  return res.json()
}

export async function executeProviderTransaction(
  headers: Record<string, string>, idempotencyKey: string,
  data: { payment_intent_id: string; provider_configuration_id: string; bridge_terminal_id: string; actor_id?: string },
): Promise<{ transaction: ProviderTransaction; negotiation: CheckoutNegotiation }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/providers/transactions`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey, 'X-Correlation-ID': crypto.randomUUID() }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível iniciar a transação no provider.')
  return res.json()
}

export async function fetchMerchantConnections(headers: Record<string, string>): Promise<MerchantConnection[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/channels/connections`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar as conexões de canais.')
  return res.json()
}

export async function createMerchantConnection(
  headers: Record<string, string>, idempotencyKey: string,
  data: { store_id: string; provider_code: string; merchant_external_id: string; channel_name: string; credentials_ref?: string; actor_id?: string },
): Promise<{ connection: MerchantConnection; webhook_secret: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/channels/connections`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível cadastrar a conexão.')
  return res.json()
}

export async function validateMerchantConnection(headers: Record<string, string>, connectionId: string, idempotencyKey: string, actorId?: string): Promise<MerchantConnection> {
  const res = await fetch(`${API_BASE_URL}/api/v1/channels/connections/${connectionId}/validate`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ actor_id: actorId }),
  })
  if (!res.ok) throw await apiError(res, 'Não foi possível validar a conexão externa.')
  return res.json()
}

export async function fetchChannelInbox(headers: Record<string, string>): Promise<ChannelInboxEvent[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/channels/inbox`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar a caixa de entrada externa.')
  return res.json()
}

export async function fetchChannelCatalogState(headers:Record<string,string>):Promise<{offers:ChannelCatalogOffer[];batches:ChannelPublicationBatch[]}>{const res=await fetch(`${API_BASE_URL}/api/v1/channel-catalog/catalog`,{headers});if(!res.ok)throw await apiError(res,'Não foi possível carregar o catálogo por canal.');return res.json()}
export async function fetchMarketplaceSettlements(headers:Record<string,string>):Promise<MarketplaceSettlement[]>{const res=await fetch(`${API_BASE_URL}/api/v1/channel-catalog/settlements`,{headers});if(!res.ok)throw await apiError(res,'Não foi possível carregar os repasses.');return res.json()}

export async function fetchProductionPoints(headers: Record<string, string>): Promise<ProductionPoint[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/production/points`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar os pontos de produção.')
  return res.json()
}

export async function createProductionPoint(headers: Record<string, string>, idempotencyKey: string, data: {
  store_id: string; code: string; name: string; point_type: ProductionPoint['point_type']; printer_configuration_ref?: string; actor_id?: string
}): Promise<ProductionPoint> {
  const res = await fetch(`${API_BASE_URL}/api/v1/production/points`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível cadastrar o ponto de produção.')
  return res.json()
}

export async function updateProductionPoint(headers: Record<string, string>, pointId: string, data: {
  name?: string; is_active?: boolean; printer_configuration_ref?: string; actor_id?: string; reason: string
}): Promise<ProductionPoint> {
  const res = await fetch(`${API_BASE_URL}/api/v1/production/points/${pointId}`, { method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o ponto de produção.')
  return res.json()
}

export async function fetchProductionRules(headers: Record<string, string>): Promise<ProductionRoutingRule[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/production/rules`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar as regras de produção.')
  return res.json()
}

export async function createProductionRule(headers: Record<string, string>, idempotencyKey: string, data: {
  production_point_id: string; product_id?: string; modifier_id?: string; fulfillment?: Order['fulfillment']; priority?: number; actor_id?: string
}): Promise<ProductionRoutingRule> {
  const res = await fetch(`${API_BASE_URL}/api/v1/production/rules`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível criar a regra de produção.')
  return res.json()
}

export async function fetchOperationalDevices(headers: Record<string, string>): Promise<OperationalDevice[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/devices`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar os dispositivos.')
  return res.json()
}

export async function createOperationalDevice(headers: Record<string, string>, data: {
  store_id: string; code: string; name: string; device_type: OperationalDevice['device_type']; register_id?: string; production_point_id?: string; point_type?: ProductionPoint['point_type']; configuration_ref?: string; actor_id?: string
}): Promise<OperationalDevice> {
  const res = await fetch(`${API_BASE_URL}/api/v1/devices`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível cadastrar o dispositivo.')
  return res.json()
}

export async function updateOperationalDevice(headers: Record<string, string>, deviceId: string, data: {
  name?: string; status?: OperationalDevice['status']; configuration_ref?: string; reason: string; actor_id?: string
}): Promise<OperationalDevice> {
  const res = await fetch(`${API_BASE_URL}/api/v1/devices/${deviceId}`, { method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o dispositivo.')
  return res.json()
}

export async function fetchProductionTickets(headers: Record<string, string>, pointId?: string): Promise<ProductionTicketProjection[]> {
  const suffix = pointId ? `?point_id=${pointId}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/production/tickets${suffix}`, { headers })
  if (!res.ok) throw await apiError(res, 'Não foi possível carregar a fila de produção.')
  return res.json()
}

export async function transitionProductionTicket(
  headers: Record<string, string>, ticketId: string, idempotencyKey: string,
  data: { target: ProductionTicketProjection['ticket']['status']; expected_version: number; actor_id: string; device_id: string },
): Promise<ProductionTicketProjection> {
  const res = await fetch(`${API_BASE_URL}/api/v1/production/tickets/${ticketId}/transition`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(data),
  })
  if (!res.ok) throw await apiError(res, 'A fila mudou em outra tela. Atualize antes de continuar.')
  return res.json()
}

export async function fetchOrders(headers: Record<string, string>, status?: Order['status']): Promise<Order[]> {
  const suffix = status ? `?status=${status}` : ''
  const res = await fetch(`${API_BASE_URL}/api/v1/orders${suffix}`, { headers })
  if (!res.ok) throw new Error('Erro ao consultar pedidos')
  return res.json()
}

export async function getOrder(headers: Record<string, string>, orderId: string): Promise<Order> {
  const res = await fetch(`${API_BASE_URL}/api/v1/orders/${orderId}`, { headers })
  if (!res.ok) throw new Error('Pedido não encontrado')
  return res.json()
}

export async function addOrderItem(
  headers: Record<string, string>, orderId: string, idempotencyKey: string,
  data: { product_id: string; quantity: number; modifier_ids?: string[]; notes?: string; actor_id?: string }
): Promise<OrderItem> {
  const res = await fetch(`${API_BASE_URL}/api/v1/orders/${orderId}/items`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(data)
  })
  if (!res.ok) throw await apiError(res, 'Erro ao lançar item no pedido')
  return res.json()
}

export async function updateOrderItem(
  headers: Record<string, string>, orderId: string, itemId: string, idempotencyKey: string,
  data: { quantity: number; notes?: string; actor_id?: string }
): Promise<OrderItem> {
  const res = await fetch(`${API_BASE_URL}/api/v1/orders/${orderId}/items/${itemId}`, {
    method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(data)
  })
  if (!res.ok) throw new Error('Erro ao alterar item do pedido')
  return res.json()
}

export async function cancelOrderItem(
  headers: Record<string, string>, orderId: string, itemId: string, idempotencyKey: string,
  reason: string, actorId?: string
): Promise<OrderItem> {
  const res = await fetch(`${API_BASE_URL}/api/v1/orders/${orderId}/items/${itemId}/cancel`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ reason, actor_id: actorId })
  })
  if (!res.ok) throw new Error('Erro ao cancelar item do pedido')
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

export async function updateRegister(headers: Record<string, string>, registerId: string, data: {
  name?: string; is_active?: boolean; actor_id?: string; reason: string
}): Promise<Register> {
  const res = await fetch(`${API_BASE_URL}/api/v1/cash/registers/${registerId}`, { method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!res.ok) throw await apiError(res, 'Não foi possível atualizar o terminal.')
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

export async function fetchCashSessions(headers: Record<string, string>, storeId?: string, status?: 'OPEN' | 'CLOSING' | 'CLOSED'): Promise<CashSession[]> {
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

export async function reconcileSale(
  headers: Record<string, string>, saleId: string, actorId: string,
  input: { provider_reported_total?: number; provider?: string; provider_reference?: string; notes?: string } = {}
): Promise<FinancialReconciliation> {
  const res = await fetch(`${API_BASE_URL}/api/v1/reconciliations/sales/${saleId}`, {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor_id: actorId, ...input })
  })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'Erro ao conciliar venda') }
  return res.json()
}

export async function fetchReconciliations(
  headers: Record<string, string>, storeId?: string, status?: FinancialReconciliation['status']
): Promise<FinancialReconciliation[]> {
  const params = new URLSearchParams()
  if (storeId) params.set('store_id', storeId)
  if (status) params.set('status', status)
  const res = await fetch(`${API_BASE_URL}/api/v1/reconciliations?${params.toString()}`, { headers })
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
