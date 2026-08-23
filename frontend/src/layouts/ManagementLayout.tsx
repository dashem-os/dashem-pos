import React, { useMemo, useState } from 'react'
import {
  Banknote, Boxes, Building2, ChefHat, CircleDollarSign, FileText, Home,
  LogOut, Menu, Package, Plug, Printer, Receipt, ShieldCheck,
  ShoppingCart, Store as StoreIcon, Tags, Users, WalletCards, X,
} from 'lucide-react'
import { usePos } from '../context/PosContext'
import { useAuth } from '../context/AuthContext'
import { DashboardBI } from '../components/management/DashboardBI'
import { SalesHistory } from '../components/management/SalesHistory'
import { CatalogManager } from '../components/management/CatalogManager'
import { CashManager } from '../components/management/CashManager'
import { TeamManager } from '../components/management/TeamManager'
import { TableServiceWorkspace } from '../components/tables/TableServiceWorkspace'
import { ChannelHubWorkspace } from '../components/management/ChannelHubWorkspace'
import { navigateTo } from '../utils/navigation'

type ModuleId = 'overview' | 'sales' | 'orders' | 'tables' | 'channels' | 'cash' | 'products' | 'categories' | 'inventory' | 'customers' | 'receipts' | 'movements' | 'stores' | 'team' | 'permissions' | 'payments' | 'printers' | 'fiscal' | 'integrations'

interface NavigationItem {
  id: ModuleId
  label: string
  icon: React.ComponentType<{ className?: string }>
  permission: string
  capability?: string
  active: boolean
  sprint?: string
}

const GROUPS: Array<{ label: string; items: NavigationItem[] }> = [
  { label: 'Visão', items: [{ id: 'overview', label: 'Visão Geral', icon: Home, permission: 'management.read', active: true }] },
  { label: 'Operação', items: [
    { id: 'sales', label: 'Vendas', icon: FileText, permission: 'sale.read', capability: 'counter_order', active: true },
    { id: 'orders', label: 'Pedidos', icon: Receipt, permission: 'sale.read', capability: 'counter_order', active: false, sprint: 'S6' },
    { id: 'tables', label: 'Mesas & Comandas', icon: ChefHat, permission: 'table.read', capability: 'table_service', active: true },
    { id: 'channels', label: 'Channel Hub', icon: Plug, permission: 'channel.read', capability: 'delivery_orders', active: true },
    { id: 'cash', label: 'Caixas', icon: Banknote, permission: 'cash.read', capability: 'cash_management', active: true },
  ] },
  { label: 'Cadastros', items: [
    { id: 'products', label: 'Produtos', icon: Package, permission: 'catalog.read', capability: 'catalog', active: true },
    { id: 'categories', label: 'Categorias', icon: Tags, permission: 'catalog.read', capability: 'catalog', active: true },
    { id: 'inventory', label: 'Estoque', icon: Boxes, permission: 'inventory.read', capability: 'inventory', active: true },
    { id: 'customers', label: 'Clientes', icon: Users, permission: 'customer.read', capability: 'customer', active: false, sprint: 'S9' },
  ] },
  { label: 'Financeiro', items: [
    { id: 'receipts', label: 'Recebimentos', icon: CircleDollarSign, permission: 'payment.read', capability: 'payments', active: false, sprint: 'S12' },
    { id: 'movements', label: 'Movimentações', icon: WalletCards, permission: 'cash.read', capability: 'cash_management', active: false, sprint: 'S13' },
  ] },
  { label: 'Administração', items: [
    { id: 'stores', label: 'Unidades', icon: Building2, permission: 'tenant.settings', active: false, sprint: 'S16' },
    { id: 'team', label: 'Equipe', icon: Users, permission: 'team.read', active: true },
    { id: 'permissions', label: 'Permissões', icon: ShieldCheck, permission: 'permission.manage', active: false, sprint: 'S16' },
  ] },
  { label: 'Configurações', items: [
    { id: 'payments', label: 'Pagamentos', icon: WalletCards, permission: 'payment.read', capability: 'payments', active: false, sprint: 'S10' },
    { id: 'printers', label: 'Impressoras', icon: Printer, permission: 'tenant.settings', active: false, sprint: 'S8' },
    { id: 'fiscal', label: 'Fiscal', icon: Receipt, permission: 'fiscal.read', capability: 'fiscal_nfce', active: false, sprint: 'S10' },
    { id: 'integrations', label: 'Integrações', icon: Plug, permission: 'tenant.settings', active: false, sprint: 'S14' },
  ] },
]

export const ManagementLayout: React.FC = () => {
  const [module, setModule] = useState<ModuleId>('overview')
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false)
  const { signOut } = useAuth()
  const { tenant, store, permissions, capabilities } = usePos()

  const visibleGroups = useMemo(() => GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => permissions.includes(item.permission) && (!item.capability || item.capability in capabilities)),
  })).filter((group) => group.items.length > 0), [permissions, capabilities])
  const selected = GROUPS.flatMap((group) => group.items).find((item) => item.id === module)

  const choose = (id: ModuleId) => { setModule(id); setMobileNavigationOpen(false) }
  const navigation = <nav className="space-y-5">{visibleGroups.map((group) => <section key={group.label}><p className="mb-2 px-3 text-[10px] font-black uppercase tracking-[.16em] text-slate-600">{group.label}</p><div className="space-y-1">{group.items.map((item) => { const Icon = item.icon; const current = module === item.id; return <button key={item.id} onClick={() => choose(item.id)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs font-extrabold transition ${current ? 'bg-dashem-surface-elevated text-white shadow-sm' : 'text-dashem-muted hover:bg-dashem-surface-elevated/60 hover:text-white'}`}><Icon className={`h-4 w-4 ${current ? 'text-dashem-red' : ''}`} /><span className="flex-1">{item.label}</span>{!item.active && <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] text-slate-400">{item.sprint}</span>}</button> })}</div></section>)}</nav>

  const content = () => {
    switch (module) {
      case 'overview': return <DashboardBI />
      case 'sales': return <SalesHistory />
      case 'products': case 'categories': case 'inventory': return <CatalogManager />
      case 'cash': return <CashManager />
      case 'tables': return <TableServiceWorkspace />
      case 'channels': return <ChannelHubWorkspace />
      case 'team': return <TeamManager />
      default: return <ModuleBoundary item={selected} />
    }
  }

  return <div className="flex min-h-screen bg-dashem-bg font-sans text-slate-100"><aside className="sticky top-0 hidden h-screen w-72 shrink-0 flex-col border-r border-dashem-border bg-dashem-surface p-5 md:flex"><Brand /><div className="mt-8 flex-1 overflow-y-auto pr-1">{navigation}</div><button onClick={() => navigateTo('/pos')} className="mt-5 flex h-11 items-center justify-center gap-2 rounded-xl bg-dashem-red text-xs font-black text-white"><ShoppingCart className="h-4 w-4" />Abrir PDV</button></aside>{mobileNavigationOpen && <div className="fixed inset-0 z-50 md:hidden"><button aria-label="Fechar menu" className="absolute inset-0 bg-slate-950/80" onClick={() => setMobileNavigationOpen(false)} /><aside className="relative h-full w-[min(88vw,20rem)] overflow-y-auto bg-dashem-surface p-5"><div className="flex items-center justify-between"><Brand /><button onClick={() => setMobileNavigationOpen(false)} className="flex h-10 w-10 items-center justify-center rounded-xl border border-dashem-border"><X className="h-5 w-5" /></button></div><div className="mt-8">{navigation}</div></aside></div>}<div className="min-w-0 flex-1"><header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-dashem-border bg-dashem-surface px-4 sm:px-6"><div className="flex items-center gap-3"><button onClick={() => setMobileNavigationOpen(true)} className="flex h-10 w-10 items-center justify-center rounded-xl border border-dashem-border md:hidden"><Menu className="h-5 w-5" /></button><StoreIcon className="h-4 w-4 text-dashem-red" /><div><p className="text-xs font-black text-white">{tenant?.name}</p><p className="text-[11px] text-dashem-muted">{store?.name}</p></div></div><div className="flex gap-2"><button onClick={() => navigateTo('/pos')} className="flex h-10 items-center gap-2 rounded-xl bg-dashem-red px-4 text-xs font-black"><ShoppingCart className="h-4 w-4" /><span className="hidden sm:inline">PDV</span></button><button onClick={signOut} className="flex h-10 items-center gap-2 rounded-xl border border-dashem-border px-3 text-xs font-black text-dashem-muted"><LogOut className="h-4 w-4" /><span className="hidden xl:inline">Sair</span></button></div></header><main className="mx-auto w-full max-w-[1500px] p-4 sm:p-6">{content()}</main></div></div>
}

function Brand() { return <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-dashem-red text-xl font-black text-white">D</div><div><p className="font-black text-white">DASHEM <span className="text-dashem-red">GESTÃO</span></p><p className="text-[10px] font-bold uppercase tracking-wider text-dashem-muted">Business Console</p></div></div> }

function ModuleBoundary({ item }: { item?: NavigationItem }) {
  if (!item) return null
  const Icon = item.icon
  return <section className="flex min-h-[55vh] items-center justify-center rounded-3xl border border-dashed border-dashem-border bg-dashem-surface/60 p-8 text-center"><div className="max-w-lg"><div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-dashem-surface-elevated text-dashem-red"><Icon className="h-7 w-7" /></div><p className="mt-5 text-xs font-black uppercase tracking-[.16em] text-dashem-red">Contrato do módulo reconhecido</p><h2 className="mt-2 text-2xl font-black text-white">{item.label}</h2><p className="mt-3 leading-7 text-dashem-muted">Seu contrato e sua permission permitem visualizar este módulo. A operação ainda não foi liberada porque o domínio persistente será entregue no {item.sprint}; nenhum dado demonstrativo será exibido.</p></div></section>
}
