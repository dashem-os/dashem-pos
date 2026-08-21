import React, { useCallback, useEffect, useState } from 'react'
import { Loader2, LogOut, ShieldAlert } from 'lucide-react'
import { PosProvider, usePos } from './context/PosContext'
import { PosLayout } from './layouts/PosLayout'
import { ManagementLayout } from './layouts/ManagementLayout'
import { Toast } from './components/common/Toast'
import { AuthProvider, useAuth } from './context/AuthContext'
import { SignInScreen } from './components/auth/SignInScreen'
import { OwnerMfaScreen, PasswordSetupScreen } from './components/auth/FirstAccessSecurity'
import { PlatformOwnerConsole } from './components/owner/PlatformOwnerConsole'
import { AuthMe, fetchMe } from './services/api'

const PLATFORM_CONSOLE_ROLES = new Set(['PLATFORM_OWNER', 'PLATFORM_ADMIN'])

const AppContent: React.FC = () => {
  const { activeView, loading, toast } = usePos()
  if (loading) return <FullScreenLoader label="Carregando ambiente operacional..." />
  return <><Toast toast={toast} />{activeView === 'pdv' ? <PosLayout /> : <ManagementLayout />}</>
}

export default function App() {
  return <AuthProvider><IdentityRouter /></AuthProvider>
}

function IdentityRouter() {
  const { session, loading, passwordRecovery, signOut } = useAuth()
  const [me, setMe] = useState<AuthMe | null>(null)
  const [identityLoading, setIdentityLoading] = useState(false)
  const [identityError, setIdentityError] = useState<string | null>(null)

  const loadIdentity = useCallback(async () => {
    if (!session) return
    setIdentityLoading(true)
    setIdentityError(null)
    try {
      setMe(await fetchMe())
    } catch (err) {
      setMe(null)
      setIdentityError(err instanceof Error ? err.message : 'Não foi possível resolver seu acesso.')
    } finally {
      setIdentityLoading(false)
    }
  }, [session])

  useEffect(() => { if (session) loadIdentity(); else setMe(null) }, [session, loadIdentity])

  useEffect(() => {
    if (!loading && !session && window.location.pathname !== '/login') {
      window.history.replaceState({}, '', '/login')
    }
  }, [loading, session])

  if (loading) return <FullScreenLoader label="Validando sessão..." />
  if (!session) return <SignInScreen />

  if (passwordRecovery || new URLSearchParams(window.location.search).get('mode') === 'recovery') {
    return <PasswordSetupScreen recovery onComplete={async () => { window.location.assign('/login') }} />
  }

  if (identityLoading && !me) return <FullScreenLoader label="Reconhecendo identidade e permissões..." />
  if (identityError || !me) return <AccessState message={identityError ?? 'Seu usuário ainda não possui acesso ao Dashem POS.'} onSignOut={signOut} onRetry={loadIdentity} />

  const platformRole = me.platform_role ?? ''
  if (PLATFORM_CONSOLE_ROLES.has(platformRole)) {
    if (me.password_setup_required) return <PasswordSetupScreen onComplete={loadIdentity} />
    if (me.mfa_required) return <OwnerMfaScreen onComplete={loadIdentity} />
    if (window.location.pathname !== '/owner') window.history.replaceState({}, '', '/owner')
    return <PlatformOwnerConsole me={me} />
  }

  if (platformRole && !me.memberships?.length) {
    return <AccessState message="Seu papel de plataforma está autenticado, mas este módulo do Console ainda não foi liberado para o perfil atual." onSignOut={signOut} onRetry={loadIdentity} />
  }

  if (window.location.pathname === '/owner') window.history.replaceState({}, '', '/')
  return <PosProvider><AppContent /></PosProvider>
}

function FullScreenLoader({ label }: { label: string }) {
  return <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#07101f] text-white"><div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[.04] text-rose-500"><Loader2 className="h-7 w-7 animate-spin" /></div><p className="text-sm font-bold text-slate-400">{label}</p></div>
}

function AccessState({ message, onSignOut, onRetry }: { message: string; onSignOut: () => Promise<void>; onRetry: () => Promise<void> }) {
  return <main className="flex min-h-screen items-center justify-center bg-[#07101f] p-6"><section className="w-full max-w-lg rounded-3xl bg-white p-8 text-center shadow-2xl"><div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-50 text-amber-600"><ShieldAlert className="h-7 w-7" /></div><p className="mt-6 text-xs font-black uppercase tracking-[.18em] text-amber-600">Acesso pendente</p><h1 className="mt-2 text-2xl font-black text-slate-950">Identidade reconhecida</h1><p className="mt-3 leading-7 text-slate-500">{message}</p><div className="mt-7 flex gap-3"><button onClick={onSignOut} className="flex h-11 flex-1 items-center justify-center gap-2 rounded-xl border border-slate-300 font-black text-slate-600"><LogOut className="h-4 w-4" />Sair</button><button onClick={onRetry} className="h-11 flex-1 rounded-xl bg-slate-950 font-black text-white">Verificar novamente</button></div></section></main>
}
