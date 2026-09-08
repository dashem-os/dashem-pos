/**
 * A navegação da Gestão como decisão pura: URL entra, estado sai.
 *
 * Antes desta sprint o módulo aberto era `useState` e a URL era um espelho
 * escrito com `replaceState`. Isso produzia os atritos medidos na UX-00: voltar
 * não voltava (nada era empilhado), e um endereço inválido caía calado na visão
 * geral. Aqui a URL é o estado, e o histórico é do navegador.
 *
 * As sete áreas não estão escritas neste arquivo. Elas vêm da malha
 * (`metadata_json.area` de cada contribuição, migração 090), pelo mesmo motivo
 * que a palavra do nicho veio na 088: quem abrir uma área nova insere dado, não
 * edita código de projeção.
 */

export interface ContribuicaoDeNavegacao {
  surface: string
  contribution_key: string
  implementation_key: string
  label: string
  sort_order: number
  metadata_json?: Record<string, unknown> | null
}

export interface CardDeArea {
  id: string
  label: string
  descricao: string
  ordem: number
}

export interface AreaDaGestao {
  chave: string
  label: string
  ordem: number
  cards: CardDeArea[]
}

export type EstadoDaGestao =
  | { tipo: 'ENTRADA' }
  | { tipo: 'AREA'; area: string }
  | { tipo: 'MODULO'; area: string; modulo: string }
  | { tipo: 'INDISPONIVEL'; pedido: string }

function metadados(contribuicao: ContribuicaoDeNavegacao): Record<string, unknown> {
  return (contribuicao.metadata_json ?? {}) as Record<string, unknown>
}

/** Uma contribuição que declara `placement: ENTRY` é conteúdo da entrada. */
export function ehConteudoDaEntrada(contribuicao: ContribuicaoDeNavegacao): boolean {
  return metadados(contribuicao).placement === 'ENTRY'
}

function areaDeclarada(contribuicao: ContribuicaoDeNavegacao) {
  const area = metadados(contribuicao).area
  if (!area || typeof area !== 'object') return null
  const { key, label, order } = area as { key?: unknown; label?: unknown; order?: unknown }
  if (typeof key !== 'string' || typeof label !== 'string') return null
  return { chave: key, label, ordem: typeof order === 'number' ? order : Number.MAX_SAFE_INTEGER }
}

/**
 * Monta as áreas a partir do que o servidor autorizou.
 *
 * Contribuição sem área declarada não vira card: o contrato proíbe inventar
 * destino para completar sete itens, e uma linha sem área é dado incompleto,
 * não uma área nova. Ela continua alcançável por endereço direto.
 */
export function montarAreas(contribuicoes: ContribuicaoDeNavegacao[]): AreaDaGestao[] {
  const porChave = new Map<string, AreaDaGestao>()
  contribuicoes
    .filter((item) => item.surface === 'MANAGEMENT_NAV' && !ehConteudoDaEntrada(item))
    .forEach((item) => {
      const area = areaDeclarada(item)
      if (!area) return
      const existente = porChave.get(area.chave) ?? { ...area, cards: [] }
      existente.cards.push({
        id: item.implementation_key,
        label: item.label,
        descricao: String(metadados(item).description ?? ''),
        ordem: item.sort_order,
      })
      porChave.set(area.chave, existente)
    })

  return [...porChave.values()]
    .map((area) => ({ ...area, cards: [...area.cards].sort((a, b) => a.ordem - b.ordem) }))
    .sort((a, b) => a.ordem - b.ordem || a.label.localeCompare(b.label, 'pt-BR'))
}

export function acharArea(areas: AreaDaGestao[], chave: string | null): AreaDaGestao | null {
  return chave ? areas.find((area) => area.chave === chave) ?? null : null
}

export function areaDoModulo(areas: AreaDaGestao[], modulo: string): AreaDaGestao | null {
  return areas.find((area) => area.cards.some((card) => card.id === modulo)) ?? null
}

/**
 * Resolve o endereço em estado.
 *
 * Regras que vêm direto dos atritos medidos:
 * - `?module=X` sem `?area=` é link legado e continua funcionando: a área é
 *   deduzida de quem contém o módulo (atrito A1 do baseline não retorna, mas o
 *   endereço antigo não pode quebrar);
 * - destino desconhecido ou não autorizado **não** cai calado na visão geral;
 *   vira `INDISPONIVEL` para a tela poder dizer o que houve (atritos A4 e A5).
 */
export function resolverEstado(busca: string, areas: AreaDaGestao[]): EstadoDaGestao {
  const parametros = new URLSearchParams(busca)
  const moduloPedido = parametros.get('module')
  const areaPedida = parametros.get('area')

  if (moduloPedido) {
    const area = areaDoModulo(areas, moduloPedido)
    if (!area) return { tipo: 'INDISPONIVEL', pedido: moduloPedido }
    return { tipo: 'MODULO', area: area.chave, modulo: moduloPedido }
  }
  if (areaPedida) {
    const area = acharArea(areas, areaPedida)
    if (!area) return { tipo: 'INDISPONIVEL', pedido: areaPedida }
    return { tipo: 'AREA', area: areaPedida }
  }
  return { tipo: 'ENTRADA' }
}

/** O endereço canônico de um estado — o que a barra do navegador deve mostrar. */
export function enderecoDe(estado: EstadoDaGestao): string {
  if (estado.tipo === 'MODULO') return `/manage?area=${encodeURIComponent(estado.area)}&module=${encodeURIComponent(estado.modulo)}`
  if (estado.tipo === 'AREA') return `/manage?area=${encodeURIComponent(estado.area)}`
  if (estado.tipo === 'INDISPONIVEL') return `/manage?module=${encodeURIComponent(estado.pedido)}`
  return '/manage'
}

/**
 * Um link legado precisa ser reescrito no lugar, não empilhado: senão o
 * primeiro "voltar" devolve o usuário ao mesmo endereço antigo, em laço.
 */
export function precisaNormalizar(busca: string, estado: EstadoDaGestao): boolean {
  return estado.tipo !== 'INDISPONIVEL' && enderecoDe(estado) !== `/manage${busca ? busca : ''}`
}
