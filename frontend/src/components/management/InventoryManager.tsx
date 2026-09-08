import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowDownToLine, CheckCircle2, ClipboardCheck, History, PackageX, Scale, Search, Target } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Modal } from '../common/Modal'
import { RowAction, RowActions } from '../common/RowActions'
import { DataTable } from '../common/DataTable'
import * as api from '../../services/api'
import { formatApiDateTime } from '../../utils/format'
import { ApiError } from '../../services/http'
import { requiringAction, stockSituation } from '../../domain/stockSituation'
import { DEFAULT_STOCK_REASONS, countPreview, movementAmount, movementLabel, reasonForMovement, type StockMovementType } from '../../domain/stockMovements'

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

  // Quantidade sem unidade não é quantidade. O histórico usa a mesma unidade
  // que a linha da mercadoria usa acima.
  const unitOf = (productId: string) =>
    holdings.find((item) => item.product_id === productId)?.unit || 'un'

  const filtered = holdings.filter((item) => {
    const agulha = search.trim().toLocaleLowerCase('pt-BR')
    if (!agulha) return true
    return item.name.toLocaleLowerCase('pt-BR').includes(agulha)
      || item.sku.toLocaleLowerCase('pt-BR').includes(agulha)
  })
  const semEstoque = filtered.filter((item) => item.is_out_of_stock).length
  // Cada mercadoria conta uma vez: quem está sem estoque também está abaixo da
  // referência, e somar os dois contadores inflava o resumo.
  const exigindoAcao = requiringAction(filtered)
  // Somar quilo, litro e unidade num número só produz um total que não é de
  // nada. O que dá para contar sem conversão é quantas mercadorias existem, e
  // cada saldo aparece com a sua unidade na linha.
  const controlados = filtered.length

  // ----------------------------------------------------------- movimentação
  const [selected, setSelected] = useState<api.StockHolding | null>(null)
  const [form, setForm] = useState({
    quantity: '', movement_type: 'PURCHASE',
    reason: DEFAULT_STOCK_REASONS.PURCHASE,
  })
  const [movementError, setMovementError] = useState('')

  // Receber mercadoria e registrar perda são duas intenções, e quem clica já
  // sabe qual é a sua. Um seletor entre as duas obrigava quem só queria repor a
  // passar por uma escolha que ele já tinha feito antes de abrir a tela.
  const abrirMovimentacao = (item: api.StockHolding, tipo: 'PURCHASE' | 'LOSS') => {
    setSelected(item)
    setMovementError('')
    setForm({
      quantity: '', movement_type: tipo,
      reason: DEFAULT_STOCK_REASONS[tipo],
    })
  }
  const recebendo = form.movement_type === 'PURCHASE'

  // ------------------------------------------------------------- mínimo
  // Configurar o mínimo é decisão de política, não movimentação: nada entra,
  // nada sai, nenhum movimento é criado. Antes o único caminho até ele era o
  // formulário de entrada, então quem só queria definir um mínimo precisava
  // inventar um recebimento — e um recebimento inventado é saldo errado.
  const [minimo, setMinimo] = useState<api.StockHolding | null>(null)
  const [minimoValor, setMinimoValor] = useState('')
  const [minimoErro, setMinimoErro] = useState('')

  const abrirMinimo = (item: api.StockHolding) => {
    setMinimo(item)
    setMinimoErro('')
    setMinimoValor(item.has_minimum ? String(Number(item.minimum_stock)) : '')
  }

  const salvarMinimo = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!minimo || !store || minimoValor === '') return
    setBusy(true)
    setMinimoErro('')
    try {
      await api.setMinimumStock(headers, store.id, minimo.product_id, Number(minimoValor))
      await load()
      setMinimo(null)
      showToast('success', 'Mínimo salvo. O saldo não mudou e nenhum movimento foi criado.')
    } catch (reason) {
      setMinimoErro(reason instanceof Error ? reason.message : 'O mínimo não foi salvo.')
    } finally { setBusy(false) }
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selected || !store) return
    setBusy(true)
    setMovementError('')
    try {
      await adjustStock(selected.product_id, Number(form.quantity), form.movement_type, form.reason)
    } catch (reason) {
      // A recusa fica no formulário, onde a pessoa está olhando. O aviso
      // flutuante some sozinho em poucos segundos: quem digitou 999 e viu o
      // aviso passar não descobre mais por que nada foi registrado.
      setMovementError(reason instanceof Error ? reason.message : 'A movimentação não foi registrada.')
      setBusy(false)
      return
    }
    // O mínimo saiu daqui: configurar é operação própria, e misturá-la com a
    // movimentação era o que obrigava a inventar uma entrada para salvar uma
    // política.
    try {
      await load()
      setSelected(null)
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

  // A chave nasce com a conferência e sobrevive ao reenvio. Gerar uma nova a
  // cada clique tornava a guarda do servidor inalcançável: uma resposta perdida
  // seguida de novo envio chegaria como comando diferente e registraria uma
  // segunda contagem. A chave só muda quando a conferência muda.
  const [countKey, setCountKey] = useState('')

  const openCount = async (item: api.StockHolding) => {
    if (!store) return
    setCounting(item)
    setCounted('')
    setCountConflict('')
    setRecounted(false)
    // Zerar antes de buscar: sem isto o formulário abre exibindo o saldo do
    // produto anterior, e a prévia calcula a diferença contra ele.
    setCountBase(null)
    setCountKey(`count-${item.product_id}-${crypto.randomUUID()}`)
    try {
      setCountBase(await api.fetchInventoryBalance(headers, store.id, item.product_id))
    } catch (reason) {
      // Sem o saldo lido não há conferência possível, e um formulário aberto
      // que nunca habilita é pior do que não abrir: a pessoa fica esperando um
      // botão que não vem. Fecha e diz o que houve.
      setCounting(null)
      showToast('error', reason instanceof Error ? reason.message : 'Não foi possível ler o saldo para conferir.')
    }
  }

  const submitCount = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!counting || !store || counted === '' || countBase === null) return
    setBusy(true)
    try {
      await api.countStock(headers, countKey, {
        store_id: store.id, product_id: counting.product_id, actor_id: operatorId,
        counted_quantity: Number(counted),
        expected_version: countBase.version,
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
        // Confirmar depois do conflito é outra conferência, sobre outra versão:
        // reaproveitar a chave anterior seria reenvio de um comando que já foi
        // recusado, e o servidor a trataria como conteúdo diferente.
        setCountKey(`count-${counting.product_id}-${crypto.randomUUID()}`)
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
        <p className="text-[11px] font-black uppercase tracking-[.18em] text-state-success">Controle de mercadorias</p>
        <h1 className="mt-2 text-3xl font-black text-dashem-strong">Estoque por unidade</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-dashem-muted">
          Quanto você tem de cada mercadoria nesta unidade.
        </p>
        {/*
          Três contadores ocupavam um terço da tela sem dizer o que fazer. Uma
          faixa conclui, e obedece ao pior risco (ADR-034).
        */}
        <Resumo controlados={controlados} semEstoque={semEstoque} exigindoAcao={exigindoAcao} />
      </section>

      <div className="relative">
        <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-dashem-muted" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por produto ou SKU..."
          className="h-12 w-full rounded-xl border border-dashem-border bg-dashem-surface pl-11 pr-4 text-sm text-dashem-strong outline-none focus:border-state-success"
        />
      </div>

      {loadError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-state-warning-border bg-state-warning-soft p-4 text-sm font-bold text-state-warning">
          Não foi possível carregar o estoque desta unidade.
          <button
            type="button" onClick={() => { void load() }}
            className="inline-flex min-h-11 items-center rounded-lg border border-state-warning-border px-3 text-xs font-black"
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
              // Disponível é o que pode ser vendido agora. O físico e o
              // comprometido ficam no detalhe (ADR-034).
              key: 'qty', header: 'Disponível',
              cell: (item) => (
                <div>
                  <span className="text-base font-black text-dashem-strong">
                    {Number(item.available ?? item.quantity)} {item.unit}
                  </span>
                  {Number(item.reserved) > 0 && (
                    <p className="text-[11px] text-dashem-muted">{Number(item.reserved)} em vendas</p>
                  )}
                </div>
              ),
            },
            {
              key: 'state', header: 'Situação',
              cell: (item) => <Situation item={item} />,
            },
            {
              key: 'action', header: 'Ação', actions: true, align: 'right',
              // Por frequência: mercadoria chega toda semana, prateleira se
              // confere de vez em quando, e ajuste técnico é excepcional — ele
              // sai da linha e vai para o menu, onde não é clicado por engano.
              // Uma ação dominante por linha, e ela é a que a situação pede:
              // mercadoria em falta quer receber. O resto — contar, perda,
              // ajuste, estoque de referência — está no menu, a um clique, sem
              // disputar a atenção de quem só passou os olhos na lista.
              cell: (item) => (
                <div className="flex flex-nowrap items-center justify-end gap-2">
                  {canAdjust && (item.is_out_of_stock || item.is_low_stock) && (
                    <button
                      onClick={() => abrirMovimentacao(item, 'PURCHASE')}
                      className="inline-flex min-h-11 items-center rounded-xl border border-dashem-border px-3 text-xs font-black text-dashem-strong"
                    >
                      <ArrowDownToLine className="mr-1.5 inline h-4 w-4 text-state-success" />Receber
                    </button>
                  )}
                  <RowActions label={`Ações de ${item.name}`}>
                    {canAdjust && !(item.is_out_of_stock || item.is_low_stock) && (
                      <RowAction icon={ArrowDownToLine} onClick={() => abrirMovimentacao(item, 'PURCHASE')}>
                        Receber mercadoria
                      </RowAction>
                    )}
                    {canCount && (
                      <RowAction icon={ClipboardCheck} onClick={() => { void openCount(item) }}>
                        Contar estoque
                      </RowAction>
                    )}
                    {canAdjust && (
                      <RowAction icon={PackageX} onClick={() => abrirMovimentacao(item, 'LOSS')}>
                        Registrar perda
                      </RowAction>
                    )}
                    {canAdjust && (
                      <RowAction icon={Target} onClick={() => abrirMinimo(item)}>
                        {item.has_minimum
                          ? `Estoque de referência: ${Number(item.minimum_stock)} ${item.unit}`
                          : 'Definir estoque de referência'}
                      </RowAction>
                    )}
                    {canAdjustTechnically && (
                      <RowAction icon={Scale} onClick={() => { setTechnical(item); setTechnicalForm({ difference: '', reason: '' }) }}>
                        Ajuste técnico
                      </RowAction>
                    )}
                  </RowActions>
                </div>
              ),
            },
          ]}
        />
      </section>

      <section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5">
        <div className="flex items-center gap-2">
          <History className="h-5 w-5 text-state-success" />
          <h2 className="font-black text-dashem-strong">Movimentações recentes</h2>
        </div>
        <div className="mt-4 divide-y divide-dashem-border">
          {movements.slice(0, 12).map((item) => (
            <div key={item.id} className="grid gap-1 py-3 text-xs sm:grid-cols-[1fr_auto_auto] sm:items-center sm:gap-4">
              <span className="font-bold text-dashem-strong">{nameOf(item.product_id)}</span>
              <span className="font-black text-dashem-strong">
                {movementLabel(item.movement_type, item.origin)}
                <span className={`ml-2 font-black ${Number(item.quantity) < 0 ? 'text-state-danger' : 'text-state-success'}`}>
                  {movementAmount(Number(item.quantity), unitOf(item.product_id))}
                </span>
              </span>
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
          <div className="rounded-xl border border-state-warning-border bg-state-warning-soft p-3 text-xs font-bold text-state-warning">
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
        isOpen={Boolean(minimo)} onClose={() => setMinimo(null)}
        title={`Estoque de referência — ${minimo?.name || ''}`}
        subtitle="Usado enquanto não há histórico para calcular a reposição."
      >
        <form onSubmit={salvarMinimo} className="space-y-4">
          <div className="rounded-xl border border-dashem-border bg-dashem-surface-elevated p-3 text-xs text-dashem-muted">
            <p>Em estoque agora: <b className="text-dashem-strong">{Number(minimo?.quantity ?? 0)} {minimo?.unit}</b></p>
          </div>
          <Field label={`Quantidade mínima (${minimo?.unit || 'un'})`} type="number" value={minimoValor} onChange={setMinimoValor} placeholder="Ex.: 12" />
          {minimoErro && (
            <p role="alert" className="rounded-xl border border-state-danger-border bg-state-danger-soft p-3 text-xs font-bold text-state-danger">
              {minimoErro}
            </p>
          )}
          <button disabled={busy || minimoValor === ''} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">
            {busy ? 'Salvando...' : 'Salvar mínimo'}
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
            {/*
              Saldo ainda não lido não é saldo zero. Exibir 0 enquanto a
              resposta não chega afirma um número que ninguém verificou — e a
              instância hiberna, então essa espera pode durar quase um minuto.
              A conferência é contra o saldo registrado: sem ele, não há contra
              o que conferir.
            */}
            {countBase === null ? (
              <p>Lendo o saldo registrado...</p>
            ) : (
              <>
                <p>Saldo registrado agora: <b className="text-dashem-strong">{Number(countBase.quantity)} {counting?.unit}</b></p>
                {counted !== '' && (
                  <p className="mt-1 text-dashem-strong">
                    {countPreview(Number(counted), Number(countBase.quantity), counting?.unit || 'un')}
                  </p>
                )}
              </>
            )}
          </div>
          <Field label="Quantidade encontrada" type="number" value={counted} onChange={setCounted} placeholder="Ex.: 31" />
          {countConflict && (
            <div role="alert" className="rounded-xl border border-state-warning-border bg-state-warning-soft p-3 text-xs font-bold text-state-warning">
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
          <button disabled={busy || countBase === null || counted === '' || (Boolean(countConflict) && !recounted)} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">
            {busy ? 'Registrando...' : 'Confirmar contagem'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={Boolean(selected)} onClose={() => setSelected(null)}
        title={`${recebendo ? 'Receber mercadoria' : 'Registrar perda'} — ${selected?.name || ''}`}
        subtitle={recebendo
          ? 'Quanto chegou na unidade.'
          : 'Quanto se perdeu: avaria, vencimento ou quebra.'}
      >
        <form onSubmit={submit} className="space-y-4">
          <Field label={recebendo ? 'Quantidade recebida' : 'Quantidade perdida'} type="number" value={form.quantity} onChange={(value) => setForm({ ...form, quantity: value })} placeholder={recebendo ? 'Ex.: 24' : 'Ex.: 2'} />
          <Field label="Motivo" value={form.reason} onChange={(value) => setForm({ ...form, reason: value })} />
          {movementError && (
            <p role="alert" className="rounded-xl border border-state-danger-border bg-state-danger-soft p-3 text-xs font-bold text-state-danger">
              {movementError}
            </p>
          )}
          <button disabled={busy || !form.quantity || form.reason.length < 3} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40">
            {busy ? 'Registrando...' : recebendo ? 'Confirmar recebimento' : 'Registrar perda'}
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
  const situacao = stockSituation(item)
  if (situacao === 'SEM_ESTOQUE') {
    return <span className="rounded-full bg-state-danger-soft px-2 py-1 text-xs font-black text-state-danger">Sem estoque</span>
  }
  if (situacao === 'REPOR') {
    return <span className="rounded-full bg-state-danger-soft px-2 py-1 text-xs font-black text-state-danger">Repor</span>
  }
  if (situacao === 'ATENCAO') {
    const folga = Number(item.quantity) - Number(item.minimum_stock)
    return (
      <span className="rounded-full bg-state-warning-soft px-2 py-1 text-xs font-black text-state-warning">
        Atenção · folga de {folga} {item.unit.toLowerCase()}
      </span>
    )
  }
  if (situacao === 'SEM_REFERENCIA') {
    return <span className="rounded-full bg-dashem-surface-elevated px-2 py-1 text-xs font-black text-dashem-muted">Sem referência</span>
  }
  return <span className="rounded-full bg-state-success-soft px-2 py-1 text-xs font-black text-state-success">Saudável</span>
}

/**
 * O resumo conclui em vez de contar.
 *
 * Ele obedece ao pior risco relevante: havendo um item em falta entre cem
 * saudáveis, a faixa não anuncia normalidade — ela diz que há um item exigindo
 * ação (ADR-033, ADR-034).
 */
function Resumo({ controlados, semEstoque, exigindoAcao }: {
  controlados: number; semEstoque: number; exigindoAcao: number
}) {
  if (controlados === 0) return null
  if (exigindoAcao === 0) {
    return (
      <div className="mt-6 flex items-center gap-3 rounded-2xl bg-state-success-soft p-4">
        <CheckCircle2 className="h-5 w-5 shrink-0 text-state-success" />
        <div>
          <p className="text-sm font-black text-state-success">Estoque saudável</p>
          <p className="text-xs text-state-success">Nenhum item requer ação agora · {controlados} acompanhados</p>
        </div>
      </div>
    )
  }
  return (
    <div className="mt-6 flex items-center gap-3 rounded-2xl bg-state-warning-soft p-4">
      <AlertTriangle className="h-5 w-5 shrink-0 text-state-warning" />
      <div>
        <p className="text-sm font-black text-state-warning">
          {exigindoAcao === 1 ? '1 produto precisa de atenção' : `${exigindoAcao} produtos precisam de atenção`}
        </p>
        <p className="text-xs text-state-warning">
          {controlados} acompanhados · {semEstoque === 0 ? 'nenhum sem estoque' : semEstoque === 1 ? '1 sem estoque' : `${semEstoque} sem estoque`}
        </p>
      </div>
    </div>
  )
}


function Field({ label, value, onChange, type = 'text', required = true, placeholder }: {
  label: string; value: string; onChange: (value: string) => void
  type?: string; required?: boolean; placeholder?: string
}) {
  return (
    <label className="block text-xs font-black text-dashem-strong">
      {label}
      <input
        required={required} type={type} step={type === 'number' ? '0.0001' : undefined}
        placeholder={placeholder}
        value={value} onChange={(event) => onChange(event.target.value)}
        className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong outline-none focus:border-dashem-red"
      />
    </label>
  )
}
