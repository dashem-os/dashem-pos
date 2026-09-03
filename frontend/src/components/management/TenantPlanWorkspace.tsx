import { FileCheck2 } from 'lucide-react'
import { CommercialRequestsPanel } from './CommercialRequestsPanel'

export function TenantPlanWorkspace() {
  return <div className="space-y-6">
    <header className="rounded-3xl border border-dashem-border bg-gradient-to-br from-dashem-surface to-[#14253f] p-6 shadow-xl">
      <div className="flex items-start gap-4">
        <div className="rounded-2xl bg-dashem-red/15 p-3 text-dashem-red"><FileCheck2 className="h-6 w-6" /></div>
        <div><p className="text-[11px] font-extrabold uppercase tracking-[.18em] text-dashem-red">Administração do tenant</p><h1 className="mt-2 text-3xl font-black text-dashem-strong">Plano e solicitações</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-dashem-muted">Consulte a quota vigente e encaminhe ao Owner pedidos de expansão. Solicitações não alteram o acesso até uma decisão contratual auditada.</p></div>
      </div>
    </header>
    <CommercialRequestsPanel />
  </div>
}
