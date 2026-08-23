import { Toast } from '../components/common/Toast'
import { PosProvider, usePos } from '../context/PosContext'
import { ManagementLayout } from '../layouts/ManagementLayout'

export default function ManageShell() {
  return <PosProvider><ManageSurface /></PosProvider>
}

function ManageSurface() {
  const { loading, toast } = usePos()
  if (loading) return <div className="flex min-h-screen items-center justify-center bg-dashem-bg font-bold text-dashem-muted">Carregando gestão...</div>
  return <><Toast toast={toast} /><ManagementLayout /></>
}
