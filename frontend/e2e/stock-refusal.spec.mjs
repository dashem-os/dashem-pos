/**
 * A recusa do servidor tem que aparecer na tela e não pode fechar o formulário.
 *
 * Antes desta correção o formulário limpava e fechava incondicionalmente depois
 * de chamar a API, porque `adjustStock` engolia o erro. A pessoa via um aviso
 * vermelho passar e o modal sumir junto com o que ela tinha digitado, sem saber
 * se a perda foi registrada ou não.
 *
 * Uso:
 *   node e2e/stock-refusal.spec.mjs <tenant> <store> <operator> <produto> <pasta-de-saida>
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
  return Number((await res.json()).quantity)
}

const antes = await saldo()
console.log(`saldo antes: ${antes}`)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const erros = []
const chamadas = []
page.on('pageerror', e => erros.push(String(e)))
page.on('requestfailed', r => { if (r.url().includes('inventory')) chamadas.push(`FALHOU ${r.method()} ${r.url()} :: ${r.failure()?.errorText}`) })
page.on('console', m => { if (m.type() === 'error') chamadas.push(`CONSOLE ${m.text()}`.slice(0, 200)) })
page.on('response', async res => {
  if (res.status() >= 400) {
    chamadas.push(`${res.status()} ${res.url()} :: ${(await res.text().catch(() => '')).slice(0, 200)}`)
  }
})

await page.goto(
  `http://127.0.0.1:5173/e2e/stock-refusal.html?tenant=${tenant}&store=${store}&operator=${operator}`,
  { waitUntil: 'networkidle' },
)
await page.getByText('Refrigerante lata').first().waitFor({ timeout: 20000 })

// O lojista abre a movimentação pelo botão que existe hoje na lista.
await page.getByRole('button', { name: 'Ajustar' }).first().click()
await page.getByText('Ajustar Inventário de Estoque').waitFor({ timeout: 10000 })

// Perda maior do que existe: o servidor tem que recusar.
await page.locator('select').first().selectOption('LOSS')
const quantidade = page.locator('input[type="number"]').first()
await quantidade.fill('50')
// O motivo precisa ter acompanhado a troca de operacao: uma perda gravada como
// "Entrada de mercadoria" deixa o historico contradizendo o proprio movimento.
const motivo = page.locator('input[type="text"]').filter({ hasNot: page.locator('[readonly]') })
const motivoAtual = await page.evaluate(() => {
  const campos = Array.from(document.querySelectorAll('input[type=text]'))
  return campos.map(c => c.value)
})
assert.ok(
  motivoAtual.includes('Perda, avaria ou vencimento'),
  `o motivo nao acompanhou a operacao: ${JSON.stringify(motivoAtual)}`,
)

await page.screenshot({ path: `${outDir}/recusa-1-antes-de-confirmar.png` })
await page.getByRole('button', { name: /Confirmar|Registrar|Salvar/i }).first().click()
await page.waitForTimeout(2500)
await page.screenshot({ path: `${outDir}/recusa-2-depois-da-recusa.png` })

console.log('--- chamadas a /inventory/adjust ---')
console.log(chamadas.join(' // ') || '(nenhuma)')

const texto = await page.evaluate(() => document.body.innerText)
console.log('--- aviso na tela ---')
console.log(texto.split('\n').filter(l => /saldo|insuficiente|erro|dispon/i.test(l)).join('\n'))

assert.match(texto, /Saldo insuficiente de 'Refrigerante lata'/,
  'a tela não mostrou a recusa do servidor com a mercadoria e os números')
assert.doesNotMatch(texto, /INSUFFICIENT_STOCK/,
  'a tela mostrou código interno para o lojista')
assert.ok(
  await page.getByText('Ajustar Inventário de Estoque').isVisible(),
  'o formulário fechou em cima de uma recusa',
)
assert.equal(
  await quantidade.inputValue(), '50',
  'o formulário apagou o que a pessoa tinha digitado',
)

const depois = await saldo()
console.log(`saldo depois: ${depois}`)
assert.equal(depois, antes, 'a recusa mexeu no saldo')
assert.deepEqual(erros, [], `erros de página: ${erros.join(' | ')}`)

console.log('\nOK: a recusa apareceu, o formulário continuou aberto com os dados, e o saldo não mudou.')
await browser.close()
