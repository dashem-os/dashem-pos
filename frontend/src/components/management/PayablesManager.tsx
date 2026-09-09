import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CalendarClock, Check, Pencil, RotateCcw, Scale, Search, Undo2 } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Modal } from '../common/Modal'
import { RowAction, RowActions } from '../common/RowActions'
import { DataTable } from '../common/DataTable'
import * as api from '../../services/api'

/**
 * Contas a pagar.
 *
 * O contrato está em `docs/product/ux-10-contas-a-pagar-contrato.md`. Três
 * decisões de tela que vêm dele:
 *
 * **A lista abre no que está em aberto, ordenada por vencimento.** Quem entra
 * aqui está decidindo o que pagar hoje, não navegando um cadastro. "Vencida" é
 * derivada no servidor — não existe coluna que alguém precise virar à
 * meia-noite — e a tela só a mostra.
 *
 * **Baixa parcial é primeira classe.** Um sistema que só aceita baixa total
 * obriga a pessoa a registrar como paga uma conta que não está, e o dado passa
 * a valer menos que o caderno que ele substituiu.
 *
 * **Nada aqui calcula juros, multa ou desconto.** Ajuste é valor digitado com
 * motivo obrigatório — o registro de uma decisão humana, não uma regra que eu
 * teria escolhido sozinho para desbloquear a sprint.
 */
export function PayablesManager() {
  const { tenant, store, permissions, showToast } = usePos()
  const headers = useMemo<Record<string, string>>(
    () => (tenant ? { 'X-Tenant-ID': tenant.id, ...(store ? { 'X-Store-ID': store.id } : {}) } : {}),
    [tenant, store],
  )

  const podeLancar = permissions.includes('payable.manage')
  const podeBaixar = permissions.includes('payable.settle')
  const podeReverter = permissions.includes('payable.reverse')

  const [contas, setContas] = useState<api.Payable[]>([])
  const [fornecedores, setFornecedores] = useState<api.Supplier[]>([])
  const [situacao, setSituacao] = useState<api.PayableFilter>('ABERTAS')
  const [busca, setBusca] = useState('')
  const [carregando, setCarregando] = useState(true)
  const [erroDeCarga, setErroDeCarga] = useState('')
  const [ocupado, setOcupado] = useState(false)

  const carregar = useCallback(async () => {
    if (!tenant) return
    setCarregando(true)
    try {
      setContas(await api.fetchPayables(headers, { situacao, busca: busca.trim() || undefined }))
      setErroDeCarga('')
    } catch (motivo) {
      // Lista vazia por falha e lista vazia por não haver conta são coisas
      // diferentes, e confundi-las faz o lojista achar que não deve nada.
      setContas([])
      setErroDeCarga(motivo instanceof Error ? motivo.message : 'Não foi possível carregar.')
    } finally { setCarregando(false) }
  }, [tenant, headers, situacao, busca])

  useEffect(() => { void carregar() }, [carregar])
  useEffect(() => {
    if (!tenant || !permissions.includes('supplier.read')) return
    let ativo = true
    api.fetchSuppliers(headers)
      .then((lista) => { if (ativo) setFornecedores(lista) })
      .catch(() => { if (ativo) setFornecedores([]) })
    return () => { ativo = false }
  }, [tenant, headers, permissions])

  // ------------------------------------------------------------- lançar
  const [lancando, setLancando] = useState(false)
  const [formulario, setFormulario] = useState(vazio())
  const [erroDoFormulario, setErroDoFormulario] = useState('')
  // Uma intenção, uma chave: reenviar depois de um erro de rede reusa a mesma,
  // e o servidor devolve a mesma conta em vez de abrir a segunda.
  const [chaveDoLancamento, setChaveDoLancamento] = useState('')

  const abrirLancamento = () => {
    setFormulario(vazio())
    setErroDoFormulario('')
    setChaveDoLancamento(crypto.randomUUID())
    setLancando(true)
  }

  const lancar = async (evento: React.FormEvent) => {
    evento.preventDefault()
    if (ocupado) return
    setOcupado(true); setErroDoFormulario('')
    try {
      await api.createPayable(headers, chaveDoLancamento, {
        supplier_id: formulario.supplier_id || null,
        payee_name: formulario.payee_name.trim() || null,
        description: formulario.description.trim() || null,
        amount: formulario.amount,
        due_on: formulario.due_on,
      })
      showToast('success', 'Conta lançada.')
      setLancando(false)
      await carregar()
    } catch (motivo) {
      setErroDoFormulario(motivo instanceof Error ? motivo.message : 'Não foi possível lançar.')
    } finally { setOcupado(false) }
  }

  // -------------------------------------------------------------- a conta
  const [aberta, setAberta] = useState<api.Payable | null>(null)
  const [erroDaConta, setErroDaConta] = useState('')
  const [baixa, setBaixa] = useState({ amount: '', method: '', occurred_on: hoje() })
  const [chaveDaBaixa, setChaveDaBaixa] = useState('')

  const abrirConta = async (conta: api.Payable) => {
    setErroDaConta('')
    setBaixa({ amount: '', method: '', occurred_on: hoje() })
    setChaveDaBaixa(crypto.randomUUID())
    try {
      // A lista não traz a razão — são muitas contas, e quem olha a lista está
      // decidindo o que pagar. Ao abrir uma, a razão inteira vem junto.
      setAberta(await api.fetchPayable(headers, conta.id))
    } catch {
      setAberta(conta)
    }
  }

  const darBaixa = async (evento: React.FormEvent) => {
    evento.preventDefault()
    if (!aberta || ocupado) return
    setOcupado(true); setErroDaConta('')
    try {
      const atualizada = await api.settlePayable(headers, aberta.id, chaveDaBaixa, {
        amount: baixa.amount,
        method: baixa.method.trim() || null,
        occurred_on: baixa.occurred_on,
        // A versão que a pessoa tinha à vista. Quem perde a corrida é recusado
        // com o saldo atual, não com um "tente de novo" que não explica nada.
        version: aberta.version,
      })
      setAberta(atualizada)
      setBaixa({ amount: '', method: '', occurred_on: hoje() })
      setChaveDaBaixa(crypto.randomUUID())
      showToast('success', Number(atualizada.balance) > 0
        ? `Baixa registrada. Ainda faltam ${dinheiro(atualizada.balance)}.`
        : 'Conta paga.')
      await carregar()
    } catch (motivo) {
      setErroDaConta(motivo instanceof Error ? motivo.message : 'A baixa não foi registrada.')
    } finally { setOcupado(false) }
  }

  // Juros, multa e abatimento entram por aqui: **digitados**, com motivo. O
  // sistema não calcula nenhum dos três — regra de cálculo é decisão do dono, e
  // escolher uma para desbloquear a sprint é como o número fica errado.
  const [ajuste, setAjuste] = useState({ amount: '', reason: '' })
  const [ajustando, setAjustando] = useState(false)

  const lancarAjuste = async (evento: React.FormEvent) => {
    evento.preventDefault()
    if (!aberta || ocupado) return
    setOcupado(true); setErroDaConta('')
    try {
      const atualizada = await api.adjustPayable(headers, aberta.id, crypto.randomUUID(), {
        amount: ajuste.amount, reason: ajuste.reason.trim(), version: aberta.version,
      })
      setAberta(atualizada)
      setAjuste({ amount: '', reason: '' })
      setAjustando(false)
      showToast('success', 'Ajuste lançado no histórico da conta.')
      await carregar()
    } catch (motivo) {
      setErroDaConta(motivo instanceof Error ? motivo.message : 'O ajuste não foi lançado.')
    } finally { setOcupado(false) }
  }

  // Corrigir cadastro da conta. O **valor** não se edita aqui: mudar o valor de
  // uma dívida é ajuste, que deixa rastro e pede motivo.
  const [editando, setEditando] = useState<api.Payable | null>(null)

  const abrirEdicao = (conta: api.Payable) => {
    setFormulario({
      supplier_id: conta.supplier_id || '', payee_name: conta.payee_name,
      amount: conta.principal_amount, due_on: conta.due_on.slice(0, 10),
      description: conta.description || '',
    })
    setErroDoFormulario('')
    setEditando(conta)
  }

  const salvarEdicao = async (evento: React.FormEvent) => {
    evento.preventDefault()
    if (!editando || ocupado) return
    setOcupado(true); setErroDoFormulario('')
    try {
      await api.updatePayable(headers, editando.id, {
        payee_name: formulario.payee_name.trim(),
        supplier_id: formulario.supplier_id || null,
        description: formulario.description.trim() || null,
        due_on: formulario.due_on,
      })
      showToast('success', 'Conta atualizada.')
      setEditando(null)
      await carregar()
    } catch (motivo) {
      setErroDoFormulario(motivo instanceof Error ? motivo.message : 'Não foi possível salvar.')
    } finally { setOcupado(false) }
  }

  const reverter = async (entrada: api.PayableLedgerEntry) => {
    if (!aberta || ocupado) return
    const motivo = window.prompt(
      'Por que este lançamento está sendo desfeito? O motivo fica no histórico.')
    if (!motivo || motivo.trim().length < 3) return
    setOcupado(true); setErroDaConta('')
    try {
      const atualizada = await api.reversePayableEntry(headers, aberta.id, crypto.randomUUID(), {
        entry_id: entrada.id, reason: motivo.trim(), version: aberta.version,
      })
      setAberta(atualizada)
      showToast('success', 'Lançamento desfeito. Os dois ficam no histórico.')
      await carregar()
    } catch (falha) {
      setErroDaConta(falha instanceof Error ? falha.message : 'Não foi possível reverter.')
    } finally { setOcupado(false) }
  }

  const arquivar = async (conta: api.Payable) => {
    const motivo = window.prompt('Por que esta conta está sendo arquivada?')
    if (!motivo || motivo.trim().length < 3) return
    setOcupado(true)
    try {
      await api.archivePayable(headers, conta.id, { reason: motivo.trim(), version: conta.version })
      showToast('success', 'Conta arquivada. Ela sai da lista e continua no histórico.')
      await carregar()
    } catch (falha) {
      showToast('error', falha instanceof Error ? falha.message : 'Não foi possível arquivar.')
    } finally { setOcupado(false) }
  }

  const emAberto = contas.filter((c) => c.status === 'OPEN' || c.status === 'PARTIALLY_PAID')
  const vencidas = emAberto.filter((c) => c.is_overdue)
  const totalEmAberto = emAberto.reduce((soma, c) => soma + Number(c.balance), 0)

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-black uppercase tracking-wide text-state-success">Financeiro</p>
            <h1 className="text-2xl font-black text-dashem-strong">Contas a pagar</h1>
            <p className="mt-1 max-w-2xl text-sm leading-5 text-dashem-muted">
              O que você deve e quando vence. Receber mercadoria não lança conta aqui:
              quem lança é você.
            </p>
          </div>
          {podeLancar && (
            <button
              onClick={abrirLancamento}
              className="min-h-11 rounded-xl bg-dashem-red px-4 text-sm font-black text-brand-contrast"
            >
              Lançar conta
            </button>
          )}
        </div>

        {vencidas.length > 0 && (
          <div className="mt-4 flex items-center gap-3 rounded-xl border border-state-danger-border bg-state-danger-soft p-3">
            <AlertTriangle className="h-5 w-5 shrink-0 text-state-danger" />
            <p className="text-sm font-bold text-state-danger">
              {vencidas.length === 1 ? '1 conta vencida' : `${vencidas.length} contas vencidas`}
              {' · '}{dinheiro(String(vencidas.reduce((s, c) => s + Number(c.balance), 0)))}
            </p>
          </div>
        )}
        {emAberto.length > 0 && (
          <p className="mt-3 text-sm font-bold text-dashem-strong">
            Em aberto: {dinheiro(String(totalEmAberto))} em {emAberto.length}
            {emAberto.length === 1 ? ' conta' : ' contas'}
          </p>
        )}
      </section>

      <section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dashem-muted" />
            <input
              value={busca} onChange={(evento) => setBusca(evento.target.value)}
              placeholder="Buscar pelo favorecido..."
              className="h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface pl-9 pr-3 text-sm font-bold text-dashem-strong"
            />
          </div>
          <div role="tablist" aria-label="Situação das contas" className="flex flex-wrap gap-2">
            {([['ABERTAS', 'Em aberto'], ['VENCIDAS', 'Vencidas'],
               ['PAGAS', 'Pagas'], ['ARQUIVADAS', 'Arquivadas']] as const).map(([chave, rotulo]) => (
              <button
                key={chave} role="tab" aria-selected={situacao === chave}
                onClick={() => setSituacao(chave)}
                className={`min-h-11 rounded-xl px-4 text-xs font-black transition
                  ${situacao === chave ? 'bg-brand text-brand-contrast' : 'border border-dashem-border text-dashem-muted'}`}
              >
                {rotulo}
              </button>
            ))}
          </div>
        </div>

        {erroDeCarga && (
          <p role="alert" className="mt-4 rounded-xl border border-state-danger-border bg-state-danger-soft p-3 text-xs font-bold text-state-danger">
            {erroDeCarga}
          </p>
        )}

        <div className="mt-4">
          <DataTable<api.Payable>
            rows={contas}
            rowKey={(conta) => conta.id}
            empty={carregando ? 'Carregando...' : erroDeCarga
              ? 'A lista não carregou. Isso não quer dizer que você não deve nada.'
              : 'Nenhuma conta nesta situação.'}
            columns={[
              {
                key: 'payee', header: 'Favorecido',
                cell: (conta) => (
                  <div>
                    <p className="font-black text-dashem-strong">{conta.payee_name}</p>
                    {conta.description && (
                      <p className="text-xs text-dashem-muted">{conta.description}</p>
                    )}
                  </div>
                ),
              },
              {
                key: 'due', header: 'Vencimento',
                cell: (conta) => <Vencimento conta={conta} />,
              },
              {
                key: 'amount', header: 'Saldo', align: 'right',
                cell: (conta) => (
                  <div className="text-right">
                    <p className="text-base font-black text-dashem-strong">{dinheiro(conta.balance)}</p>
                    {Number(conta.paid_amount) > 0 && (
                      <p className="text-[11px] text-dashem-muted">
                        {dinheiro(conta.paid_amount)} já pago de {dinheiro(conta.principal_amount)}
                      </p>
                    )}
                  </div>
                ),
              },
              {
                key: 'action', header: 'Ação', actions: true, align: 'right',
                cell: (conta) => (
                  <div className="flex flex-nowrap items-center justify-end gap-2">
                    {podeBaixar && (conta.status === 'OPEN' || conta.status === 'PARTIALLY_PAID') && (
                      <button
                        onClick={() => { void abrirConta(conta) }}
                        className="inline-flex min-h-11 items-center rounded-xl border border-dashem-border px-3 text-xs font-black text-dashem-strong"
                      >
                        <Check className="mr-1.5 inline h-4 w-4 text-state-success" />Dar baixa
                      </button>
                    )}
                    <RowActions label={`Ações de ${conta.payee_name}`}>
                      <RowAction icon={CalendarClock} onClick={() => { void abrirConta(conta) }}>
                        Ver histórico
                      </RowAction>
                      {podeLancar && conta.status !== 'ARCHIVED' && (
                        <RowAction icon={Pencil} onClick={() => abrirEdicao(conta)}>
                          Corrigir dados da conta
                        </RowAction>
                      )}
                      {podeLancar && conta.status !== 'ARCHIVED' && Number(conta.paid_amount) === 0 && (
                        <RowAction icon={RotateCcw} tone="critical" onClick={() => { void arquivar(conta) }}>
                          Arquivar conta
                        </RowAction>
                      )}
                    </RowActions>
                  </div>
                ),
              },
            ]}
          />
        </div>
      </section>

      <Modal
        isOpen={lancando} onClose={() => setLancando(false)}
        title="Lançar conta a pagar"
        subtitle="Nada lança sozinho: receber mercadoria não cria dívida."
      >
        <form onSubmit={lancar} className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-xs font-black uppercase tracking-wide text-brand-ink-soft">
              Fornecedor
            </span>
            <select
              value={formulario.supplier_id}
              onChange={(evento) => setFormulario({ ...formulario, supplier_id: evento.target.value })}
              className="h-12 w-full rounded-xl border border-brand-line bg-brand-surface px-3 text-sm font-bold text-brand-ink"
            >
              <option value="">Não é fornecedor cadastrado</option>
              {fornecedores.filter((f) => f.status === 'ACTIVE').map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
            <span className="mt-1.5 block text-xs font-semibold text-brand-ink-soft">
              A conta de luz não tem fornecedor cadastrado — escreva o nome abaixo.
            </span>
          </label>
          <Campo
            label="Favorecido" value={formulario.payee_name}
            onChange={(valor) => setFormulario({ ...formulario, payee_name: valor })}
            placeholder="Ex.: Companhia de Energia"
          />
          <Campo
            label="Valor" type="number" value={formulario.amount}
            onChange={(valor) => setFormulario({ ...formulario, amount: valor })}
            placeholder="Ex.: 480,00"
          />
          <Campo
            label="Vencimento" type="date" value={formulario.due_on}
            onChange={(valor) => setFormulario({ ...formulario, due_on: valor })}
          />
          <Campo
            label="Descrição" value={formulario.description}
            onChange={(valor) => setFormulario({ ...formulario, description: valor })}
            placeholder="Ex.: Energia de setembro"
          />
          {erroDoFormulario && (
            <p role="alert" className="rounded-xl border border-state-danger-border bg-state-danger-soft p-3 text-xs font-bold text-state-danger">
              {erroDoFormulario}
            </p>
          )}
          <button
            disabled={ocupado || !formulario.amount || !formulario.due_on
              || (!formulario.payee_name.trim() && !formulario.supplier_id)}
            className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40"
          >
            {ocupado ? 'Lançando...' : 'Lançar conta'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={Boolean(editando)} onClose={() => setEditando(null)}
        title="Corrigir dados da conta"
        subtitle="O valor não se corrige aqui: mudar o valor de uma dívida é ajuste, e ajuste pede motivo."
      >
        <form onSubmit={salvarEdicao} className="space-y-4">
          <Campo
            label="Favorecido" value={formulario.payee_name}
            onChange={(valor) => setFormulario({ ...formulario, payee_name: valor })}
          />
          <Campo
            label="Vencimento" type="date" value={formulario.due_on}
            onChange={(valor) => setFormulario({ ...formulario, due_on: valor })}
          />
          <Campo
            label="Descrição" value={formulario.description}
            onChange={(valor) => setFormulario({ ...formulario, description: valor })}
          />
          {erroDoFormulario && (
            <p role="alert" className="rounded-xl border border-state-danger-border bg-state-danger-soft p-3 text-xs font-bold text-state-danger">
              {erroDoFormulario}
            </p>
          )}
          <button
            disabled={ocupado || !formulario.payee_name.trim() || !formulario.due_on}
            className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40"
          >
            {ocupado ? 'Salvando...' : 'Salvar'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={Boolean(aberta)} onClose={() => setAberta(null)}
        title={aberta ? `${aberta.payee_name} — ${dinheiro(aberta.balance)}` : ''}
        subtitle={aberta ? resumo(aberta) : ''}
      >
        {aberta && (
          <div className="space-y-5">
            {podeBaixar && (aberta.status === 'OPEN' || aberta.status === 'PARTIALLY_PAID') && (
              <form onSubmit={darBaixa} className="space-y-3 rounded-2xl border border-dashem-border p-4">
                <p className="text-xs font-black uppercase tracking-wide text-brand-ink-soft">
                  Registrar pagamento
                </p>
                <Campo
                  label="Valor pago" type="number" value={baixa.amount}
                  onChange={(valor) => setBaixa({ ...baixa, amount: valor })}
                  placeholder={`Até ${dinheiro(aberta.balance)}`}
                />
                <Campo
                  label="Forma" value={baixa.method}
                  onChange={(valor) => setBaixa({ ...baixa, method: valor })}
                  placeholder="Ex.: Pix, dinheiro, transferência"
                />
                <Campo
                  label="Data do pagamento" type="date" value={baixa.occurred_on}
                  onChange={(valor) => setBaixa({ ...baixa, occurred_on: valor })}
                />
                <p className="text-xs font-semibold text-brand-ink-soft">
                  Pode ser parcial: o que faltar continua em aberto.
                </p>
                <button
                  disabled={ocupado || !baixa.amount}
                  className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40"
                >
                  {ocupado ? 'Registrando...' : 'Registrar pagamento'}
                </button>
              </form>
            )}

            {podeBaixar && (aberta.status === 'OPEN' || aberta.status === 'PARTIALLY_PAID') && (
              ajustando ? (
                <form onSubmit={lancarAjuste} className="space-y-3 rounded-2xl border border-dashem-border p-4">
                  <p className="text-xs font-black uppercase tracking-wide text-brand-ink-soft">
                    Ajustar valor
                  </p>
                  <Campo
                    label="Valor do ajuste" type="number" value={ajuste.amount}
                    onChange={(valor) => setAjuste({ ...ajuste, amount: valor })}
                    placeholder="Positivo acresce, negativo abate"
                  />
                  <Campo
                    label="Motivo do ajuste" value={ajuste.reason}
                    onChange={(valor) => setAjuste({ ...ajuste, reason: valor })}
                    placeholder="Ex.: multa de atraso combinada por telefone"
                  />
                  <p className="text-xs font-semibold text-brand-ink-soft">
                    O sistema não calcula juros nem desconto: o valor é o que você combinou.
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button" onClick={() => setAjustando(false)}
                      className="h-12 flex-1 rounded-xl border border-dashem-border text-sm font-black text-dashem-strong"
                    >
                      Cancelar
                    </button>
                    <button
                      disabled={ocupado || !ajuste.amount || ajuste.reason.trim().length < 3}
                      className="h-12 flex-1 rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40"
                    >
                      {ocupado ? 'Lançando...' : 'Lançar ajuste'}
                    </button>
                  </div>
                </form>
              ) : (
                <button
                  onClick={() => setAjustando(true)}
                  className="inline-flex min-h-11 items-center rounded-xl border border-dashem-border px-3 text-xs font-black text-dashem-strong"
                >
                  <Scale className="mr-1.5 inline h-4 w-4" />Ajustar valor (juros, multa ou desconto)
                </button>
              )
            )}

            {erroDaConta && (
              <p role="alert" className="rounded-xl border border-state-danger-border bg-state-danger-soft p-3 text-xs font-bold text-state-danger">
                {erroDaConta}
              </p>
            )}

            <div>
              <p className="text-xs font-black uppercase tracking-wide text-brand-ink-soft">Histórico</p>
              <div className="mt-2 divide-y divide-dashem-border">
                {aberta.ledger.map((entrada) => (
                  <div key={entrada.id} className="flex items-start justify-between gap-3 py-2.5">
                    <div>
                      <p className={`text-xs font-black ${entrada.reversed_by_entry_id ? 'text-dashem-muted line-through' : 'text-dashem-strong'}`}>
                        {rotuloDoLancamento(entrada)} · {dinheiro(Math.abs(Number(entrada.amount)))}
                      </p>
                      <p className="text-[11px] text-dashem-muted">
                        {formatarData(entrada.occurred_on)}
                        {entrada.method ? ` · ${entrada.method}` : ''}
                        {entrada.reason ? ` · ${entrada.reason}` : ''}
                      </p>
                      {entrada.reversed_by_entry_id && (
                        <p className="text-[11px] font-bold text-state-warning">Desfeito</p>
                      )}
                    </div>
                    {podeReverter && !entrada.reversed_by_entry_id
                      && entrada.entry_type !== 'ISSUE' && entrada.entry_type !== 'REVERSAL' && (
                      <button
                        onClick={() => { void reverter(entrada) }}
                        disabled={ocupado}
                        className="inline-flex min-h-9 shrink-0 items-center rounded-xl border border-dashem-border px-2.5 text-[11px] font-black text-dashem-strong disabled:opacity-40"
                      >
                        <Undo2 className="mr-1 inline h-3.5 w-3.5" />Desfazer
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

function vazio() {
  return { supplier_id: '', payee_name: '', amount: '', due_on: hoje(), description: '' }
}

function hoje(): string {
  const agora = new Date()
  const mes = String(agora.getMonth() + 1).padStart(2, '0')
  const dia = String(agora.getDate()).padStart(2, '0')
  return `${agora.getFullYear()}-${mes}-${dia}`
}

/**
 * Dinheiro em português, com vírgula.
 *
 * A UX-08 achou uma tela escrevendo "R$ 25.00" com ponto enquanto o PDV, ao
 * lado, escrevia "R$ 80,00" — e quem confere não sabe qual das duas está certa.
 * Toda quantia desta tela passa por aqui.
 */
function dinheiro(valor: string | number): string {
  return Number(valor).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function formatarData(iso: string): string {
  const [ano, mes, dia] = iso.slice(0, 10).split('-')
  return `${dia}/${mes}/${ano}`
}

/**
 * O rótulo carrega a direção, então o valor não precisa do sinal.
 *
 * "Pagamento · -R$ 1.000,00" faz o lojista ler duas vezes para entender que
 * saiu mil reais. A palavra já disse o que aconteceu; o número só precisa
 * dizer quanto.
 */
function rotuloDoLancamento(entrada: api.PayableLedgerEntry): string {
  if (entrada.entry_type === 'ISSUE') return 'Conta lançada'
  if (entrada.entry_type === 'PAYMENT') return 'Pagamento'
  if (entrada.entry_type === 'REVERSAL') return 'Lançamento desfeito'
  return Number(entrada.amount) > 0 ? 'Acréscimo' : 'Abatimento'
}

function resumo(conta: api.Payable): string {
  if (conta.status === 'PAID') return 'Conta paga.'
  if (conta.status === 'ARCHIVED') return `Arquivada: ${conta.archived_reason || 'sem motivo registrado'}.`
  if (Number(conta.paid_amount) > 0) {
    return `${dinheiro(conta.paid_amount)} já pago de ${dinheiro(conta.principal_amount)}.`
  }
  return `Vence em ${formatarData(conta.due_on)}.`
}

/**
 * "Vencida" não é situação gravada: ela é a data contra hoje, e o servidor a
 * deriva. Uma coluna gravada obrigaria alguém a virar linhas à meia-noite — e
 * esse processo não existe, então a lista mentiria por um dia inteiro.
 */
function Vencimento({ conta }: { conta: api.Payable }) {
  const data = formatarData(conta.due_on)
  if (conta.status === 'PAID' || conta.status === 'ARCHIVED') {
    return <span className="text-xs font-bold text-dashem-muted">{data}</span>
  }
  if (conta.is_overdue) {
    const dias = Math.abs(conta.days_to_due)
    return (
      <span className="inline-flex items-center rounded-lg bg-state-danger-soft px-2 py-1 text-xs font-black text-state-danger">
        {data} · venceu há {dias === 1 ? '1 dia' : `${dias} dias`}
      </span>
    )
  }
  if (conta.days_to_due === 0) {
    return (
      <span className="inline-flex items-center rounded-lg bg-state-warning-soft px-2 py-1 text-xs font-black text-state-warning">
        {data} · vence hoje
      </span>
    )
  }
  return <span className="text-xs font-bold text-dashem-strong">{data}</span>
}

function Campo({ label, value, onChange, type = 'text', placeholder }: {
  label: string; value: string; onChange: (valor: string) => void
  type?: string; placeholder?: string
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-black uppercase tracking-wide text-brand-ink-soft">
        {label}
      </span>
      <input
        type={type} value={value} placeholder={placeholder}
        onChange={(evento) => onChange(evento.target.value)}
        className="h-12 w-full rounded-xl border border-brand-line bg-brand-surface px-3 text-sm font-bold text-brand-ink"
      />
    </label>
  )
}
