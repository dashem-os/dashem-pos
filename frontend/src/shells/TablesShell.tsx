import { LogOut, ShoppingCart } from 'lucide-react'

import { Toast } from '../components/common/Toast'
import { OperationalContextGate, OperationalSelection } from '../components/context/OperationalContextGate'
import { TableServiceWorkspace } from '../components/tables/TableServiceWorkspace'
import { useAuth } from '../context/AuthContext'
import { PosProvider, usePos } from '../context/PosContext'
import { navigateTo } from '../utils/navigation'


export default function TablesShell() {
  return <OperationalContextGate requireTerminal={false}>{(selection) => <SelectedTablesShell selection={selection} />}</OperationalContextGate>
}

function SelectedTablesShell({ selection }: { selection: OperationalSelection }) {
  return <PosProvider {...selection}><TablesSurface /></PosProvider>
}

function TablesSurface() {
  const { signOut } = useAuth()
  const { loading, toast, tenant, store, permissions, capabilities } = usePos()
  if (loading) return <div className="flex min-h-screen items-center justify-center bg-slate-100 font-bold text-slate-500">Carregando mesas e comandas...</div>
  if (!permissions.includes('table.read') || !('table_service' in capabilities)) {
    return <main className="flex min-h-screen items-center justify-center bg-slate-100 p-6"><section className="max-w-lg rounded-3xl bg-white p-8 text-center shadow-xl"><p className="text-xs font-black uppercase tracking-[.16em] text-rose-600">Acesso não contratado</p><h1 className="mt-2 text-2xl font-black text-slate-950">Mesas e comandas indisponíveis</h1><p className="mt-3 text-sm leading-6 text-slate-500">A permission e a capability da unidade são verificadas separadamente pelo servidor.</p><button onClick={() => navigateTo('/pos')} className="mt-6 rounded-xl bg-rose-600 px-5 py-3 text-sm font-black text-white">Voltar ao PDV</button></section></main>
  }
  return <div className="min-h-screen bg-slate-100">
    <Toast toast={toast} />
    <nav className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-6"><div><p className="text-sm font-black text-slate-950">DASHEM <span className="text-orange-500">MESAS</span></p><p className="text-[10px] font-bold text-slate-500">{tenant?.name} · {store?.name}</p></div><div className="flex gap-2"><button onClick={() => navigateTo('/pos')} className="flex h-9 items-center gap-2 rounded-xl bg-rose-600 px-3 text-xs font-black text-white"><ShoppingCart className="h-4 w-4" />PDV</button><button onClick={signOut} className="flex h-9 items-center gap-2 rounded-xl border border-slate-300 px-3 text-xs font-black text-slate-600"><LogOut className="h-4 w-4" />Sair</button></div></nav>
    <main className="mx-auto max-w-[1600px] p-4 sm:p-6"><TableServiceWorkspace /></main>
  </div>
}
