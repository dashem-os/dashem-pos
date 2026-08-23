import { ChefHat, LogOut } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { navigateTo } from '../utils/navigation'

export default function KdsShell({ canManage }: { canManage: boolean }) {
  const { signOut } = useAuth()
  return <main className="min-h-screen bg-emerald-950 p-6 text-white"><header className="mx-auto flex max-w-6xl items-center justify-between"><div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500 text-emerald-950"><ChefHat /></div><div><p className="font-black">DASHEM KDS</p><p className="text-xs text-emerald-200">Produção</p></div></div><div className="flex gap-2">{canManage && <button onClick={() => navigateTo('/manage')} className="rounded-xl border border-emerald-700 px-4 py-2 text-sm font-bold">Gestão</button>}<button onClick={signOut} className="flex items-center gap-2 rounded-xl border border-emerald-700 px-4 py-2 text-sm font-bold"><LogOut className="h-4 w-4" />Sair</button></div></header><section className="mx-auto mt-24 max-w-xl rounded-3xl border border-emerald-800 bg-emerald-900/60 p-10 text-center"><ChefHat className="mx-auto h-12 w-12 text-emerald-400" /><h1 className="mt-5 text-2xl font-black">KDS separado e protegido</h1><p className="mt-3 leading-7 text-emerald-100">A superfície de produção já possui rota e sessão próprias. Nenhuma comanda fictícia é exibida: o fluxo real de orders e produção será conectado nos sprints S6 e S8.</p></section></main>
}
