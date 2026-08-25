import { useEffect, useState } from 'react'
import { KeyRound, Loader2, ShieldAlert } from 'lucide-react'
import { OperationalSelection } from '../context/OperationalContextGate'
import { useAuth } from '../../context/AuthContext'
import * as api from '../../services/api'
import { navigateTo } from '../../utils/navigation'
import { hasManagementAccess } from '../../domain/operationalRules'

export function OperationalPinGate({ selection, children }: { selection: OperationalSelection; children: React.ReactNode }) {
  const { session, operationalActive } = useAuth()
  const [managementAuthorized, setManagementAuthorized] = useState(false)
  const [checkingManagement, setCheckingManagement] = useState(Boolean(session) && !operationalActive)

  useEffect(() => {
    if (operationalActive || !session) { setCheckingManagement(false); return }
    let active = true
    setCheckingManagement(true)
    api.fetchMe().then(me => {
      if (!active) return
      setManagementAuthorized(hasManagementAccess(
        (me.memberships ?? []).filter((membership) => membership.tenant_id === selection.tenantId),
      ))
    }).catch(() => { if (active) setManagementAuthorized(false) })
      .finally(() => { if (active) setCheckingManagement(false) })
    return () => { active = false }
  }, [operationalActive, selection.tenantId, session])

  if (operationalActive || managementAuthorized) return <>{children}</>
  if (checkingManagement) return <main className="flex min-h-screen items-center justify-center bg-[#06101f] text-sm font-bold text-slate-300"><Loader2 className="mr-3 h-5 w-5 animate-spin" />Validando acesso gerencial...</main>

  return <main className="flex min-h-screen items-center justify-center bg-[#06101f] p-5 text-slate-950"><section className="w-full max-w-lg rounded-3xl bg-white p-7 text-center shadow-2xl"><div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-50 text-amber-600"><ShieldAlert className="h-7 w-7" /></div><p className="mt-5 text-xs font-black uppercase tracking-[.18em] text-amber-600">Identidade operacional necessária</p><h1 className="mt-2 text-2xl font-black">Assuma o turno no terminal</h1><p className="mt-3 text-sm leading-6 text-slate-500">Código e PIN são aceitos apenas na entrada do ponto de operação previamente autorizado pela Gestão.</p><button onClick={() => navigateTo('/operate')} className="mt-6 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-slate-950 font-black text-white"><KeyRound className="h-4 w-4" />Ir para entrada do terminal</button></section></main>
}
