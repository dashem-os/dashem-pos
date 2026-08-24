import { Toast } from '../components/common/Toast'
import { PosProvider, usePos } from '../context/PosContext'
import { PosLayout } from '../layouts/PosLayout'
import { OperationalContextGate, OperationalSelection } from '../components/context/OperationalContextGate'

export default function PosShell() {
  return <OperationalContextGate requireTerminal>{(selection) => <SelectedPosShell selection={selection} />}</OperationalContextGate>
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
