import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { getItemPresentationStatus } from '../src/domain/channelCatalogPresentation.ts'

const root = join(import.meta.dirname, '..', 'src')
const api = readFileSync(join(root, 'services', 'api.ts'), 'utf8')
const hub = readFileSync(join(root, 'components', 'management', 'ChannelHubWorkspace.tsx'), 'utf8')
const presentation = readFileSync(join(root, 'domain', 'channelCatalogPresentation.ts'), 'utf8')

test('projects real catalog publication backlog and marketplace settlements', () => {
  assert.match(api, /\/api\/v1\/channel-catalog\/catalog/)
  assert.match(api, /\/api\/v1\/channel-catalog\/settlements/)
  assert.match(hub, /last_publication_status/)
  assert.match(hub, /Venda e liquidação financeira são fatos separados/)
})

test('never assumes empty marketplace data is synchronized or paid', () => {
  assert.match(hub, /não aparecem conciliadas por suposição/)
  assert.match(hub, /fonte canônica/)
  assert.doesNotMatch(hub, /Sincronizado com sucesso.*0|mock|fixture/i)
})

test('connects publication execution and resumption in API client and ChannelHubWorkspace', () => {
  assert.match(api, /executeChannelPublicationBatch/)
  assert.match(api, /resumeChannelPublicationBatch/)
  assert.match(api, /\/api\/v1\/channel-catalog\/publications\/\$\{batchId\}\/execute/)
  assert.match(api, /\/api\/v1\/channel-catalog\/publications\/\$\{batchId\}\/resume/)
  assert.match(hub, /executeChannelPublicationBatch/)
  assert.match(hub, /resumeChannelPublicationBatch/)
  assert.match(hub, /getItemPresentationStatus/)
  assert.match(hub, /Retomar/)
  assert.match(hub, /Executar/)
  assert.match(presentation, /Tentativa sem confirmação/)
  assert.match(presentation, /Pendente de envio/)
  assert.match(hub, /title=\{!isConnectionReady/)
})

test('getItemPresentationStatus preserves specification table precedence and distinguishes attempt_count', () => {
  // 1. Item SUCCEEDED -> Confirmado
  assert.deepEqual(getItemPresentationStatus({ status: 'SUCCEEDED' }, 'SUCCEEDED'), {
    label: 'Confirmado',
    toneClass: 'text-state-success font-bold',
  })
  assert.deepEqual(getItemPresentationStatus({ status: 'SUCCEEDED', attempt_count: 2 }, 'PARTIAL'), {
    label: 'Confirmado',
    toneClass: 'text-state-success font-bold',
  })

  // 2. Item FAILED por rejeição de negócio -> Rejeitado pelo canal
  assert.deepEqual(getItemPresentationStatus({ status: 'FAILED', error_code: 'INVALID_CATEGORY' }, 'PARTIAL'), {
    label: 'Rejeitado pelo canal',
    toneClass: 'text-state-danger font-bold',
  })

  // 3. Item FAILED com TIMEOUT ou NETWORK_FAILURE -> Resposta não confirmada
  assert.deepEqual(getItemPresentationStatus({ status: 'FAILED', error_code: 'TIMEOUT' }, 'PARTIAL'), {
    label: 'Resposta não confirmada',
    toneClass: 'text-state-warning font-bold',
  })
  assert.deepEqual(getItemPresentationStatus({ status: 'FAILED', error_code: 'NETWORK_FAILURE' }, 'FAILED'), {
    label: 'Resposta não confirmada',
    toneClass: 'text-state-warning font-bold',
  })

  // 4. Item PENDING em lote PROCESSING -> Em execução
  assert.deepEqual(getItemPresentationStatus({ status: 'PENDING', attempt_count: 0 }, 'PROCESSING'), {
    label: 'Em execução',
    toneClass: 'text-dashem-strong font-bold',
  })
  assert.deepEqual(getItemPresentationStatus({ status: 'PENDING', attempt_count: 1 }, 'PROCESSING'), {
    label: 'Em execução',
    toneClass: 'text-dashem-strong font-bold',
  })

  // 5. Item PENDING fora de PROCESSING, attempt_count > 0 -> Tentativa sem confirmação
  assert.deepEqual(getItemPresentationStatus({ status: 'PENDING', attempt_count: 1 }, 'PARTIAL'), {
    label: 'Tentativa sem confirmação',
    toneClass: 'text-state-warning font-bold',
  })
  assert.deepEqual(getItemPresentationStatus({ status: 'PENDING', attempt_count: 2 }, 'FAILED'), {
    label: 'Tentativa sem confirmação',
    toneClass: 'text-state-warning font-bold',
  })

  // 6. Item PENDING fora de PROCESSING, attempt_count = 0 -> Pendente de envio (inclusive em lote PARTIAL e FAILED)
  // DETECTOR DIRETO DO DEFEITO 1:
  assert.deepEqual(getItemPresentationStatus({ status: 'PENDING', attempt_count: 0 }, 'PARTIAL'), {
    label: 'Pendente de envio',
    toneClass: 'text-dashem-muted',
  })
  assert.deepEqual(getItemPresentationStatus({ status: 'PENDING', attempt_count: 0 }, 'FAILED'), {
    label: 'Pendente de envio',
    toneClass: 'text-dashem-muted',
  })
  assert.deepEqual(getItemPresentationStatus({ status: 'PENDING', attempt_count: 0 }, 'PENDING'), {
    label: 'Pendente de envio',
    toneClass: 'text-dashem-muted',
  })
})
