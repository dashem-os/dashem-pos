import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft, BadgeDollarSign, Banknote, Boxes, Building2, ChefHat, FileCheck2, FileText, Handshake, Home,
  Layers, LayoutGrid, LogOut, Monitor, CreditCard, Package, Plug, Settings, ShoppingCart,
  Store as StoreIcon, Tags, Users, Wallet,
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
import { AreaHub } from '../components/management/AreaHub'
import {
  EstadoDaGestao, acharArea, ehConteudoDaEntrada, enderecoDe,
  montarAreas, precisaNormalizar, resolverEstado,
} from '../domain/managementNavigation'
import { navigateTo } from '../utils/navigation'

const ICONES: Record<string, React.ComponentType<{ className?: string }>> = {
  overview: Home, sales: FileText, cash: Banknote, channels: Plug,
  receivables: BadgeDollarSign, products: Package, assortments: Layers, categories: Tags,
  inventory: Boxes, customers: Users, tables: ChefHat, devices: Monitor, team: Users,
  subscription: FileCheck2, payment_providers: CreditCard,
}

/** Cada área tem o seu ícone: sete quadrados iguais não informam nada. */
const ICONES_DE_AREA: Record<string, React.ComponentType<{ className?: string }>> = {
  OPERACAO: ShoppingCart, MERCADORIAS: Package, ESTRUTURA: Building2, PESSOAS: Users,
  RELACIONAMENTO: Handshake, FINANCEIRO: Wallet, ADMINISTRACAO: Settings,
}

/** Quantos módulos ficam montados para o filtro sobreviver ao ir e voltar. */
const MODULOS_VIVOS = 3

function conteudoDoModulo(id: string, abrir: (destino: string) => void, disponiveis: Set<string>) {
  switch (id) {
    case 'sales': return <SalesHistory />
    case 'products': return <CatalogManager onOpenAssortments={disponiveis.has('assortments') ? () => abrir('assortments') : undefined} />
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
    default: return null
  }
}

export const ManagementLayout: React.FC = () => {
  const { signOut } = useAuth()
  const { tenant, store, contributions, activities } = usePos()

  // Mesas continuam presas à atividade contratada, exatamente como antes:
  // reorganizar navegação não é lugar de afrouxar autorização.
  const navegaveis = useMemo(
    () => contributions.filter((item) => item.implementation_key !== 'tables' || activities.includes('FOOD_SERVICE')),
    [activities, contributions],
  )
  const areas = useMemo(() => montarAreas(navegaveis), [navegaveis])
  const temEntrada = useMemo(
    () => navegaveis.some((item) => item.surface === 'MANAGEMENT_NAV' && ehConteudoDaEntrada(item)),
    [navegaveis],
  )
  const todosOsCards = useMemo(
    () => new Set(areas.flatMap((area) => area.cards.map((card) => card.id))),
    [areas],
  )

  // A URL é o estado. O histórico é do navegador, e voltar volta.
  const [busca, setBusca] = useState(window.location.search)
  useEffect(() => {
    const sincronizar = () => setBusca(window.location.search)
    window.addEventListener('popstate', sincronizar)
    return () => window.removeEventListener('popstate', sincronizar)
  }, [])

  const estado = useMemo(() => resolverEstado(busca, areas), [busca, areas])

  const ir = useCallback((destino: EstadoDaGestao) => {
    navigateTo(enderecoDe(destino))
    setBusca(window.location.search)
  }, [])

  // Endereço legado (`?module=x` sem área) é reescrito no lugar: empilhá-lo
  // faria o primeiro "voltar" devolver ao mesmo endereço, em laço.
  useEffect(() => {
    if (!areas.length || !precisaNormalizar(busca, estado)) return
    window.history.replaceState({}, '', enderecoDe(estado))
    setBusca(window.location.search)
  }, [areas.length, busca, estado])

  const abrirModulo = useCallback((modulo: string) => {
    const area = areas.find((item) => item.cards.some((card) => card.id === modulo))
    if (!area) return
    ir({ tipo: 'MODULO', area: area.chave, modulo })
  }, [areas, ir])

  // Filtros sobrevivem ao ir e voltar porque o módulo visitado continua
  // montado. Sem isso o componente remonta e o que a pessoa digitou some —
  // o atrito A3 da UX-00.
  //
  // Ficar montado tem custo: `PaymentProviderManager` recarrega a cada 30s, e
  // um módulo invisível que continua pedindo é gasto sem dono. Por isso a vida
  // é presa à área: sair de Mercadorias desmonta os módulos de Mercadorias.
  // O contrato pede o filtro preservado ao voltar ao hub, e é exatamente esse
  // trecho que fica vivo — não a Gestão inteira.
  const [vivos, setVivos] = useState<string[]>([])
  const areaDosVivos = useRef<string | null>(null)
  useEffect(() => {
    const areaAgora = estado.tipo === 'MODULO' || estado.tipo === 'AREA' ? estado.area : null
    if (areaAgora !== areaDosVivos.current) {
      areaDosVivos.current = areaAgora
      setVivos(estado.tipo === 'MODULO' ? [estado.modulo] : [])
      return
    }
    if (estado.tipo !== 'MODULO') return
    setVivos((atuais) => (
      atuais[0] === estado.modulo
        ? atuais
        : [estado.modulo, ...atuais.filter((id) => id !== estado.modulo)].slice(0, MODULOS_VIVOS)
    ))
  }, [estado])

  const areaAtual = acharArea(areas, estado.tipo === 'ENTRADA' || estado.tipo === 'INDISPONIVEL' ? null : estado.area)
  const cardAtual = estado.tipo === 'MODULO' ? areaAtual?.cards.find((card) => card.id === estado.modulo) : undefined

  // O foco segue para o título depois de navegar, e volta para o card de onde
  // a pessoa saiu quando ela retorna ao hub.
  const tituloRef = useRef<HTMLHeadingElement>(null)
  const cardParaFocar = useRef<string | null>(null)
  const primeiraTela = useRef(true)
  useEffect(() => {
    if (primeiraTela.current) { primeiraTela.current = false; return }
    if (estado.tipo === 'AREA' && cardParaFocar.current) return
    tituloRef.current?.focus()
  }, [estado])

  const voltarParaArea = () => {
    if (estado.tipo !== 'MODULO') return
    cardParaFocar.current = estado.modulo
    ir({ tipo: 'AREA', area: estado.area })
  }

  const cabecalho = (
    <header className="sticky top-0 z-30 flex h-[72px] items-center justify-between gap-3 border-b border-dashem-border bg-dashem-surface/95 px-4 backdrop-blur sm:px-7">
      <div className="flex min-w-0 items-center gap-3">
        <StoreIcon className="hidden h-5 w-5 shrink-0 text-brand-ink sm:block" />
        <div className="min-w-0">
          <p className="truncate text-sm font-black text-dashem-strong">
            {estado.tipo === 'MODULO' ? cardAtual?.label : estado.tipo === 'AREA' ? areaAtual?.label : 'Gestão'}
          </p>
          <p className="truncate text-xs text-dashem-muted">{store?.name}</p>
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        {estado.tipo !== 'ENTRADA' && (
          <Button variant="secondary" icon={LayoutGrid} aria-label="Menu principal" onClick={() => ir({ tipo: 'ENTRADA' })}>
            <span className="hidden sm:inline">Menu principal</span>
          </Button>
        )}
        <Button variant="secondary" icon={LogOut} aria-label="Sair" onClick={signOut}>
          <span className="hidden xl:inline">Sair</span>
        </Button>
      </div>
    </header>
  )

  const listaDeAreas = (
    <nav aria-label="Áreas da Gestão" className="space-y-1">
      {areas.map((area) => {
        const Icone = ICONES_DE_AREA[area.chave] ?? LayoutGrid
        return (
        <button
          key={area.chave}
          onClick={() => ir({ tipo: 'AREA', area: area.chave })}
          className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-extrabold text-dashem-muted transition hover:bg-dashem-surface-elevated hover:text-dashem-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-ink"
        >
          <Icone className="h-5 w-5" />
          {/* Sem número solto ao lado do nome: "Operação 3" lê-se como três
              pendências. O contrato só admite quantidade com dado confiável e
              relevante, e a contagem de destinos não é nenhum dos dois. */}
          <span className="flex-1">{area.label}</span>
        </button>
        )
      })}
    </nav>
  )

  return (
    <div className="flex min-h-screen bg-dashem-bg font-sans text-dashem-strong">
      {estado.tipo === 'ENTRADA' && (
        <aside className="sticky top-0 hidden h-dvh w-72 shrink-0 flex-col border-r border-dashem-border bg-dashem-surface p-6 lg:flex">
          <Brand />
          <div className="mt-8 flex-1 overflow-y-auto pr-2">{listaDeAreas}</div>
          <div className="mt-5 rounded-2xl border border-dashem-border bg-dashem-surface-elevated p-4">
            <p className="text-sm font-black text-dashem-strong">{tenant?.name}</p>
            <p className="mt-1 text-xs text-dashem-muted">{store?.name}</p>
          </div>
        </aside>
      )}

      <div className="min-w-0 flex-1">
        {cabecalho}
        <main className="mx-auto w-full max-w-[1440px] p-4 sm:p-7">
          {estado.tipo === 'ENTRADA' && (
            <div className="space-y-6">
              <h1 ref={tituloRef} tabIndex={-1} className="text-2xl font-black text-dashem-strong outline-none">
                O que você quer fazer?
              </h1>
              {/* No celular não há gaveta: as áreas são o próprio conteúdo.
                  Mesmo nome acessível da barra, para leitor de tela e medida
                  encontrarem a mesma coisa nos dois tamanhos. */}
              <nav aria-label="Áreas da Gestão" className="lg:hidden">
                <AreaHub
                  cards={areas.map((area) => ({
                    id: area.chave,
                    label: area.label,
                    // O que há dentro vale mais que quantos: "Vendas · Caixas"
                    // responde a pergunta que "3 destinos" só adia.
                    descricao: area.cards.map((card) => card.label).join(' · '),
                  }))}
                  icones={ICONES_DE_AREA}
                  aoAbrir={(chave) => ir({ tipo: 'AREA', area: chave })}
                />
              </nav>
              {temEntrada && (
                <DashboardBI availableModules={todosOsCards} onOpenModule={(destino) => abrirModulo(destino)} />
              )}
            </div>
          )}

          {estado.tipo === 'AREA' && areaAtual && (
            <div className="space-y-6">
              <h1 ref={tituloRef} tabIndex={-1} className="text-2xl font-black text-dashem-strong outline-none">
                {areaAtual.label}
              </h1>
              <AreaHub
                cards={areaAtual.cards}
                icones={ICONES}
                focar={cardParaFocar.current}
                aoFocar={() => { cardParaFocar.current = null }}
                aoAbrir={(id) => abrirModulo(id)}
              />
              {areaAtual.chave === 'OPERACAO' && <ValidarNoPdv />}
            </div>
          )}

          {estado.tipo === 'INDISPONIVEL' && (
            <DestinoIndisponivel pedido={estado.pedido} tituloRef={tituloRef} aoVoltar={() => ir({ tipo: 'ENTRADA' })} />
          )}

          {/* Módulos visitados continuam montados; só o atual aparece. */}
          {vivos.map((id) => {
            const ativo = estado.tipo === 'MODULO' && estado.modulo === id
            return (
              <section key={id} className={ativo ? 'space-y-4' : 'hidden'} aria-hidden={!ativo}>
                {ativo && (
                  <>
                    <button
                      onClick={voltarParaArea}
                      className="inline-flex min-h-11 items-center gap-2 rounded-xl px-2 text-sm font-black text-brand-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-ink"
                    >
                      <ArrowLeft className="h-4 w-4" />
                      Voltar para {areaAtual?.label}
                    </button>
                    <h1 ref={tituloRef} tabIndex={-1} className="sr-only outline-none">{cardAtual?.label}</h1>
                  </>
                )}
                {conteudoDoModulo(id, abrirModulo, todosOsCards)}
              </section>
            )
          })}
        </main>
      </div>
    </div>
  )
}

/**
 * "Validar no PDV" saiu do topo global: é ação de negócio, e o contrato reserva
 * o topo para Menu principal e Sair. Ela vive no conteúdo de Operação, com a
 * identidade gerencial preservada — o PDV continua avisando que a sessão é
 * administrativa e auditada.
 */
function ValidarNoPdv() {
  return (
    <Card padding="lg" className="flex flex-wrap items-center justify-between gap-4">
      <div>
        <p className="text-sm font-black text-dashem-strong">Ver o PDV como o operador vê</p>
        <p className="mt-1 text-sm text-dashem-muted">
          Você entra com a sua identidade administrativa; o que for feito ali é real e fica auditado.
        </p>
      </div>
      <Button icon={ShoppingCart} onClick={() => navigateTo('/pos?access=management')}>Validar no PDV</Button>
    </Card>
  )
}

function DestinoIndisponivel({ pedido, tituloRef, aoVoltar }: {
  pedido: string
  tituloRef: React.RefObject<HTMLHeadingElement>
  aoVoltar: () => void
}) {
  return (
    <Card padding="lg" className="mx-auto max-w-xl text-center">
      <h1 ref={tituloRef} tabIndex={-1} className="text-2xl font-black text-dashem-strong outline-none">
        Este destino não está disponível
      </h1>
      <p className="mt-3 leading-7 text-dashem-muted">
        O endereço pedia <code className="font-mono text-sm">{pedido}</code>, que não existe nesta unidade ou não faz
        parte do seu acesso. Nada foi aberto.
      </p>
      <Button className="mt-6" icon={LayoutGrid} onClick={aoVoltar}>Ir para o menu principal</Button>
    </Card>
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
