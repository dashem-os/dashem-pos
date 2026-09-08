import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const ler = (caminho: string) => readFileSync(new URL(caminho, import.meta.url), 'utf8')

const busca = ler('../src/components/pos/ProductSearch.tsx')
const grade = ler('../src/components/pos/QuickProductGrid.tsx')

test('a mesma tela não responde dois números para a mesma pergunta', () => {
  // Na homologação de 07/09/2026 a busca dizia "Estoque: 16 un" enquanto a
  // recusa, na mesma janela, dizia que não havia o que vender: dezesseis na
  // prateleira, todas prometidas a vendas abertas.
  assert.match(busca, /Number\(product\.available \?\? product\.quantity\)/)
  assert.match(grade, /Number\(product\.available \?\? product\.quantity\)/)
  assert.ok(!/Estoque: \{formatStock/.test(busca), 'a busca voltou a anunciar a prateleira')
})

test('quando falta, a tela diz por que falta', () => {
  assert.match(busca, /Disponível: \$\{formatStock\(stock\)\}/)
  // Zero não se anuncia como "Disponível: Sem estoque".
  assert.match(busca, /'Nada disponível agora'/)
  assert.match(busca, /em vendas abertas/)
})
