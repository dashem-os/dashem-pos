/**
 * Contar a prateleira pela tela, inclusive quando o estoque anda no meio.
 *
 * O roteiro percorre o que uma pessoa faria: abre a contagem, vê o saldo
 * registrado, digita o que encontrou, lê a prévia e confirma. Depois refaz o
 * caminho com uma venda entrando entre a leitura e a confirmação, que é o caso
 * em que a tela precisa se comportar bem: dizer o que aconteceu, **preservar o
 * número digitado** e não deixar que um clique confirme a contagem velha.
 *
 * As permissões vêm interceptadas no navegador da bancada — o bypass local não
 * devolve nenhuma. Isso não muda permissão de produto: o backend continua
 * exigindo o que exige. Não substitui o teste autenticado nem homologa a tela.
 *
 * Uso:
 *   node e2e/stock-count.spec.mjs <tenant> <store> <operator> <produto> <saida>
 */
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const [tenant, store, operator, product, outDir = '.'] = process.argv.slice(2)
const API = 'http://127.0.0.1:8002'
const headers = { 'X-Tenant-ID': tenant, 'X-Store-ID': store, 'X-User-ID': operator }

const saldo = async () => {
  const res = await fetch(
    `${API}/api/v1/inventory/balance?store_id=${store}&product_id=${product}`, { headers },
  )
  const body = await res.json()
  return { quantity: Number(body.quantity), version: body.version }
}

const receber = async (quantidade) => {
  const res = await fetch(`${API}/api/v1/inventory/adjust`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      store_id: store, product_id: product, actor_id: operator,
      movement_type: 'PURCHASE', quantity: quantidade, reason: 'Recebimento da bancada',
    }),
  })
  assert.ok(res.ok, `recebimento falhou: ${await res.text()}`)
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 960 } })
const erros = []
page.on('pageerror', e => erros.push(String(e)))

// A única interceptação: as permissões que o bypass local não devolve.
await page.route('**/api/v1/capabilities/effective*', async route => {
  const response = await route.fetch()
  const body = await response.json()
  await route.fulfill({
    response,
    json: {
      ...body,
      permissions: [...(body.permissions || []), 'inventory.read', 'inventory.count'],
    },
  })
})

await page.goto(
  `http://127.0.0.1:5173/e2e/stock-count.html?tenant=${tenant}&store=${store}&operator=${operator}`,
  { waitUntil: 'networkidle' },
)
await page.getByText('Refrigerante lata').first().waitFor({ timeout: 20000 })

const contar = page.getByRole('button', { name: 'Contar estoque' }).first()
const confirmar = page.getByRole('button', { name: /Confirmar contagem|Registrando/ })
const quantidade = () => page.locator('input[type="number"]').first()

// ---------------------------------------------- 1. a prévia diz o que vai acontecer
const inicial = await saldo()
console.log(`saldo inicial: ${inicial.quantity} (versão ${inicial.version})`)

await contar.click()
await page.getByText('Saldo registrado agora').waitFor({ timeout: 10000 })

await quantidade().fill(String(inicial.quantity))
await page.getByText(/Confere/).waitFor({ timeout: 5000 })
const previaConfere = await page.evaluate(() => document.body.innerText)
assert.match(previaConfere, /sem movimentar estoque/)

await quantidade().fill(String(inicial.quantity - 2))
const previaDiferenca = await page.evaluate(() => document.body.innerText)
assert.match(previaDiferenca, /Diferença: −2/)
console.log('prévia: diferença anunciada antes de confirmar')

// ------------------------------------------ 2. o estoque anda durante a contagem
await receber(3)
console.log(`entrou mercadoria: saldo agora ${(await saldo()).quantity}`)

await confirmar.click()
await page.getByRole('alert').waitFor({ timeout: 10000 })
await page.screenshot({ path: `${outDir}/contagem-1-conflito.png` })

const conflito = await page.evaluate(() => document.body.innerText)
assert.match(conflito, /movimentado durante a contagem/)
assert.equal(
  await quantidade().inputValue(), String(inicial.quantity - 2),
  'a tela apagou o número que a pessoa tinha contado',
)
assert.ok(
  await confirmar.isDisabled(),
  'um clique confirmaria a contagem velha contra a versão nova',
)
console.log('conflito: número preservado e confirmação travada')

// ----------------------------- 3. só depois do ato deliberado a confirmação volta
await page.getByRole('checkbox').check()
assert.ok(!(await confirmar.isDisabled()), 'a nova conferência não reabilitou a confirmação')

await confirmar.click()
await page.getByText('Conferência registrada.').waitFor({ timeout: 10000 })
await page.screenshot({ path: `${outDir}/contagem-2-registrada.png` })

const final = await saldo()
console.log(`saldo final: ${final.quantity} (versão ${final.version})`)
assert.equal(final.quantity, inicial.quantity - 2, 'a contagem confirmada não virou saldo')
assert.deepEqual(erros, [], `erros de página: ${erros.join(' | ')}`)

console.log('\nOK: prévia, conflito com número preservado, e confirmação só após nova conferência.')
await browser.close()
