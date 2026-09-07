import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowDownToLine, Boxes, ClipboardCheck, History, PackageX, Scale, Search } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Modal } from '../common/Modal'
import { DataTable } from '../common/DataTable'
import * as api from '../../services/api'
import { formatApiDateTime } from '../../utils/format'
import { ApiError } from '../../services/http'
import { DEFAULT_STOCK_REASONS, countPreview, reasonForMovement, type StockMovementType } from '../../domain/stockMovements'

/**
 * Estoque por unidade.
 *
 * Esta tela lia o catálogo **vendável** — a projeção de venda por contexto — e o
 * efeito era que uma mercadoria cadastrada, com recebimento registrado e
 * controle de estoque ativo, não aparecia aqui enquanto ninguém a publicasse em
 * um sortimento. Publicação decide onde o item pode ser vendido; ela não decide
 * se ele existe na prateleira. Agora a fonte é o acervo físico da unidade.
 */
export function InventoryManager() {
  const { tenant, store, operatorId, adjustStock, permissions, showToast } = usePos()
  const [holdings, setHoldings] = useState<api.StockHolding[]>([])
  const [movements, setMovements] = useState<api.InventoryMovement[]>([])
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState(false)

  const headers = useMemo<Record<string, string>>(
    () => (tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : {} as Record<string, string>),
    [tenant, store],
  )
  const canAdjust = permissions.includes('inventory.adjust')
  const canCount = permissions.includes('inventory.count')
  // Diferença lançada à mão passa por cima da conferência da prateleira. Quem
  // não tem essa autoridade não vê a ação — e a rota recusa de qualquer forma.
  const canAdjustTechnically = permissions.includes('inventory.adjust.technical')

  const load = useCallback(async () => {
    if (!store) return
    try {
      const [acervo, historico] = await Promise.all([
        api.fetchStockHoldings(headers, store.id),
        api.fetchInventoryMovements(headers, store.id),
      ])
      setHoldings(acervo)
      setMovements(historico)
      setLoadError(false)
    } catch {
      // Falha de carregamento não pode se passar por prateleira vazia: a tela
      // diz que não conseguiu ler e oferece tentar de novo.
      setLoadError(true)
    }
  }, [headers, store])

  useEffect(() => { void load() }, [load])

  const nameOf = (productId: string) =>
    holdings.find((item) => item.product_id === productId)?.name || productId.slice(0, 8)

  const filtered = holdings.filter((item) => {
    const agulha = search.trim().toLocaleLowerCase('pt-BR')
    if (!agulha) return true
    return item.name.toLocaleLowerCase('pt-BR').includes(agulha)
      || item.sku.toLocaleLowerCase('pt-BR').includes(agulha)
  })
  const semEstoque = filtered.filter((item) => item.is_out_of_stock).length
  const abaixoDoMinimo = filtered.filter((item) => item.is_low_stock).length
  // Somar quilo, litro e unidade num número só produz um total que não é de
  // nada. O que dá para contar sem conversão é quantas mercadorias existem, e
  // cada saldo aparece com a sua unidade na linha.
  const controlados = filtered.length

  // ----------------------------------------------------------- movimentação
  const [selected, setSelected] = useState<api.StockHolding | null>(null)
  const [form, setForm] = useState({
    quantity: '', movement_type: 'PURCHASE',
    reason: DEFAULT_STOCK_REASONS.PURCHASE, minimum_stock: '',
  })

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selected || !store) return
    setBusy(true)
    try {
      await adjustStock(selected.product_id, Number(form.quantity), form.movement_type, form.reason)
      if (form.minimum_stock !== '') {
        await api.setMinimumStock(headers, store.id, selected.product_id, Number(form.minimum_stock))
      }
      await load()
      setSelected(null)
      showToast('success', 'Movimentação registrada no histórico do estoque.')
    } catch {
      /* o aviso de falha já foi dado por quem chamou a API; aqui só não seguimos adiante */
    } finally { setBusy(false) }
  }

  // -------------------------------------------------------- ajuste técnico
  const [technical, setTechnical] = useState<api.StockHolding | null>(null)
  const [technicalForm, setTechnicalForm] = useState({ difference: '', reason: '' })

  const submitTechnical = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!technical || !store || technicalForm.difference === '') return
    setBusy(true)
    try {
      await api.adjustStockTechnically(headers, {
        store_id: store.id, product_id: technical.product_id, actor_id: operatorId,
        difference: Number(technicalForm.difference), reason: technicalForm.reason,
      })
      await load()
      setTechnical(null)
      setTechnicalForm({ difference: '', reason: '' })
      showToast('success', 'Ajuste técnico registrado no histórico do estoque.')
    } catch (reason) {
      showToast('error', reason instanceof Error ? reason.message : 'Não foi possível lançar o ajuste.')
    } finally { setBusy(false) }
  }

  // --------------------------------------------------------------- contagem
  // A contagem carrega o saldo e a versão que a pessoa tinha à vista quando foi
  // olhar a prateleira. É essa versão que o servidor confere ao confirmar.
  const [counting, setCounting] = useState<api.StockHolding | null>(null)
  const [counted, setCounted] = useState('')
  const [countBase, setCountBase] = useState<api.InventoryBalance | null>(null)
  const [countConflict, setCountConflict] = useState('')
  // Depois de um conflito, confirmar de novo exige um ato deliberado. Sem isto,
  // um clique reenviaria o número contado antes da movimentação contra a versão
  // recém-lida — que é exatamente a aceitação silenciosa que a versão existe
  // para impedir. O número digitado permanece; o que falta é a pessoa dizer que
  // voltou à prateleira.
  const [recounted, setRecounted] = useState(false)

  const openCount = async (item: api.StockHolding) => {
    if (!store) return
    setCounting(item); setCounted(''); setCountConflict(''); setRecounted(false)
    setCountBase(await api.fetchInventoryBalance(headers, store.id, item.product_id))
  }

  const submitCount = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!counting || !store || counted === '') return
    setBusy(true)
    try {
      await api.countStock(headers, `count-${counting.product_id}-${crypto.randomUUID()}`, {
        store_id: store.id, product_id: counting.product_id, actor_id: operatorId,
        counted_quantity: Number(counted),
        expected_version: countBase?.version ?? 0,
      })
      await load()
      setCounting(null); setCounted(''); setCountConflict(''); setRecounted(false)
      showToast('success', 'Conferência registrada.')
    } catch (reason) {
      // Conflito não é erro da pessoa: o estoque andou enquanto ela contava. O
      // que ela digitou permanece, o saldo é relido, e ela decide se confirma o
      // mesmo número ou conta de novo. Nunca aceitamos por cima com a versão
      // nova — isso apagaria do estoque a venda que entrou no meio.
      if (reason instanceof ApiError && reason.status === 409) {
        setCountConflict(reason.message)
        setRecounted(false)
        setCountBase(await api.fetchInventoryBalance(headers, store.id, counting.product_id))
        // A tabela atrás do formulário também é relida. Dois saldos diferentes
        // na mesma tela, sem dizer qual está velho, comprometem a conferência:
        // a pessoa não sabe contra qual número está conferindo.
        await load()
      } else {
        showToast('error', reason instanceof Error ? reason.message : 'Não foi possível registrar a contagem.')
      }
    } finally { setBusy(false) }
  }

  const saldoNaTabela = counting
    ? holdings.find((item) => item.product_id === counting.product_id)?.quantity
    : undefined

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-6">
        <p className="text-[11px] font-black uppercase tracking-[.18em] text-emerald-700">Controle de mercadorias</p>
        <h1 className="mt-2 text-3xl font-black text-dashem-strong">Estoque por unidade</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-dashem-muted">
          Tudo o que esta unidade controla, publicado no PDV ou não. Cada movimentação
          fica no histórico com quantidade, motivo e responsável.
        </p>
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <Metric label="Mercadorias controladas" value={controlados} icon={Boxes} />
          <Metric label="Sem estoque" value={semEstoque} icon={PackageX} attention={semEstoque > 0} />
          <Metric label="Abaixo do mínimo" value={abaixoDoMinimo} icon={AlertTriangle} attention={abaixoDoMinimo > 0} />
        </div>
      </section>

      <div className="relative">
        <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-dashem-muted" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por produto ou SKU..."
          className="h-12 w-full rounded-xl border border-dashem-border bg-dashem-surface pl-11 pr-4 text-sm text-dashem-strong outline-none focus:border-emerald-600"
        />
      </div>

      {loadError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm font-bold text-amber-900">
          Não foi possível carregar o estoque desta unidade.
          <button
            type="button" onClick={() => { void load() }}
            className="inline-flex min-h-11 items-center rounded-lg border border-amber-400 px-3 text-xs font-black"
          >
            Tentar novamente
          </button>
        </div>
      )}

      <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface">
        <DataTable
          rows={filtered}
          rowKey={(item) => item.product_id}
          empty={<p className="p-8 text-center text-sm font-bold text-dashem-muted">
            {loadError ? 'Estoque não carregado.' : 'Nenhuma mercadoria controlada nesta unidade.'}
          </p>}
          columns={[
            {
              key: 'name', header: 'Mercadoria', primary: true,
              cell: (item) => (
                <div>
                  <p className="font-black text-dashem-strong">{item.name}</p>
                  <p className="text-xs text-dashem-muted">{item.sku}</p>
                </div>
              ),
            },
            {
              key: 'qty', header: 'Saldo',
              cell: (item) => <span className="font-black text-dashem-strong">{Number(item.quantity)} {item.unit}</span>,
            },
            {
              key: 'min', header: 'Mínimo',
              cell: (item) => item.has_minimum
                ? <span className="text-dashem-muted">{Number(item.minimum_stock)} {item.unit}</span>
                : <span className="text-dashem-muted">—</span>,
            },
            {
              key: 'state', header: 'Situação',
              cell: (item) => <Situation item={item} />,
            },
            {
              key: 'action', header: 'Ação', actions: true, align: 'right',
              cell: (item) => (
                <div className="flex flex-wrap justify-end gap-2">
                  {canCount && (
                    <button onClick={() => { void openCount(item) }} className="inline-flex min-h-11 items-center rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-strong">
                      <ClipboardCheck className="mr-1 inline h-4 w-4 text-emerald-700" />Contar estoque
                    </button>
                  )}
                  {canAdjust && (
                    <button
                      onClick={() => {
                        setSelected(item)
                        setForm({
                          quantity: '', movement_type: 'PURCHASE',
                          reason: DEFAULT_STOCK_REASONS.PURCHASE,
                          minimum_stock: String(item.minimum_stock),
                        })
                      }}
                      className="inline-flex min-h-11 items-center rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-strong"
                    >
                      <ArrowDownToLine className="mr-1 inline h-4 w-4 text-emerald-700" />Movimentar
                    </button>
                  )}
                  {canAdjustTechnically && (
                    <button
                      onClick={() => { setTechnical(item); setTechnicalForm({ difference: '', reason: '' }) }}
                      className="inline-flex min-h-11 items-center rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-strong"
                    >
                      <Scale className="mr-1 inline h-4 w-4 text-amber-700" />Ajuste técnico
                    </button>
                  )}
                </div>
              ),
            },
          ]}
        />
      </section>

      <section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5">
        <div className="flex items-center gap-2">
          <History className="h-5 w-5 text-emerald-700" />
          <h2 className="font-black text-dashem-strong">Movimentações recentes</h2>
        </div>
        <div className="mt-4 divide-y divide-dashem-border">
          {movements.slice(0, 12).map((item) => (
            <div key={item.id} className="grid gap-1 py-3 text-xs sm:grid-cols-[1fr_auto_auto]">
              <span className="font-bold text-dashem-strong">{nameOf(item.product_id)}</span>
              <span className="text-dashem-muted">{item.movement_type} · {Number(item.quantity)}</span>
              <span className="text-dashem-muted">{formatApiDateTime(item.created_at)}</span>
            </div>
          ))}
          {movements.length === 0 && (
            <p className="py-6 text-center text-sm text-dashem-muted">
              {loadError ? 'Histórico não carregado.' : 'Nenhuma movimentação registrada.'}
            </p>
          )}
        </div>
      </section>

      <Modal
        isOpen={Boolean(technical)} onClose={() => setTechnical(null)}
        title={`Ajuste técnico de ${technical?.name || ''}`}
        subtitle="Diferença lançada à mão, quando a contagem não resolve."
      >
        <form onSubmit={submitTechnical} className="space-y-4">
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs font-bold text-amber-900">
            Esta operação não passa pela conferência da prateleira. Prefira <b>Contar estoque</b> sempre
            que a mercadoria puder ser conferida.
          </div>
          <Field label="Diferença (use sinal negativo para retirar)" type="number" value={technicalForm.difference} onChange={(value) => setTechnicalForm({ ...technicalForm, difference: value })} />
          <Field label="Motivo" value={technicalForm.reason} onChange={(value) => setTechnicalForm({ ...technicalForm, reason: value })} />
          <button disabled={busy || technicalForm.difference === '' || technicalForm.reason.trim().length < 3} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">
            {busy ? 'Registrando...' : 'Lançar ajuste técnico'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={Boolean(counting)} onClose={() => setCounting(null)}
        title={`Contar ${counting?.name || ''}`}
        subtitle="Informe quanto você encontrou na prateleira. A diferença é calculada aqui."
      >
        <form onSubmit={submitCount} className="space-y-4">
          <div className="rounded-xl border border-dashem-border bg-dashem-surface-elevated p-3 text-xs text-dashem-muted">
            <p>Saldo registrado agora: <b className="text-dashem-strong">{Number(countBase?.quantity ?? 0)} {counting?.unit}</b></p>
            {counted !== '' && (
              <p className="mt-1 text-dashem-strong">
                {countPreview(Number(counted), Number(countBase?.quantity ?? 0), counting?.unit || 'un')}
              </p>
            )}
          </div>
          <Field label="Quantidade encontrada" type="number" value={counted} onChange={setCounted} />
          {countConflict && (
            <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs font-bold text-amber-900">
              {countConflict}
              <span className="mt-1 block font-medium">
                O saldo acima e a lista atrás já foram relidos
                {saldoNaTabela !== undefined && ` (${Number(saldoNaTabela)} ${counting?.unit})`}. O número que
                você digitou continua aqui, mas ele foi contado antes desta movimentação.
              </span>
              <label className="mt-3 flex items-center gap-2 font-black">
                <input type="checkbox" checked={recounted} onChange={(event) => setRecounted(event.target.checked)} className="h-4 w-4" />
                Voltei à prateleira e confirmo a quantidade acima
              </label>
            </div>
          )}
          <button disabled={busy || counted === '' || (Boolean(countConflict) && !recounted)} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">
            {busy ? 'Registrando...' : 'Confirmar contagem'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={Boolean(selected)} onClose={() => setSelected(null)}
        title={`Movimentar ${selected?.name || ''}`}
        subtitle="Informe a quantidade e o motivo operacional."
      >
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-xs font-black text-dashem-strong">
            Tipo
            <select
              value={form.movement_type}
              onChange={(event) => setForm({
                ...form, movement_type: event.target.value,
                reason: reasonForMovement(form.reason, event.target.value as StockMovementType),
              })}
              className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong"
            >
              <option value="PURCHASE">Entrada / compra</option>
              <option value="LOSS">Perda</option>
              <option value="RETURN">Devolução</option>
            </select>
          </label>
          <Field label="Quantidade" type="number" value={form.quantity} onChange={(value) => setForm({ ...form, quantity: value })} />
          <Field label="Estoque mínimo" type="number" value={form.minimum_stock} onChange={(value) => setForm({ ...form, minimum_stock: value })} />
          <Field label="Motivo" value={form.reason} onChange={(value) => setForm({ ...form, reason: value })} />
          <button disabled={busy || !form.quantity || form.reason.length < 3} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">
            {busy ? 'Registrando...' : 'Registrar movimentação'}
          </button>
        </form>
      </Modal>
    </div>
  )
}

/**
 * A situação de uma mercadoria tem três estados, não dois.
 *
 * "Sem estoque" e "abaixo do mínimo" são coisas diferentes, e produto sem mínimo
 * definido não é regular nem irregular — não há política contra a qual julgá-lo.
 * Chamar tudo isso de "Regular" escondia justamente o que precisa de decisão.
 */
function Situation({ item }: { item: api.StockHolding }) {
  if (item.is_out_of_stock) {
    return <span className="rounded-full bg-rose-50 px-2 py-1 text-xs font-black text-rose-700">Sem estoque</span>
  }
  if (item.is_low_stock) {
    return <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-black text-amber-700">Abaixo do mínimo</span>
  }
  if (!item.has_minimum) {
    return <span className="rounded-full bg-dashem-surface-elevated px-2 py-1 text-xs font-black text-dashem-muted">Sem mínimo definido</span>
  }
  return <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-black text-emerald-700">Regular</span>
}

function Metric({ label, value, icon: Icon, attention = false }: {
  label: string; value: number
  icon: React.ComponentType<{ className?: string }>; attention?: boolean
}) {
  return (
    <div className="flex items-center gap-4 rounded-2xl bg-dashem-bg p-4">
      <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${attention ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <p className="text-2xl font-black text-dashem-strong">{value}</p>
        <p className="text-xs font-bold text-dashem-muted">{label}</p>
      </div>
    </div>
  )
}

function Field({ label, value, onChange, type = 'text' }: {
  label: string; value: string; onChange: (value: string) => void; type?: string
}) {
  return (
    <label className="block text-xs font-black text-dashem-strong">
      {label}
      <input
        required type={type} step={type === 'number' ? '0.0001' : undefined}
        value={value} onChange={(event) => onChange(event.target.value)}
        className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong outline-none focus:border-dashem-red"
      />
    </label>
  )
}
