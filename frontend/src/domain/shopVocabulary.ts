/**
 * A tela chama a mercadoria curada pelo nome do negócio de quem vende.
 *
 * "Sortimento" é o agregado do domínio: um conjunto publicado por unidade,
 * atividade e jornada. Quem serve comida chama aquilo de cardápio; quem vende
 * roupa ou cosmético chama de catálogo. O nome do domínio continua no código,
 * no banco e na API — ele só não aparece para quem está trabalhando.
 *
 * A palavra vem do rótulo que o servidor já resolveu para o menu
 * (`capabilities.py`), porque menu e tela não podem discordar sobre o nome do
 * lugar em que a pessoa acabou de clicar. As atividades são o reserva: se a
 * contribuição não veio, a regra é a mesma, aplicada aqui.
 */

export type VocabularioDoSortimento = {
  /** Como o menu chama: "Cardápios" ou "Catálogos". */
  plural: string
  /** No meio da frase: "remover o cardápio ...". */
  singular: string
  /** Começando título ou botão: "Novo cardápio" vira "Cardápio". */
  Singular: string
}

const CARDAPIO: VocabularioDoSortimento = { plural: 'Cardápios', singular: 'cardápio', Singular: 'Cardápio' }
const CATALOGO: VocabularioDoSortimento = { plural: 'Catálogos', singular: 'catálogo', Singular: 'Catálogo' }

type Origem = {
  /** Rótulo da contribuição `assortments` em MANAGEMENT_NAV, já resolvido. */
  rotuloDoMenu?: string
  /** Atividades contratadas, quando o rótulo não estiver disponível. */
  activities?: readonly string[]
}

export function vocabularioDoSortimento({ rotuloDoMenu, activities }: Origem): VocabularioDoSortimento {
  const rotulo = (rotuloDoMenu || '').trim()
  if (rotulo) {
    // Deriva o singular do próprio rótulo: quem mudar a palavra no servidor
    // não precisa vir mudar esta lista.
    const plural = rotulo
    const singular = (plural.endsWith('s') ? plural.slice(0, -1) : plural).toLocaleLowerCase('pt-BR')
    return { plural, singular, Singular: singular.charAt(0).toLocaleUpperCase('pt-BR') + singular.slice(1) }
  }
  return (activities || []).includes('FOOD_SERVICE') ? CARDAPIO : CATALOGO
}

/** O rótulo que o servidor mandou para o card do menu, se veio. */
export function rotuloDaContribuicao(
  contributions: ReadonlyArray<{ contribution_key: string; surface: string; label: string }> | undefined,
  chave: string,
): string | undefined {
  return (contributions || []).find(
    (item) => item.contribution_key === chave && item.surface === 'MANAGEMENT_NAV',
  )?.label
}
