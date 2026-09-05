import React, { useMemo, useState } from 'react'
import {
  BadgeDollarSign, Banknote, Boxes, ChefHat, FileCheck2, FileText, Home, Layers, LogOut, Menu, Monitor,
  CreditCard, Package, Plug, ShoppingCart, Store as StoreIcon, Tags, Users, X,
} from 'lucide-react'
import { usePos } from '../context/PosContext'
import { useAuth } from '../context/AuthContext'
import { Button } from '../components/common/Button'
import { Card } from '../components/common/Surface'
import { DashboardBI } from '../components/management/DashboardBI'
import { SalesHistory } from '../components/management/SalesHistory'
import { CatalogManager } from '../components/management/CatalogManager'
import { AssortmentManager } from '../components/management/AssortmentManager'
import { CashManager } from '../components/management/CashManager'
import { TeamManager } from '../components/management/TeamManager'
import { ChannelHubWorkspace } from '../components/management/ChannelHubWorkspace'
import { ServiceSetupManager } from '../components/management/ServiceSetupManager'
import { DeviceManager } from '../components/management/DeviceManager'
import { PaymentProviderManager } from '../components/management/PaymentProviderManager'
import { CategoryManager } from '../components/management/CategoryManager'
import { InventoryManager } from '../components/management/InventoryManager'
import { ReceivablesManager } from '../components/management/ReceivablesManager'
import { CustomerManager } from '../components/management/CustomerManager'
import { TenantPlanWorkspace } from '../components/management/TenantPlanWorkspace'
import { navigateTo } from '../utils/navigation'

type ModuleId = 'overview' | 'sales' | 'tables' | 'channels' | 'cash' | 'receivables' | 'products' | 'assortments' | 'categories' | 'inventory' | 'customers' | 'team' | 'devices' | 'subscription' | 'payment_providers'

interface NavigationItem {
  id: ModuleId
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const MODULE_ICONS: Record<ModuleId, React.ComponentType<{ className?: string }>> = {
  overview: Home, sales: FileText, cash: Banknote, channels: Plug,
  receivables: BadgeDollarSign, products: Package, assortments: Layers, categories: Tags,
  inventory: Boxes, customers: Users, tables: ChefHat, devices: Monitor, team: Users,
  subscription: FileCheck2,
  payment_providers: CreditCard,
}
const MODULE_IDS = new Set<ModuleId>(Object.keys(MODULE_ICONS) as ModuleId[])

export const ManagementLayout: React.FC = () => {
  const [module, setModule] = useState<ModuleId>(() => {
    const requested = new URLSearchParams(window.location.search).get('module')
    return requested && MODULE_IDS.has(requested as ModuleId) ? requested as ModuleId : 'overview'
  })
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false)
  const { signOut } = useAuth()
  const { tenant, store, contributions, activities } = usePos()

  const visibleGroups = useMemo(() => {
    const groups = new Map<string, NavigationItem[]>()
    contributions.filter(item => item.surface === 'MANAGEMENT_NAV' && MODULE_IDS.has(item.implementation_key as ModuleId))
      .filter(item => item.implementation_key !== 'tables' || activities.includes('FOOD_SERVICE'))
      .forEach(item => {
      const group = item.group_key || 'OUTROS'
      const entry: NavigationItem = { id: item.implementation_key as ModuleId, label: item.label, icon: MODULE_ICONS[item.implementation_key as ModuleId] }
      groups.set(group, [...(groups.get(group) || []), entry])
    })
    return Array.from(groups, ([label, items]) => ({ label, items }))
  }, [activities, contributions])
  const selected = visibleGroups.flatMap((group) => group.items).find((item) => item.id === module)
  const availableModules = useMemo(() => new Set(visibleGroups.flatMap((group) => group.items.map((item) => item.id))), [visibleGroups])

  const choose = (id: ModuleId) => {
    if (!availableModules.has(id)) return
    setModule(id)
    setMobileNavigationOpen(false)
    const url = new URL(window.location.href)
    url.searchParams.set('module', id)
    window.history.replaceState({}, '', url)
  }
  const navigation = (
    <nav className="space-y-6">
      {visibleGroups.map((group) => (
        <section key={group.label}>
          <p className="mb-2 px-3 text-[11px] font-black uppercase tracking-[.14em] text-dashem-muted">{group.label}</p>
          <div className="space-y-1">
            {group.items.map((item) => {
              const Icon = item.icon
              const current = module === item.id
              return (
                <button
                  key={item.id}
                  onClick={() => choose(item.id)}
                  aria-current={current ? 'page' : undefined}
                  className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-extrabold transition
                    ${current
                      ? 'bg-brand text-brand-contrast shadow-sm'
                      : 'text-dashem-muted hover:bg-dashem-surface-elevated hover:text-dashem-strong'}`}
                >
                  <Icon className="h-5 w-5" />
                  <span className="flex-1">{item.label}</span>
                </button>
              )
            })}
          </div>
        </section>
      ))}
    </nav>
  )

  const content = () => {
    if (!selected) return null
    switch (module) {
      case 'overview': return <DashboardBI availableModules={availableModules} onOpenModule={(target) => choose(target)} />
      case 'sales': return <SalesHistory />
      case 'products': return <CatalogManager onOpenAssortments={availableModules.has('assortments') ? () => choose('assortments') : undefined} />
      case 'assortments': return <AssortmentManager />
      case 'categories': return <CategoryManager />
      case 'inventory': return <InventoryManager />
      case 'customers': return <CustomerManager />
      case 'cash': return <CashManager />
      case 'receivables': return <ReceivablesManager />
      case 'tables': return <ServiceSetupManager />
      case 'devices': return <DeviceManager />
      case 'payment_providers': return <PaymentProviderManager />
      case 'channels': return <ChannelHubWorkspace />
      case 'team': return <TeamManager />
      case 'subscription': return <TenantPlanWorkspace />
      default: return <ModuleBoundary item={selected} />
    }
  }

  return (
    <div className="flex min-h-screen bg-dashem-bg font-sans text-dashem-strong">
      <aside className="sticky top-0 hidden h-dvh w-72 shrink-0 flex-col border-r border-dashem-border bg-dashem-surface p-6 lg:flex">
        <Brand />
        <div className="mt-8 flex-1 overflow-y-auto pr-2">{navigation}</div>
        <div className="mt-5 rounded-2xl border border-dashem-border bg-dashem-surface-elevated p-4">
          <p className="text-sm font-black text-dashem-strong">{tenant?.name}</p>
          <p className="mt-1 text-xs text-dashem-muted">{store?.name}</p>
        </div>
      </aside>

      {mobileNavigationOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button aria-label="Fechar menu" className="absolute inset-0 bg-slate-950/50" onClick={() => setMobileNavigationOpen(false)} />
          <aside className="relative h-full w-[min(90vw,22rem)] overflow-y-auto bg-dashem-surface p-5 shadow-2xl">
            <div className="flex items-center justify-between">
              <Brand />
              <Button variant="secondary" icon={X} onClick={() => setMobileNavigationOpen(false)} aria-label="Fechar menu" className="px-3" />
            </div>
            <div className="mt-8">{navigation}</div>
          </aside>
        </div>
      )}

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex h-[72px] items-center justify-between gap-3 border-b border-dashem-border bg-dashem-surface/95 px-4 backdrop-blur sm:px-7">
          <div className="flex min-w-0 items-center gap-3">
            <Button variant="secondary" icon={Menu} onClick={() => setMobileNavigationOpen(true)} aria-label="Abrir menu" className="px-3 lg:hidden" />
            <StoreIcon className="hidden h-5 w-5 shrink-0 text-brand-ink sm:block" />
            <div className="min-w-0">
              <p className="truncate text-sm font-black text-dashem-strong">{selected?.label || 'Gestão'}</p>
              <p className="truncate text-xs text-dashem-muted">{store?.name}</p>
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button icon={ShoppingCart} aria-label="Validar no PDV" onClick={() => navigateTo('/pos?access=management')}>
              <span className="hidden sm:inline">Validar no PDV</span>
            </Button>
            <Button variant="secondary" icon={LogOut} aria-label="Sair" onClick={signOut}>
              <span className="hidden xl:inline">Sair</span>
            </Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1440px] p-4 sm:p-7">{content()}</main>
      </div>
    </div>
  )
}

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand text-xl font-black text-brand-contrast">D</div>
      <div>
        <p className="font-black text-dashem-strong">DASHEM <span className="text-brand-ink">GESTÃO</span></p>
        <p className="text-[10px] font-bold uppercase tracking-wider text-dashem-muted">Business Console</p>
      </div>
    </div>
  )
}

function ModuleBoundary({ item }: { item?: NavigationItem }) {
  return item ? (
    <Card padding="lg">
      <h2 className="text-2xl font-black text-dashem-strong">{item.label}</h2>
    </Card>
  ) : null
}
