import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { rotuloDaContribuicao, vocabularioDoSortimento } from '../src/domain/shopVocabulary.ts'

const nav = (label: string) => [
  { contribution_key: 'assortments', surface: 'MANAGEMENT_NAV', label },
  { contribution_key: 'products', surface: 'MANAGEMENT_NAV', label: 'Produtos e preços' },
]

test('a palavra vem do rótulo que o servidor já resolveu para o menu', () => {
  const comida = vocabularioDoSortimento({ rotuloDoMenu: rotuloDaContribuicao(nav('Cardápios'), 'assortments') })
  assert.equal(comida.plural, 'Cardápios')
  assert.equal(comida.singular, 'cardápio')
  assert.equal(comida.Singular, 'Cardápio')

  const loja = vocabularioDoSortimento({ rotuloDoMenu: rotuloDaContribuicao(nav('Catálogos'), 'assortments') })
  assert.equal(loja.plural, 'Catálogos')
  assert.equal(loja.singular, 'catálogo')
})

test('cardápio é só de quem tem FOOD; beleza e comércio têm catálogo', () => {
  assert.equal(vocabularioDoSortimento({ activities: ['FOOD_SERVICE'] }).plural, 'Cardápios')
  assert.equal(vocabularioDoSortimento({ activities: ['RETAIL'] }).plural, 'Catálogos')
  assert.equal(vocabularioDoSortimento({ activities: ['BEAUTY_RESELLER'] }).plural, 'Catálogos')
  // Quem serve comida e também vende produto continua tendo cardápio.
  assert.equal(vocabularioDoSortimento({ activities: ['RETAIL', 'FOOD_SERVICE'] }).plural, 'Cardápios')
  // Sem atividade declarada não se inventa cardápio.
  assert.equal(vocabularioDoSortimento({}).plural, 'Catálogos')
})

test('o rótulo do menu vence a atividade, porque é o que a pessoa acabou de ler', () => {
  const palavra = vocabularioDoSortimento({ rotuloDoMenu: 'Catálogos', activities: ['FOOD_SERVICE'] })
  assert.equal(palavra.plural, 'Catálogos')
})

test('a tela do módulo não fala a língua do modelo de dados', () => {
  const tela = readFileSync(new URL('../src/components/management/AssortmentManager.tsx', import.meta.url), 'utf8')
  // O agregado continua se chamando sortimento na API e no banco; o que não
  // pode é a palavra aparecer para quem está trabalhando. Sobram os
  // comentários, que explicam o domínio, e o nome da própria função.
  const visivel = tela
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/vocabularioDoSortimento/g, '')
  const sobras = visivel.split('\n').filter((linha) => /[Ss]ortimento/.test(linha))
  assert.deepEqual(sobras, [], 'texto visível ainda usa a palavra do domínio')
  assert.match(tela, /vocabularioDoSortimento/)
  assert.match(tela, /rotuloDaContribuicao\(contributions, 'assortments'\)/)
})

test('a busca do PDV manda a pessoa ao destino com o nome que o menu mostra', () => {
  const busca = readFileSync(new URL('../src/components/pos/ProductSearch.tsx', import.meta.url), 'utf8')
  assert.match(busca, /Confira a publicação em \$\{palavra\.plural\}/)
})
