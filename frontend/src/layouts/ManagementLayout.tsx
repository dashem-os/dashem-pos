import React, { useMemo, useState } from 'react'
import {
  BadgeDollarSign, Banknote, Boxes, ChefHat, FileText, Home, LogOut, Menu, Monitor,
  Package, Plug, ShoppingCart, Store as StoreIcon, Tags, Users, X,
} from 'lucide-react'
import { usePos } from '../context/PosContext'
import { useAuth } from '../context/AuthContext'
import { DashboardBI } from '../components/management/DashboardBI'
import { SalesHistory } from '../components/management/SalesHistory'
import { CatalogManager } from '../components/management/CatalogManager'
import { CashManager } from '../components/management/CashManager'
import { TeamManager } from '../components/management/TeamManager'
import { ChannelHubWorkspace } from '../components/management/ChannelHubWorkspace'
import { ServiceSetupManager } from '../components/management/ServiceSetupManager'
import { DeviceManager } from '../components/management/DeviceManager'
import { CategoryManager } from '../components/management/CategoryManager'
import { InventoryManager } from '../components/management/InventoryManager'
import { ReceivablesManager } from '../components/management/ReceivablesManager'
import { CustomerManager } from '../components/management/CustomerManager'
import { navigateTo } from '../utils/navigation'

type ModuleId = 'overview' | 'sales' | 'tables' | 'channels' | 'cash' | 'receivables' | 'products' | 'categories' | 'inventory' | 'customers' | 'team' | 'devices'

interface NavigationItem {
  id: ModuleId
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const MODULE_ICONS: Record<ModuleId, React.ComponentType<{ className?: string }>> = {
  overview: Home, sales: FileText, cash: Banknote, channels: Plug,
  receivables: BadgeDollarSign, products: Package, categories: Tags,
  inventory: Boxes, customers: Users, tables: ChefHat, devices: Monitor, team: Users,
}
const MODULE_IDS = new Set<ModuleId>(Object.keys(MODULE_ICONS) as ModuleId[])

export const ManagementLayout: React.FC = () => {
  const [module, setModule] = useState<ModuleId>('overview')
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false)
  const { signOut } = useAuth()
  const { tenant, store, contributions } = usePos()

  const visibleGroups = useMemo(() => {
    const groups = new Map<string, NavigationItem[]>()
    contributions.filter(item => item.surface === 'MANAGEMENT_NAV' && MODULE_IDS.has(item.implementation_key as ModuleId)).forEach(item => {
      const group = item.group_key || 'OUTROS'
      const entry: NavigationItem = { id: item.implementation_key as ModuleId, label: item.label, icon: MODULE_ICONS[item.implementation_key as ModuleId] }
      groups.set(group, [...(groups.get(group) || []), entry])
    })
    return Array.from(groups, ([label, items]) => ({ label, items }))
  }, [contributions])
  const selected = visibleGroups.flatMap((group) => group.items).find((item) => item.id === module)

  const choose = (id: ModuleId) => { setModule(id); setMobileNavigationOpen(false) }
  const navigation = <nav className="space-y-5">{visibleGroups.map((group) => <section key={group.label}><p className="mb-2 px-3 text-[10px] font-black uppercase tracking-[.16em] text-slate-600">{group.label}</p><div className="space-y-1">{group.items.map((item) => { const Icon = item.icon; const current = module === item.id; return <button key={item.id} onClick={() => choose(item.id)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs font-extrabold transition ${current ? 'bg-white text-slate-950 shadow-sm' : 'text-dashem-muted hover:bg-dashem-surface-elevated hover:text-white'}`}><Icon className={`h-4 w-4 ${current ? 'text-dashem-red' : ''}`} /><span className="flex-1">{item.label}</span></button> })}</div></section>)}</nav>

  const content = () => {
    switch (module) {
      case 'overview': return <DashboardBI onOpenModule={(target) => choose(target)} />
      case 'sales': return <SalesHistory />
      case 'products': return <CatalogManager />
      case 'categories': return <CategoryManager />
      case 'inventory': return <InventoryManager />
      case 'customers': return <CustomerManager />
      case 'cash': return <CashManager />
      case 'receivables': return <ReceivablesManager />
      case 'tables': return <ServiceSetupManager />
      case 'devices': return <DeviceManager />
      case 'channels': return <ChannelHubWorkspace />
      case 'team': return <TeamManager />
      default: return <ModuleBoundary item={selected} />
    }
  }

  return <div className="flex min-h-screen bg-dashem-bg font-sans text-slate-100"><aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-dashem-border bg-dashem-surface p-5 md:flex"><Brand /><div className="mt-8 flex-1 overflow-y-auto pr-1">{navigation}</div><div className="mt-5 rounded-2xl border border-dashem-border bg-dashem-bg p-4"><p className="text-xs font-black text-white">{tenant?.name}</p><p className="mt-1 text-[11px] text-dashem-muted">{store?.name}</p></div></aside>{mobileNavigationOpen && <div className="fixed inset-0 z-50 md:hidden"><button aria-label="Fechar menu" className="absolute inset-0 bg-slate-950/80" onClick={() => setMobileNavigationOpen(false)} /><aside className="relative h-full w-[min(88vw,20rem)] overflow-y-auto bg-dashem-surface p-5"><div className="flex items-center justify-between"><Brand /><button onClick={() => setMobileNavigationOpen(false)} className="flex h-10 w-10 items-center justify-center rounded-xl border border-dashem-border"><X className="h-5 w-5" /></button></div><div className="mt-8">{navigation}</div></aside></div>}<div className="min-w-0 flex-1"><header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-dashem-border bg-dashem-surface/95 px-4 backdrop-blur sm:px-6"><div className="flex items-center gap-3"><button onClick={() => setMobileNavigationOpen(true)} className="flex h-10 w-10 items-center justify-center rounded-xl border border-dashem-border md:hidden"><Menu className="h-5 w-5" /></button><StoreIcon className="h-4 w-4 text-dashem-red" /><div><p className="text-xs font-black text-white">{selected?.label || 'Gestão'}</p><p className="text-[11px] text-dashem-muted">{store?.name}</p></div></div><div className="flex gap-2"><button onClick={() => navigateTo('/pos')} className="flex h-10 items-center gap-2 rounded-xl bg-dashem-red px-4 text-xs font-black"><ShoppingCart className="h-4 w-4" /><span className="hidden sm:inline">Abrir PDV</span></button><button onClick={signOut} className="flex h-10 items-center gap-2 rounded-xl border border-dashem-border px-3 text-xs font-black text-dashem-muted"><LogOut className="h-4 w-4" /><span className="hidden xl:inline">Sair</span></button></div></header><main className="mx-auto w-full max-w-[1500px] p-4 sm:p-6">{content()}</main></div></div>
}

function Brand() { return <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-dashem-red text-xl font-black text-white">D</div><div><p className="font-black text-white">DASHEM <span className="text-dashem-red">GESTÃO</span></p><p className="text-[10px] font-bold uppercase tracking-wider text-dashem-muted">Business Console</p></div></div> }

function ModuleBoundary({ item }: { item?: NavigationItem }) { return item ? <section className="rounded-3xl border border-dashem-border bg-dashem-surface p-8"><h2 className="text-2xl font-black text-white">{item.label}</h2></section> : null }
