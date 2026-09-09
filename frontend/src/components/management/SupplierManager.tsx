import React, { useCallback, useEffect, useState } from 'react'
import { Building2, Phone, Plus, Search, Star, Trash2 } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { DataTable } from '../common/DataTable'
import { Modal } from '../common/Modal'
import { EmptyState } from '../common/EmptyState'
import * as api from '../../services/api'

/**
 * Quem fornece a mercadoria.
 *
 * Domínio novo: o inventário da UX-09 não achou nem tabela, nem rota, nem tela.
 * O que esta tela faz é o que o enunciado pediu — cadastrar, achar, manter os
 * contatos e mostrar o vínculo com os recebimentos.
 *
 * **Não há pedido de compra.** Nenhum botão aqui promete comprar, aprovar ou
 * receber pedido: o enunciado proíbe inventá-lo como entregue, e um card que
 * promete o que não existe é o botão morto que o contrato de navegação recusa.
 *
 * O documento é opcional de propósito. Muita reposição de bairro não tem nota
 * no cadastro, e exigir CNPJ para registrar o hortifruti da esquina inventaria
 * uma burocracia que a operação real não tem.
 */
export const SupplierManager: React.FC = () => {
  const { tenant, permissions, showToast } = usePos()
  const podeEditar = permissions.includes('supplier.manage')
  const cabecalhos: Record<string, string> = tenant ? { 'X-Tenant-ID': tenant.id } : {}

  const [fornecedores, setFornecedores] = useState<api.Supplier[]>([])
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState<string | null>(null)
  const [busca, setBusca] = useState('')
  const [incluirInativos, setIncluirInativos] = useState(false)

  const [cadastro, setCadastro] = useState<{ name: string; legal_name: string; document: string; notes: string } | null>(null)
  const [editando, setEditando] = useState<api.Supplier | null>(null)
  const [salvando, setSalvando] = useState(false)
  // A chave nasce quando o formulário abre: reenviar depois de um erro de rede
  // devolve o mesmo cadastro, em vez de abrir um segundo fornecedor igual.
  const [chaveDoCadastro, setChaveDoCadastro] = useState('')

  const [contatosDe, setContatosDe] = useState<api.Supplier | null>(null)
  const [novoContato, setNovoContato] = useState({ name: '', role: '', email: '', phone: '', is_primary: false })

  const carregar = useCallback(async () => {
    if (!tenant) return
    setCarregando(true)
    try {
      setFornecedores(await api.fetchSuppliers(cabecalhos, { busca: busca.trim() || undefined, incluirInativos }))
      setErro(null)
    } catch (motivo) {
      setErro(motivo instanceof Error ? motivo.message : 'Não foi possível carregar os fornecedores.')
      setFornecedores([])
    } finally { setCarregando(false) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenant?.id, busca, incluirInativos])

  useEffect(() => {
    const atraso = window.setTimeout(() => { void carregar() }, 300)
    return () => window.clearTimeout(atraso)
  }, [carregar])

  const abrirCadastro = () => {
    setCadastro({ name: '', legal_name: '', document: '', notes: '' })
    setEditando(null)
    setChaveDoCadastro(crypto.randomUUID())
    setErro(null)
  }

  const abrirEdicao = (fornecedor: api.Supplier) => {
    setEditando(fornecedor)
    setCadastro({
      name: fornecedor.name, legal_name: fornecedor.legal_name || '',
      document: fornecedor.document || '', notes: fornecedor.notes || '',
    })
    setErro(null)
  }

  const salvar = async (evento: React.FormEvent) => {
    evento.preventDefault()
    if (!cadastro || salvando) return
    setSalvando(true); setErro(null)
    try {
      // `null`, e não `undefined`: apagar o campo na tela precisa chegar ao
      // servidor como "apague". `undefined` some do JSON, e o campo antigo
      // ficava lá — o lojista apagava o CNPJ errado, salvava, e ele voltava.
      const corpo = {
        name: cadastro.name.trim(),
        legal_name: apagavel(cadastro.legal_name),
        document: apagavel(cadastro.document),
        notes: apagavel(cadastro.notes),
      }
      if (editando) {
        await api.updateSupplier(cabecalhos, editando.id, corpo)
        showToast('success', 'Fornecedor atualizado.')
      } else {
        await api.createSupplier(cabecalhos, chaveDoCadastro, corpo)
        showToast('success', 'Fornecedor cadastrado.')
      }
      setCadastro(null); setEditando(null)
      await carregar()
    } catch (motivo) {
      setErro(motivo instanceof Error ? motivo.message : 'Não foi possível salvar.')
    } finally { setSalvando(false) }
  }

  const alternarSituacao = async (fornecedor: api.Supplier) => {
    try {
      await api.updateSupplier(cabecalhos, fornecedor.id, {
        status: fornecedor.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE',
      })
      showToast('success', fornecedor.status === 'ACTIVE'
        ? 'Fornecedor arquivado. O histórico de recebimentos continua.'
        : 'Fornecedor reativado.')
      await carregar()
    } catch (motivo) {
      showToast('error', motivo instanceof Error ? motivo.message : 'Não foi possível alterar a situação.')
    }
  }

  const adicionarContato = async (evento: React.FormEvent) => {
    evento.preventDefault()
    if (!contatosDe || !novoContato.name.trim()) return
    setSalvando(true)
    try {
      const atualizado = await api.addSupplierContact(cabecalhos, contatosDe.id, {
        name: novoContato.name, role: novoContato.role || undefined,
        email: novoContato.email || undefined, phone: novoContato.phone || undefined,
        is_primary: novoContato.is_primary,
      })
      setContatosDe(atualizado)
      setNovoContato({ name: '', role: '', email: '', phone: '', is_primary: false })
      await carregar()
    } catch (motivo) {
      setErro(motivo instanceof Error ? motivo.message : 'Não foi possível adicionar o contato.')
    } finally { setSalvando(false) }
  }

  const removerContato = async (contatoId: string) => {
    if (!contatosDe) return
    try {
      setContatosDe(await api.removeSupplierContact(cabecalhos, contatosDe.id, contatoId))
      await carregar()
    } catch (motivo) {
      setErro(motivo instanceof Error ? motivo.message : 'Não foi possível remover o contato.')
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-black uppercase tracking-[.18em] text-brand-ink">Relacionamento</p>
            <h1 className="mt-1 text-2xl font-black text-dashem-strong">Fornecedores</h1>
            <p className="mt-1 max-w-2xl text-sm leading-5 text-dashem-muted">
              Quem fornece as suas mercadorias, com quem falar e o que já chegou de cada um.
            </p>
          </div>
          {podeEditar && (
            <button
              onClick={abrirCadastro}
              className="flex min-h-11 shrink-0 items-center gap-2 rounded-xl bg-dashem-red px-5 text-xs font-black text-brand-contrast"
            >
              <Plus className="h-4 w-4" />Cadastrar fornecedor
            </button>
          )}
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1">
          <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-dashem-muted" />
          <input
            value={busca}
            onChange={(evento) => setBusca(evento.target.value)}
            placeholder="Buscar por nome ou documento..."
            className="h-12 w-full rounded-xl border border-dashem-border bg-dashem-surface pl-11 pr-4 text-sm text-dashem-strong outline-none focus:border-brand"
          />
        </div>
        <label className="flex min-h-11 shrink-0 items-center gap-2 text-xs font-black text-dashem-muted">
          <input
            type="checkbox" checked={incluirInativos}
            onChange={(evento) => setIncluirInativos(evento.target.checked)}
            className="h-4 w-4"
          />
          Mostrar arquivados
        </label>
      </div>

      {erro && <p role="alert" className="text-sm font-bold text-state-danger">{erro}</p>}

      <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface">
        {carregando ? (
          <div className="p-10 text-center text-sm font-bold text-dashem-muted">Carregando fornecedores...</div>
        ) : fornecedores.length === 0 ? (
          <EmptyState
            icon={Building2}
            title={busca ? 'Nenhum fornecedor encontrado' : 'Nenhum fornecedor cadastrado'}
            description={busca
              ? 'Tente outro nome ou documento.'
              : 'Cadastre quem fornece as suas mercadorias para saber de quem veio cada recebimento.'}
          />
        ) : (
          <DataTable
            rows={fornecedores}
            rowKey={(fornecedor) => fornecedor.id}
            columns={[
              {
                key: 'nome', header: 'Fornecedor', primary: true,
                cell: (fornecedor) => (
                  <div>
                    <p className="font-black text-dashem-strong">{fornecedor.name}</p>
                    <p className="text-xs text-dashem-muted">
                      {fornecedor.legal_name || documentoLegivel(fornecedor.document) || 'Sem documento cadastrado'}
                    </p>
                  </div>
                ),
              },
              {
                key: 'contato', header: 'Contato',
                cell: (fornecedor) => {
                  const principal = fornecedor.contacts.find((contato) => contato.is_primary) || fornecedor.contacts[0]
                  return principal ? (
                    <div className="text-sm text-dashem-muted">
                      <p className="font-bold text-dashem-strong">{principal.name}</p>
                      <p className="text-xs">{principal.phone || principal.email || principal.role || '—'}</p>
                    </div>
                  ) : <span className="text-xs text-dashem-muted">Sem contato</span>
                },
              },
              {
                key: 'recebimentos', header: 'Recebimentos',
                cell: (fornecedor) => (
                  <span className="text-sm font-black text-dashem-strong">
                    {fornecedor.recebimentos === 0 ? 'Nenhum ainda' : fornecedor.recebimentos}
                  </span>
                ),
              },
              {
                key: 'situacao', header: 'Situação',
                cell: (fornecedor) => (
                  <span className={`rounded-full px-2 py-1 text-xs font-black ${fornecedor.status === 'ACTIVE'
                    ? 'bg-state-success-soft text-state-success'
                    : 'bg-dashem-bg text-dashem-muted'}`}>
                    {fornecedor.status === 'ACTIVE' ? 'Ativo' : 'Arquivado'}
                  </span>
                ),
              },
              {
                key: 'acoes', header: 'Ações', actions: true,
                cell: (fornecedor) => podeEditar ? (
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => setContatosDe(fornecedor)}
                      className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-muted">
                      <Phone className="h-3.5 w-3.5" />Contatos
                    </button>
                    <button onClick={() => abrirEdicao(fornecedor)}
                      className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-muted">
                      Editar
                    </button>
                    <button onClick={() => void alternarSituacao(fornecedor)}
                      className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-xs font-black text-dashem-muted">
                      {fornecedor.status === 'ACTIVE' ? 'Arquivar' : 'Reativar'}
                    </button>
                  </div>
                ) : null,
              },
            ]}
          />
        )}
      </section>

      {cadastro && (
        <Modal
          isOpen
          onClose={() => { setCadastro(null); setEditando(null) }}
          title={editando ? 'Editar fornecedor' : 'Cadastrar fornecedor'}
          subtitle="O documento é opcional: muita reposição chega de quem não tem CNPJ no cadastro."
        >
          <form onSubmit={salvar} className="space-y-4">
            <Campo label="Nome" value={cadastro.name} onChange={(valor) => setCadastro({ ...cadastro, name: valor })} required />
            <Campo label="Razão social" value={cadastro.legal_name} onChange={(valor) => setCadastro({ ...cadastro, legal_name: valor })} />
            <Campo label="CNPJ ou CPF" value={cadastro.document} onChange={(valor) => setCadastro({ ...cadastro, document: valor })} />
            <Campo label="Observações" value={cadastro.notes} onChange={(valor) => setCadastro({ ...cadastro, notes: valor })} />
            {erro && <p role="alert" className="text-sm font-bold text-state-danger">{erro}</p>}
            <button
              disabled={salvando || cadastro.name.trim().length < 2}
              className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-brand-contrast disabled:opacity-40"
            >
              {salvando ? 'Salvando...' : editando ? 'Salvar fornecedor' : 'Cadastrar fornecedor'}
            </button>
          </form>
        </Modal>
      )}

      {contatosDe && (
        <Modal
          isOpen
          onClose={() => { setContatosDe(null); setErro(null) }}
          title={`Contatos de ${contatosDe.name}`}
          subtitle="Um fornecedor tem o vendedor, o financeiro e quem entrega. Guardar um telefone só obriga a escolher qual deles cabe."
        >
          <div className="space-y-4">
            <div className="space-y-2">
              {contatosDe.contacts.length === 0 && (
                <p className="text-sm text-dashem-muted">Nenhum contato cadastrado ainda.</p>
              )}
              {contatosDe.contacts.map((contato) => (
                <div key={contato.id} className="flex items-center justify-between gap-3 rounded-xl border border-dashem-border bg-dashem-surface-elevated p-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-1.5 text-sm font-black text-dashem-strong">
                      {contato.is_primary && <Star className="h-3.5 w-3.5 text-state-warning" />}
                      {contato.name}
                    </p>
                    <p className="text-xs text-dashem-muted">
                      {[contato.role, contato.phone, contato.email].filter(Boolean).join(' · ') || '—'}
                    </p>
                  </div>
                  <button
                    onClick={() => void removerContato(contato.id)}
                    aria-label={`Remover ${contato.name}`}
                    className="inline-flex min-h-11 shrink-0 items-center rounded-lg px-3 text-xs font-black text-state-danger"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
            <form onSubmit={adicionarContato} className="space-y-3 rounded-xl border border-dashem-border p-3">
              <Campo label="Nome do contato" value={novoContato.name} onChange={(valor) => setNovoContato({ ...novoContato, name: valor })} required />
              <div className="grid gap-3 sm:grid-cols-2">
                <Campo label="Função" value={novoContato.role} onChange={(valor) => setNovoContato({ ...novoContato, role: valor })} />
                <Campo label="Telefone" value={novoContato.phone} onChange={(valor) => setNovoContato({ ...novoContato, phone: valor })} />
              </div>
              <Campo label="E-mail" value={novoContato.email} onChange={(valor) => setNovoContato({ ...novoContato, email: valor })} />
              <label className="flex min-h-11 items-center gap-2 text-xs font-black text-dashem-muted">
                <input
                  type="checkbox" checked={novoContato.is_primary}
                  onChange={(evento) => setNovoContato({ ...novoContato, is_primary: evento.target.checked })}
                  className="h-4 w-4"
                />
                Este é o contato principal
              </label>
              <button
                disabled={salvando || novoContato.name.trim().length < 2}
                className="h-11 w-full rounded-xl border border-dashem-border text-xs font-black text-dashem-strong disabled:opacity-40"
              >
                <Plus className="mr-1 inline h-3.5 w-3.5" />Adicionar contato
              </button>
            </form>
            {erro && <p role="alert" className="text-sm font-bold text-state-danger">{erro}</p>}
          </div>
        </Modal>
      )}
    </div>
  )
}

/** Campo opcional apagado vai como `null`; campo intocado vai como está. */
function apagavel(valor: string): string | null {
  const limpo = valor.trim()
  return limpo === '' ? null : limpo
}

/**
 * O documento é guardado sem máscara — é assim que se compara o CNPJ digitado
 * com pontos e o mesmo CNPJ digitado sem eles. Mostrar os caracteres crus,
 * porém, obriga o lojista a ler posição por posição para reconhecer o próprio
 * fornecedor.
 *
 * O CNPJ alfanumérico está em operação desde julho de 2026: as doze primeiras
 * posições podem ser letras, e só os dois dígitos verificadores são
 * obrigatoriamente numéricos. A máscara é a mesma; o que muda é o que cabe
 * dentro dela.
 */
function documentoLegivel(documento?: string): string | null {
  if (!documento) return null
  if (documento.length === 14) {
    return documento.replace(
      /^([A-Z\d]{2})([A-Z\d]{3})([A-Z\d]{3})([A-Z\d]{4})(\d{2})$/,
      '$1.$2.$3/$4-$5',
    )
  }
  if (documento.length === 11) {
    return documento.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, '$1.$2.$3-$4')
  }
  return documento
}

function Campo({ label, value, onChange, required = false }: {
  label: string; value: string; onChange: (valor: string) => void; required?: boolean
}) {
  return (
    <label className="block text-xs font-black text-dashem-strong">
      {label}
      <input
        required={required}
        value={value}
        onChange={(evento) => onChange(evento.target.value)}
        className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-dashem-strong outline-none focus:border-brand"
      />
    </label>
  )
}
