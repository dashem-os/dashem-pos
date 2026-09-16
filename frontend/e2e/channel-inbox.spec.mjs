/**
 * Olhar a caixa de entrada de canais com um evento em cada estado.
 *
 * Confere na tela, em largura de mesa e de celular:
 * - cada estado aparece em linguagem de operação, e "Aguardando processamento"
 *   não se apresenta como pedido processado;
 * - a falta de processamento contínuo hospedado está dita;
 * - "Retomar" aparece só onde retomar faz sentido, e só com `channel.manage`;
 * - nenhum marcador de dado pessoal do payload chega à tela;
 * - nenhuma palavra quebra no meio (a lição da auditoria de palavra partida).
 *
 * As permissões vêm interceptadas no navegador da bancada. Não substitui a
 * travessia autenticada nem homologa a tela.
 *
 * Uso:
 *   node e2e/channel-inbox.spec.mjs <bench.json> <saida>
 * onde bench.json é a saída de backend/tests/support/seed_channel_inbox_bench.py.
 */
import assert from 'node:assert/strict'
import { readFileSync, mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const [benchPath, outDir = 'artifacts/channel-inbox'] = process.argv.slice(2)
const bench = JSON.parse(readFileSync(benchPath, 'utf8'))
mkdirSync(outDir, { recursive: true })

const labels = {
  applied: 'Aplicado ao pedido', quarantined: 'Em quarentena', review: 'Precisa de uma pessoa',
  waiting: 'Aguardando processamento', expired: 'Expirado sem aplicação',
}

async function visit(permissions, viewport, name) {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport })
  const errors = []
  page.on('pageerror', e => errors.push(String(e)))
  await page.route('**/api/v1/capabilities/effective*', async route => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({ response, json: { ...body, permissions: [...(body.permissions || []), ...permissions] } })
  })
  await page.goto(`http://127.0.0.1:5173/e2e/channel-inbox.html?tenant=${bench.tenant}&store=${bench.store}&operator=${bench.operator}`)
  await page.getByText('External Order Inbox').waitFor({ timeout: 30000 })
  await page.getByText(labels.waiting).first().waitFor({ timeout: 30000 })
  const inbox = page.locator('section', { has: page.getByRole('heading', { name: 'External Order Inbox' }) }).last()
  const text = await inbox.innerText()
  const resumeButtons = await inbox.getByRole('button', { name: 'Retomar' }).count()
  await inbox.screenshot({ path: `${outDir}/${name}.png` })

  const broken = await inbox.evaluate(root => {
    const found = []
    for (const el of root.querySelectorAll('span, p, td, button')) {
      const words = (el.textContent || '').trim().split(/\s+/).filter(w => w.length > 3)
      if (!words.length || el.children.length) continue
      const range = document.createRange()
      range.selectNodeContents(el)
      const lines = new Set([...range.getClientRects()].map(r => Math.round(r.top)))
      if (lines.size > words.length) found.push(el.textContent.trim().slice(0, 40))
    }
    return found
  })
  await browser.close()
  return { text, errors, broken, resumeButtons }
}

const manager = await visit(['channel.read', 'channel.manage', 'channel.configure'], { width: 1280, height: 900 }, 'caixa-gestora-1280')
for (const [state, label] of Object.entries(labels)) {
  assert.match(manager.text, new RegExp(label), `${state}: "${label}" não apareceu`)
}
assert.match(manager.text, /Sem processamento contínuo hospedado/)
assert.equal(manager.resumeButtons, 2, 'Retomar deve aparecer só na quarentena e na revisão')
assert.match(manager.text, /venceu em .*; a limpeza ainda não é automática/, 'prazo vencido não pode parecer conteúdo removido')
assert.match(manager.text, /uma pessoa decide/)
assert.doesNotMatch(manager.text, /\b(RECEIVED|QUARANTINED|NEEDS_REVIEW|APPLIED|EXPIRED)\b/, 'código cru na tela')
for (const marker of bench.markers) assert.ok(!manager.text.includes(marker), `dado pessoal na tela: ${marker}`)
assert.deepEqual(manager.errors, [])
assert.deepEqual(manager.broken, [], `palavra quebrada: ${manager.broken.join(' | ')}`)

const reader = await visit(['channel.read'], { width: 390, height: 844 }, 'caixa-leitura-390')
assert.match(reader.text, new RegExp(labels.waiting))
assert.equal(reader.resumeButtons, 0, 'sem channel.manage não há Retomar')
for (const marker of bench.markers) assert.ok(!reader.text.includes(marker), `dado pessoal na tela: ${marker}`)
assert.deepEqual(reader.errors, [])
assert.deepEqual(reader.broken, [], `palavra quebrada no celular: ${reader.broken.join(' | ')}`)

console.log(JSON.stringify({ ok: true, capturas: [`${outDir}/caixa-gestora-1280.png`, `${outDir}/caixa-leitura-390.png`] }))
