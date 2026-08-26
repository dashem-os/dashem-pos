import { useEffect, useState } from 'react'
import { Loader2, ShieldAlert } from 'lucide-react'

import { useAuth } from '../../context/AuthContext'
import * as api from '../../services/api'
import { ApiError, isTransientNetworkError } from '../../services/http'
import { navigateTo } from '../../utils/navigation'
import { OperationalSelection } from './OperationalContextGate'

type SessionFailure = { kind: 'ENDED' | 'UNAVAILABLE'; message: string }

export function OperationalSessionGate({
  children,
}: {
  children: (selection: OperationalSelection) => React.ReactNode
}) {
  const { operationalToken, clearOperationalSession } = useAuth()
  const [context, setContext] = useState<api.OperationalSessionContext | null>(null)
  const [failure, setFailure] = useState<SessionFailure | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!operationalToken) {
      navigateTo('/operate')
      return
    }
    let active = true
    setContext(null)
    setFailure(null)
    api.fetchOperationalSessionContext(operationalToken).then((value) => {
      if (active) setContext(value)
    }).catch((reason) => {
      if (!active) return
      if (reason instanceof ApiError && [401, 403, 409].includes(reason.status)) {
        clearOperationalSession()
        setFailure({ kind: 'ENDED', message: reason.message })
        return
      }
      setFailure({
        kind: 'UNAVAILABLE',
        message: isTransientNetworkError(reason)
          ? 'Sem conexão com o Dashem. A sessão foi preservada e será revalidada antes de qualquer operação.'
          : reason instanceof Error ? reason.message : 'Não foi possível validar a sessão agora.',
      })
    })
    return () => { active = false }
  }, [attempt, clearOperationalSession, operationalToken])

  if (context) {
    return <>{children({
      source: 'OPERATIONAL_SESSION',
      tenantId: context.tenant_id,
      tenantName: context.tenant_name,
      tenantSlug: context.tenant_slug,
      storeId: context.store_id,
      storeName: context.store_name,
      storeCode: context.store_code,
      registerId: context.register_id,
      registerName: context.register_name,
      registerCode: context.register_code,
      deviceId: context.device_id,
      deviceName: context.device_name,
    })}</>
  }

  if (failure) {
    const ended = failure.kind === 'ENDED'
    return <main className="flex min-h-screen items-center justify-center bg-[#06101f] p-6"><section className="w-full max-w-lg rounded-3xl bg-white p-8 text-center shadow-2xl"><ShieldAlert className="mx-auto h-8 w-8 text-amber-700" /><h1 className="mt-4 text-xl font-black text-slate-950">{ended ? 'Sessão operacional encerrada' : 'Validação indisponível'}</h1><p role="alert" className="mt-3 text-sm leading-6 text-slate-700">{failure.message}</p><button onClick={() => ended ? navigateTo('/operate') : setAttempt(value => value + 1)} className="mt-6 h-12 w-full rounded-xl bg-slate-950 font-black text-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-200">{ended ? 'Voltar à identificação' : 'Tentar novamente'}</button></section></main>
  }

  return <main className="flex min-h-screen items-center justify-center bg-[#06101f] text-sm font-bold text-slate-300"><Loader2 className="mr-3 h-5 w-5 animate-spin" />Validando sessão e terminal...</main>
}
