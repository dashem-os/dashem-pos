import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ChefHat, Clock3, Loader2, LogOut, RefreshCw } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { navigateTo } from '../utils/navigation'
import { OperationalContextGate, OperationalSelection } from '../components/context/OperationalContextGate'
import * as api from '../services/api'

export default function KdsShell({ canManage }: { canManage: boolean }) {
  return <OperationalContextGate requireTerminal={false}>{(selection) => <SelectedKdsShell selection={selection} canManage={canManage} />}</OperationalContextGate>
}

const nextStatus: Partial<Record<api.ProductionTicketProjection['ticket']['status'], api.ProductionTicketProjection['ticket']['status']>> = { NEW: 'ACCEPTED', ACCEPTED: 'PREPARING', PREPARING: 'READY', READY: 'DELIVERED' }
const labels: Record<api.ProductionTicketProjection['ticket']['status'], string> = { NEW: 'Aceitar', ACCEPTED: 'Iniciar preparo', PREPARING: 'Marcar pronto', READY: 'Entregar', DELIVERED: 'Entregue', CANCELED: 'Cancelado' }

function SelectedKdsShell({ selection, canManage }: { selection: OperationalSelection; canManage: boolean }) {
  const { signOut } = useAuth()
  const headers = useMemo(() => ({ 'X-Tenant-ID': selection.tenantId, 'X-Store-ID': selection.storeId }), [selection])
  const [points, setPoints] = useState<api.ProductionPoint[]>([])
  const [tickets, setTickets] = useState<api.ProductionTicketProjection[]>([])
  const [pointId, setPointId] = useState(''); const [operatorId, setOperatorId] = useState('')
  const [allowed, setAllowed] = useState<boolean | null>(null); const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null); const [error, setError] = useState<string | null>(null)
  const deviceId = useMemo(() => { const key=`dashem.kds.device.${selection.storeId}`; const value=sessionStorage.getItem(key)||`kds-${crypto.randomUUID()}`; sessionStorage.setItem(key,value); return value }, [selection.storeId])
  const load = useCallback(async () => {
    try {
      const [access, me, nextPoints, nextTickets] = await Promise.all([api.fetchEffectiveAccess(headers), api.fetchMe(), api.fetchProductionPoints(headers), api.fetchProductionTickets(headers, pointId || undefined)])
      setAllowed(Boolean(access.capabilities.kitchen_routing && access.permissions.includes('production.read')))
      setOperatorId(me.user?.id || '00000000-0000-0000-0000-000000000001'); setPoints(nextPoints); setTickets(nextTickets); setError(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Produção indisponível.') } finally { setLoading(false) }
  }, [headers, pointId])
  useEffect(() => { void load(); const timer=window.setInterval(() => void load(),10000); return ()=>window.clearInterval(timer) }, [load])
  const transition = async (projection: api.ProductionTicketProjection) => {
    const target=nextStatus[projection.ticket.status]; if(!target||!operatorId)return; setBusy(projection.ticket.id)
    try { await api.transitionProductionTicket(headers,projection.ticket.id,crypto.randomUUID(),{target,expected_version:projection.ticket.version,actor_id:operatorId,device_id:deviceId}); await load() }
    catch(reason){setError(reason instanceof Error?reason.message:'Conflito na fila de produção.');await load()} finally{setBusy(null)}
  }
  if (allowed===false) return <main className="flex min-h-screen items-center justify-center bg-emerald-950 p-6 text-emerald-100"><div className="max-w-lg rounded-3xl border border-emerald-800 p-8 text-center"><AlertTriangle className="mx-auto"/><h1 className="mt-4 text-xl font-black">KDS não contratado ou não autorizado</h1><p className="mt-2 text-sm">A capability kitchen_routing e a permissão production.read precisam estar efetivas nesta unidade.</p></div></main>
  return <main className="min-h-screen bg-[#052e2b] p-4 text-white lg:p-6"><header className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4"><div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-400 text-emerald-950"><ChefHat /></div><div><p className="font-black">DASHEM KDS</p><p className="text-xs text-emerald-200">Fila persistida · dispositivo {deviceId.slice(-8)}</p></div></div><div className="flex gap-2"><button onClick={()=>void load()} className="rounded-xl border border-emerald-700 p-2"><RefreshCw className={`h-5 w-5 ${loading?'animate-spin':''}`}/></button>{canManage&&<button onClick={()=>navigateTo('/manage')} className="rounded-xl border border-emerald-700 px-4 py-2 text-sm font-bold">Gestão</button>}<button onClick={signOut} className="flex items-center gap-2 rounded-xl border border-emerald-700 px-4 py-2 text-sm font-bold"><LogOut className="h-4 w-4"/>Sair</button></div></header><section className="mx-auto mt-6 max-w-7xl"><div className="flex flex-wrap items-center gap-2"><button onClick={()=>setPointId('')} className={`rounded-full px-4 py-2 text-xs font-black ${!pointId?'bg-emerald-400 text-emerald-950':'bg-emerald-900'}`}>Todos</button>{points.map(point=><button key={point.id} onClick={()=>setPointId(point.id)} className={`rounded-full px-4 py-2 text-xs font-black ${pointId===point.id?'bg-emerald-400 text-emerald-950':'bg-emerald-900'} ${!point.is_active?'opacity-50':''}`}>{point.name}{!point.is_active?' · indisponível':''}</button>)}</div>{error&&<p className="mt-4 rounded-xl border border-amber-500 bg-amber-950/60 p-3 text-sm text-amber-100">{error}</p>}{loading&&tickets.length===0&&<Loader2 className="mx-auto mt-20 animate-spin"/>}{!loading&&tickets.length===0&&<div className="mt-16 rounded-3xl border border-dashed border-emerald-700 p-12 text-center text-emerald-200"><ChefHat className="mx-auto h-10 w-10"/><p className="mt-4 font-black">Fila vazia</p><p className="mt-1 text-sm">Nenhuma comanda fictícia é exibida. Tickets surgem somente após dispatch persistido.</p></div>}<div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{tickets.map(projection=><article key={projection.ticket.id} className="rounded-3xl bg-white p-5 text-slate-950 shadow-xl"><div className="flex items-start justify-between"><div><p className="text-xs font-black uppercase tracking-wider text-emerald-700">{projection.point.name}</p><p className="mt-1 font-mono text-xs text-slate-500">#{projection.ticket.order_id.slice(0,8)}</p></div><span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-black">{projection.ticket.status} · v{projection.ticket.version}</span></div><p className="mt-3 flex items-center gap-1 text-xs text-slate-500"><Clock3 className="h-3.5 w-3.5"/>{new Date(projection.ticket.created_at).toLocaleTimeString('pt-BR')}</p><div className="mt-4 space-y-3">{projection.items.map(item=><div key={item.id} className={`rounded-xl border p-3 ${item.operation==='CANCEL'?'border-red-300 bg-red-50':'border-slate-200'}`}><p className="font-black">{Number(item.quantity)}× {item.product_name_snapshot}</p><p className="text-[10px] font-bold text-slate-500">{item.operation} · item v{item.item_version}</p>{item.notes_snapshot&&<p className="mt-1 text-xs">{item.notes_snapshot}</p>}</div>)}</div>{nextStatus[projection.ticket.status]&&<button disabled={busy===projection.ticket.id} onClick={()=>void transition(projection)} className="mt-5 h-11 w-full rounded-xl bg-emerald-600 text-sm font-black text-white disabled:opacity-50">{busy===projection.ticket.id?'Atualizando...':labels[projection.ticket.status]}</button>}</article>)}</div></section></main>
}
