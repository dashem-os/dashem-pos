const fs = require('node:fs')
const { chromium } = require('playwright')
const fixture = JSON.parse(fs.readFileSync(process.env.WALK_FIXTURE, 'utf8'))
;(async () => {
  const b = await chromium.launch()
  try {
    const c = await b.newContext({ viewport: { width: 1660, height: 860 }, locale: 'pt-BR' })
    const agora = Math.floor(Date.now() / 1000)
    const sub = JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub
    await c.addInitScript(([k, v]) => window.localStorage.setItem(k, v), ['sb-127-auth-token', JSON.stringify({
      access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800, expires_at: agora + 28800,
      refresh_token: 'walk', user: { id: sub, aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
        app_metadata: { provider: 'email' }, user_metadata: {}, created_at: new Date().toISOString() } })])
    const p = await c.newPage()
    p.setDefaultTimeout(15000)
    await p.goto(process.env.WALK_APP_URL + '/pos?access=management', { waitUntil: 'domcontentloaded' })
    await p.waitForTimeout(6000)
    console.log((await p.locator('body').innerText()).slice(0, 700))
    console.log('--- botões ---')
    console.log((await p.getByRole('button').allInnerTexts()).slice(0, 20).join(' / '))
    await p.screenshot({ path: process.env.PROBE_OUT })
  } finally { await b.close() }
})().catch(e => { console.error(String(e).slice(0, 300)); process.exit(1) })
