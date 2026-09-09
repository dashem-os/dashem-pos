import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, HelpCircle, RefreshCw, ShieldCheck, XCircle } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'
import { formatApiDateTime, parseApiDate } from '../../utils/format'

/**
 * Diagnóstico do sistema e acesso ao suporte.
 *
 * Duas perguntas do lojista, uma tela.
 *
 * **"Está tudo funcionando?"** As respostas vêm prontas do servidor, em
 * `resumo`. Se cada tela redigisse a sua, duas partes do produto passariam a
 * responder a mesma pergunta com palavras diferentes, e ele não saberia em qual
 * acreditar. Aqui a tela escolhe o ícone e a cor; a frase é do servidor.
 *
 * **"Quem entra nos meus dados?"** Até esta sprint, ninguém respondia: o acesso
 * do suporte era pedido pela plataforma e aprovado pela plataforma, e o dono dos
 * dados não via, não aprovava e não revogava. Agora quem decide é ele — e o que
 * ele decide está à vista: **quem** está pedindo, o escopo, o motivo e o prazo.
 *
 * A autorização é **nominal**. Ela vale para a pessoa que pediu, e para mais
 * ninguém. Uma tela que promete dizer quem tem acesso aos dados e mostra um
 * pedido anônimo promete mais do que entrega.
 *
 * Uma regra que atravessa tudo: **silêncio não é saúde.** Quando a verificação
 * falha, a tela diz que não conseguiu verificar. Nunca verde por falta de
 * resposta.
 */
export function DiagnosticsManager() {
  const { tenant, store, permissions, showToast } = usePos()
  const headers = useMemo<Record<string, string>>(
    () => (tenant ? { 'X-Tenant-ID': tenant.id, ...(store ? { 'X-Store-ID': store.id } : {}) } : {}),
    [tenant, store],
  )
  const podeDecidir = permissions.includes('support.access.manage')

  const [diagnostico, setDiagnostico] = useState<api.Diagnostico | null>(null)
  const [acessos, setAcessos] = useState<api.AcessoAssistido[]>([])
  const [verificando, setVerificando] = useState(true)
  const [naoVerificou, setNaoVerificou] = useState('')
  const [ocupado, setOcupado] = useState(false)

  const verificar = useCallback(async () => {
    if (!tenant) return
    setVerificando(true)
    try {
      setDiagnostico(await api.fetchDiagnostico(headers))
      setNaoVerificou('')
    } catch (motivo) {
      // O que não foi verificado não é saudável. Apagar o resultado antigo é
      // parte da honestidade: um número velho na tela é pior que nenhum.
      setDiagnostico(null)
      setNaoVerificou(motivo instanceof Error ? motivo.message : 'Não foi possível verificar.')
    } finally { setVerificando(false) }
  }, [tenant, headers])

  const carregarAcessos = useCallback(async () => {
    if (!tenant) return
    try {
      setAcessos(await api.fetchAcessosAssistidos(headers))
    } catch {
      setAcessos([])
    }
  }, [tenant, headers])

  useEffect(() => { void verificar() }, [verificar])
  useEffect(() => { void carregarAcessos() }, [carregarAcessos])

  const decidir = async (
    acesso: api.AcessoAssistido, acao: 'aprovar' | 'revogar',
  ) => {
    if (ocupado) return
    const pergunta = acao === 'aprovar'
      ? 'Por que você está autorizando este acesso? O motivo fica registrado.'
      : 'Por que este acesso está sendo cortado? O motivo fica registrado.'
    const motivo = window.prompt(pergunta)
    if (!motivo || motivo.trim().length < 3) return
    setOcupado(true)
    try {
      if (acao === 'aprovar') {
        await api.aprovarAcessoAssistido(headers, acesso.id, motivo.trim())
        showToast('success', 'Acesso autorizado. Ele vale até o prazo e você pode cortar quando quiser.')
      } else {
        await api.revogarAcessoAssistido(headers, acesso.id, motivo.trim())
        showToast('success', 'Acesso cortado. Ele deixa de valer imediatamente.')
      }
      await carregarAcessos()
    } catch (falha) {
      showToast('error', falha instanceof Error ? falha.message : 'Não foi possível concluir.')
    } finally { setOcupado(false) }
  }

  const pendentes = acessos.filter((a) => a.situacao === 'PENDING' && !a.expirado)
  const valendo = acessos.filter((a) => a.vale_agora)
  const encerrados = acessos.filter((a) => !a.vale_agora && !(a.situacao === 'PENDING' && !a.expirado))

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-black uppercase tracking-wide text-state-success">Administração</p>
            <h1 className="text-2xl font-black text-dashem-strong">Diagnóstico e suporte</h1>
            <p className="mt-1 max-w-2xl text-sm leading-5 text-dashem-muted">
              Se está tudo funcionando, e quem tem acesso aos seus dados.
            </p>
          </div>
          <button
            onClick={() => { void verificar() }}
            disabled={verificando}
            className="inline-flex min-h-11 items-center rounded-xl border border-dashem-border px-4 text-sm font-black text-dashem-strong disabled:opacity-40"
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${verificando ? 'animate-spin' : ''}`} />
            {verificando ? 'Verificando...' : 'Verificar agora'}
          </button>
        </div>

        {diagnostico && (
          <div className={`mt-4 flex items-center gap-3 rounded-xl border p-3 ${fundoDa(diagnostico.situacao_geral)}`}>
            <Simbolo situacao={diagnostico.situacao_geral} />
            <div>
              <p className={`text-sm font-black ${corDa(diagnostico.situacao_geral)}`}>
                {tituloGeral(diagnostico.situacao_geral)}
              </p>
              <p className="text-xs text-dashem-muted">
                Verificado às {hora(diagnostico.verificado_em)}.
              </p>
            </div>
          </div>
        )}

        {naoVerificou && (
          <div role="alert" className="mt-4 flex items-center gap-3 rounded-xl border border-state-warning-border bg-state-warning-soft p-3">
            <HelpCircle className="h-5 w-5 shrink-0 text-state-warning" />
            <div>
              <p className="text-sm font-black text-state-warning">Não foi possível verificar agora.</p>
              <p className="text-xs text-dashem-muted">
                Isso não quer dizer que está tudo bem, nem que está tudo errado: quer dizer
                que não deu para saber. {naoVerificou}
              </p>
            </div>
          </div>
        )}
      </section>

      {diagnostico && (
        <section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5">
          <h2 className="font-black text-dashem-strong">O que foi verificado</h2>
          <div className="mt-4 divide-y divide-dashem-border">
            {diagnostico.verificacoes.map((item) => (
              <div key={item.chave} className="flex items-start gap-3 py-3">
                <Simbolo situacao={item.situacao} />
                <div className="min-w-0">
                  <p className="text-sm font-black text-dashem-strong">{item.titulo}</p>
                  <p className={`text-xs font-semibold ${corDa(item.situacao)}`}>{item.resumo}</p>
                </div>
              </div>
            ))}
          </div>

          {diagnostico.aparelhos.length > 0 && (
            <div className="mt-5">
              <h3 className="text-xs font-black uppercase tracking-wide text-brand-ink-soft">
                Seus equipamentos
              </h3>
              <div className="mt-2 divide-y divide-dashem-border">
                {diagnostico.aparelhos.map((aparelho) => (
                  <div key={aparelho.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <Simbolo situacao={aparelho.situacao} />
                      <span className="text-sm font-bold text-dashem-strong">{aparelho.nome}</span>
                    </div>
                    <span className={`text-xs font-semibold ${corDa(aparelho.situacao)}`}>
                      {sinalDo(aparelho)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      <section className="rounded-2xl border border-dashem-border bg-dashem-surface p-5">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-state-success" />
          <h2 className="font-black text-dashem-strong">Quem tem acesso aos seus dados</h2>
        </div>
        <p className="mt-1 text-sm text-dashem-muted">
          O suporte só entra se você autorizar. Você vê <span className="font-bold">quem</span> está
          pedindo, o que ele quer ver e por quanto tempo — e pode cortar a qualquer momento.
          Cada autorização vale para uma pessoa só.
        </p>

        {pendentes.length > 0 && (
          <div className="mt-4 space-y-3">
            <p className="text-xs font-black uppercase tracking-wide text-state-warning">
              Esperando a sua decisão
            </p>
            {pendentes.map((acesso) => (
              <Pedido key={acesso.id} acesso={acesso} podeDecidir={podeDecidir}
                      ocupado={ocupado} decidir={decidir} />
            ))}
          </div>
        )}

        {valendo.length > 0 && (
          <div className="mt-4 space-y-3">
            <p className="text-xs font-black uppercase tracking-wide text-state-success">
              Valendo agora
            </p>
            {valendo.map((acesso) => (
              <Pedido key={acesso.id} acesso={acesso} podeDecidir={podeDecidir}
                      ocupado={ocupado} decidir={decidir} />
            ))}
          </div>
        )}

        {acessos.length === 0 && (
          <p className="mt-4 rounded-xl border border-dashem-border p-4 text-sm text-dashem-muted">
            Ninguém do suporte pediu acesso aos seus dados.
          </p>
        )}

        {encerrados.length > 0 && (
          <details className="mt-4">
            <summary className="cursor-pointer text-xs font-black uppercase tracking-wide text-brand-ink-soft">
              Encerrados ({encerrados.length})
            </summary>
            <div className="mt-2 divide-y divide-dashem-border">
              {encerrados.map((acesso) => (
                <div key={acesso.id} className="py-2.5">
                  <p className="text-xs font-black text-dashem-muted">
                    {rotuloDoEncerrado(acesso)} · {acesso.solicitante}
                  </p>
                  <p className="text-[11px] text-dashem-muted">
                    {acesso.escopo.join(', ') || 'sem escopo'} · {acesso.motivo}
                  </p>
                </div>
              ))}
            </div>
          </details>
        )}
      </section>
    </div>
  )
}

function Pedido({ acesso, podeDecidir, ocupado, decidir }: {
  acesso: api.AcessoAssistido
  podeDecidir: boolean
  ocupado: boolean
  decidir: (acesso: api.AcessoAssistido, acao: 'aprovar' | 'revogar') => Promise<void>
}) {
  const pendente = acesso.situacao === 'PENDING'
  return (
    <div className="rounded-xl border border-dashem-border p-4">
      {/*
        Quem pede vem primeiro. A autorização é nominal — vale para esta
        pessoa e para mais ninguém — e uma linha sem nome não responde a
        pergunta que a seção faz.
      */}
      <p className="text-sm font-black text-dashem-strong">{acesso.solicitante}</p>
      {acesso.solicitante_email && (
        <p className="text-xs text-dashem-muted">{acesso.solicitante_email}</p>
      )}
      <p className="mt-2 text-sm text-dashem-strong">{acesso.motivo}</p>
      <p className="mt-1 text-xs text-dashem-muted">
        Quer ver: <span className="font-bold">{acesso.escopo.join(', ') || 'nada declarado'}</span>
        {' · '}até {dataHora(acesso.expira_em)}
      </p>
      {acesso.invalidada_porque && (
        <p className="mt-2 rounded-lg bg-state-warning-soft p-2 text-[11px] font-semibold text-state-warning">
          {acesso.invalidada_porque}
        </p>
      )}
      {podeDecidir ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {pendente && (
            <button
              onClick={() => { void decidir(acesso, 'aprovar') }}
              disabled={ocupado}
              className="min-h-11 rounded-xl bg-dashem-red px-4 text-xs font-black text-brand-contrast disabled:opacity-40"
            >
              Autorizar
            </button>
          )}
          <button
            onClick={() => { void decidir(acesso, 'revogar') }}
            disabled={ocupado}
            className="min-h-11 rounded-xl border border-dashem-border px-4 text-xs font-black text-dashem-strong disabled:opacity-40"
          >
            {pendente ? 'Recusar' : 'Cortar acesso'}
          </button>
        </div>
      ) : (
        <p className="mt-3 text-xs font-semibold text-brand-ink-soft">
          Quem autoriza acesso aos dados da empresa é quem responde por ela.
        </p>
      )}
      {podeDecidir && pendente && (
        <p className="mt-2 text-[11px] text-dashem-muted">
          Autorizar libera <span className="font-bold">só esta pessoa</span>, e só até o prazo.
        </p>
      )}
    </div>
  )
}

function Simbolo({ situacao }: { situacao: api.SituacaoDoDiagnostico }) {
  if (situacao === 'SAUDAVEL') return <CheckCircle2 className="h-5 w-5 shrink-0 text-state-success" />
  if (situacao === 'ATENCAO') return <AlertTriangle className="h-5 w-5 shrink-0 text-state-warning" />
  if (situacao === 'PARADO') return <XCircle className="h-5 w-5 shrink-0 text-state-danger" />
  return <HelpCircle className="h-5 w-5 shrink-0 text-dashem-muted" />
}

function corDa(situacao: api.SituacaoDoDiagnostico): string {
  if (situacao === 'SAUDAVEL') return 'text-state-success'
  if (situacao === 'ATENCAO') return 'text-state-warning'
  if (situacao === 'PARADO') return 'text-state-danger'
  return 'text-dashem-muted'
}

function fundoDa(situacao: api.SituacaoDoDiagnostico): string {
  if (situacao === 'SAUDAVEL') return 'border-state-success-border bg-state-success-soft'
  if (situacao === 'ATENCAO') return 'border-state-warning-border bg-state-warning-soft'
  if (situacao === 'PARADO') return 'border-state-danger-border bg-state-danger-soft'
  return 'border-dashem-border bg-dashem-surface-elevated'
}

/**
 * A frase do topo. "Não verificado" não vira "tudo certo" nem "tudo errado":
 * quer dizer que não deu para saber, que é uma terceira coisa.
 */
function tituloGeral(situacao: api.SituacaoDoDiagnostico): string {
  if (situacao === 'SAUDAVEL') return 'Está tudo funcionando.'
  if (situacao === 'ATENCAO') return 'Funcionando, com um ponto de atenção.'
  if (situacao === 'PARADO') return 'Alguma coisa parou. Veja abaixo.'
  return 'Não foi possível verificar tudo.'
}

function sinalDo(aparelho: api.AparelhoNoDiagnostico): string {
  if (aparelho.visto_em == null) return 'Nunca deu sinal'
  const minutos = aparelho.minutos_sem_sinal ?? 0
  if (minutos < 1) return 'Respondendo agora'
  if (minutos === 1) return 'Visto há 1 minuto'
  if (minutos < 60) return `Visto há ${minutos} minutos`
  const horas = Math.floor(minutos / 60)
  return horas === 1 ? 'Visto há 1 hora' : `Visto há ${horas} horas`
}

function rotuloDoEncerrado(acesso: api.AcessoAssistido): string {
  if (acesso.situacao === 'REVOKED') return 'Cortado'
  if (acesso.expirado) return 'Prazo vencido'
  return 'Encerrado'
}

/**
 * O produto já tinha o utilitário certo, e eu tinha reescrito à mão.
 *
 * `parseApiDate` sabe que o servidor manda instante em UTC sem fuso escrito, e
 * `new Date` cru sobre isso lê como hora local — um pedido que expira às 03:12
 * apareceria três horas fora. Há um guarda no repositório que reprova
 * exatamente esse `new Date`, e foi ele quem pegou.
 */
function hora(iso: string): string {
  return formatApiDateTime(iso, 'time')
}

function dataHora(iso: string): string {
  const instante = parseApiDate(iso)
  if (!instante) return '—'
  return instante.toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}
