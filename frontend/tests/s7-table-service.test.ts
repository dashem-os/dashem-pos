import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'


const root = join(import.meta.dirname, '..', 'src')
const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
const workspace = readFileSync(join(root, 'components', 'tables', 'TableServiceWorkspace.tsx'), 'utf8')
const management = readFileSync(join(root, 'layouts', 'ManagementLayout.tsx'), 'utf8')
const context = readFileSync(join(root, 'context', 'PosContext.tsx'), 'utf8')
const navegacao = readFileSync(join(root, 'domain', 'managementNavigation.ts'), 'utf8')

test('uses persistent table session APIs and idempotency keys', () => {
  assert.match(api, /fetchServiceTables/)
  assert.match(api, /openTableSession/)
  assert.match(api, /getTableSession/)
  assert.match(api, /addTableSessionOrder/)
  assert.match(api, /'Idempotency-Key': idempotencyKey/)
})

test('keeps table configuration in Gestão instead of the attendant workspace', () => {
  assert.match(context, /setContributions\(access\.contributions\)/)
  assert.match(navegacao, /item\.surface === 'MANAGEMENT_NAV'/)
  assert.match(management, /case 'tables': return <ServiceSetupManager/)
  assert.doesNotMatch(workspace, /Cadastrar mesa/)
  assert.match(workspace, /Mesa reservada/)
  assert.match(workspace, /Sinalizar impedimento/)
  assert.match(workspace, /Bloquear após fechamento/)
  assert.doesNotMatch(workspace, /window\.prompt/)
})

test('renders real empty state and server-composed totals without fixtures', () => {
  assert.match(workspace, /Mapa ainda não configurado/)
  assert.match(workspace, /consolidated_total/)
  assert.doesNotMatch(workspace, /mock|fixture|Mesa 2.*120/)
})


test('the table selector scope is fixed to TABLE/FOOD_SERVICE and never follows the operated activity', () => {
  const selector = readFileSync(join(root, 'components', 'tables', 'TableProductSelector.tsx'), 'utf8')

  // Num tenant misto — varejo e food service no mesmo contrato — a pessoa troca
  // de atividade no PDV para vender balcão. Isso não pode reescrever o cardápio
  // da mesa: mesa é food service por definição, não pela aba selecionada.
  assert.match(selector, /sales_context: 'TABLE', activity: 'FOOD_SERVICE'/)
  assert.doesNotMatch(
    selector,
    /activity:\s*(activeActivity|operationMode|scope\.)/,
    'o escopo do seletor de mesa passou a seguir a atividade operada',
  )
  assert.doesNotMatch(
    selector,
    /sales_context:\s*(activeActivity|operationMode)/,
    'o contexto de venda do seletor de mesa deixou de ser fixo em TABLE',
  )

  // A vitrine do balcão, essa sim, segue a atividade operada — as duas telas
  // divergem de propósito, e é isso que o teste registra.
  const showcase = readFileSync(join(root, 'components', 'pos', 'ProductShowcase.tsx'), 'utf8')
  assert.match(showcase, /business_activity: activeActivity/)
})
