import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'


const root = join(import.meta.dirname, '..', 'src')
const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
const workspace = readFileSync(join(root, 'components', 'management', 'ChannelHubWorkspace.tsx'), 'utf8')
const layout = readFileSync(join(root, 'layouts', 'ManagementLayout.tsx'), 'utf8')
const context = readFileSync(join(root, 'context', 'PosContext.tsx'), 'utf8')
const navegacao = readFileSync(join(root, 'domain', 'managementNavigation.ts'), 'utf8')

test('uses the durable Channel Hub API and requires idempotency for mutations', () => {
  assert.match(api, /\/api\/v1\/channels\/connections/)
  assert.match(api, /\/api\/v1\/channels\/inbox/)
  assert.match(api, /'Idempotency-Key': idempotencyKey/)
  assert.match(workspace, /crypto\.randomUUID\(\)/)
})

test('renders persisted connection and inbox state without sample orders', () => {
  assert.match(workspace, /Pedidos recebidos dos canais/)
  assert.match(workspace, /Uma conexão só aparece como conectada depois que o canal a valida/)
  assert.match(workspace, /Nenhum evento externo recebido/)
  assert.doesNotMatch(workspace, /Pedido #123|João da Silva|fixture|mock/i)
})

test('keeps Channel Hub behind capability and permission boundaries', () => {
  assert.match(context, /setContributions\(access\.contributions\)/)
  assert.match(navegacao, /item\.surface === 'MANAGEMENT_NAV'/)
  assert.match(layout, /case 'channels': return <ChannelHubWorkspace/)
  assert.match(workspace, /permissions\.includes\('channel\.configure'\)/)
})

test('never shows a waiting event as a processed order, and says when nothing runs by itself', () => {
  assert.match(workspace, /RECEIVED: 'Aguardando processamento'/)
  assert.doesNotMatch(workspace, /: <CheckCircle2 className="h-3\.5 w-3\.5 text-state-success" \/>\}\{event\.status\}/)
  assert.match(workspace, /Sem processamento contínuo hospedado/)
  assert.match(workspace, /a limpeza ainda não é automática/)
  assert.doesNotMatch(workspace, /Conteúdo guardado até/)
  assert.match(workspace, /permissions\.includes\('channel\.manage'\) && resumableInbox\.includes\(event\.status\)/)
  assert.match(api, /\/api\/v1\/channels\/inbox\/\$\{eventId\}\/resume/)
})

test('asks for no per-connection webhook secret and shows none', () => {
  assert.doesNotMatch(workspace, /webhookSecret|webhook_secret|Segredo de webhook/)
  assert.doesNotMatch(api, /webhook_secret/)
})

test('shows notices to the channel as delivered only when the channel confirmed, and resends only dead letters', () => {
  assert.match(api, /\/api\/v1\/channels\/outbound`/)
  assert.match(api, /\/api\/v1\/channels\/outbound\/\$\{messageId\}\/resend/)
  assert.match(workspace, /DELIVERED: 'Entregue ao canal'/)
  assert.match(workspace, /PENDING: 'Na fila'/)
  assert.match(workspace, /noticeTypeLabels\[notice\.message_type\] \?\? notice\.message_type/)
  assert.match(workspace, /canManage && notice\.status === 'DEAD_LETTER'/)
  assert.match(workspace, /nenhum é criado sozinho/)
})

test('names the order by its local state, shows what each connector can do, and asks no credential', () => {
  assert.doesNotMatch(workspace, /\{event\.order_id \|\| '—'\}/)
  assert.match(workspace, /orderStatusLabels\[event\.order_status\]/)
  assert.match(workspace, /Sem conector disponível neste ambiente/)
  assert.doesNotMatch(workspace, /secret:\/\/|credentials_ref|Referência segura das credenciais/)
  assert.doesNotMatch(api, /credentials_ref\?: string; actor_id\?: string \},\n\): Promise<\{ connection: MerchantConnection \}>/)
})

test('shows deadlines as counts and never says anything was removed', () => {
  assert.match(api, /\/api\/v1\/channels\/deadlines`/)
  assert.match(workspace, /Nenhuma limpeza foi executada: a limpeza ainda não existe/)
  assert.match(workspace, /Prazo vencido não quer dizer dado removido/)
  assert.doesNotMatch(workspace, /dados eliminados|dado eliminado|foram removidos|foi removido/i)
})
