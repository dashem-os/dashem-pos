import React, { useState } from 'react'
import { ArrowRight, Eye, EyeOff, Loader2, Mail, ShieldCheck, Sparkles } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

export function SignInScreen() {
  const { configured, signIn, signInSocial, requestPasswordReset } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [recovery, setRecovery] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setSubmitting(true); setError(null); setNotice(null)
    if (recovery) {
      const result = await requestPasswordReset(email.trim())
      if (result) setError(result)
      else setNotice('Enviamos um link seguro para redefinir sua senha.')
    } else setError(await signIn(email.trim(), password))
    setSubmitting(false)
  }

  const social = async (provider: 'google' | 'azure') => {
    setError(null)
    setError(await signInSocial(provider))
  }

  return <main className="relative min-h-screen overflow-hidden bg-[#07111f] font-sans text-white">
    <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_12%_15%,rgba(244,63,94,.25),transparent_30%),radial-gradient(circle_at_78%_72%,rgba(14,165,233,.16),transparent_32%)]" />
    <div className="pointer-events-none absolute inset-0 opacity-[.05] [background-image:linear-gradient(rgba(255,255,255,.8)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.8)_1px,transparent_1px)] [background-size:48px_48px]" />
    <div className="relative mx-auto grid min-h-screen w-full max-w-[1580px] lg:grid-cols-[minmax(0,1fr)_minmax(430px,540px)]">
      <section className="flex min-h-[280px] flex-col justify-between px-6 py-7 sm:px-10 lg:min-h-screen lg:px-16 lg:py-12 xl:px-20">
        <Brand />
        <div className="max-w-3xl py-10 lg:py-0">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[.05] px-3 py-1.5 text-[11px] font-black uppercase tracking-[.18em] text-rose-300 backdrop-blur"><Sparkles className="h-3.5 w-3.5" />Gestão conectada à operação</div>
          <h1 className="mt-6 max-w-2xl text-4xl font-black leading-[.98] tracking-[-.045em] sm:text-5xl lg:text-6xl xl:text-7xl">Seu negócio em movimento. Sob seu controle.</h1>
          <p className="mt-6 max-w-xl text-base leading-7 text-slate-300 sm:text-lg">Entre para administrar sua empresa, acompanhar resultados e conduzir cada unidade no contexto certo.</p>
        </div>
        <div className="hidden items-center gap-3 text-xs text-slate-500 lg:flex"><ShieldCheck className="h-4 w-4 text-emerald-400" />Identidade protegida e ações auditáveis</div>
      </section>
      <section className="flex items-center justify-center border-t border-white/10 bg-slate-50 px-5 py-8 text-slate-950 lg:min-h-screen lg:border-l lg:border-t-0 lg:px-12">
        <div className="w-full max-w-md">
          <p className="text-xs font-black uppercase tracking-[.2em] text-brand-ink">{recovery ? 'Recuperar acesso' : 'Acesso à gestão'}</p>
          <h2 className="mt-3 text-3xl font-black tracking-[-.035em] sm:text-4xl">{recovery ? 'Redefina sua senha' : 'Bem-vindo de volta'}</h2>
          <p className="mt-3 text-sm leading-6 text-slate-500">{recovery ? 'Informe seu e-mail para receber um link seguro.' : 'Use sua identidade administrativa. A operação do terminal é iniciada no próprio ponto autorizado.'}</p>
          {!configured ? <div className="mt-7 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Configure <code>VITE_SUPABASE_URL</code> e <code>VITE_SUPABASE_PUBLISHABLE_KEY</code> para habilitar o login.</div> : <>
            {!recovery && <><div className="mt-8 grid grid-cols-2 gap-3"><Social onClick={() => social('google')}>Google</Social><Social onClick={() => social('azure')}>Microsoft</Social></div><Divider /></>}
            <form onSubmit={submit} className={recovery ? 'mt-8 space-y-5' : 'space-y-5'}>
              <Field label="E-mail"><Mail className="h-5 w-5 text-slate-400" /><input className="h-full min-w-0 flex-1 bg-transparent px-3 font-semibold outline-none" type="email" value={email} onChange={event => setEmail(event.target.value)} required autoComplete="email" placeholder="voce@empresa.com.br" /></Field>
              {!recovery && <Field label="Senha"><input className="h-full min-w-0 flex-1 bg-transparent font-semibold outline-none" type={showPassword ? 'text' : 'password'} value={password} onChange={event => setPassword(event.target.value)} required autoComplete="current-password" placeholder="Sua senha" /><button type="button" onClick={() => setShowPassword(value => !value)} className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}>{showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}</button></Field>}
              {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">{error}</p>}
              {notice && <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-semibold text-emerald-700">{notice}</p>}
              <button disabled={submitting} className="flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-brand font-black text-brand-contrast shadow-[0_16px_36px_rgba(225,29,72,.22)] transition hover:-translate-y-0.5 hover:bg-brand-strong disabled:translate-y-0 disabled:opacity-60">{submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <>{recovery ? 'Enviar link seguro' : 'Entrar na Gestão'}<ArrowRight className="h-4 w-4" /></>}</button>
            </form>
            <button type="button" onClick={() => { setRecovery(value => !value); setError(null); setNotice(null) }} className="mt-4 flex min-h-11 w-full items-center justify-center text-sm font-bold text-slate-500 hover:text-brand-ink">{recovery ? 'Voltar ao login' : 'Esqueci minha senha'}</button>
          </>}
          <p className="mt-8 border-t border-slate-200 pt-5 text-center text-xs leading-5 text-slate-500">Esta entrada é exclusiva da Gestão. O acesso operacional acontece no próprio terminal autorizado.</p>
        </div>
      </section>
    </div>
  </main>
}

function Brand() { return <div className="flex items-center gap-3"><div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand text-lg font-black shadow-[0_16px_45px_rgba(225,29,72,.35)]">D</div><div><p className="text-lg font-black tracking-tight">DASHEM POS</p><p className="text-[10px] font-bold uppercase tracking-[.24em] text-slate-400">Commerce Operating System</p></div></div> }
function Social({ onClick, children }: { onClick: () => void; children: React.ReactNode }) { return <button type="button" onClick={onClick} className="h-12 rounded-xl border border-slate-200 bg-white text-sm font-black text-slate-700 transition hover:border-slate-300 hover:bg-slate-100">{children}</button> }
function Divider() { return <div className="my-6 flex items-center gap-3 text-[10px] font-black uppercase tracking-[.16em] text-slate-400"><span className="h-px flex-1 bg-slate-200" />ou use seu e-mail<span className="h-px flex-1 bg-slate-200" /></div> }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block text-sm font-black text-slate-700">{label}<div className="mt-2 flex h-14 items-center rounded-xl border border-slate-300 bg-white px-4 transition focus-within:border-brand-ink focus-within:ring-4 focus-within:ring-brand-soft">{children}</div></label> }
