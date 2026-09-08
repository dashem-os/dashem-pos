import React, { useEffect, useRef, useState } from 'react'
import { Modal } from '../common/Modal'
import { ShieldCheck } from 'lucide-react'
import { usePos } from '../../context/PosContext'

/**
 * A autorização presencial: quem tem autoridade digita no terminal do operador.
 *
 * Antes deste diálogo havia só dois estados, e nenhum deles é a loja real: ou o
 * operador tinha a permissão e cancelava sozinho, sem testemunha, ou não tinha
 * e o botão ficava apagado — então o supervisor precisava sair do próprio caixa
 * e vir operar no lugar dele, o que registra a operação no nome da pessoa
 * errada. O balcão resolve isso há décadas com a gerente chegando e liberando.
 *
 * O que a pessoa autoriza é **esta** operação: a permissão vale para uma
 * requisição, não é gravada no cadastro do operador, e as duas pessoas ficam na
 * auditoria — quem pediu e quem permitiu.
 */
export const SupervisorAuthorization: React.FC = () => {
  const { autorizacaoPendente, confirmarAutorizacao, cancelarAutorizacao, actionLoading } = usePos()
  const [codigo, setCodigo] = useState('')
  const [pin, setPin] = useState('')
  const [erro, setErro] = useState('')
  const primeiroCampo = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (autorizacaoPendente) {
      setCodigo('')
      setPin('')
      setErro('')
      // O supervisor chegou para digitar: o cursor já está onde ele digita.
      window.setTimeout(() => primeiroCampo.current?.focus(), 60)
    }
  }, [autorizacaoPendente])

  if (!autorizacaoPendente) return null

  const confirmar = async () => {
    setErro('')
    const falha = await confirmarAutorizacao(codigo.trim(), pin)
    if (falha) {
      setErro(falha)
      setPin('')
      primeiroCampo.current?.focus()
    }
  }

  const aoTeclar = (evento: React.KeyboardEvent) => {
    if (evento.key === 'Enter' && codigo.trim() && pin) confirmar()
  }

  return (
    <Modal
      isOpen
      onClose={cancelarAutorizacao}
      title="Autorização do supervisor"
      maxWidth="sm"
    >
      <div className="flex flex-col space-y-4">
        <div className="flex items-start space-x-3 p-3.5 rounded-xl bg-amber-50 border border-amber-200 text-amber-900">
          <ShieldCheck className="w-5 h-5 shrink-0 text-amber-600" />
          <p className="text-xs font-semibold leading-relaxed">
            {autorizacaoPendente.acao} exige autorização. Quem tem essa autoridade
            digita o próprio código e senha aqui — a operação fica registrada no
            nome de vocês dois.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-bold text-slate-700 block" htmlFor="supervisor-codigo">
            Código do supervisor
          </label>
          <input
            id="supervisor-codigo"
            ref={primeiroCampo}
            value={codigo}
            onChange={(e) => setCodigo(e.target.value)}
            onKeyDown={aoTeclar}
            autoComplete="off"
            inputMode="text"
            className="w-full h-11 px-3 rounded-xl bg-white border border-slate-200 text-slate-800 text-sm font-semibold outline-none focus:border-amber-600"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-bold text-slate-700 block" htmlFor="supervisor-pin">
            Senha numérica
          </label>
          <input
            id="supervisor-pin"
            type="password"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            onKeyDown={aoTeclar}
            autoComplete="off"
            inputMode="numeric"
            className="w-full h-11 px-3 rounded-xl bg-white border border-slate-200 text-slate-800 text-sm font-semibold tracking-[0.4em] outline-none focus:border-amber-600"
          />
        </div>

        {erro && (
          <p role="alert" className="text-xs font-bold text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2">
            {erro}
          </p>
        )}

        <div className="grid grid-cols-2 gap-2 pt-1">
          <button
            type="button"
            onClick={cancelarAutorizacao}
            disabled={actionLoading}
            className="h-11 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition-colors border border-slate-200"
          >
            Voltar
          </button>
          <button
            type="button"
            onClick={confirmar}
            disabled={actionLoading || !codigo.trim() || !pin}
            className="h-11 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-black flex items-center justify-center space-x-1.5 transition-all shadow-sm active:scale-95 disabled:opacity-40"
          >
            <ShieldCheck className="w-4 h-4" />
            <span>Autorizar</span>
          </button>
        </div>
      </div>
    </Modal>
  )
}
