import React, { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { Loader2, LogOut, ShieldAlert } from 'lucide-react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { SignInScreen } from './components/auth/SignInScreen'
import { OwnerMfaScreen, PasswordSetupScreen } from './components/auth/FirstAccessSecurity'
import { AuthMe, fetchMe } from './services/api'
import { normalizeAuthenticatedRoute, ShellRoute } from './domain/operationalRules'

const OwnerConsole = lazy(() => import('./components/owner/PlatformOwnerConsole').then((module) => ({ default: module.PlatformOwnerConsole })))
const ManageShell = lazy(() => import('./shells/ManageShell'))
const PosShell = lazy(() => import('./shells/PosShell'))
const KdsShell = lazy(() => import('./shells/KdsShell'))
const TablesShell = lazy(() => import('./shells/TablesShell'))

const PLATFORM_CONSOLE_ROLES = new Set(['PLATFORM_OWNER', 'PLATFORM_ADMIN'])
const MANAGEMENT_ROLES = new Set(['OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER'])

export default function App() {
  return <AuthProvider><IdentityRouter /></AuthProvider>
}

function IdentityRouter() {
  const { session, loading, passwordRecovery, signOut } = useAuth()
  const [me, setMe] = useState<AuthMe | null>(null)
  const [identityLoading, setIdentityLoading] = useState(false)
  const [identityError, setIdentityError] = useState<string | null>(null)
  const [pathname, setPathname] = useState(window.location.pathname)

  useEffect(() => {
    const syncPath = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', syncPath)
    return () => window.removeEventListener('popstate', syncPath)
  }, [])

  const replacePath = useCallback((path: ShellRoute) => {
    if (window.location.pathname === path) return
    window.history.replaceState({}, '', path)
  }, [])

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
  useEffect(() => { if (!loading && !session) replacePath('/login') }, [loading, session, replacePath])

  if (loading) return <FullScreenLoader label="Validando sessão..." />
  if (!session) return <SignInScreen />

  if (passwordRecovery || new URLSearchParams(window.location.search).get('mode') === 'recovery') {
    return <PasswordSetupScreen recovery onComplete={async () => { window.location.assign('/login') }} />
  }

  if (identityLoading && !me) return <FullScreenLoader label="Reconhecendo identidade e permissões..." />
  if (identityError || !me) return <AccessState message={identityError ?? 'Seu usuário ainda não possui acesso ao Dashem POS.'} onSignOut={signOut} onRetry={loadIdentity} />
  if (me.password_setup_required) return <PasswordSetupScreen onComplete={loadIdentity} />

  const platformRole = me.platform_role ?? ''
  if (PLATFORM_CONSOLE_ROLES.has(platformRole)) {
    if (me.mfa_required) return <OwnerMfaScreen onComplete={loadIdentity} />
    if (pathname !== '/owner') replacePath('/owner')
    return <ShellSuspense label="Carregando Dashem Control..."><OwnerConsole me={me} /></ShellSuspense>
  }

  if (platformRole && !me.memberships?.length) {
    return <AccessState message="Seu papel de plataforma está autenticado, mas este módulo do Console ainda não foi liberado para o perfil atual." onSignOut={signOut} onRetry={loadIdentity} />
  }

  const activeMemberships = (me.memberships ?? []).filter((membership) => membership.status === 'ACTIVE')
  if (!activeMemberships.length) {
    return <AccessState message="Sua identidade não possui membership ativa em um tenant." onSignOut={signOut} onRetry={loadIdentity} />
  }

  const canManage = activeMemberships.some((membership) => MANAGEMENT_ROLES.has(membership.role))
  const canUseKds = activeMemberships.length > 0
  const route = normalizeAuthenticatedRoute(pathname, platformRole, canManage, canUseKds)
  if (route !== pathname) replacePath(route)

  if (route === '/manage') return <ShellSuspense label="Carregando Dashem Gestão..."><ManageShell /></ShellSuspense>
  if (route === '/kds') return <ShellSuspense label="Carregando Dashem KDS..."><KdsShell canManage={canManage} /></ShellSuspense>
  if (route === '/tables') return <ShellSuspense label="Carregando mesas e comandas..."><TablesShell /></ShellSuspense>
  return <ShellSuspense label="Carregando frente de caixa..."><PosShell canManage={canManage} /></ShellSuspense>
}

function ShellSuspense({ label, children }: { label: string; children: React.ReactNode }) {
  return <Suspense fallback={<FullScreenLoader label={label} />}>{children}</Suspense>
}

function FullScreenLoader({ label }: { label: string }) {
  return <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#07101f] text-white"><div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[.04] text-rose-500"><Loader2 className="h-7 w-7 animate-spin" /></div><p className="text-sm font-bold text-slate-400">{label}</p></div>
}

function AccessState({ message, onSignOut, onRetry }: { message: string; onSignOut: () => Promise<void>; onRetry: () => Promise<void> }) {
  return <main className="flex min-h-screen items-center justify-center bg-[#07101f] p-6"><section className="w-full max-w-lg rounded-3xl bg-white p-8 text-center shadow-2xl"><div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-50 text-amber-600"><ShieldAlert className="h-7 w-7" /></div><p className="mt-6 text-xs font-black uppercase tracking-[.18em] text-amber-600">Acesso pendente</p><h1 className="mt-2 text-2xl font-black text-slate-950">Identidade reconhecida</h1><p className="mt-3 leading-7 text-slate-500">{message}</p><div className="mt-7 flex gap-3"><button onClick={onSignOut} className="flex h-11 flex-1 items-center justify-center gap-2 rounded-xl border border-slate-300 font-black text-slate-600"><LogOut className="h-4 w-4" />Sair</button><button onClick={onRetry} className="h-11 flex-1 rounded-xl bg-slate-950 font-black text-white">Verificar novamente</button></div></section></main>
}
