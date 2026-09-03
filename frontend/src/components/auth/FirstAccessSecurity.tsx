import React, { useEffect, useMemo, useState } from 'react'
import { Check, Copy, KeyRound, Loader2, LogOut, ShieldCheck } from 'lucide-react'
import { completeOwnerOnboarding, completePasswordSetup } from '../../services/api'
import { TotpEnrollment, useAuth } from '../../context/AuthContext'

const requirements = [
  ['12 caracteres', (value: string) => value.length >= 12],
  ['Letra maiúscula', (value: string) => /[A-Z]/.test(value)],
  ['Letra minúscula', (value: string) => /[a-z]/.test(value)],
  ['Número', (value: string) => /\d/.test(value)],
  ['Símbolo', (value: string) => /[^A-Za-z0-9]/.test(value)],
] as const

function SecurityShell({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  const { signOut } = useAuth()
  return (
    <main className="min-h-screen bg-[#07101f] p-6 text-white sm:p-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8 flex items-center justify-between text-white">
          <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand font-black">D</div><span className="font-black">DASHEM POS</span></div>
          <button onClick={signOut} className="flex items-center gap-2 text-sm font-bold text-slate-400 hover:text-white"><LogOut className="h-4 w-4" />Sair</button>
        </div>
        <section className="rounded-3xl bg-white p-7 shadow-2xl sm:p-10">
          <div className="mb-7 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-soft text-brand-ink"><ShieldCheck className="h-6 w-6" /></div>
          <p className="text-xs font-black uppercase tracking-[.2em] text-brand-ink">Primeiro acesso seguro</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight">{title}</h1>
          <p className="mt-3 leading-7 text-slate-500">{description}</p>
          {children}
        </section>
      </div>
    </main>
  )
}

export function PasswordSetupScreen({ onComplete, recovery = false }: { onComplete: () => Promise<void>; recovery?: boolean }) {
  const { updatePassword } = useAuth()
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const valid = requirements.every(([, test]) => test(password)) && password === confirmation

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!valid) return
    setLoading(true)
    setError(null)
    const authError = await updatePassword(password)
    if (authError) {
      setError(authError)
      setLoading(false)
      return
    }
    try {
      // Password recovery and first access finish the same Dashem-side
      // security transition. Keeping this call idempotent prevents a user
      // whose password was already changed in Supabase from being sent back
      // to this screen on every subsequent sign-in.
      await completePasswordSetup()
      await onComplete()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível concluir a configuração.')
      setLoading(false)
    }
  }

  return (
    <SecurityShell title={recovery ? 'Defina uma nova senha' : 'Crie sua senha de acesso'} description="Sua senha é protegida pelo Supabase Auth e nunca é armazenada pelo Dashem POS.">
      <form onSubmit={submit} className="mt-8 space-y-5">
        <label className="block text-sm font-bold">Nova senha<input type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 outline-none focus:border-brand-ink focus:ring-4 focus:ring-brand-soft" /></label>
        <label className="block text-sm font-bold">Confirme a senha<input type="password" autoComplete="new-password" value={confirmation} onChange={e => setConfirmation(e.target.value)} className="mt-2 h-12 w-full rounded-xl border border-slate-300 px-4 outline-none focus:border-brand-ink focus:ring-4 focus:ring-brand-soft" /></label>
        <div className="grid grid-cols-2 gap-2 rounded-2xl bg-slate-50 p-4 text-xs font-bold text-slate-500 sm:grid-cols-3">
          {requirements.map(([label, test]) => <span key={label} className={`flex items-center gap-2 ${test(password) ? 'text-emerald-700' : ''}`}><Check className="h-3.5 w-3.5" />{label}</span>)}
          <span className={`flex items-center gap-2 ${password && password === confirmation ? 'text-emerald-700' : ''}`}><Check className="h-3.5 w-3.5" />Senhas iguais</span>
        </div>
        {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm font-semibold text-red-700">{error}</p>}
        <button disabled={!valid || loading} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-brand font-black text-brand-contrast disabled:cursor-not-allowed disabled:opacity-40">{loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <><KeyRound className="h-5 w-5" />Salvar senha forte</>}</button>
      </form>
    </SecurityShell>
  )
}

export function OwnerMfaScreen({ onComplete }: { onComplete: () => Promise<void> }) {
  const { listTotpFactors, enrollTotp, verifyTotp } = useAuth()
  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null)
  const [factorId, setFactorId] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const prepare = async () => {
      const listed = await listTotpFactors()
      if (!active) return
      if (listed.error) { setError(listed.error); setLoading(false); return }
      const verified = listed.factors.find(factor => factor.status === 'verified')
      if (verified) { setFactorId(verified.id); setLoading(false); return }
      const result = await enrollTotp()
      if (!active) return
      setEnrollment(result.enrollment)
      setFactorId(result.enrollment?.factorId ?? null)
      setError(result.error)
      setLoading(false)
    }
    prepare()
    return () => { active = false }
  }, [enrollTotp, listTotpFactors])

  const verify = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!factorId) return
    setLoading(true)
    setError(null)
    const authError = await verifyTotp(factorId, code.replace(/\D/g, ''))
    if (authError) { setError(authError); setLoading(false); return }
    try {
      await completeOwnerOnboarding()
      await onComplete()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível validar o segundo fator.')
      setLoading(false)
    }
  }

  const qrSource = useMemo(() => {
    if (!enrollment?.qrCode) return null
    return enrollment.qrCode.startsWith('data:') ? enrollment.qrCode : `data:image/svg+xml;utf-8,${encodeURIComponent(enrollment.qrCode)}`
  }, [enrollment])

  return (
    <SecurityShell title={enrollment ? 'Proteja o Console Owner' : 'Confirme seu segundo fator'} description={enrollment ? 'Escaneie o QR code com seu aplicativo autenticador. O acesso administrativo exige MFA.' : 'Digite o código atual do seu aplicativo autenticador para continuar.'}>
      {loading && !factorId ? <div className="flex justify-center py-12"><Loader2 className="h-7 w-7 animate-spin text-brand-ink" /></div> : (
        <form onSubmit={verify} className="mt-8">
          {qrSource && <div className="mb-6 grid gap-5 rounded-2xl border border-slate-200 bg-slate-50 p-5 sm:grid-cols-[180px_1fr] sm:items-center"><img src={qrSource} alt="QR code para cadastrar o segundo fator" className="h-44 w-44 rounded-xl bg-white p-2" /><div><p className="text-sm font-bold">Não consegue escanear?</p><p className="mt-2 break-all font-mono text-xs text-slate-500">{enrollment?.secret}</p><button type="button" onClick={() => enrollment && navigator.clipboard.writeText(enrollment.secret)} className="mt-3 flex items-center gap-2 text-xs font-black text-brand-ink"><Copy className="h-3.5 w-3.5" />Copiar chave</button></div></div>}
          <label className="block text-sm font-bold">Código de 6 dígitos<input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} className="mt-2 h-14 w-full rounded-xl border border-slate-300 px-4 text-center font-mono text-2xl font-black tracking-[.45em] outline-none focus:border-brand-ink focus:ring-4 focus:ring-brand-soft" /></label>
          {error && <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-sm font-semibold text-red-700">{error}</p>}
          <button disabled={code.length !== 6 || loading || !factorId} className="mt-5 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-brand font-black text-brand-contrast disabled:opacity-40">{loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <><ShieldCheck className="h-5 w-5" />Validar e acessar o Console</>}</button>
        </form>
      )}
    </SecurityShell>
  )
}
