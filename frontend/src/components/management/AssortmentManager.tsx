import React, { useState, useEffect, useCallback } from 'react'
import {
  Layers, Plus, Search, RefreshCw, AlertCircle,
  Trash2, Edit3, X, Check, AlertTriangle
} from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { NICHE_LABELS } from '../../utils/nicheTheme'

const CONTEXT_LABELS: Record<api.SalesContext, string> = {
  COUNTER: 'Balcão',
  TAKEAWAY: 'Retirada',
  TABLE: 'Mesa / Comanda',
  DELIVERY: 'Delivery',
  ECOMMERCE: 'E-commerce',
}

export interface FormScope {
  store_id: string
  sales_context: api.SalesContext
  channel_id: string | null
}

const AVAILABLE_CONTEXTS: Array<{ key: api.SalesContext; label: string; operational: boolean }> = [
  { key: 'COUNTER', label: 'Balcão', operational: true },
  { key: 'TAKEAWAY', label: 'Retirada', operational: true },
  { key: 'TABLE', label: 'Mesa / Comanda', operational: true },
  { key: 'DELIVERY', label: 'Delivery', operational: true },
  { key: 'ECOMMERCE', label: 'E-commerce (Não contratado)', operational: false },
]

export const AssortmentManager: React.FC = () => {
  const { tenant, store, permissions, activities, homologation, operatorId, showToast } = usePos()
  const canManage = permissions.includes('catalog.update')
  // Food service speaks of menus; retail and beauty speak of catalogues.
  const setsLabel = activities.includes('FOOD_SERVICE') ? 'Sortimentos e cardápios' : 'Sortimentos e catálogos'

  const [assortments, setAssortments] = useState<api.Assortment[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [conflictError, setConflictError] = useState<string | null>(null)

  // Modals & Selected items
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [editingAssortment, setEditingAssortment] = useState<api.Assortment | null>(null)
  const [managingProductsAssortment, setManagingProductsAssortment] = useState<api.Assortment | null>(null)
  const [assortmentProducts, setAssortmentProducts] = useState<api.AssortmentProductItem[]>([])
  const [productsLoading, setProductsLoading] = useState(false)
  const [availableMasterProducts, setAvailableMasterProducts] = useState<api.Product[]>([])
  const [selectedProductIdToAdd, setSelectedProductIdToAdd] = useState('')

  // Form states for Create/Edit
  const [formCode, setFormCode] = useState('')
  const [formName, setFormName] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formStatus, setFormStatus] = useState<'ACTIVE' | 'INACTIVE'>('ACTIVE')
  // Empty string means the set serves every contracted activity.
  const [formActivity, setFormActivity] = useState<string>('')
  const [formScopes, setFormScopes] = useState<FormScope[]>([])
  const [actionLoading, setActionLoading] = useState(false)
  const [starterActivity, setStarterActivity] = useState('')
  const [starterBusy, setStarterBusy] = useState(false)

  const headers = useCallback((): Record<string, string> => {
    if (!tenant) return {}
    const h: Record<string, string> = { 'X-Tenant-ID': tenant.id }
    if (store) h['X-Store-ID'] = store.id
    return h
  }, [tenant, store])

  const loadAssortments = useCallback(async () => {
    if (!tenant) return
    setLoading(true)
    setError(null)
    setConflictError(null)
    try {
      const data = await api.fetchAssortments(headers(), {
        page,
        pageSize: 20,
        search: search.trim() || undefined,
        status: statusFilter || undefined,
      })
      setAssortments(data.items)
      setTotal(data.total)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar sortimentos.')
    } finally {
      setLoading(false)
    }
  }, [tenant, headers, page, search, statusFilter])

  useEffect(() => {
    loadAssortments()
  }, [loadAssortments])

  // Load master products for linking
  const loadMasterProducts = useCallback(async () => {
    if (!tenant) return
    try {
      const prods = await api.fetchProducts(headers())
      setAvailableMasterProducts(prods.filter(p => p.is_active && p.available_for_sale))
    } catch (e) {
      console.error(e)
    }
  }, [tenant, headers])

  // Load products of selected assortment
  const loadAssortmentProducts = useCallback(async (assortmentId: string) => {
    setProductsLoading(true)
    try {
      const data = await api.fetchAssortmentProducts(headers(), assortmentId, { pageSize: 100 })
      setAssortmentProducts(data.items)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar produtos do sortimento.')
    } finally {
      setProductsLoading(false)
    }
  }, [headers])

  const openCreateModal = () => {
    setFormCode('')
    setFormName('')
    setFormDescription('')
    setFormStatus('ACTIVE')
    setFormActivity('')
    setFormScopes(store ? [{ store_id: store.id, sales_context: 'COUNTER', channel_id: null }] : [])
    setConflictError(null)
    setIsCreateOpen(true)
  }

  const openEditModal = (ass: api.Assortment) => {
    setEditingAssortment(ass)
    setFormCode(ass.code)
    setFormName(ass.name)
    setFormDescription(ass.description || '')
    setFormStatus(ass.status)
    setFormActivity(ass.business_activity || '')
    setFormScopes(ass.scopes.map(s => ({
      store_id: s.store_id,
      sales_context: s.sales_context,
      channel_id: s.channel_id ?? null,
    })))
    setConflictError(null)
  }

  const openManageProducts = (ass: api.Assortment) => {
    setManagingProductsAssortment(ass)
    setSelectedProductIdToAdd('')
    loadAssortmentProducts(ass.id)
    loadMasterProducts()
  }

  const toggleScope = (storeId: string, ctx: api.SalesContext) => {
    const existing = formScopes.find(s => s.store_id === storeId && s.sales_context === ctx)
    if (existing) {
      setFormScopes(formScopes.filter(s => !(s.store_id === storeId && s.sales_context === ctx)))
    } else {
      setFormScopes([...formScopes, { store_id: storeId, sales_context: ctx, channel_id: null }])
    }
  }

  const publishStarter = async () => {
    const activity = starterActivity || activities[0]
    if (!activity) return
    setStarterBusy(true)
    setError(null)
    try {
      const result = await api.publishStarterCatalogue(headers(), activity as api.BusinessNiche, operatorId || undefined)
      const retired = result.retired_assortments.length
      showToast('success', `${result.products_total} produto(s) publicados em ${result.assortment_code}` +
        (retired > 0 ? `; ${retired} sortimento(s) sem atividade foram desativados.` : '.'))
      loadAssortments()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Falha ao publicar o catálogo inicial.')
    } finally {
      setStarterBusy(false)
    }
  }

  const handleSaveCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formCode || !formName || formScopes.length === 0) return
    setActionLoading(true)
    setError(null)
    try {
      await api.createAssortment(headers(), {
        code: formCode.trim().toUpperCase(),
        name: formName.trim(),
        description: formDescription.trim() || undefined,
        business_activity: (formActivity || null) as api.BusinessNiche | null,
        status: formStatus,
        scopes: formScopes.map(s => ({
          store_id: s.store_id,
          sales_context: s.sales_context,
          channel_id: s.channel_id || undefined,
        })),
      }, `create-assortment-${Date.now()}`)
      setIsCreateOpen(false)
      loadAssortments()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao criar sortimento'
      setError(msg)
    } finally {
      setActionLoading(false)
    }
  }

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingAssortment || !formName || formScopes.length === 0) return
    setActionLoading(true)
    setConflictError(null)
    try {
      await api.updateAssortment(headers(), editingAssortment.id, {
        expected_version: editingAssortment.version,
        code: formCode.trim().toUpperCase() !== editingAssortment.code ? formCode.trim().toUpperCase() : undefined,
        name: formName.trim(),
        description: formDescription.trim() || undefined,
        business_activity: (formActivity || null) as api.BusinessNiche | null,
        status: formStatus,
        scopes: formScopes.map(s => ({
          store_id: s.store_id,
          sales_context: s.sales_context,
          channel_id: s.channel_id || undefined,
        })),
      }, `update-assortment-${editingAssortment.id}-${Date.now()}`)
      setEditingAssortment(null)
      loadAssortments()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao atualizar'
      if (msg.toLowerCase().includes('conflito de versão') || msg.toLowerCase().includes('concorrência') || msg.includes('409')) {
        setConflictError('Conflito de concorrência detectado: este sortimento foi alterado simultaneamente por outro processo.')
      } else {
        setError(msg)
      }
    } finally {
      setActionLoading(false)
    }
  }

  const handleLinkProduct = async () => {
    if (!managingProductsAssortment || !selectedProductIdToAdd) return
    setActionLoading(true)
    setConflictError(null)
    try {
      const updated = await api.linkAssortmentProducts(
        headers(),
        managingProductsAssortment.id,
        [selectedProductIdToAdd],
        managingProductsAssortment.version,
        `link-prod-${managingProductsAssortment.id}-${selectedProductIdToAdd}-${Date.now()}`
      )
      setManagingProductsAssortment(updated)
      setSelectedProductIdToAdd('')
      loadAssortmentProducts(updated.id)
      loadAssortments()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao vincular produto'
      if (msg.includes('409') || msg.includes('versão')) {
        setConflictError('Conflito de versão ao vincular: recarregue o sortimento e tente novamente.')
      } else {
        setError(msg)
      }
    } finally {
      setActionLoading(false)
    }
  }

  const handleUnlinkProduct = async (productId: string) => {
    if (!managingProductsAssortment) return
    setActionLoading(true)
    setConflictError(null)
    try {
      const updated = await api.unlinkAssortmentProducts(
        headers(),
        managingProductsAssortment.id,
        [productId],
        managingProductsAssortment.version,
        `unlink-prod-${managingProductsAssortment.id}-${productId}-${Date.now()}`
      )
      setManagingProductsAssortment(updated)
      loadAssortmentProducts(updated.id)
      loadAssortments()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Erro ao desvincular produto'
      if (msg.includes('409') || msg.includes('versão')) {
        setConflictError('Conflito de versão ao desvincular: recarregue o sortimento e tente novamente.')
      } else {
        setError(msg)
      }
    } finally {
      setActionLoading(false)
    }
  }

  const handleDelete = async (ass: api.Assortment) => {
    if (!window.confirm(`Deseja remover o sortimento "${ass.name}"?`)) return
    try {
      await api.deleteAssortment(headers(), ass.id, ass.version)
      loadAssortments()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Falha ao remover sortimento')
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Layers className="h-6 w-6 text-dashem-red" />
            <h1 className="text-xl font-black text-dashem-strong">{setsLabel}</h1>
          </div>
          <p className="text-xs text-dashem-muted font-medium mt-1">
            Fonte canônica de sortimento por contexto operacional. Cada jornada possui escopo explícito sem fallback global.
          </p>
        </div>

        {canManage && (
          <button
            onClick={openCreateModal}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-dashem-red text-brand-contrast text-xs font-black shadow-sm hover:bg-dashem-red-light transition active:scale-95"
          >
            <Plus className="h-4 w-4" />
            <span>Novo Sortimento</span>
          </button>
        )}
      </div>

      {/* Error alert */}
      {error && (
        <div className="flex items-center justify-between p-4 rounded-2xl bg-red-50 border border-red-200 text-red-700 text-xs">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={loadAssortments}
            className="flex items-center gap-1.5 px-3 py-1 bg-red-50 hover:bg-red-100 rounded-lg text-red-700 text-xs font-bold"
          >
            <RefreshCw className="h-3 w-3" />
            <span>Tentar novamente</span>
          </button>
        </div>
      )}

      {/* Conflict error alert */}
      {conflictError && (
        <div className="flex items-center justify-between p-4 rounded-2xl bg-amber-50 border border-amber-200 text-amber-700 text-xs">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-700" />
            <span>{conflictError}</span>
          </div>
          <button
            onClick={() => {
              setConflictError(null)
              loadAssortments()
              if (editingAssortment) {
                api.getAssortment(headers(), editingAssortment.id).then(openEditModal).catch(() => setEditingAssortment(null))
              }
              if (managingProductsAssortment) {
                api.getAssortment(headers(), managingProductsAssortment.id).then(openManageProducts).catch(() => setManagingProductsAssortment(null))
              }
            }}
            className="flex items-center gap-1.5 px-3 py-1 bg-amber-800/80 hover:bg-amber-700 rounded-lg text-white text-xs font-bold"
          >
            <RefreshCw className="h-3 w-3" />
            <span>Recarregar e sincronizar</span>
          </button>
        </div>
      )}

      {/* Homologation only: publishes a set coherent with the contracted activity
          and retires the sets that publish here without declaring one. */}
      {homologation && canManage && activities.length > 0 && (
        <section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5">
          <p className="text-xs font-black uppercase tracking-wider text-brand-ink">Tenant de homologação</p>
          <h2 className="mt-1 text-base font-black text-dashem-strong">Publicar catálogo inicial da atividade</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-dashem-muted">
            Cria um sortimento declarando a atividade escolhida, com produtos coerentes com ela, e desativa
            os sortimentos que publicam nesta unidade sem declarar atividade nenhuma. Nada é apagado: o
            catálogo mestre continua intacto e um sortimento desativado pode ser reativado.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <select
              value={starterActivity || activities[0]}
              onChange={(event) => setStarterActivity(event.target.value)}
              className="min-h-11 rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold text-dashem-strong outline-none focus:border-brand-ink"
            >
              {activities.map((activity) => (
                <option key={activity} value={activity}>{NICHE_LABELS[activity] || activity}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void publishStarter()}
              disabled={starterBusy}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-brand px-4 text-sm font-black text-brand-contrast disabled:opacity-40"
            >
              {starterBusy ? 'Publicando...' : 'Publicar catálogo inicial'}
            </button>
          </div>
        </section>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-dashem-muted absolute left-4 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            placeholder="Buscar por código ou nome do sortimento..."
            className="w-full h-10 pl-11 pr-4 rounded-xl bg-dashem-surface border border-dashem-border text-dashem-strong text-xs font-medium focus:border-dashem-red outline-none"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="h-10 px-3 rounded-xl bg-dashem-surface border border-dashem-border text-dashem-strong text-xs font-medium focus:border-dashem-red outline-none"
        >
          <option value="">Todos os estados</option>
          <option value="ACTIVE">Ativos</option>
          <option value="INACTIVE">Inativos</option>
        </select>
      </div>

      {/* Main List Table */}
      <div className="rounded-3xl border border-dashem-border bg-dashem-surface overflow-hidden shadow-sm">
        {loading ? (
          <div className="p-12 text-center text-dashem-muted text-xs font-medium flex flex-col items-center gap-2">
            <RefreshCw className="h-5 w-5 animate-spin text-dashem-red" />
            <span>Carregando sortimentos...</span>
          </div>
        ) : assortments.length === 0 ? (
          <div className="p-12 text-center text-dashem-muted text-xs font-medium flex flex-col items-center gap-2">
            <Layers className="h-8 w-8 text-dashem-muted/40" />
            <span className="text-dashem-strong font-bold text-sm">Nenhum sortimento encontrado</span>
            <span className="max-w-md">
              Não há sortimentos cadastrados para os filtros selecionados. Crie um novo sortimento para vincular produtos aos contextos de venda.
            </span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-dashem-surface-elevated text-dashem-muted font-extrabold uppercase tracking-wider text-[10px] border-b border-dashem-border">
                <tr>
                  <th className="px-5 py-3.5">Código / Nome</th>
                  <th className="px-4 py-3.5">Contextos Atribuídos</th>
                  <th className="px-4 py-3.5 text-center">Produtos</th>
                  <th className="px-4 py-3.5 text-center">Versão</th>
                  <th className="px-4 py-3.5 text-center">Estado</th>
                  <th className="px-5 py-3.5 text-right">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-dashem-border/50 font-medium">
                {assortments.map((ass) => (
                  <tr key={ass.id} className="hover:bg-dashem-surface-elevated/50 transition">
                    <td className="px-5 py-4">
                      <div className="font-extrabold text-dashem-strong text-sm">{ass.name}</div>
                      <div className="text-xs font-mono text-dashem-muted">{ass.code}</div>
                      {ass.description && (
                        <div className="text-xs text-dashem-muted mt-0.5 line-clamp-1">{ass.description}</div>
                      )}
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex flex-wrap gap-1.5">
                        {ass.scopes.map((s, idx) => (
                          <span
                            key={idx}
                            className="px-2 py-0.5 rounded-lg bg-dashem-bg border border-dashem-border text-xs font-bold text-dashem-muted"
                          >
                            {CONTEXT_LABELS[s.sales_context] || s.sales_context}
                          </span>
                        ))}
                        {ass.scopes.length === 0 && (
                          <span className="text-xs text-amber-700 font-semibold italic">Sem escopos</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-4 text-center">
                      <span className="font-bold text-dashem-strong">{ass.product_count}</span>
                    </td>
                    <td className="px-4 py-4 text-center font-mono text-dashem-muted text-xs">
                      v{ass.version}
                    </td>
                    <td className="px-4 py-4 text-center">
                      <span
                        className={`inline-block px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wider ${
                          ass.status === 'ACTIVE'
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                            : 'bg-dashem-surface-elevated text-dashem-muted border border-dashem-border'
                        }`}
                      >
                        {ass.status === 'ACTIVE' ? 'Ativo' : 'Inativo'}
                      </span>
                    </td>
                    <td className="px-5 py-4 text-right space-x-2">
                      <button
                        onClick={() => openManageProducts(ass)}
                        className="px-3 py-1.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-dashem-strong text-xs font-bold hover:border-dashem-red transition"
                      >
                        Produtos ({ass.product_count})
                      </button>
                      {canManage && (
                        <>
                          <button
                            onClick={() => openEditModal(ass)}
                            className="p-1.5 rounded-lg text-dashem-muted hover:text-dashem-strong transition"
                            title="Editar sortimento"
                          >
                            <Edit3 className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(ass)}
                            className="p-1.5 rounded-lg text-dashem-muted hover:text-red-700 transition"
                            title="Excluir sortimento"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal: Create Assortment */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-lg bg-dashem-surface border border-dashem-border rounded-3xl p-6 shadow-2xl space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-dashem-border pb-4">
              <h2 className="text-base font-black text-dashem-strong">Criar Novo Sortimento</h2>
              <button onClick={() => setIsCreateOpen(false)} className="text-dashem-muted hover:text-dashem-strong">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveCreate} className="space-y-4">
              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Código único</label>
                <input
                  type="text"
                  required
                  placeholder="EX: CARDAPIO-BALCAO"
                  value={formCode}
                  onChange={(e) => setFormCode(e.target.value.toUpperCase())}
                  className="w-full h-10 px-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-xs font-mono font-bold focus:border-dashem-red outline-none"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Nome</label>
                <input
                  type="text"
                  required
                  placeholder="Ex: Cardápio Principal do Balcão"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="w-full h-10 px-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-xs font-bold focus:border-dashem-red outline-none"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Descrição</label>
                <textarea
                  rows={2}
                  placeholder="Finalidade e observações deste sortimento..."
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  className="w-full p-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-xs font-medium focus:border-dashem-red outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-dashem-muted uppercase tracking-wider mb-1">Atividade de negócio</label>
                <p className="text-xs text-dashem-muted mb-2">Define para qual modelo de negócio este conjunto é publicado. Sem atividade, ele vale para todas as contratadas.</p>
                <select
                  value={formActivity}
                  onChange={(e) => setFormActivity(e.target.value)}
                  className="w-full min-h-11 px-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-sm font-bold focus:border-brand-ink outline-none"
                >
                  <option value="">Todas as atividades contratadas</option>
                  {activities.map((activity) => (
                    <option key={activity} value={activity}>{NICHE_LABELS[activity] || activity}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Contextos Operacionais Habilitados</label>
                <p className="text-xs text-dashem-muted mb-2">Selecione as jornadas em que este sortimento será publicado na unidade ativa:</p>
                <div className="grid grid-cols-2 gap-2">
                  {AVAILABLE_CONTEXTS.map((item) => {
                    const ctx = item.key
                    const scope = store ? formScopes.find(s => s.store_id === store.id && s.sales_context === ctx) : null
                    const isChecked = !!scope
                    return (
                      <button
                        key={ctx}
                        type="button"
                        disabled={!item.operational}
                        onClick={() => store && item.operational && toggleScope(store.id, ctx)}
                        className={`flex items-center justify-between p-2.5 rounded-xl border text-xs font-bold text-left transition ${
                          !item.operational
                            ? 'opacity-40 cursor-not-allowed bg-dashem-bg border-dashem-border text-dashem-muted'
                            : isChecked
                              ? 'bg-brand-soft border-brand text-brand-ink'
                              : 'bg-dashem-bg border-dashem-border text-dashem-muted hover:border-brand/40'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <div className={`w-4 h-4 rounded flex items-center justify-center border ${isChecked ? 'bg-dashem-red border-dashem-red text-brand-contrast' : 'border-dashem-border'}`}>
                            {isChecked && <Check className="w-3 h-3" />}
                          </div>
                          <span>{item.label}</span>
                        </div>
                        {scope?.channel_id && (
                          <span className="text-xs font-mono text-amber-700 bg-amber-400/10 px-1.5 py-0.5 rounded">
                            Canal: {scope.channel_id.slice(0, 6)}
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="pt-2 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-4 py-2 rounded-xl border border-dashem-border text-xs font-bold text-dashem-muted hover:text-dashem-strong"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={actionLoading || formScopes.length === 0}
                  className="px-5 py-2 rounded-xl bg-dashem-red text-xs font-black text-brand-contrast hover:bg-dashem-red-light disabled:opacity-50 shadow-sm"
                >
                  {actionLoading ? 'Salvando...' : 'Criar Sortimento'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Edit Assortment */}
      {editingAssortment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-lg bg-dashem-surface border border-dashem-border rounded-3xl p-6 shadow-2xl space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-dashem-border pb-4">
              <div>
                <h2 className="text-base font-black text-dashem-strong">Editar Sortimento</h2>
                <p className="text-xs font-mono text-dashem-muted">Versão esperada: v{editingAssortment.version}</p>
              </div>
              <button onClick={() => setEditingAssortment(null)} className="text-dashem-muted hover:text-dashem-strong">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="space-y-4">
              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Código</label>
                <input
                  type="text"
                  required
                  value={formCode}
                  onChange={(e) => setFormCode(e.target.value.toUpperCase())}
                  className="w-full h-10 px-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-xs font-mono font-bold focus:border-dashem-red outline-none"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Nome</label>
                <input
                  type="text"
                  required
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="w-full h-10 px-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-xs font-bold focus:border-dashem-red outline-none"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Descrição</label>
                <textarea
                  rows={2}
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  className="w-full p-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-xs font-medium focus:border-dashem-red outline-none"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Estado</label>
                <select
                  value={formStatus}
                  onChange={(e) => setFormStatus(e.target.value as 'ACTIVE' | 'INACTIVE')}
                  className="w-full h-10 px-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-xs font-bold focus:border-dashem-red outline-none"
                >
                  <option value="ACTIVE">Ativo</option>
                  <option value="INACTIVE">Inativo</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-dashem-muted uppercase tracking-wider mb-1">Atividade de negócio</label>
                <p className="text-xs text-dashem-muted mb-2">Define para qual modelo de negócio este conjunto é publicado. Sem atividade, ele vale para todas as contratadas.</p>
                <select
                  value={formActivity}
                  onChange={(e) => setFormActivity(e.target.value)}
                  className="w-full min-h-11 px-3 rounded-xl bg-dashem-bg border border-dashem-border text-dashem-strong text-sm font-bold focus:border-brand-ink outline-none"
                >
                  <option value="">Todas as atividades contratadas</option>
                  {activities.map((activity) => (
                    <option key={activity} value={activity}>{NICHE_LABELS[activity] || activity}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[11px] font-bold text-dashem-muted uppercase tracking-wider mb-1">Contextos Operacionais Habilitados</label>
                <div className="grid grid-cols-2 gap-2">
                  {AVAILABLE_CONTEXTS.map((item) => {
                    const ctx = item.key
                    const scope = store ? formScopes.find(s => s.store_id === store.id && s.sales_context === ctx) : null
                    const isChecked = !!scope
                    return (
                      <button
                        key={ctx}
                        type="button"
                        disabled={!item.operational}
                        onClick={() => store && item.operational && toggleScope(store.id, ctx)}
                        className={`flex items-center justify-between p-2.5 rounded-xl border text-xs font-bold text-left transition ${
                          !item.operational
                            ? 'opacity-40 cursor-not-allowed bg-dashem-bg border-dashem-border text-dashem-muted'
                            : isChecked
                              ? 'bg-brand-soft border-brand text-brand-ink'
                              : 'bg-dashem-bg border-dashem-border text-dashem-muted hover:border-brand/40'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <div className={`w-4 h-4 rounded flex items-center justify-center border ${isChecked ? 'bg-dashem-red border-dashem-red text-brand-contrast' : 'border-dashem-border'}`}>
                            {isChecked && <Check className="w-3 h-3" />}
                          </div>
                          <span>{item.label}</span>
                        </div>
                        {scope?.channel_id && (
                          <span className="text-xs font-mono text-amber-700 bg-amber-400/10 px-1.5 py-0.5 rounded">
                            Canal: {scope.channel_id.slice(0, 6)}
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="pt-2 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setEditingAssortment(null)}
                  className="px-4 py-2 rounded-xl border border-dashem-border text-xs font-bold text-dashem-muted hover:text-dashem-strong"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={actionLoading || formScopes.length === 0}
                  className="px-5 py-2 rounded-xl bg-dashem-red text-xs font-black text-brand-contrast hover:bg-dashem-red-light disabled:opacity-50 shadow-sm"
                >
                  {actionLoading ? 'Salvando...' : 'Salvar Alterações'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Manage Products */}
      {managingProductsAssortment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-2xl bg-dashem-surface border border-dashem-border rounded-3xl p-6 shadow-2xl space-y-5 max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-dashem-border pb-4">
              <div>
                <h2 className="text-base font-black text-dashem-strong">Produtos do Sortimento</h2>
                <p className="text-xs text-dashem-muted">{managingProductsAssortment.name} ({managingProductsAssortment.code}) — v{managingProductsAssortment.version}</p>
              </div>
              <button onClick={() => setManagingProductsAssortment(null)} className="text-dashem-muted hover:text-dashem-strong">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Link product picker */}
            {canManage && (
              <div className="p-3 bg-dashem-bg rounded-2xl border border-dashem-border flex flex-col sm:flex-row items-center gap-3">
                <select
                  value={selectedProductIdToAdd}
                  onChange={(e) => setSelectedProductIdToAdd(e.target.value)}
                  className="w-full sm:flex-1 h-10 px-3 rounded-xl bg-dashem-surface border border-dashem-border text-dashem-strong text-xs font-medium focus:border-dashem-red outline-none"
                >
                  <option value="">Selecione um produto do catálogo mestre...</option>
                  {availableMasterProducts
                    .filter(mp => !assortmentProducts.some(ap => ap.id === mp.id))
                    .map(mp => (
                      <option key={mp.id} value={mp.id}>
                        {mp.name} ({mp.sku})
                      </option>
                    ))}
                </select>
                <button
                  type="button"
                  disabled={!selectedProductIdToAdd || actionLoading}
                  onClick={handleLinkProduct}
                  className="w-full sm:w-auto px-4 py-2 rounded-xl bg-dashem-red text-brand-contrast text-xs font-bold hover:bg-dashem-red-light disabled:opacity-50 shrink-0"
                >
                  Vincular ao Sortimento
                </button>
              </div>
            )}

            {/* List of linked products */}
            <div className="flex-1 overflow-auto border border-dashem-border rounded-2xl">
              {productsLoading ? (
                <div className="p-8 text-center text-dashem-muted text-xs flex items-center justify-center gap-2">
                  <RefreshCw className="h-4 w-4 animate-spin text-dashem-red" />
                  <span>Carregando produtos...</span>
                </div>
              ) : assortmentProducts.length === 0 ? (
                <div className="p-8 text-center text-dashem-muted text-xs">
                  Nenhum produto vinculado a este sortimento. Utilize o seletor acima para adicionar produtos.
                </div>
              ) : (
                <table className="w-full min-w-[32rem] text-left text-xs">
                  <thead className="bg-dashem-surface-elevated text-dashem-muted font-bold text-[10px] uppercase border-b border-dashem-border">
                    <tr>
                      <th className="px-4 py-2.5">Produto</th>
                      <th className="px-4 py-2.5">SKU</th>
                      <th className="px-4 py-2.5 text-center">Unidade</th>
                      {canManage && <th className="px-4 py-2.5 text-right">Ação</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-dashem-border/50">
                    {assortmentProducts.map((p) => (
                      <tr key={p.id} className="hover:bg-dashem-surface-elevated/40">
                        <td className="px-4 py-2.5 font-bold text-dashem-strong">{p.name}</td>
                        <td className="px-4 py-2.5 font-mono text-dashem-muted">{p.sku}</td>
                        <td className="px-4 py-2.5 text-center text-dashem-muted">{p.unit}</td>
                        {canManage && (
                          <td className="px-4 py-2.5 text-right">
                            <button
                              onClick={() => handleUnlinkProduct(p.id)}
                              disabled={actionLoading}
                              className="text-red-700 hover:text-red-700 font-bold text-xs"
                            >
                              Desvincular
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setManagingProductsAssortment(null)}
                className="px-4 py-2 rounded-xl bg-dashem-surface-elevated border border-dashem-border text-xs font-bold text-dashem-strong hover:border-dashem-red"
              >
                Concluir
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
