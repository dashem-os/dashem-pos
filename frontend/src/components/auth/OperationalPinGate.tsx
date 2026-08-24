import { useEffect, useState } from 'react'
import { ArrowLeft, Delete, KeyRound, Loader2, ShieldCheck, Store, UserRound } from 'lucide-react'

import { OperationalSelection } from '../context/OperationalContextGate'
import { useAuth } from '../../context/AuthContext'
import * as api from '../../services/api'
import { navigateTo } from '../../utils/navigation'


export function OperationalPinGate({ selection, children }: { selection: OperationalSelection; children: React.ReactNode }) {
  const { session, operationalActive, activateOperationalSession } = useAuth()
  const [employeeCode, setEmployeeCode] = useState('')
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [managementAuthorized, setManagementAuthorized] = useState(false)
  const [checkingManagement, setCheckingManagement] = useState(Boolean(session) && !operationalActive)

  useEffect(() => {
    if (operationalActive || !session) {
      setCheckingManagement(false)
      return
    }
    let active = true
    setCheckingManagement(true)
    api.fetchMe().then(me => {
      if (!active) return
      const managementRoles = new Set(['OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER'])
      setManagementAuthorized(Boolean(me.memberships?.some(membership =>
        membership.tenant_id === selection.tenantId
        && membership.status === 'ACTIVE'
        && managementRoles.has(membership.role),
      )))
    }).catch(() => { if (active) setManagementAuthorized(false) })
      .finally(() => { if (active) setCheckingManagement(false) })
    return () => { active = false }
  }, [operationalActive, selection.tenantId, session])

  if (operationalActive || managementAuthorized) return <>{children}</>
  if (checkingManagement) return <main className="flex min-h-screen items-center justify-center bg-[#06101f] text-sm font-bold text-slate-300"><Loader2 className="mr-3 h-5 w-5 animate-spin" />Validando acesso gerencial...</main>

  const append = (digit: string) => setPin(current => current.length < 8 ? `${current}${digit}` : current)
  const activate = async (event: React.FormEvent) => {
    event.preventDefault()
    if (employeeCode.trim().length < 3 || pin.length < 4) return
    setBusy(true); setError(null)
    try {
      const session = await api.activateOperationalAccess(
        { 'X-Tenant-ID': selection.tenantId, 'X-Store-ID': selection.storeId },
        { employee_code: employeeCode, pin, store_id: selection.storeId, register_id: selection.registerId },
      )
      activateOperationalSession(session.access_token)
      setEmployeeCode('')
      setPin('')
    } catch (reason) {
      setPin('')
      setError(reason instanceof Error ? reason.message : 'Não foi possível assumir a operação.')
    } finally { setBusy(false) }
  }

  return <main className="grid min-h-screen bg-[#06101f] lg:grid-cols-[minmax(360px,0.9fr)_minmax(480px,1.1fr)]">
    <section className="hidden flex-col justify-between border-r border-white/10 bg-[radial-gradient(circle_at_top_left,#341126_0,#07172b_52%)] p-12 text-white lg:flex">
      <div><div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-rose-600 text-xl font-black shadow-lg shadow-rose-950/40">D</div><p className="mt-7 text-xs font-black uppercase tracking-[.22em] text-rose-400">Dashem · turno operacional</p><h1 className="mt-4 max-w-lg text-4xl font-black leading-tight">Cada operação fica ligada à pessoa certa.</h1><p className="mt-5 max-w-lg text-base leading-7 text-slate-300">O administrador autoriza este terminal. Agora o colaborador assume o atendimento com sua identidade individual.</p></div>
      <div className="rounded-2xl border border-white/10 bg-white/[.04] p-5"><p className="flex items-center gap-2 text-sm font-black"><Store className="h-4 w-4 text-rose-400" />{selection.storeName || 'Unidade autorizada'}</p><p className="mt-2 text-xs text-slate-400">{selection.registerName || 'Operação de mesas e comandas'} · sessão auditável</p></div>
    </section>
    <section className="flex items-center justify-center p-5 sm:p-10">
      <form onSubmit={activate} className="w-full max-w-md rounded-[28px] bg-white p-6 shadow-2xl sm:p-8">
        <div className="flex items-start justify-between"><div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-rose-50 text-rose-600"><KeyRound className="h-6 w-6" /></div><button type="button" onClick={() => navigateTo('/manage')} className="flex items-center gap-2 text-xs font-black text-slate-500 hover:text-slate-950"><ArrowLeft className="h-4 w-4" />Gestão</button></div>
        <p className="mt-7 text-xs font-black uppercase tracking-[.18em] text-rose-600">Identificação do colaborador</p>
        <h2 className="mt-2 text-3xl font-black text-slate-950">Assumir operação</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">Use o código e o PIN fornecidos pelo administrador da empresa.</p>
        <label className="mt-7 block text-xs font-black uppercase tracking-wide text-slate-600">Código do colaborador<div className="mt-2 flex h-12 items-center rounded-xl border border-slate-300 px-3 focus-within:border-rose-500"><UserRound className="h-5 w-5 text-slate-400" /><input autoFocus autoComplete="username" value={employeeCode} onChange={event => setEmployeeCode(event.target.value.toUpperCase())} placeholder="Ex.: ATD01" className="h-full min-w-0 flex-1 px-3 font-black uppercase outline-none" /></div></label>
        <div className="mt-5"><p className="text-xs font-black uppercase tracking-wide text-slate-600">PIN</p><div className="mt-2 flex h-14 items-center justify-center gap-2 rounded-xl border border-slate-300 bg-slate-50" aria-label={`${pin.length} dígitos informados`}>{Array.from({ length: 6 }, (_, index) => <span key={index} className={`h-3 w-3 rounded-full ${index < pin.length ? 'bg-rose-600' : 'bg-slate-200'}`} />)}</div></div>
        <div className="mt-4 grid grid-cols-3 gap-2">{['1','2','3','4','5','6','7','8','9'].map(digit => <button key={digit} type="button" onClick={() => append(digit)} className="h-12 rounded-xl border border-slate-200 bg-white text-lg font-black text-slate-800 hover:border-rose-300 hover:bg-rose-50">{digit}</button>)}<button type="button" onClick={() => setPin('')} className="h-12 rounded-xl border border-slate-200 text-xs font-black text-slate-500">Limpar</button><button type="button" onClick={() => append('0')} className="h-12 rounded-xl border border-slate-200 text-lg font-black">0</button><button type="button" onClick={() => setPin(current => current.slice(0, -1))} className="flex h-12 items-center justify-center rounded-xl border border-slate-200 text-slate-500"><Delete className="h-5 w-5" /></button></div>
        {error && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{error}</p>}
        <button disabled={busy || employeeCode.trim().length < 3 || pin.length < 4} className="mt-5 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-rose-600 font-black text-white shadow-lg shadow-rose-200 disabled:opacity-40">{busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <ShieldCheck className="h-5 w-5" />}{busy ? 'Validando...' : 'Entrar no turno'}</button>
        <p className="mt-4 text-center text-[11px] leading-5 text-slate-400">5 tentativas inválidas bloqueiam temporariamente o código. O PIN nunca é armazenado em texto aberto.</p>
      </form>
    </section>
  </main>
}
