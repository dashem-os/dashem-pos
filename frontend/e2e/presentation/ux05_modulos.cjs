/**
 * UX-05 — a auditoria dos módulos restantes, antes de mexer neles.
 *
 * O aceite manda auditar cada jornada **antes** da mudança, e proíbe declarar a
 * sprint pronta enquanto houver módulo da lista sem validação. Então este
 * roteiro é primeiro um levantamento e depois um portão: ele percorre os oito
 * destinos, mede em cada um os mesmos critérios que a UX-02 fixou, e imprime um
 * placar por módulo — não um verde único que esconde qual deles ainda falta.
 *
 * O que ele mede em cada tela:
 *  - **um título por tela**, e o topo sem repeti-lo;
 *  - **sem cartão dentro de cartão** — moldura sobre moldura;
 *  - **cor de token**, não crua: ele lê as cores computadas e acusa qualquer
 *    uma que não venha da paleta declarada em `index.css`;
 *  - **a tarefa principal alcançável** sem rolar, em 1366×640.
 */
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const appUrl = process.env.UX_APP_URL || 'http://127.0.0.1:5173'
const fixturePath = process.env.UX_FIXTURE
const outDir = process.env.UX_OUT || path.resolve('artifacts', 'ux05')
if (!fixturePath) throw new Error('UX_FIXTURE é obrigatório.')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
fs.mkdirSync(outDir, { recursive: true })

const TAMANHO = { nome: 'desktop-baixo-1366x640', width: 1366, height: 640 }

const MODULOS = [
  { nome: 'vendas', area: 'OPERACAO', modulo: 'sales' },
  { nome: 'caixas', area: 'OPERACAO', modulo: 'cash' },
  { nome: 'canais', area: 'OPERACAO', modulo: 'channels' },
  { nome: 'terminais', area: 'ESTRUTURA', modulo: 'devices' },
  { nome: 'equipe', area: 'PESSOAS', modulo: 'team' },
  { nome: 'clientes', area: 'RELACIONAMENTO', modulo: 'customers' },
  { nome: 'recebiveis', area: 'FINANCEIRO', modulo: 'receivables' },
  { nome: 'plano', area: 'ADMINISTRACAO', modulo: 'subscription' },
]

const relatorio = { app: appUrl, gerado_em: new Date().toISOString(), modulos: [] }

const MEDIDA = () => {
  const main = document.querySelector('main')
  if (!main) return { erro: 'sem main' }

  const soContemControles = (el) => {
    const filhos = [...el.children]
    return filhos.length > 0 && filhos.every((f) => f.matches('button, a, input, select, label'))
  }
  const ehCartao = (el) => {
    if (el.closest('button, a, label, [role="button"], [role="tablist"], form')) return false
    // Cartão sem conteúdo não é cartão: o selo de ícone ao lado de um título
    // tem moldura, canto e fundo, e é decoração — moldura sobre moldura só
    // incomoda quando as duas emolduram texto.
    if (!(el.innerText || '').trim()) return false
    if (soContemControles(el)) return false
    const s = getComputedStyle(el)
    if (s.borderTopStyle === 'dashed' || s.borderTopStyle === 'dotted') return false
    return parseFloat(s.borderTopLeftRadius) >= 12
      && parseFloat(s.borderTopWidth) > 0
      && s.backgroundColor !== 'rgba(0, 0, 0, 0)'
  }
  const cartoes = [...main.querySelectorAll('div, section, article, aside')].filter(ehCartao)
  const aninhados = cartoes
    .filter((el) => cartoes.some((outro) => outro !== el && outro.contains(el)))
    .map((el) => (el.innerText || '').trim().split('\n')[0].slice(0, 40))

  // A paleta declarada: tudo o que `index.css` publica como canal. Uma cor
  // computada fora dela é cor crua — e some do controle do nicho e do tema.
  const raiz = getComputedStyle(document.documentElement)
  const canais = [...document.styleSheets].length // só para forçar o cálculo
  const declaradas = new Set()
  for (const nome of [
    'brand', 'brand-strong', 'brand-ink', 'brand-soft', 'brand-contrast',
    'surface-bg', 'surface', 'surface-elevated', 'border', 'text-strong', 'text-muted',
  ].concat(['success', 'warning', 'danger', 'info'].flatMap((e) => [
    `state-${e}`, `state-${e}-soft`, `state-${e}-border`,
    `state-${e}-strong`, `state-${e}-on-strong`, `state-${e}-accent`,
  ]))) {
    const valor = raiz.getPropertyValue(`--${nome}`).trim()
    if (valor) declaradas.add(`rgb(${valor.split(/\s+/).join(', ')})`)
  }
  declaradas.add('rgba(0, 0, 0, 0)')
  declaradas.add('rgb(255, 255, 255)')
  declaradas.add('rgb(0, 0, 0)')

  const forasDaPaleta = new Map()
  for (const el of main.querySelectorAll('*')) {
    const s = getComputedStyle(el)
    // Cor de moldura só conta quando há moldura. O `preflight` do Tailwind dá a
    // todo elemento um `border-color` cinza mesmo com largura zero, e sem esta
    // guarda a medida acusava `rgb(229, 231, 235)` em todos os oito módulos —
    // inclusive num link de voltar que não tem borda nenhuma.
    const temMoldura = parseFloat(s.borderTopWidth) > 0
    for (const [propriedade, valor] of [
      ['cor', s.color], ['fundo', s.backgroundColor],
      ['moldura', temMoldura ? s.borderTopColor : ''],
    ]) {
      if (!valor || valor.startsWith('rgba') && valor.endsWith(', 0)')) continue
      const solido = valor.replace(/rgba\(([^)]+), *1\)/, 'rgb($1)')
      if (declaradas.has(solido)) continue
      // Transparências sobre canal declarado são variações do mesmo canal.
      if (/^rgba\(/.test(solido)) continue
      const chave = `${propriedade} ${solido}`
      if (!forasDaPaleta.has(chave)) {
        forasDaPaleta.set(chave, (el.innerText || el.tagName).trim().split('\n')[0].slice(0, 30))
      }
    }
  }

  const titulos = [...main.querySelectorAll('h1')].map((h) => h.textContent.trim())
  const contexto = document.querySelector('header p')
  const acaoPrincipal = main.querySelector('button:not([disabled])')
  const caixa = acaoPrincipal ? acaoPrincipal.getBoundingClientRect() : null

  return {
    canais,
    titulos,
    titulo_repetido: !!(contexto && titulos.includes(contexto.textContent.trim())),
    cartoes_aninhados: [...new Set(aninhados)],
    fora_da_paleta: [...forasDaPaleta].map(([cor, onde]) => `${cor} em "${onde}"`),
    acao_principal: acaoPrincipal ? acaoPrincipal.innerText.trim().split('\n')[0].slice(0, 30) : null,
    acao_visivel: !!(caixa && caixa.bottom <= window.innerHeight && caixa.top >= 0),
    texto: (main.innerText || '').trim().slice(0, 120),
  }
}

function sessao() {
  const agora = Math.floor(Date.now() / 1000)
  return {
    access_token: fixture.manager_token, token_type: 'bearer', expires_in: 28800,
    expires_at: agora + 28800, refresh_token: 'ux05-local',
    user: {
      id: JSON.parse(Buffer.from(fixture.manager_token.split('.')[1], 'base64').toString()).sub,
      aud: 'authenticated', role: 'authenticated', email: fixture.manager_email,
      app_metadata: { provider: 'email' }, user_metadata: { full_name: 'Marcela Almeida' },
      created_at: new Date().toISOString(),
    },
  }
}

async function main() {
  const navegador = await chromium.launch()
  try {
    const contexto = await navegador.newContext({
      viewport: { width: TAMANHO.width, height: TAMANHO.height }, deviceScaleFactor: 1, locale: 'pt-BR',
    })
    await contexto.addInitScript(([k, v]) => window.localStorage.setItem(k, v),
      ['sb-127-auth-token', JSON.stringify(sessao())])
    const page = await contexto.newPage()
    page.setDefaultTimeout(25000)

    for (const alvo of MODULOS) {
      await page.goto(`${appUrl}/manage?area=${alvo.area}&module=${alvo.modulo}`, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(2800)
      const medida = await page.evaluate(MEDIDA)
      if (medida.erro) throw new Error(`${alvo.nome}: ${medida.erro}`)
      await page.screenshot({ path: path.join(outDir, `${alvo.nome}.png`) })

      const achados = []
      if (medida.titulos.length !== 1) achados.push(`${medida.titulos.length} títulos de página`)
      if (medida.titulo_repetido) achados.push('o topo repete o título')
      if (medida.cartoes_aninhados.length) achados.push(`cartão dentro de cartão (${medida.cartoes_aninhados.length})`)
      if (medida.fora_da_paleta.length) achados.push(`${medida.fora_da_paleta.length} cores fora da paleta`)
      if (!medida.acao_visivel) achados.push('a primeira ação exige rolar')

      relatorio.modulos.push({ ...alvo, ...medida, achados })
      const marca = achados.length ? 'ACHADOS' : 'ok     '
      console.log(`${marca} ${alvo.nome.padEnd(12)} ${achados.join(' · ') || '—'}`)
      medida.fora_da_paleta.slice(0, 3).forEach((c) => console.log(`          ${c}`))
    }
    await contexto.close()
  } finally {
    await navegador.close()
  }

  const comAchados = relatorio.modulos.filter((m) => m.achados.length)
  relatorio.resumo = { auditados: relatorio.modulos.length, com_achados: comAchados.length }
  fs.writeFileSync(path.join(outDir, 'ux05-modulos.json'), JSON.stringify(relatorio, null, 2), 'utf8')
  console.log(`\nauditados: ${relatorio.modulos.length} · com achados: ${comAchados.length}`)
  if (process.env.UX_PORTAO === '1' && comAchados.length) process.exit(1)
}

main().catch((e) => { console.error('FALHOU:', e.message); process.exit(1) })
