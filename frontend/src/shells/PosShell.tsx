import { Toast } from '../components/common/Toast'
import { PosProvider, usePos } from '../context/PosContext'
import { PosLayout } from '../layouts/PosLayout'
import { OperationalSelection } from '../components/context/OperationalContextGate'
import { OperationalSessionGate } from '../components/context/OperationalSessionGate'
import { OperationalContextGate } from '../components/context/OperationalContextGate'
import { useAuth } from '../context/AuthContext'

export default function PosShell() {
  const { session } = useAuth()
  const managementAccess = new URLSearchParams(window.location.search).get('access') === 'management'

  if (managementAccess && session) {
    return <OperationalContextGate requireTerminal>{(selection) => <SelectedPosShell selection={selection} />}</OperationalContextGate>
  }
  return <OperationalSessionGate>{(selection) => <SelectedPosShell selection={selection} />}</OperationalSessionGate>
}

function SelectedPosShell({ selection }: { selection: OperationalSelection }) {
  return <PosProvider {...selection}><PosSurface /></PosProvider>
}

function PosSurface() {
  const { loading, toast } = usePos()
  if (loading) return <ShellLoader label="Carregando frente de caixa..." />
  return <><Toast toast={toast} /><PosLayout /></>
}

function ShellLoader({ label }: { label: string }) {
  return <div className="flex min-h-screen items-center justify-center bg-slate-100 font-bold text-slate-500">{label}</div>
}
