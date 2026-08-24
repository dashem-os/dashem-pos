import React, { useState } from 'react'
import { ArrowRight, Building2, KeyRound, Loader2, LockKeyhole, Mail, ShieldCheck } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { navigateTo } from '../../utils/navigation'

export function SignInScreen() {
  const { configured, signIn, signInSocial, requestPasswordReset } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [recovery, setRecovery] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    setNotice(null)
    if (recovery) {
      const result = await requestPasswordReset(email.trim())
      if (result) setError(result)
      else setNotice('Enviamos um link seguro para redefinir sua senha.')
    } else {
      setError(await signIn(email.trim(), password))
    }
    setSubmitting(false)
  }

  const social = async (provider: 'google' | 'azure') => {
    setError(null)
    setError(await signInSocial(provider))
  }

  return (
    <main className="min-h-screen bg-[#07101f] text-slate-950 lg:grid lg:grid-cols-[minmax(0,1fr)_560px]">
      <section className="relative hidden overflow-hidden p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_10%,rgba(225,29,72,.22),transparent_34%),radial-gradient(circle_at_80%_80%,rgba(14,165,233,.14),transparent_38%)]" />
        <div className="relative flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-rose-600 text-lg font-black shadow-[0_16px_50px_rgba(225,29,72,.35)]">D</div>
          <div>
            <p className="text-lg font-black tracking-tight">DASHEM POS</p>
            <p className="text-xs font-semibold uppercase tracking-[.18em] text-slate-400">Commerce Operating System</p>
          </div>
        </div>

        <div className="relative max-w-2xl">
          <p className="mb-5 text-sm font-bold uppercase tracking-[.24em] text-rose-400">Uma identidade. O ambiente certo.</p>
          <h1 className="text-5xl font-black leading-[1.05] tracking-[-.04em]">Operação, gestão e plataforma em um único acesso.</h1>
          <p className="mt-6 max-w-xl text-lg leading-8 text-slate-300">O Dashem reconhece seu papel, seus tenants e suas lojas. Cada usuário entra somente no contexto autorizado.</p>
          <div className="mt-10 grid max-w-xl grid-cols-3 gap-3 text-sm">
            {[
              [ShieldCheck, 'Acesso protegido'],
              [Building2, 'Multi-tenant real'],
              [LockKeyhole, 'Permissões efetivas'],
            ].map(([Icon, label]) => (
              <div key={String(label)} className="rounded-2xl border border-white/10 bg-white/[.04] p-4 backdrop-blur">
                <Icon className="mb-3 h-5 w-5 text-rose-400" />
                <p className="font-bold text-slate-200">{String(label)}</p>
              </div>
            ))}
          </div>
        </div>
        <p className="relative text-xs text-slate-500">© 2026 Dashem. Acesso monitorado e auditável.</p>
      </section>

      <section className="flex min-h-screen items-center justify-center bg-slate-50 p-6 sm:p-10">
        <div className="w-full max-w-md">
          <div className="mb-9 lg:hidden">
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-2xl bg-rose-600 font-black text-white">D</div>
            <p className="font-black">DASHEM POS</p>
          </div>
          <p className="text-sm font-bold text-rose-600">{recovery ? 'RECUPERAR ACESSO' : 'ACESSO SEGURO'}</p>
          <h2 className="mt-2 text-3xl font-black tracking-tight text-slate-950">{recovery ? 'Redefina sua senha' : 'Bem-vindo ao Dashem'}</h2>
          <p className="mt-3 text-sm leading-6 text-slate-500">{recovery ? 'Informe seu e-mail para receber o link de recuperação.' : 'Use as credenciais associadas ao seu convite ou organização.'}</p>

          {!configured ? (
            <div className="mt-8 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              Configure <code>VITE_SUPABASE_URL</code> e <code>VITE_SUPABASE_PUBLISHABLE_KEY</code> para habilitar o login.
            </div>
          ) : (
            <>
              {!recovery && (
                <div className="mt-8 grid grid-cols-2 gap-3">
                  <button type="button" onClick={() => social('google')} className="h-12 rounded-xl border border-slate-200 bg-white text-sm font-bold text-slate-700 transition hover:border-slate-300 hover:bg-slate-100">Google</button>
                  <button type="button" onClick={() => social('azure')} className="h-12 rounded-xl border border-slate-200 bg-white text-sm font-bold text-slate-700 transition hover:border-slate-300 hover:bg-slate-100">Microsoft</button>
                </div>
              )}
              {!recovery && <div className="my-6 flex items-center gap-3 text-xs font-bold uppercase tracking-wider text-slate-400"><span className="h-px flex-1 bg-slate-200" />ou e-mail<span className="h-px flex-1 bg-slate-200" /></div>}
              <form onSubmit={submit} className={recovery ? 'mt-8 space-y-5' : 'space-y-5'}>
                <label className="block text-sm font-bold text-slate-700">
                  E-mail
                  <div className="relative mt-2">
                    <Mail className="absolute left-4 top-3.5 h-5 w-5 text-slate-400" />
                    <input className="h-12 w-full rounded-xl border border-slate-300 bg-white pl-12 pr-4 font-medium outline-none transition focus:border-rose-500 focus:ring-4 focus:ring-rose-100" type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" />
                  </div>
                </label>
                {!recovery && (
                  <label className="block text-sm font-bold text-slate-700">
                    Senha
                    <input className="mt-2 h-12 w-full rounded-xl border border-slate-300 bg-white px-4 font-medium outline-none transition focus:border-rose-500 focus:ring-4 focus:ring-rose-100" type="password" value={password} onChange={e => setPassword(e.target.value)} required autoComplete="current-password" />
                  </label>
                )}
                {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">{error}</p>}
                {notice && <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-semibold text-emerald-700">{notice}</p>}
                <button disabled={submitting} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-rose-600 font-black text-white shadow-lg shadow-rose-600/20 transition hover:bg-rose-700 disabled:opacity-60">
                  {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <>{recovery ? 'Enviar link seguro' : 'Entrar'}<ArrowRight className="h-4 w-4" /></>}
                </button>
              </form>
              <button type="button" onClick={() => { setRecovery(!recovery); setError(null); setNotice(null) }} className="mt-4 flex min-h-11 w-full items-center justify-center text-center text-sm font-bold text-slate-500 hover:text-rose-600">
                {recovery ? 'Voltar ao login' : 'Esqueci minha senha'}
              </button>
              {!recovery && <><div className="my-5 flex items-center gap-3 text-xs font-bold uppercase tracking-wider text-slate-400"><span className="h-px flex-1 bg-slate-200" />ou operação<span className="h-px flex-1 bg-slate-200" /></div><button type="button" onClick={() => navigateTo('/operate')} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white text-sm font-black text-slate-700 hover:border-rose-300 hover:text-rose-600"><KeyRound className="h-4 w-4" />Entrar com código e PIN</button><p className="mt-3 text-center text-[11px] leading-5 text-slate-400">Disponível somente em um terminal previamente autorizado pela gestão.</p></>}
            </>
          )}
        </div>
      </section>
    </main>
  )
}
