import React, { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import type { Factor, Session } from '@supabase/supabase-js'
import { setApiAccessTokenProvider } from '../services/api'
import { hasSupabaseConfig, supabase } from '../services/supabase'

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
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [passwordRecovery, setPasswordRecovery] = useState(false)

  useEffect(() => {
    if (!supabase) {
      setLoading(false)
      return
    }
    supabase.auth.getSession().then(({ data }) => {
      setApiAccessTokenProvider(async () => data.session?.access_token ?? null)
      setSession(data.session)
      setLoading(false)
    })
    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      setApiAccessTokenProvider(async () => nextSession?.access_token ?? null)
      setSession(nextSession)
      setPasswordRecovery(event === 'PASSWORD_RECOVERY')
      setLoading(false)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  useLayoutEffect(() => {
    setApiAccessTokenProvider(async () => session?.access_token ?? null)
  }, [session])

  const value = useMemo<AuthContextValue>(() => ({
    session,
    loading,
    configured: hasSupabaseConfig,
    passwordRecovery,
    signIn: async (email, password) => {
      if (!supabase) return 'Supabase Auth não está configurado.'
      const { error } = await supabase.auth.signInWithPassword({ email, password })
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
      if (supabase) await supabase.auth.signOut()
    },
  }), [session, loading, passwordRecovery])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
