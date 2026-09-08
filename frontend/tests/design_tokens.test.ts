import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

/**
 * A cor da situação vem do token, não da paleta crua do Tailwind.
 *
 * Antes da UX-02 cada tela escolhia a sua: `emerald-700` aqui, `emerald-800`
 * ali, e um `violet-700` em Categorias sem motivo nenhum. Eram 36 escolhas
 * soltas nas quatro telas de Mercadorias — nenhuma acompanhava o nicho, e
 * corrigir o verde de "em dia" exigia achar as seis grafias dele.
 *
 * Este guarda não é sobre gosto: é sobre existir um lugar para mudar. Ele vale
 * para as telas que a UX-02 consolidou; as demais entram junto com a UX-05, e
 * a lista abaixo é o placar dessa dívida.
 */

const SRC = fileURLToPath(new URL('../src', import.meta.url))

/** Telas já consolidadas: cor crua aqui reprova. */
const CONSOLIDADAS = [
  'components/management/CatalogManager.tsx',
  'components/management/CategoryManager.tsx',
  'components/management/AssortmentManager.tsx',
  'components/management/InventoryManager.tsx',
  'components/management/AreaHub.tsx',
  'components/management/DashboardBI.tsx',
  'layouts/ManagementLayout.tsx',
  // A fundação: quem define faixa, aviso, etiqueta e estado vazio precisa
  // falar em token, senão cada tela reinventa a cor ao usá-los.
  'components/common/Badge.tsx',
  'components/common/Button.tsx',
  'components/common/EmptyState.tsx',
  'components/common/Field.tsx',
  'components/common/RowActions.tsx',
  'components/common/StatCard.tsx',
  'components/common/Toast.tsx',
  // UX-05: os oito módulos restantes da Gestão, auditados um a um antes de
  // mexer neles. Clientes e Recebíveis já estavam limpos e entram para não
  // regredirem.
  'components/management/SalesHistory.tsx',
  'components/management/CashManager.tsx',
  'components/management/ChannelHubWorkspace.tsx',
  'components/management/DeviceManager.tsx',
  'components/management/TeamManager.tsx',
  'components/management/CustomerManager.tsx',
  'components/management/ReceivablesManager.tsx',
  'components/management/TenantPlanWorkspace.tsx',
  'components/management/CommercialRequestsPanel.tsx',
]

const PALETA_CRUA = /\b(?:text|bg|border|ring|from|via|to|divide|outline|decoration|shadow)-(?:violet|indigo|purple|fuchsia|pink|blue|sky|cyan|teal|emerald|green|lime|yellow|amber|orange|red|rose)-\d{2,3}\b/g

test('as telas consolidadas usam token de estado, não cor crua da paleta', () => {
  for (const caminho of CONSOLIDADAS) {
    const fonte = readFileSync(join(SRC, caminho), 'utf8')
    const cruas = [...new Set(fonte.match(PALETA_CRUA) ?? [])]
    assert.deepEqual(
      cruas, [],
      `${caminho} usa cor crua da paleta: ${cruas.join(', ')}. ` +
      'Situação vem de state-success / state-warning / state-danger / state-info; ' +
      'identidade vem de brand.',
    )
  }
})

test('os quatro estados existem como token, com fundo e moldura próprios', () => {
  const css = readFileSync(join(SRC, 'index.css'), 'utf8')
  for (const estado of ['success', 'warning', 'danger', 'info']) {
    for (const sufixo of ['', '-soft', '-border', '-strong', '-on-strong', '-accent']) {
      assert.match(css, new RegExp(`--state-${estado}${sufixo}:`),
        `falta o canal --state-${estado}${sufixo} em index.css`)
    }
  }
})

test('os canais de estado não mudam por nicho', () => {
  // "Em falta" é vermelho na padaria e na revendedora de beleza. Só a marca
  // troca por nicho; misturar as duas famílias faria a situação mentir.
  const css = readFileSync(join(SRC, 'index.css'), 'utf8')
  const blocosDeNicho = css.match(/:root\[data-niche='[^']+'\]\s*\{[^}]*\}/g) ?? []
  assert.ok(blocosDeNicho.length >= 3, 'esperava um bloco por nicho contratado')
  for (const bloco of blocosDeNicho) {
    assert.doesNotMatch(bloco, /--state-/, 'um nicho está redefinindo cor de situação')
  }
})
