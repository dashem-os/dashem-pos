import React, { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react'
import * as api from '../services/api'
import { paymentProgress, requireAuthenticatedActor, saleNeedsCreation } from '../domain/operationalRules'

export interface ToastInfo {
  type: 'success' | 'error' | 'info'
  text: string
}

interface PosContextType {
  // Context state
  accessMode: 'MANAGEMENT' | 'OPERATIONAL_SESSION'
  tenant: api.Tenant | null
  store: api.Store | null
  register: api.Register | null
  cashSession: api.CashSession | null
  operatorId: string
  operatorName: string
  operatorRole?: 'SUPERVISOR' | 'CASHIER' | 'OPERATOR'
  health: api.ApiHealth | null
  permissions: string[]
  capabilities: api.EffectiveAccess['capabilities']
  contributions: api.EffectiveAccess['contributions']
  connectionState: 'ONLINE' | 'DEGRADED' | 'OFFLINE'
  operationMode: 'COUNTER' | 'TAKEAWAY'

  // Data state
  products: api.SellableProduct[]
  categories: api.Category[]
  prices: Record<string, number>
  balances: Record<string, number>
  salesHistory: api.Sale[]
  currentSale: api.Sale | null
  confirmedPayments: api.Payment[]
  fiscalDoc: api.FiscalDocument | null

  // Operational modal states
  isPaymentModalOpen: boolean
  isQuantityModalOpen: boolean
  isDiscountModalOpen: boolean
  isFiscalModalOpen: boolean
  isCancelModalOpen: boolean
  selectedItemForQuantity: api.SaleItem | null

  // Status
  loading: boolean
  actionLoading: boolean
  toast: ToastInfo | null

  // Actions
  showToast: (type: 'success' | 'error' | 'info', text: string) => void
  setOperationMode: (mode: 'COUNTER' | 'TAKEAWAY') => void
  startNewSale: () => Promise<void>
  addItemToCart: (productId: string, quantity?: number) => Promise<boolean>
  updateItemQuantity: (itemId: string, quantity: number) => Promise<void>
  removeItemFromCart: (itemId: string) => Promise<void>
  applyDiscount: (type: 'FIXED' | 'PERCENTAGE', value: number) => Promise<void>
  cancelCurrentSale: (reason?: string) => Promise<void>
  openPaymentModal: () => void
  closePaymentModal: () => void
  openQuantityModal: (item: api.SaleItem) => void
  closeQuantityModal: () => void
  openDiscountModal: () => void
  closeDiscountModal: () => void
  openCancelModal: () => void
  closeCancelModal: () => void
  closeFiscalModal: () => void
  processPayment: (method: api.Payment['method'], amount: number, tenderedAmount?: number) => Promise<boolean>
  issueFiscal: (simulateStatus?: string) => Promise<void>
  openCash: (openingBalance: number) => Promise<void>
  closeCash: (closingBalance: number) => Promise<void>
  addCashMovement: (type: 'BLEED' | 'REINFORCEMENT', amount: number, notes?: string) => Promise<void>
  createNewProduct: (product: { name: string; sku: string; barcode?: string; item_type?: 'PRODUCT' | 'SERVICE' }, price: number, initialStock?: number) => Promise<void>
  adjustStock: (productId: string, quantity: number, type: string, reason?: string) => Promise<void>
  refreshData: () => Promise<void>
}

const PosContext = createContext<PosContextType | undefined>(undefined)

export const PosProvider: React.FC<{
  children: ReactNode
  source?: 'MANAGEMENT' | 'OPERATIONAL_SESSION'
  operatorId?: string
  operatorName?: string
  operatorRole?: 'SUPERVISOR' | 'CASHIER' | 'OPERATOR'
  tenantId: string
  storeId: string
  registerId?: string
  tenantName?: string
  tenantSlug?: string
  storeName?: string
  storeCode?: string
  registerName?: string
  registerCode?: string
}> = ({
  children, source = 'MANAGEMENT', tenantId, storeId, registerId,
  operatorId: operationalOperatorId, operatorName: operationalOperatorName, operatorRole,
  tenantName, tenantSlug, storeName, storeCode, registerName, registerCode,
}) => {

  const [tenant, setTenant] = useState<api.Tenant | null>(null)
  const [store, setStore] = useState<api.Store | null>(null)
  const [register, setRegister] = useState<api.Register | null>(null)
  const [cashSession, setCashSession] = useState<api.CashSession | null>(null)
  const [operatorId, setOperatorId] = useState<string>('')
  const [operatorName, setOperatorName] = useState<string>('')
  const [health, setHealth] = useState<api.ApiHealth | null>(null)
  const [permissions, setPermissions] = useState<string[]>([])
  const [capabilities, setCapabilities] = useState<api.EffectiveAccess['capabilities']>({})
  const [contributions, setContributions] = useState<api.EffectiveAccess['contributions']>([])
  const [connectionState, setConnectionState] = useState<'ONLINE' | 'DEGRADED' | 'OFFLINE'>(navigator.onLine ? 'ONLINE' : 'OFFLINE')
  const [operationMode, setOperationModeState] = useState<'COUNTER' | 'TAKEAWAY'>('COUNTER')

  const [products, setProducts] = useState<api.SellableProduct[]>([])
  const [categories, setCategories] = useState<api.Category[]>([])
  const [prices, setPrices] = useState<Record<string, number>>({})
  const [balances, setBalances] = useState<Record<string, number>>({})
  const [salesHistory, setSalesHistory] = useState<api.Sale[]>([])
  const [currentSale, setCurrentSale] = useState<api.Sale | null>(null)
  const [confirmedPayments, setConfirmedPayments] = useState<api.Payment[]>([])
  const [fiscalDoc, setFiscalDoc] = useState<api.FiscalDocument | null>(null)

  const [isPaymentModalOpen, setIsPaymentModalOpen] = useState(false)
  const [isQuantityModalOpen, setIsQuantityModalOpen] = useState(false)
  const [isDiscountModalOpen, setIsDiscountModalOpen] = useState(false)
  const [isFiscalModalOpen, setIsFiscalModalOpen] = useState(false)
  const [isCancelModalOpen, setIsCancelModalOpen] = useState(false)
  const [selectedItemForQuantity, setSelectedItemForQuantity] = useState<api.SaleItem | null>(null)

  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [toast, setToast] = useState<ToastInfo | null>(null)

  const showToast = useCallback((type: 'success' | 'error' | 'info', text: string) => {
    setToast({ type, text })
    setTimeout(() => setToast(null), 4000)
  }, [])

  const setOperationMode = useCallback((mode: 'COUNTER' | 'TAKEAWAY') => {
    if (currentSale && currentSale.items.length > 0 && currentSale.status !== 'COMPLETED' && currentSale.status !== 'CANCELED') {
      showToast('error', 'Finalize ou cancele a operação atual antes de trocar o modo.')
      return
    }
    setOperationModeState(mode)
  }, [currentSale, showToast])

  useEffect(() => {
    let active = true
    const inspect = async () => {
      if (!navigator.onLine) {
        if (active) setConnectionState('OFFLINE')
        return
      }
      const response = await api.fetchHealth().catch(() => null)
      if (active) setConnectionState(response ? 'ONLINE' : 'DEGRADED')
    }
    const online = () => void inspect()
    const offline = () => setConnectionState('OFFLINE')
    window.addEventListener('online', online)
    window.addEventListener('offline', offline)
    void inspect()
    const interval = window.setInterval(inspect, 15000)
    return () => {
      active = false
      window.clearInterval(interval)
      window.removeEventListener('online', online)
      window.removeEventListener('offline', offline)
    }
  }, [])

  const getHeaders = useCallback((): Record<string, string> => {
    if (!tenant || !store) return {}
    return {
      'X-Tenant-ID': tenant.id,
      'X-Store-ID': store.id
    }
  }, [tenant, store])

  // Load context on startup cleanly without duplicating records
  const loadInitialContext = useCallback(async () => {
    try {
      setLoading(true)
      const h = await api.fetchHealth().catch(() => null)
      setHealth(h)

      const me = source === 'OPERATIONAL_SESSION' ? null : await api.fetchMe()
      if (source === 'OPERATIONAL_SESSION') {
        if (!operationalOperatorId) throw new Error('A sessão operacional não informou o colaborador.')
        setOperatorId(operationalOperatorId)
        setOperatorName(operationalOperatorName || 'Colaborador')
      } else {
        setOperatorId(requireAuthenticatedActor(me?.user))
        setOperatorName(me?.user?.full_name || 'Gestão')
      }

      const selectedTenant = source === 'OPERATIONAL_SESSION'
        ? { id: tenantId, name: tenantName || 'Empresa', slug: tenantSlug || '', status: 'ACTIVE' as const }
        : (await api.fetchTenants()).find((item) => item.id === tenantId)
      if (!selectedTenant) throw new Error('Tenant selecionado não está autorizado para esta identidade.')
      setTenant(selectedTenant)
      const selectedStore = source === 'OPERATIONAL_SESSION'
        ? { id: storeId, tenant_id: tenantId, name: storeName || 'Unidade', code: storeCode || '', is_active: true }
        : (await api.fetchStores(selectedTenant.id)).find((item) => item.id === storeId)
      if (!selectedStore) throw new Error('Unidade selecionada não está autorizada para esta identidade.')
      setStore(selectedStore)
      const hdrs = { 'X-Tenant-ID': selectedTenant.id, 'X-Store-ID': selectedStore.id }
      const access = await api.fetchEffectiveAccess(hdrs)
      if (source === 'MANAGEMENT' && !access.permissions.includes('management.read')) {
        throw new Error('Esta identidade não possui permissão gerencial para validar o PDV.')
      }
      setPermissions(access.permissions)
      setCapabilities(access.capabilities)
      setContributions(access.contributions)
      if (registerId) {
        const selectedRegister = source === 'OPERATIONAL_SESSION'
          ? { id: registerId, tenant_id: tenantId, store_id: storeId, name: registerName || 'Terminal', code: registerCode || '', is_active: true }
          : (await api.fetchRegisters(hdrs, selectedStore.id)).find((item) => item.id === registerId)
        if (!selectedRegister) throw new Error('Terminal selecionado não está autorizado nesta unidade.')
        setRegister(selectedRegister)
        if (access.permissions.includes('cash.read')) {
          const activeCs = await api.fetchActiveCashSession(hdrs, selectedStore.id, selectedRegister.id)
          setCashSession(activeCs)
        } else {
          setCashSession(null)
        }
      } else {
        setRegister(null)
        setCashSession(null)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Falha ao inicializar contexto'
      showToast('error', msg)
    } finally {
      setLoading(false)
    }
  }, [source, operationalOperatorId, operationalOperatorName, tenantId, tenantName, tenantSlug, storeId, storeName, storeCode, registerId, registerName, registerCode, showToast])

  // Refresh products, inventory and sales data
  const refreshData = useCallback(async () => {
    if (!tenant || !store) return
    try {
      const hdrs = getHeaders()
      const catalog = await api.fetchSellableProducts(hdrs, { pageSize: 100 })
      const prods = catalog.items
      setProducts(prods)

      const cats = await api.fetchCategories(hdrs).catch(() => [])
      setCategories(cats)

      const priceMap: Record<string, number> = {}
      for (const product of prods) {
        priceMap[product.id] = Number(product.sale_price)
      }
      setPrices(priceMap)

      const balMap: Record<string, number> = {}
      for (const product of prods) {
        balMap[product.id] = Number(product.quantity)
      }
      setBalances(balMap)

      const sales = await api.fetchSales(hdrs, store.id)
      setSalesHistory(sales)
    } catch (err: unknown) {
      console.error('Error refreshing data:', err)
    }
  }, [tenant, store, getHeaders])

  useEffect(() => {
    loadInitialContext()
  }, [loadInitialContext])

  useEffect(() => {
    if (tenant && store) {
      refreshData()
    }
  }, [tenant, store, refreshData])

  useEffect(() => {
    if (!tenant || !store || !register || !operatorId) return
    const headers = { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
    api.fetchActiveSale(headers, store.id, register.id, operatorId)
      .then((sale) => {
        if (!sale) return
        setCurrentSale(sale)
        setOperationModeState(sale.operation_mode)
        if (sale.status === 'AWAITING_PAYMENT') {
          api.fetchSalePayments(headers, sale.id)
            .then((payments) => setConfirmedPayments(payments.filter((payment) => payment.status === 'CONFIRMED')))
            .catch(() => setConnectionState(navigator.onLine ? 'DEGRADED' : 'OFFLINE'))
        }
      })
      .catch(() => setConnectionState(navigator.onLine ? 'DEGRADED' : 'OFFLINE'))
  }, [tenant, store, register, operatorId])

  const startNewSale = async () => {
    if (!store || !register) {
      showToast('error', 'Unidade e terminal precisam estar selecionados.')
      return
    }
    if (connectionState !== 'ONLINE') {
      showToast('error', 'Operação indisponível sem conexão confirmada. Nenhum dado foi descartado.')
      return
    }
    if (!cashSession || cashSession.status !== 'OPEN') {
      showToast('error', 'O Caixa precisa estar ABERTO para iniciar vendas!')
      return
    }
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const newSale = await api.createSale(hdrs, store.id, register.id, operatorId, operationMode)
      setCurrentSale(newSale)
      setConfirmedPayments([])
      setFiscalDoc(null)
      setIsPaymentModalOpen(false)
      setIsFiscalModalOpen(false)
      showToast('info', 'Nova venda iniciada!')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao iniciar nova venda'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const addItemToCart = async (productId: string, quantity: number = 1): Promise<boolean> => {
    if (!store || !register) {
      showToast('error', 'Unidade e terminal não configurados.')
      return false
    }
    if (connectionState !== 'ONLINE') {
      showToast('error', 'Sem conexão confirmada. A operação persistida continua segura no servidor.')
      return false
    }
    if (!cashSession || cashSession.status !== 'OPEN') {
      showToast('error', 'Caixa fechado! Abra o caixa para registrar vendas.')
      return false
    }
    if (actionLoading) return false

    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      let saleToUse = currentSale

      // If no current sale or sale is finished/canceled, create a new sale first
      if (saleNeedsCreation(saleToUse?.status)) {
        saleToUse = await api.createSale(hdrs, store.id, register.id, operatorId, operationMode)
        setConfirmedPayments([])
        setFiscalDoc(null)
      }

      if (!saleToUse) throw new Error('Não foi possível iniciar a venda.')

      // Add item to sale
      const updatedSale = await api.addItemToSale(hdrs, saleToUse.id, productId, quantity)
      setCurrentSale(updatedSale)

      const prod = products.find((p) => p.id === productId)
      showToast('success', `${quantity}x ${prod?.name || 'Item'} adicionado!`)
      return true
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao adicionar item'
      showToast('error', msg)
      return false
    } finally {
      setActionLoading(false)
    }
  }

  const updateItemQuantity = async (itemId: string, quantity: number) => {
    if (!currentSale) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const updatedSale = await api.updateSaleItem(hdrs, currentSale.id, itemId, quantity)
      setCurrentSale(updatedSale)
      showToast('success', 'Quantidade atualizada!')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao atualizar quantidade'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const removeItemFromCart = async (itemId: string) => {
    if (!currentSale) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const updatedSale = await api.deleteSaleItem(hdrs, currentSale.id, itemId)
      setCurrentSale(updatedSale)
      showToast('info', 'Item removido do carrinho.')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao remover item'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const applyDiscount = async (type: 'FIXED' | 'PERCENTAGE', value: number) => {
    if (!currentSale) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const updatedSale = await api.applySaleDiscount(hdrs, currentSale.id, type, value)
      setCurrentSale(updatedSale)
      const descLabel = type === 'PERCENTAGE' ? `${value}%` : `R$ ${value.toFixed(2)}`
      showToast('success', `Desconto de ${descLabel} aplicado com sucesso!`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao aplicar desconto'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const cancelCurrentSale = async (reason: string = 'Cancelamento solicitado pelo operador') => {
    if (!currentSale) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const canceled = await api.cancelSale(hdrs, currentSale.id, operatorId, reason)
      setCurrentSale(canceled)
      setIsCancelModalOpen(false)
      setIsPaymentModalOpen(false)
      showToast('info', 'Venda cancelada.')
      refreshData()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao cancelar venda'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const openPaymentModal = async () => {
    if (!currentSale || currentSale.items.length === 0) {
      showToast('error', 'O carrinho está vazio.')
      return
    }
    try {
      setActionLoading(true)
      const hdrs = getHeaders()

      // If sale is in DRAFT or CHECKOUT, proceed with checkout to move into AWAITING_PAYMENT
      if (currentSale.status === 'DRAFT' || currentSale.status === 'CHECKOUT') {
        const checkedSale = await api.checkoutSale(hdrs, currentSale.id, operatorId)
        setCurrentSale(checkedSale)
      }

      // Load existing confirmed payments for this sale (handles resuming after refresh)
      const existingPayments = await api.fetchSalePayments(hdrs, currentSale.id)
      setConfirmedPayments(existingPayments.filter((p) => p.status === 'CONFIRMED'))
      setIsPaymentModalOpen(true)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao preparar checkout'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const closePaymentModal = () => {
    setIsPaymentModalOpen(false)
  }

  const openQuantityModal = (item: api.SaleItem) => {
    setSelectedItemForQuantity(item)
    setIsQuantityModalOpen(true)
  }

  const closeQuantityModal = () => {
    setSelectedItemForQuantity(null)
    setIsQuantityModalOpen(false)
  }

  const openDiscountModal = () => setIsDiscountModalOpen(true)
  const closeDiscountModal = () => setIsDiscountModalOpen(false)
  const openCancelModal = () => setIsCancelModalOpen(true)
  const closeCancelModal = () => setIsCancelModalOpen(false)
  const closeFiscalModal = () => setIsFiscalModalOpen(false)

  const processPayment = async (method: api.Payment['method'], amount: number, tenderedAmount?: number): Promise<boolean> => {
    if (!currentSale) return false
    try {
      setActionLoading(true)
      const hdrs = getHeaders()

      const pay = await api.createPayment(
        hdrs,
        currentSale.id,
        method,
        amount,
        method === 'CASH' ? cashSession?.id : undefined,
        tenderedAmount
      )

      const confirmRes = await api.confirmPayment(hdrs, pay.id, operatorId, `pay-idemp-${pay.id}-${Date.now()}`)

      const updatedPayments = [...confirmedPayments, confirmRes.payment]
      setConfirmedPayments(updatedPayments)

      const { remaining } = paymentProgress(currentSale.net_total, updatedPayments.map((payment) => payment.amount))

      if (confirmRes.sale_status === 'PAID') {
        setCurrentSale((prev) => (prev ? { ...prev, status: 'PAID' } : null))
        showToast('success', '✓ Pagamento total concluído!')

        // Trigger fiscal issuance automatically
        await issueFiscal()
        return true
      } else {
        showToast('info', `Parcela de R$ ${amount.toFixed(2)} confirmada! Restam R$ ${remaining.toFixed(2)}.`)
        return false
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao processar pagamento'
      showToast('error', msg)
      return false
    } finally {
      setActionLoading(false)
    }
  }

  const issueFiscal = async (simulateStatus?: string) => {
    if (!currentSale) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const res = await api.issueFiscalDocument(hdrs, currentSale.id, operatorId, 'NFCE', simulateStatus)
      setFiscalDoc(res.fiscal_document)
      setIsFiscalModalOpen(true)

      if (res.sale_status === 'COMPLETED') {
        setCurrentSale((prev) => (prev ? { ...prev, status: 'COMPLETED' } : null))
        showToast('success', '✓ Venda e NFC-e concluídas com sucesso!')
      } else if (res.fiscal_document.status === 'REJECTED') {
        showToast('error', `Rejeição SEFAZ [${res.fiscal_document.rejection_code}]: ${res.fiscal_document.rejection_reason}`)
      } else if (res.fiscal_document.status === 'CONTINGENCY') {
        showToast('info', 'Documento emitido em Contingência Offline.')
      }
      refreshData()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao emitir documento fiscal'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const openCash = async (openingBalance: number) => {
    if (!store || !register) return
    if (!permissions.includes('cash.open')) {
      showToast('info', 'Seu perfil não abre caixa. Solicite a um Caixa ou Supervisor.')
      return
    }
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const cs = await api.openCashSession(hdrs, store.id, register.id, operatorId, openingBalance)
      setCashSession(cs)
      showToast('success', `Caixa aberto com saldo inicial de R$ ${openingBalance.toFixed(2)}!`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao abrir caixa'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const closeCash = async (closingBalance: number) => {
    if (!cashSession) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const closed = await api.closeCashSession(hdrs, cashSession.id, operatorId, closingBalance)
      setCashSession(closed)
      showToast(
        'success',
        `Caixa fechado! Saldo apurado: R$ ${closed.closing_balance?.toFixed(2)} | Divergência: R$ ${closed.variance?.toFixed(2)}`
      )
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao fechar caixa'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const addCashMovement = async (type: 'BLEED' | 'REINFORCEMENT', amount: number, notes?: string) => {
    if (!cashSession) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      await api.addCashMovement(hdrs, cashSession.id, operatorId, type, amount, notes)
      showToast('success', `${type === 'BLEED' ? 'Sangria' : 'Suprimento'} de R$ ${amount.toFixed(2)} registrado!`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao movimentar caixa'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const createNewProduct = async (
    product: { name: string; sku: string; barcode?: string; item_type?: 'PRODUCT' | 'SERVICE' },
    price: number,
    initialStock: number = 0
  ) => {
    if (!store) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      const created = await api.createProduct(hdrs, product)
      await api.setProductPrice(hdrs, created.id, store.id, price)
      if (product.item_type !== 'SERVICE' && initialStock > 0) {
        await api.adjustInventory(hdrs, {
          store_id: store.id,
          product_id: created.id,
          actor_id: operatorId,
          movement_type: 'PURCHASE',
          quantity: initialStock,
          reason: 'Cadastro Inicial'
        })
      }
      showToast('success', `Produto '${product.name}' cadastrado!`)
      refreshData()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao cadastrar produto'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  const adjustStock = async (productId: string, quantity: number, type: string, reason?: string) => {
    if (!store) return
    try {
      setActionLoading(true)
      const hdrs = getHeaders()
      await api.adjustInventory(hdrs, {
        store_id: store.id,
        product_id: productId,
        actor_id: operatorId,
        movement_type: type,
        quantity,
        reason
      })
      showToast('success', 'Estoque ajustado com sucesso!')
      refreshData()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao ajustar estoque'
      showToast('error', msg)
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <PosContext.Provider
      value={{
        accessMode: source,
        tenant,
        store,
        register,
        cashSession,
        operatorId,
        operatorName,
        operatorRole,
        health,
        permissions,
        capabilities,
        contributions,
        connectionState,
        operationMode,
        products,
        categories,
        prices,
        balances,
        salesHistory,
        currentSale,
        confirmedPayments,
        fiscalDoc,
        isPaymentModalOpen,
        isQuantityModalOpen,
        isDiscountModalOpen,
        isFiscalModalOpen,
        isCancelModalOpen,
        selectedItemForQuantity,
        loading,
        actionLoading,
        toast,
        showToast,
        setOperationMode,
        startNewSale,
        addItemToCart,
        updateItemQuantity,
        removeItemFromCart,
        applyDiscount,
        cancelCurrentSale,
        openPaymentModal,
        closePaymentModal,
        openQuantityModal,
        closeQuantityModal,
        openDiscountModal,
        closeDiscountModal,
        openCancelModal,
        closeCancelModal,
        closeFiscalModal,
        processPayment,
        issueFiscal,
        openCash,
        closeCash,
        addCashMovement,
        createNewProduct,
        adjustStock,
        refreshData
      }}
    >
      {children}
    </PosContext.Provider>
  )
}

export const usePos = () => {
  const context = useContext(PosContext)
  if (!context) {
    throw new Error('usePos must be used within a PosProvider')
  }
  return context
}
