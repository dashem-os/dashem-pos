import { Toast } from '../components/common/Toast'
import { PosProvider, usePos } from '../context/PosContext'
import { PosLayout } from '../layouts/PosLayout'

export default function PosShell({ canManage }: { canManage: boolean }) {
  return <PosProvider><PosSurface canManage={canManage} /></PosProvider>
}

function PosSurface({ canManage }: { canManage: boolean }) {
  const { loading, toast } = usePos()
  if (loading) return <ShellLoader label="Carregando frente de caixa..." />
  return <><Toast toast={toast} /><PosLayout canManage={canManage} /></>
}

function ShellLoader({ label }: { label: string }) {
  return <div className="flex min-h-screen items-center justify-center bg-slate-100 font-bold text-slate-500">{label}</div>
}
