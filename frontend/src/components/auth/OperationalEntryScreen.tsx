import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Delete, KeyRound, Loader2, RefreshCw, ShieldAlert, ShieldCheck, UserRound, WifiOff } from 'lucide-react'

import { useAuth } from '../../context/AuthContext'
import * as api from '../../services/api'
import { ApiError, isTransientNetworkError } from '../../services/http'
import { navigateTo } from '../../utils/navigation'

type EntryMode = 'LOGIN' | 'ACTIVATE'

function strongPin(pin: string) {
  if (!/^\d{4,8}$/.test(pin) || new Set(pin).size === 1) return false
  return !'01234567890123456789'.includes(pin) && !'98765432109876543210'.includes(pin)
}

export function OperationalEntryScreen() {
  const { session, terminalToken, clearTerminalAuthorization, activateOperationalSession } = useAuth()
  const [context, setContext] = useState<api.TerminalAuthorizationContext | null>(null)
  const [mode, setMode] = useState<EntryMode>('LOGIN')
  const [employeeCode, setEmployeeCode] = useState('')
  const [pin, setPin] = useState('')
  const [confirmPin, setConfirmPin] = useState('')
  const [activationCode, setActivationCode] = useState('')
  const [loading, setLoading] = useState(Boolean(terminalToken))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [online, setOnline] = useState(navigator.onLine)
  const [terminalCheck, setTerminalCheck] = useState(0)
  const pinInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const connected = () => { setOnline(true); setTerminalCheck(value => value + 1) }
    const disconnected = () => setOnline(false)
    window.addEventListener('online', connected)
    window.addEventListener('offline', disconnected)
    return () => {
      window.removeEventListener('online', connected)
      window.removeEventListener('offline', disconnected)
    }
  }, [])

  useEffect(() => {
    if (!terminalToken) { setLoading(false); setContext(null); return }
    let active = true
    setLoading(true); setContext(null); setError(null)
    api.resolveOperationalTerminal(terminalToken).then(value => {
      if (active) { setOnline(true); setContext(value) }
    }).catch(reason => {
      if (!active) return
      if (reason instanceof ApiError && [401, 403].includes(reason.status)) {
        clearTerminalAuthorization()
      }
      const transient = isTransientNetworkError(reason) || !(reason instanceof ApiError)
      if (transient) setOnline(false)
      setError(transient
        ? 'Sem conexão com o Dashem. A autorização deste terminal foi preservada; tente novamente quando a rede voltar.'
        : reason instanceof Error ? reason.message : 'Este terminal precisa ser autorizado novamente.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [terminalToken, clearTerminalAuthorization, terminalCheck])

  const switchMode = (next: EntryMode) => {
    setMode(next); setPin(''); setConfirmPin(''); setActivationCode(''); setError(null); setNotice(null)
  }

  const append = (digit: string) => {
    setPin(current => current.length < 8 ? `${current}${digit}` : current)
    pinInputRef.current?.focus()
  }

  const submitLogin = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!online || !terminalToken || employeeCode.trim().length < 3 || pin.length < 4) return
    setBusy(true); setError(null); setNotice(null)
    try {
      const operational = await api.loginOperationalTerminal(terminalToken, { employee_code: employeeCode, pin })
      setPin(''); setEmployeeCode('')
      activateOperationalSession(operational.access_token)
      navigateTo('/pos')
    } catch (reason) {
      setPin('')
      setError(reason instanceof Error ? reason.message : 'Não foi possível iniciar o turno.')
    } finally { setBusy(false) }
  }

  const submitActivation = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!online || !terminalToken || employeeCode.trim().length < 3 || activationCode.length !== 8 || !strongPin(pin) || pin !== confirmPin) return
    setBusy(true); setError(null); setNotice(null)
    try {
      await api.activateOperationalPin(terminalToken, {
        employee_code: employeeCode, activation_code: activationCode, pin,
      })
      setPin(''); setConfirmPin(''); setActivationCode(''); setMode('LOGIN')
      setNotice('PIN pessoal ativado. Informe o mesmo código e PIN para assumir a operação.')
    } catch (reason) {
      setPin(''); setConfirmPin('')
      setError(reason instanceof Error ? reason.message : 'Não foi possível ativar o PIN pessoal.')
    } finally { setBusy(false) }
  }

  if (loading) return <main className="flex min-h-screen items-center justify-center bg-[#06101f] text-sm font-bold text-slate-300"><Loader2 className="mr-3 h-5 w-5 animate-spin" />Validando este terminal...</main>

  if (!context) return <main className="flex min-h-screen items-center justify-center bg-[#06101f] p-5">
    <section className="w-full max-w-lg rounded-[28px] bg-white p-7 text-center shadow-2xl sm:p-9">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-50 text-amber-800">{online ? <ShieldAlert className="h-7 w-7" /> : <WifiOff className="h-7 w-7" />}</div>
      <p className="mt-6 text-xs font-black uppercase tracking-[.18em] text-amber-800">{online ? 'Terminal não autorizado' : 'Conexão indisponível'}</p>
      <h1 className="mt-2 text-2xl font-black text-slate-950">{online ? 'Ative este ponto de operação' : 'O terminal continua preservado'}</h1>
      <p className="mt-3 text-sm leading-6 text-slate-600">{online ? <>Um administrador ou gerente deve entrar por e-mail, abrir <b>Terminais e dispositivos</b> e autorizar este navegador em um terminal POS ativo.</> : 'Nenhuma autorização foi removida. Restabeleça a conexão para validar este ponto e continuar.'}</p>
      {error && <p role="alert" className="mt-5 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}
      <div className="mt-6 grid gap-3 sm:grid-cols-2"><button onClick={() => setTerminalCheck(value => value + 1)} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-slate-300 font-black text-slate-800 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500"><RefreshCw className="h-4 w-4" />Tentar novamente</button><button onClick={() => navigateTo(session ? '/manage' : '/login')} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-slate-950 font-black text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500"><ArrowLeft className="h-4 w-4" />{session ? 'Voltar à Gestão' : 'Entrar como gestor'}</button></div>
    </section>
  </main>

  return <main className="flex min-h-screen items-start justify-center overflow-y-auto bg-[#06101f] p-4 sm:items-center sm:p-8">
    <form autoComplete="off" onSubmit={mode === 'LOGIN' ? submitLogin : submitActivation} className="w-full max-w-md rounded-[28px] bg-white p-6 shadow-2xl sm:p-8">
        <div className="flex items-center justify-center gap-3" aria-label="Dashem POS">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-rose-600 text-lg font-black text-white">D</div>
          <p className="text-xl font-black tracking-tight text-[#08275b]">DASHEM <span className="text-rose-600">POS</span></p>
        </div>
        <div className="mt-6 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-rose-50 text-rose-700"><KeyRound className="h-6 w-6" /></div>
          <p className="mt-4 text-xs font-black uppercase tracking-[.18em] text-rose-700">Colaborador</p>
          <h1 className="mt-2 text-3xl font-black text-slate-950">{mode === 'LOGIN' ? 'Assumir operação' : 'Criar PIN pessoal'}</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">{mode === 'LOGIN' ? 'Informe seu código e PIN pessoal.' : 'Informe o código temporário e defina seu PIN.'}</p>
        </div>
        <div className="mt-5 grid grid-cols-2 rounded-xl bg-slate-100 p-1">
          <button type="button" aria-pressed={mode === 'LOGIN'} onClick={() => switchMode('LOGIN')} className={`min-h-11 rounded-lg text-xs font-black focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500 ${mode === 'LOGIN' ? 'bg-white text-slate-950 shadow-sm' : 'text-slate-700'}`}>Entrar no turno</button>
          <button type="button" aria-pressed={mode === 'ACTIVATE'} onClick={() => switchMode('ACTIVATE')} className={`min-h-11 rounded-lg text-xs font-black focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500 ${mode === 'ACTIVATE' ? 'bg-white text-slate-950 shadow-sm' : 'text-slate-700'}`}>Primeiro acesso / novo PIN</button>
        </div>
        <label className="mt-5 block text-xs font-black uppercase tracking-wide text-slate-700">Código do colaborador<div className="mt-2 flex h-12 items-center rounded-xl border border-slate-300 px-3 focus-within:border-rose-500 focus-within:ring-4 focus-within:ring-rose-500"><UserRound className="h-5 w-5 text-slate-500" /><input autoFocus name="employee-code" autoComplete="off" autoCapitalize="characters" autoCorrect="off" spellCheck={false} value={employeeCode} onChange={event => setEmployeeCode(event.target.value.replace(/[^A-Z0-9_-]/gi, '').toUpperCase().slice(0, 20))} placeholder="Ex.: ATD01" className="h-full min-w-0 flex-1 px-3 font-black uppercase outline-none" /></div></label>
        {mode === 'ACTIVATE' && <label className="mt-4 block text-xs font-black uppercase tracking-wide text-slate-700">Código temporário de ativação<input name="activation-code" inputMode="numeric" autoComplete="off" value={activationCode} onChange={event => setActivationCode(event.target.value.replace(/\D/g, '').slice(0, 8))} placeholder="8 números" className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 font-mono text-lg font-black tracking-[.18em] text-slate-950 outline-none focus:border-rose-500 focus:ring-4 focus:ring-rose-500" /></label>}
        {mode === 'LOGIN' ? <>
          <label className="mt-5 block text-xs font-black uppercase tracking-wide text-slate-700">PIN pessoal<div className="relative mt-2 flex h-14 items-center justify-center gap-2 rounded-xl border border-slate-300 bg-slate-50 focus-within:border-rose-600 focus-within:ring-4 focus-within:ring-rose-500"><input ref={pinInputRef} aria-label="PIN pessoal" name="employee-pin" inputMode="numeric" type="password" autoComplete="off" value={pin} onChange={event => setPin(event.target.value.replace(/\D/g, '').slice(0, 8))} className="absolute inset-0 h-full w-full cursor-text opacity-0" />{Array.from({ length: 8 }, (_, index) => <span aria-hidden="true" key={index} className={`h-3 w-3 rounded-full ${index < pin.length ? 'bg-rose-600' : 'bg-slate-200'}`} />)}</div><span className="sr-only" aria-live="polite">{pin.length} dígitos informados</span></label>
          <div className="mt-4 grid grid-cols-3 gap-2">{['1','2','3','4','5','6','7','8','9'].map(digit => <button key={digit} type="button" onClick={() => append(digit)} className="h-12 rounded-xl border border-slate-300 text-lg font-black text-slate-950 hover:border-rose-400 hover:bg-rose-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500">{digit}</button>)}<button type="button" onClick={() => setPin('')} className="h-12 rounded-xl border border-slate-300 text-xs font-black text-slate-700 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500">Limpar</button><button type="button" onClick={() => append('0')} className="h-12 rounded-xl border border-slate-300 text-lg font-black text-slate-950 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500">0</button><button aria-label="Apagar último dígito" type="button" onClick={() => setPin(current => current.slice(0, -1))} className="flex h-12 items-center justify-center rounded-xl border border-slate-300 text-slate-700 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500"><Delete className="h-5 w-5" /></button></div>
        </> : <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="text-xs font-black uppercase tracking-wide text-slate-700">Novo PIN<input name="new-pin" inputMode="numeric" type="password" autoComplete="off" value={pin} onChange={event => setPin(event.target.value.replace(/\D/g, '').slice(0, 8))} className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-lg font-black text-slate-950 outline-none focus:border-rose-500 focus:ring-4 focus:ring-rose-500" /></label>
          <label className="text-xs font-black uppercase tracking-wide text-slate-700">Confirmar PIN<input name="confirm-pin" inputMode="numeric" type="password" autoComplete="off" value={confirmPin} onChange={event => setConfirmPin(event.target.value.replace(/\D/g, '').slice(0, 8))} className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 text-lg font-black text-slate-950 outline-none focus:border-rose-500 focus:ring-4 focus:ring-rose-500" /></label>
          <p className="text-xs leading-5 text-slate-600 sm:col-span-2">Use de 4 a 8 números, sem repetições simples ou sequências como 1234.</p>
        </div>}
        {!online && <p role="status" className="mt-4 flex items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm font-bold text-amber-900"><WifiOff className="h-4 w-4 shrink-0" />Sem conexão. O terminal e o turno foram preservados.</p>}
        {notice && <p role="status" className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-bold text-emerald-800">{notice}</p>}
        {error && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}
        <button disabled={!online || busy || employeeCode.length < 3 || (mode === 'LOGIN' ? pin.length < 4 : activationCode.length !== 8 || !strongPin(pin) || pin !== confirmPin)} className="mt-5 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-rose-600 font-black text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-slate-950 disabled:opacity-40">{busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <ShieldCheck className="h-5 w-5" />}{busy ? 'Validando...' : mode === 'LOGIN' ? 'Entrar no turno' : 'Ativar meu PIN'}</button>
    </form>
  </main>
}
