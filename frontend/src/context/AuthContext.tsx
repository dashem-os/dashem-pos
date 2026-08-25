import React, { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import type { Factor, Session } from '@supabase/supabase-js'
import { endOperationalSession, heartbeatOperationalSession, setApiAccessTokenProvider } from '../services/api'
import { hasSupabaseConfig, supabase } from '../services/supabase'
import { clearRecoveryModeFromBrowser } from '../utils/authUrl'

export interface TotpEnrollment {
  factorId: string
  qrCode: string
  secret: string
}

interface AuthContextValue {
  session: Session | null
  loading: boolean
  configured: boolean
  passwordRecovery: boolean
  signIn: (email: string, password: string) => Promise<string | null>
  signInSocial: (provider: 'google' | 'azure') => Promise<string | null>
  requestPasswordReset: (email: string) => Promise<string | null>
  updatePassword: (password: string) => Promise<string | null>
  listTotpFactors: () => Promise<{ factors: Factor[]; error: string | null }>
  enrollTotp: () => Promise<{ enrollment: TotpEnrollment | null; error: string | null }>
  verifyTotp: (factorId: string, code: string) => Promise<string | null>
  operationalActive: boolean
  terminalActive: boolean
  terminalToken: string | null
  activateOperationalSession: (token: string) => void
  authorizeTerminal: (token: string) => void
  clearTerminalAuthorization: () => void
  clearOperationalSession: () => void
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

function readExpiringToken(storage: Storage, key: string) {
  const token = storage.getItem(key)
  if (!token) return null
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))) as { exp?: number }
    if (!payload.exp || payload.exp * 1000 <= Date.now()) {
      storage.removeItem(key)
      return null
    }
    return token
  } catch {
    storage.removeItem(key)
    return null
  }
}

function readOperationalToken() { return readExpiringToken(sessionStorage, 'dashem.operational_token') }
function readTerminalToken() { return readExpiringToken(localStorage, 'dashem.terminal_token') }

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [passwordRecovery, setPasswordRecovery] = useState(false)
  const [operationalToken, setOperationalToken] = useState<string | null>(readOperationalToken)
  const [terminalToken, setTerminalToken] = useState<string | null>(readTerminalToken)

  useEffect(() => {
    if (!supabase) {
      setLoading(false)
      return
    }
    supabase.auth.getSession().then(({ data }) => {
      const localOperationalToken = readOperationalToken()
      setApiAccessTokenProvider(async () => localOperationalToken ?? data.session?.access_token ?? null)
      setSession(data.session)
      setLoading(false)
    })
    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      const localOperationalToken = readOperationalToken()
      setApiAccessTokenProvider(async () => localOperationalToken ?? nextSession?.access_token ?? null)
      setSession(nextSession)
      setPasswordRecovery(event === 'PASSWORD_RECOVERY')
      if (event === 'SIGNED_OUT') clearRecoveryModeFromBrowser()
      setLoading(false)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  useLayoutEffect(() => {
    setApiAccessTokenProvider(async () => operationalToken ?? session?.access_token ?? null)
  }, [session, operationalToken])

  useEffect(() => {
    if (!operationalToken) return
    let active = true
    const heartbeat = async () => {
      const valid = await heartbeatOperationalSession(operationalToken).catch(() => true)
      if (!active || valid) return
      sessionStorage.removeItem('dashem.operational_token')
      setOperationalToken(null)
      setApiAccessTokenProvider(async () => session?.access_token ?? null)
      window.location.assign('/operate')
    }
    void heartbeat()
    const interval = window.setInterval(heartbeat, 30_000)
    return () => { active = false; window.clearInterval(interval) }
  }, [operationalToken, session])

  const value = useMemo<AuthContextValue>(() => ({
    session,
    loading,
    configured: hasSupabaseConfig,
    passwordRecovery,
    operationalActive: Boolean(operationalToken),
    terminalActive: Boolean(terminalToken),
    terminalToken,
    activateOperationalSession: token => {
      sessionStorage.setItem('dashem.operational_token', token)
      setOperationalToken(token)
      setApiAccessTokenProvider(async () => token)
    },
    clearOperationalSession: () => {
      sessionStorage.removeItem('dashem.operational_token')
      setOperationalToken(null)
      setApiAccessTokenProvider(async () => session?.access_token ?? null)
    },
    authorizeTerminal: token => {
      localStorage.setItem('dashem.terminal_token', token)
      setTerminalToken(token)
    },
    clearTerminalAuthorization: () => {
      localStorage.removeItem('dashem.terminal_token')
      setTerminalToken(null)
    },
    signIn: async (email, password) => {
      if (!supabase) return 'Supabase Auth não está configurado.'
      const { error } = await supabase.auth.signInWithPassword({ email, password })
      if (!error) {
        setPasswordRecovery(false)
        clearRecoveryModeFromBrowser()
      }
      return error?.message ?? null
    },
    signInSocial: async provider => {
      if (!supabase) return 'Supabase Auth não está configurado.'
      const { error } = await supabase.auth.signInWithOAuth({
        provider,
        options: { redirectTo: `${window.location.origin}/login` },
      })
      return error?.message ?? null
    },
    requestPasswordReset: async email => {
      if (!supabase) return 'Supabase Auth não está configurado.'
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/login?mode=recovery`,
      })
      return error?.message ?? null
    },
    updatePassword: async password => {
      if (!supabase) return 'Supabase Auth não está configurado.'
      const { error } = await supabase.auth.updateUser({ password })
      return error?.message ?? null
    },
    listTotpFactors: async () => {
      if (!supabase) return { factors: [], error: 'Supabase Auth não está configurado.' }
      const { data, error } = await supabase.auth.mfa.listFactors()
      return { factors: data?.all.filter(factor => factor.factor_type === 'totp') ?? [], error: error?.message ?? null }
    },
    enrollTotp: async () => {
      if (!supabase) return { enrollment: null, error: 'Supabase Auth não está configurado.' }
      const { data, error } = await supabase.auth.mfa.enroll({
        factorType: 'totp',
        friendlyName: 'Dashem POS Owner',
      })
      return {
        enrollment: data ? {
          factorId: data.id,
          qrCode: data.totp.qr_code,
          secret: data.totp.secret,
        } : null,
        error: error?.message ?? null,
      }
    },
    verifyTotp: async (factorId, code) => {
      if (!supabase) return 'Supabase Auth não está configurado.'
      const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId, code })
      if (!error) {
        const { data } = await supabase.auth.getSession()
        setApiAccessTokenProvider(async () => data.session?.access_token ?? null)
        setSession(data.session)
      }
      return error?.message ?? null
    },
    signOut: async () => {
      setPasswordRecovery(false)
      if (operationalToken) {
        await endOperationalSession(operationalToken).catch(() => undefined)
        sessionStorage.removeItem('dashem.operational_token')
        setOperationalToken(null)
        setApiAccessTokenProvider(async () => session?.access_token ?? null)
        window.location.assign('/operate')
        return
      }
      if (supabase) await supabase.auth.signOut()
      clearRecoveryModeFromBrowser()
      if (terminalToken) window.location.assign('/operate')
    },
  }), [session, loading, passwordRecovery, operationalToken, terminalToken])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
