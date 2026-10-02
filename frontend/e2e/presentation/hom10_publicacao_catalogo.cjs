/**
 * Travessia automatizada em navegador real (Playwright / Chromium) para a fatia API/UI
 * do S13.2 (Publicação de Catálogo no Channel Hub).
 *
 * ESCOPO E CAMADA DE TESTE:
 * Este script é um teste de interface/navegador com contratos de API simulados no Playwright
 * (mocked contracts), voltado para a validação visual, fluxos de usuário, estados de tela,
 * recarga do backlog após erro, distinção individual de contadores de tentativa em itens pendentes,
 * feedback de erros de transporte HTTP 5xx vs ação contra contrato 200/PARTIAL (exceção capturada),
 * concorrência sob lease (409), badges contextuais, bloqueio sob conexão inativa/sem capacidade
 * e permissões RBAC.
 * O teste ponta a ponta integrado real do fluxo completo com banco PostgreSQL, transações reais,
 * exclusão mútua sob lease e adaptador durável SQLite é:
 * backend/tests/test_channel_catalog_execution_walkthrough.py.
 *
 * Casos cobertos:
 * 1. Distinção individual de itens pendentes em lote PARTIAL: attempt_count = 0 mostra "Pendente de envio",
 *    attempt_count > 0 mostra "Tentativa sem confirmação" (inspecionado por linha de produto).
 * 2. Executar lote PENDING: falha 500 após persistência de PROCESSING/lease; releitura automática
 *    via finally atualiza a tela para PROCESSING (sem reenvio automático).
 * 3. Retomar lote PARTIAL: falha 500 após mudança de estado; releitura automática via finally
 *    reflete PROCESSING e atualiza badge e itens.
 * 4. Retomar com recuperação parcial persistida: POST falha no reenvio, releitura devolve 1 item SUCCEEDED
 *    e 1 item PENDING com 0 tentativas -> "Confirmado" e "Pendente de envio", com contadores conferidos.
 * 5. Falha na releitura de atualização: erro é tratado com toast e o controle de busy é liberado sem deadlock.
 * 6. Separação de contratos de execução e falha:
 *    - Contrato A: Ação Executar contra contrato HTTP 200/PARTIAL (exceção externa capturada pelo executor)
 *      com waitForResponse do POST, controle determinístico de busy durante a releitura retida,
 *      toast informativo, transição do badge para Parcial com Retomar habilitado e item exibindo "Tentativa sem confirmação".
 *    - Contrato B: Ação Publicar com erro HTTP 504 de transporte/timeout na chamada de execução do canal,
 *      toast de erro, releitura via finally, contadores separados (1 criação, 1 execução), lote em PARTIAL.
 *    - Rejeição conclusiva de negócio (BUSINESS_REJECTION): fixture dedicada demonstrando item FAILED
 *      com código de erro de negócio exibindo "Rejeitado pelo canal · BUSINESS_REJECTION" e item SUCCEEDED exibindo "Confirmado".
 * 7. Conexão SUSPENDED e CONNECTED sem CATALOG_PUBLICATION: presença de Publicar, Executar e Retomar para a gestora,
 *    todos desabilitados com tooltip explicativo e 0 chamadas de mutação.
 * 8. Leitora de catálogo: consulta liberada, ausência total de checkboxes e botões de mutação.
 *    Retomada concorrente com lease ativo (409) vs autorizada após expiração.
 */
const assert = require('node:assert/strict')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const frontendDir = path.resolve(__dirname, '../..')
const outDir = path.resolve(frontendDir, '..', 'artifacts', 'hom-publicacao')
fs.mkdirSync(outDir, { recursive: true })

const port = 5195
const appUrl = `http://127.0.0.1:${port}/e2e/channel-inbox.html?tenant=tenant-test-1&store=store-test-1&operator=operator-test-1`

// Estado mutável do mock compartilhado entre rotas
const mockState = {
  connectionStatus: 'CONNECTED',
  connectionCapabilities: ['CATALOG_PUBLICATION', 'ORDER_INGRESS'],
  failExecutionWithTimeout: false,
  failCatalogReload: false,
  catalogReloadGate: null,
  leaseActive: false,
  postExecuteHandler: null,
  postResumeHandler: null,
  executeCount: 0,
  resumeCount: 0,
  publishCount: 0,
  catalogGetCount: 0,
  offers: [
    {
      id: 'off-food-1',
      merchant_connection_id: 'conn-test-1',
      product_id: 'prod-food-1',
      product_name: 'Hambúrguer Artesanal Duplo',
      product_sku: 'FOOD-01',
      price: '45.00',
      available: true,
      stock_quantity: '30',
      desired_version: 1,
      published_version: 0,
      last_publication_status: 'PENDING',
      last_published_at: null,
      updated_at: new Date().toISOString(),
    },
    {
      id: 'off-retail-1',
      merchant_connection_id: 'conn-test-1',
      product_id: 'prod-retail-1',
      product_name: 'Furadeira de Impacto 500W',
      product_sku: 'RET-01',
      price: '189.90',
      available: true,
      stock_quantity: '15',
      desired_version: 1,
      published_version: 0,
      last_publication_status: 'PENDING',
      last_published_at: null,
      updated_at: new Date().toISOString(),
    },
    {
      id: 'off-beauty-1',
      merchant_connection_id: 'conn-test-1',
      product_id: 'prod-beauty-1',
      product_name: 'Batom Matte Longa Duração',
      product_sku: 'BEA-01',
      price: '39.90',
      available: true,
      stock_quantity: '50',
      desired_version: 1,
      published_version: 0,
      last_publication_status: 'PENDING',
      last_published_at: null,
      updated_at: new Date().toISOString(),
    },
  ],
  batches: [],
}

function getCatalogPayload() {
  const conn = {
    id: 'conn-test-1',
    tenant_id: 'tenant-test-1',
    store_id: 'store-test-1',
    channel_id: 'channel-test-1',
    provider_code: 'CONTRACT_TEST',
    merchant_external_id: 'merch-demo-01',
    status: mockState.connectionStatus,
    capabilities: mockState.connectionCapabilities,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
  return {
    connections: [conn],
    offers: mockState.offers,
    mappings: [],
    batches: mockState.batches,
  }
}

function getCatalogSection(page) {
  return page.getByRole('heading', { name: 'Catálogo por canal', exact: true }).locator('xpath=ancestor::section[1]')
}

function getBatchArticle(catalogSection, batchId) {
  return catalogSection.locator(`article[data-batch-id="${batchId}"]`)
}

function getItemRow(batchArticle, productName) {
  return batchArticle.locator('li', { hasText: productName })
}

async function run() {
  console.log('--- Iniciando travessia Playwright Chromium (S13.2) ---')
  const report = {
    test_suite: 'hom10_publicacao_catalogo',
    execution_layer: 'Frontend UI (Playwright Chromium) with mocked OpenAPI contracts',
    scope_note:
      'Este teste valida a camada de interface no navegador real (fluxos de usuário, botões contextuais, tooltips explicativos, recarga do backlog no finally de mutações, classificação precisa de tentativas por item em lotes parciais, distinção entre erros 5xx e contratos 200/PARTIAL, toasts informativos de concorrência 409 e permissões RBAC). O teste integrado ponta a ponta com banco real PostgreSQL e adaptador durável SQLite é test_channel_catalog_execution_walkthrough.py.',
    started_at: new Date().toISOString(),
    steps: [],
    screenshots: [],
    assertions: [],
  }

  // Inicia servidor Vite local para a bancada
  const server = spawn(
    process.execPath,
    ['node_modules/vite/bin/vite.js', '--port', String(port)],
    { cwd: frontendDir, stdio: 'inherit', windowsHide: true }
  )

  let ready = false
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}`)
      if (res.ok) { ready = true; break }
    } catch {}
    await new Promise((r) => setTimeout(r, 400))
  }
  if (!ready) {
    server.kill()
    throw new Error('Servidor Vite não iniciou no tempo esperado.')
  }

  const browser = await chromium.launch({ headless: true })

  try {
    // =========================================================================
    // PARTE 1: GESTORA AUTORIZADA — CONFIGURAÇÃO DAS ROTAS MOCK
    // =========================================================================
    console.log('[1/8] Abrindo sessão da Gestora com autorização channel.catalog.manage...')
    const gestoraContext = await browser.newContext({ viewport: { width: 1280, height: 900 } })
    const gestoraPage = await gestoraContext.newPage()

    await gestoraPage.route('**/api/v1/**', async (route) => {
      const url = route.request().url()
      const method = route.request().method()

      if (url.includes('/capabilities/effective')) {
        return route.fulfill({
          status: 200,
          json: {
            catalog: {},
            delivery_orders: {},
            channel_hub: {},
            permissions: [
              'channel.manage',
              'channel.configure',
              'channel.catalog.manage',
              'channel.view',
            ],
          },
        })
      }

      if (url.includes('/channels/connections')) {
        return route.fulfill({ status: 200, json: [getCatalogPayload().connections[0]] })
      }

      if (url.includes('/channel-catalog/catalog') && method === 'GET') {
        mockState.catalogGetCount++
        if (mockState.catalogReloadGate) {
          await mockState.catalogReloadGate
        }
        if (mockState.failCatalogReload) {
          return route.fulfill({
            status: 500,
            json: { detail: 'Erro temporário de banco ao consultar catálogo' },
          })
        }
        return route.fulfill({ status: 200, json: getCatalogPayload() })
      }

      if (url.includes('/channels/inbox') || url.includes('/channels/outbound')) {
        return route.fulfill({ status: 200, json: [] })
      }

      if (url.includes('settlements')) {
        return route.fulfill({ status: 200, json: [] })
      }

      // POST /channel-catalog/publications/:batchId/resume
      if (url.includes('/channel-catalog/publications') && url.includes('/resume') && method === 'POST') {
        mockState.resumeCount++
        if (mockState.postResumeHandler) {
          return mockState.postResumeHandler(route)
        }
        if (mockState.leaseActive) {
          return route.fulfill({
            status: 409,
            json: { detail: 'Lote em execução por outro processo (lease ativo até 2026-10-02T10:45:00Z)' },
          })
        }
        const batchIdMatch = url.match(/\/publications\/([^/]+)\/resume/)
        const targetId = batchIdMatch ? batchIdMatch[1] : null
        const batch = mockState.batches.find((b) => b.id === targetId) || mockState.batches[0]
        if (batch) {
          batch.status = 'SUCCEEDED'
          batch.lease_token = null
          batch.lease_expires_at = null
          batch.items.forEach((it) => {
            it.status = 'SUCCEEDED'
            it.error_code = null
            it.error_message = null
          })
          mockState.offers.forEach((o) => {
            if (batch.items.some((it) => it.offer_id === o.id)) {
              o.published_version = o.desired_version
              o.last_publication_status = 'SUCCEEDED'
            }
          })
          return route.fulfill({ status: 200, json: { batch, items: batch.items } })
        }
        return route.fulfill({ status: 404, json: { detail: 'Lote não encontrado' } })
      }

      // POST /channel-catalog/publications/:batchId/execute
      if (url.includes('/channel-catalog/publications') && url.includes('/execute') && method === 'POST') {
        mockState.executeCount++
        if (mockState.postExecuteHandler) {
          return mockState.postExecuteHandler(route)
        }
        const batchIdMatch = url.match(/\/publications\/([^/]+)\/execute/)
        const targetId = batchIdMatch ? batchIdMatch[1] : null
        const batch = mockState.batches.find((b) => b.id === targetId) || mockState.batches[0]

        if (mockState.failExecutionWithTimeout) {
          // Contrato B: Falha de rede / timeout (504)
          if (batch) {
            batch.status = 'PARTIAL'
            if (batch.items[0]) {
              batch.items[0].status = 'SUCCEEDED'
              const off0 = mockState.offers.find((o) => o.id === batch.items[0].offer_id)
              if (off0) {
                off0.published_version = off0.desired_version
                off0.last_publication_status = 'SUCCEEDED'
              }
            }
            if (batch.items[1]) {
              batch.items[1].status = 'PENDING'
              batch.items[1].attempt_count = 1
            }
          }
          return route.fulfill({
            status: 504,
            json: { detail: 'Timeout na comunicação com o conector do canal' },
          })
        }

        if (batch) {
          batch.status = 'SUCCEEDED'
          batch.items.forEach((it) => {
            it.status = 'SUCCEEDED'
            it.error_code = null
            it.error_message = null
          })
          mockState.offers.forEach((o) => {
            if (batch.items.some((it) => it.offer_id === o.id)) {
              o.published_version = o.desired_version
              o.last_publication_status = 'SUCCEEDED'
            }
          })
          return route.fulfill({ status: 200, json: { batch, items: batch.items } })
        }
        return route.fulfill({ status: 404, json: { detail: 'Lote não encontrado' } })
      }

      // POST /channel-catalog/publications (Criação de lote)
      if (url.includes('/channel-catalog/publications') && method === 'POST') {
        mockState.publishCount++
        const postData = JSON.parse(route.request().postData() || '{}')
        const offerIds = postData.offer_ids || []
        const newBatchId = `batch-${Date.now()}`
        const newBatch = {
          id: newBatchId,
          tenant_id: 'tenant-test-1',
          store_id: 'store-test-1',
          merchant_connection_id: 'conn-test-1',
          status: 'PENDING',
          snapshot_version: 1,
          lease_token: null,
          lease_expires_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          items: offerIds.map((offId, idx) => {
            const off = mockState.offers.find((o) => o.id === offId)
            return {
              id: `item-${newBatchId}-${idx + 1}`,
              batch_id: newBatchId,
              offer_id: offId,
              status: 'PENDING',
              desired_version: off ? off.desired_version : 1,
              provider_operation_key: `op-${offId}`,
              provider_result_ref: null,
              attempt_count: 0,
              error_code: null,
              error_message: null,
              product_name: off ? off.product_name : 'Produto',
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            }
          }),
        }
        mockState.batches.unshift(newBatch)
        return route.fulfill({
          status: 200,
          json: { batch: newBatch, items: newBatch.items },
        })
      }

      return route.fulfill({ status: 200, json: {} })
    })

    // Prepara lote para o Caso 1 (Defeito 1): mesmo lote PARTIAL com item attempt_count = 0 e item attempt_count = 1
    const batchPartialDistinction = {
      id: 'batch-partial-distinction',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PARTIAL',
      snapshot_version: 1,
      lease_token: null,
      lease_expires_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [
        {
          id: 'item-food-succeeded',
          batch_id: 'batch-partial-distinction',
          offer_id: 'off-food-1',
          status: 'SUCCEEDED',
          desired_version: 1,
          provider_operation_key: 'op-food-1',
          provider_result_ref: 'ref-food-ok',
          attempt_count: 1,
          error_code: null,
          error_message: null,
          product_name: 'Hambúrguer Artesanal Duplo',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          id: 'item-retail-with-attempt',
          batch_id: 'batch-partial-distinction',
          offer_id: 'off-retail-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-retail-1',
          provider_result_ref: null,
          attempt_count: 1, // attempt_count > 0 -> "Tentativa sem confirmação"
          error_code: null,
          error_message: null,
          product_name: 'Furadeira de Impacto 500W',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          id: 'item-beauty-zero-attempts',
          batch_id: 'batch-partial-distinction',
          offer_id: 'off-beauty-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-beauty-1',
          provider_result_ref: null,
          attempt_count: 0, // attempt_count = 0 -> "Pendente de envio" (CORREÇÃO DEFEITO 1)
          error_code: null,
          error_message: null,
          product_name: 'Batom Matte Longa Duração',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    }
    const batchContractAPending = {
      id: 'batch-contract-a-pending',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PENDING',
      snapshot_version: 1,
      lease_token: null,
      lease_expires_at: null,
      created_at: new Date(Date.now() - 10000).toISOString(),
      updated_at: new Date(Date.now() - 10000).toISOString(),
      items: [
        {
          id: 'item-contract-a-pending',
          batch_id: 'batch-contract-a-pending',
          offer_id: 'off-beauty-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-contract-a-pending',
          provider_result_ref: null,
          attempt_count: 0,
          error_code: null,
          error_message: null,
          product_name: 'Batom Matte Longa Duração',
          created_at: new Date(Date.now() - 10000).toISOString(),
          updated_at: new Date(Date.now() - 10000).toISOString(),
        },
      ],
    }
    mockState.batches.push(batchPartialDistinction, batchContractAPending)

    await gestoraPage.goto(appUrl)
    const catalogSection = getCatalogSection(gestoraPage)
    await catalogSection.waitFor({ timeout: 15000 })
    await catalogSection.scrollIntoViewIfNeeded()

    // Confere texto explicativo de tela exigido
    const explanationText = 'Publicar cria o lote e aciona o executor do canal imediatamente. A confirmação ocorre item a item pelo conector, sem marcação antecipada de sucesso — lotes com rejeições ou falhas de rede permanecem disponíveis para retomada.'
    await catalogSection.getByText(explanationText).waitFor({ timeout: 5000 })
    report.assertions.push('Texto explicativo presente e correto.')

    // Confere os três nichos de produto na tabela
    await catalogSection.getByText('Hambúrguer Artesanal Duplo').first().waitFor()
    await catalogSection.getByText('Furadeira de Impacto 500W').first().waitFor()
    await catalogSection.getByText('Batom Matte Longa Duração').first().waitFor()
    report.assertions.push('Ofertas dos três nichos (Alimentação, Varejo, Beleza) presentes.')

    // Confere lote PENDING próprio carregado inicialmente para a ação de Executar (Contrato A)
    const cardCAInit = getBatchArticle(catalogSection, 'batch-contract-a-pending')
    await cardCAInit.waitFor({ timeout: 5000 })
    const execBtnCAInit = cardCAInit.getByRole('button', { name: 'Executar' })
    await execBtnCAInit.waitFor({ timeout: 3000 })
    assert.equal(await execBtnCAInit.isEnabled(), true, 'Botão Executar do lote PENDING deve estar habilitado no carregamento inicial')
    const rowBeautyCAInit = getItemRow(cardCAInit, 'Batom Matte Longa Duração')
    await rowBeautyCAInit.getByText('Pendente de envio').waitFor({ timeout: 3000 })
    report.assertions.push('Caso 6 (Contrato A): Lote próprio PENDING inicial carregado com botão Executar habilitado e item com 0 tentativas em "Pendente de envio".')

    // =========================================================================
    // CASO 1: DISTINÇÃO DE TENTATIVAS EM LOTE PARTIAL (CORREÇÃO DEFEITO 1)
    // =========================================================================
    console.log('[2/8] Caso 1: Conferindo classificação individual de itens no lote PARTIAL...')
    const cardDistinction = getBatchArticle(catalogSection, 'batch-partial-distinction')
    await cardDistinction.waitFor({ timeout: 5000 })

    const rowFood = getItemRow(cardDistinction, 'Hambúrguer Artesanal Duplo')
    const rowRetail = getItemRow(cardDistinction, 'Furadeira de Impacto 500W')
    const rowBeauty = getItemRow(cardDistinction, 'Batom Matte Longa Duração')

    await rowFood.getByText('Confirmado').waitFor({ timeout: 3000 })
    await rowRetail.getByText('Tentativa sem confirmação').waitFor({ timeout: 3000 })
    await rowBeauty.getByText('Pendente de envio').waitFor({ timeout: 3000 })

    report.assertions.push('Caso 1: Item SUCCEEDED mostra "Confirmado".')
    report.assertions.push('Caso 1: Item PENDING com attempt_count > 0 mostra "Tentativa sem confirmação" na sua linha de produto.')
    report.assertions.push('Caso 1: Item PENDING com attempt_count = 0 mostra "Pendente de envio" na sua linha de produto (Defeito 1 resolvido).')

    const shot1b = path.join(outDir, '01b_lote_parcial_distincao_tentativas_pendente_vs_incerto.png')
    await cardDistinction.screenshot({ path: shot1b })
    report.screenshots.push(shot1b)

    // =========================================================================
    // CASO 6 (CONTRATO B): FALHA DE TRANSPORTE / TIMEOUT (504) EM PUBLICAR
    // =========================================================================
    console.log('[3/8] Caso 6 (Contrato B): Gestora aciona Publicar com erro HTTP 504 de transporte/timeout na chamada do canal...')
    const foodCheckbox = catalogSection.locator('input[aria-label="Selecionar Hambúrguer Artesanal Duplo"]')
    const retailCheckbox = catalogSection.locator('input[aria-label="Selecionar Furadeira de Impacto 500W"]')
    await foodCheckbox.check()
    await retailCheckbox.check()

    const publishBtn = catalogSection.getByRole('button', { name: 'Publicar (2)' })
    await publishBtn.waitFor({ timeout: 3000 })
    assert.equal(await publishBtn.isEnabled(), true, 'Botão Publicar (2) deve estar habilitado com itens selecionados')

    // Captura contadores separadamente antes do clique
    const publishCallsBefore504 = mockState.publishCount
    const executeCallsBefore504 = mockState.executeCount
    const getCallsBefore504 = mockState.catalogGetCount
    const batchCountBefore504 = mockState.batches.length

    // Registra esperas de rede antes do clique para criação (200) e execução (504)
    const createResponsePromise504 = gestoraPage.waitForResponse((res) => {
      return res.request().method() === 'POST' &&
             res.request().url().includes('/channel-catalog/publications') &&
             !res.request().url().includes('/execute') &&
             !res.request().url().includes('/resume') &&
             res.status() === 200
    })
    const executeResponsePromise504 = gestoraPage.waitForResponse((res) => {
      return res.request().method() === 'POST' &&
             res.request().url().includes('/channel-catalog/publications') &&
             res.request().url().includes('/execute') &&
             res.status() === 504
    })

    mockState.failExecutionWithTimeout = true
    await publishBtn.click()

    const createRes504 = await createResponsePromise504
    assert.equal(createRes504.status(), 200, 'Criação do lote deve responder HTTP 200')
    const execRes504 = await executeResponsePromise504
    assert.equal(execRes504.status(), 504, 'Execução do lote deve falhar com HTTP 504')

    // Aguarda o toast de erro de timeout (Contrato B)
    await gestoraPage.getByText('Timeout na comunicação com o conector do canal').waitFor({ timeout: 10000 })

    // Valida contadores separados de mutação e releitura
    assert.equal(mockState.publishCount - publishCallsBefore504, 1, 'Caso 6 (Contrato B): Exatamente um POST de criação de lote')
    assert.equal(mockState.executeCount - executeCallsBefore504, 1, 'Caso 6 (Contrato B): Exatamente um POST de execução do lote')
    assert.equal(mockState.resumeCount, 0, 'Caso 6 (Contrato B): Nenhum POST de retomada')
    assert.ok(mockState.catalogGetCount > getCallsBefore504, 'Caso 6 (Contrato B): Releitura automática do catálogo disparada via finally')
    assert.equal(mockState.batches.length - batchCountBefore504, 1, 'Caso 6 (Contrato B): Exatamente um novo lote adicionado, sem duplicatas')

    // Confere o estado devolvido no novo lote renderizado na interface
    const newBatch504 = mockState.batches[0]
    const card504 = getBatchArticle(catalogSection, newBatch504.id)
    await card504.waitFor({ timeout: 5000 })
    await card504.getByText('Parcial').waitFor({ timeout: 5000 })

    const row504Confirmed = getItemRow(card504, 'Hambúrguer Artesanal Duplo')
    const row504Pending = getItemRow(card504, 'Furadeira de Impacto 500W')
    await row504Confirmed.getByText('Confirmado').waitFor({ timeout: 5000 })
    await row504Pending.getByText('Tentativa sem confirmação').waitFor({ timeout: 5000 })

    // Verifica que busy foi liberado e o botão Retomar está disponível
    const resumeBtn504 = card504.getByRole('button', { name: 'Retomar' })
    await resumeBtn504.waitFor({ timeout: 3000 })
    assert.equal(await resumeBtn504.isEnabled(), true, 'Botão Retomar do lote deve estar habilitado após releitura')

    const shot1 = path.join(outDir, '01_gestora_publicar_timeout_tentativa_sem_confirmacao.png')
    await catalogSection.screenshot({ path: shot1 })
    report.screenshots.push(shot1)

    report.assertions.push('Caso 6 (Contrato B): Erro HTTP 504 de transporte/timeout na chamada de execução do canal exibido com toast de erro, releitura via finally, contadores separados (1 criação, 1 execução), lote exibido como PARTIAL com item confirmado e item em "Tentativa sem confirmação".')

    mockState.failExecutionWithTimeout = false

    // =========================================================================
    // CASO 6 (CONTRATO A): AÇÃO EXECUTAR CONTRA CONTRATO HTTP 200/PARTIAL (EXCEÇÃO CAPTURADA)
    // =========================================================================
    console.log('[4/8] Caso 6 (Contrato A): Ação Executar contra contrato HTTP 200/PARTIAL (exceção externa capturada pelo executor)...')
    const cardCA = getBatchArticle(catalogSection, batchContractAPending.id)
    await cardCA.waitFor({ timeout: 5000 })
    const execBtnCA = cardCA.getByRole('button', { name: 'Executar' })
    await execBtnCA.waitFor({ timeout: 3000 })
    assert.equal(await execBtnCA.isEnabled(), true, 'Botão Executar deve estar habilitado')

    const rowBeautyCA = getItemRow(cardCA, 'Batom Matte Longa Duração')
    await rowBeautyCA.getByText('Pendente de envio').waitFor({ timeout: 3000 })

    // 2. Configura postExecuteHandler para a URL exata desse lote
    // Simula catalog_publisher.py: exceção externa capturada deixa itens em PENDING com attempt_count=1,
    // sem erro conclusivo nem provider_result_ref, conclui lote como PARTIAL e devolve HTTP 200 { batch, items }
    mockState.postExecuteHandler = (route) => {
      const reqUrl = route.request().url()
      if (reqUrl.includes(`/publications/${batchContractAPending.id}/execute`)) {
        batchContractAPending.status = 'PARTIAL'
        batchContractAPending.lease_token = null
        batchContractAPending.lease_expires_at = null
        batchContractAPending.items[0].status = 'PENDING'
        batchContractAPending.items[0].attempt_count = 1
        batchContractAPending.items[0].error_code = null
        batchContractAPending.items[0].error_message = null
        batchContractAPending.items[0].provider_result_ref = null
        return route.fulfill({
          status: 200,
          json: {
            batch: batchContractAPending,
            items: batchContractAPending.items,
          },
        })
      }
      return route.continue()
    }

    // 3. Registra espera da resposta correspondente ao POST correto antes do clique
    const executeResponsePromiseCA = gestoraPage.waitForResponse(async (response) => {
      const req = response.request()
      if (req.method() !== 'POST') return false
      if (!req.url().includes(`/channel-catalog/publications/${batchContractAPending.id}/execute`)) return false
      if (response.status() !== 200) return false
      try {
        const data = await response.json()
        return data && data.batch && data.batch.status === 'PARTIAL'
      } catch {
        return false
      }
    })

    // 5. Captura contadores após término do carregamento inicial e antes do clique
    const executeCountBeforeCA = mockState.executeCount
    const resumeCountBeforeCA = mockState.resumeCount
    const publishCountBeforeCA = mockState.publishCount
    const catalogGetCountBeforeCA = mockState.catalogGetCount
    const batchCountBeforeCA = mockState.batches.length

    // 6. Prova de controle determinístico de busy:
    // Retém a resposta do GET de atualização (refreshBacklog disparado no finally) até sinalização controlada
    let releaseCatalogReloadGateCA
    mockState.catalogReloadGate = new Promise((resolve) => {
      releaseCatalogReloadGateCA = resolve
    })

    // 4. Clica Executar pelo cartão identificado por data-batch-id
    await execBtnCA.click()

    // Confere que a resposta do POST execute foi recebida com HTTP 200 e batch.status == PARTIAL
    const execResponseCA = await executeResponsePromiseCA
    assert.equal(execResponseCA.status(), 200, 'POST execute deve responder HTTP 200')
    const execJsonCA = await execResponseCA.json()
    assert.equal(execJsonCA.batch.status, 'PARTIAL', 'batch.status no corpo do POST deve ser PARTIAL')

    // Confere que os controles de mutação estão desabilitados enquanto a releitura do catálogo está retida (busy ativo)
    assert.equal(await execBtnCA.isDisabled(), true, 'Botão deve estar desabilitado enquanto a leitura de atualização está retida (busy ativo)')

    // Libera a resposta do GET de atualização
    releaseCatalogReloadGateCA()
    mockState.catalogReloadGate = null

    // Aguarda a liberação dos controles e atualização da interface
    await cardCA.getByText('Parcial').waitFor({ timeout: 5000 })
    const resumeBtnCA = cardCA.getByRole('button', { name: 'Retomar' })
    await resumeBtnCA.waitFor({ timeout: 3000 })
    assert.equal(await resumeBtnCA.isEnabled(), true, 'Botão Retomar deve estar habilitado após liberação de busy')
    assert.equal(await cardCA.getByRole('button', { name: 'Executar' }).count(), 0, 'Botão Executar não deve mais existir')

    // Confere toast informativo
    await gestoraPage.getByText('Lote executado com pendências parciais.').waitFor({ timeout: 5000 })

    // Confere rótulo na linha do item correto: "Tentativa sem confirmação"
    await rowBeautyCA.getByText('Tentativa sem confirmação').waitFor({ timeout: 5000 })
    // Asserções negativas: esse item não pode exibir Confirmado, Rejeitado pelo canal ou Pendente de envio
    assert.equal(await rowBeautyCA.getByText('Confirmado').count(), 0, 'Item não pode exibir "Confirmado"')
    assert.equal(await rowBeautyCA.getByText('Rejeitado pelo canal').count(), 0, 'Item não pode exibir "Rejeitado pelo canal"')
    assert.equal(await rowBeautyCA.getByText('Pendente de envio').count(), 0, 'Item não pode exibir "Pendente de envio"')

    // Exige exatamente 1 POST de execução e 1 releitura GET, sem POST de criação/retomada e sem duplicar lote
    assert.equal(mockState.executeCount - executeCountBeforeCA, 1, 'Caso 6 (Contrato A): Exatamente um POST de execução')
    assert.equal(mockState.publishCount - publishCountBeforeCA, 0, 'Caso 6 (Contrato A): Nenhum POST de criação')
    assert.equal(mockState.resumeCount - resumeCountBeforeCA, 0, 'Caso 6 (Contrato A): Nenhum POST de retomada')
    assert.equal(mockState.catalogGetCount - catalogGetCountBeforeCA, 1, 'Caso 6 (Contrato A): Exatamente uma nova leitura do catálogo')
    assert.equal(mockState.batches.length, batchCountBeforeCA, 'Caso 6 (Contrato A): Ausência de duplicação de lotes')

    const shot6b = path.join(outDir, '06b_contrato_200_partial_capturado.png')
    await cardCA.screenshot({ path: shot6b })
    report.screenshots.push(shot6b)

    report.assertions.push('Caso 6 (Contrato A): Ação Executar contra contrato HTTP 200/PARTIAL (exceção externa capturada pelo executor) exercitada com waitForResponse do POST, controle determinístico de busy durante a releitura retida, toast informativo "Lote executado com pendências parciais.", transição do badge para Parcial com botão Retomar habilitado e linha do item exibindo exclusivamente "Tentativa sem confirmação" (sem Confirmado, Rejeitado pelo canal ou Pendente de envio).')

    mockState.postExecuteHandler = null

    // =========================================================================
    // FIXTURE DEDICADA: RENDERIZAÇÃO DE LOTE COM REJEIÇÃO CONCLUSIVA DE NEGÓCIO (BUSINESS_REJECTION)
    // =========================================================================
    console.log('Testando renderização de lote com rejeição conclusiva de negócio (BUSINESS_REJECTION)...')
    const batchBusinessRejection = {
      id: 'batch-business-rejection-demo',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PARTIAL',
      snapshot_version: 1,
      lease_token: null,
      lease_expires_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [
        {
          id: 'item-food-br-succeeded',
          batch_id: 'batch-business-rejection-demo',
          offer_id: 'off-food-1',
          status: 'SUCCEEDED',
          desired_version: 1,
          provider_operation_key: 'op-food-br',
          provider_result_ref: 'ref-br-succeeded',
          attempt_count: 1,
          error_code: null,
          error_message: null,
          product_name: 'Hambúrguer Artesanal Duplo',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          id: 'item-retail-br-failed',
          batch_id: 'batch-business-rejection-demo',
          offer_id: 'off-retail-1',
          status: 'FAILED',
          desired_version: 1,
          provider_operation_key: 'op-retail-br',
          provider_result_ref: 'ref-br-failed',
          attempt_count: 1,
          error_code: 'BUSINESS_REJECTION',
          error_message: 'Preço mínimo do canal violado',
          product_name: 'Furadeira de Impacto 500W',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    }
    mockState.batches.unshift(batchBusinessRejection)
    await gestoraPage.reload()

    const catalogSectionBR = getCatalogSection(gestoraPage)
    await catalogSectionBR.waitFor({ timeout: 15000 })
    const cardBR = getBatchArticle(catalogSectionBR, 'batch-business-rejection-demo')
    await cardBR.waitFor({ timeout: 5000 })

    const rowFoodBR = getItemRow(cardBR, 'Hambúrguer Artesanal Duplo')
    const rowRetailBR = getItemRow(cardBR, 'Furadeira de Impacto 500W')
    await rowFoodBR.getByText('Confirmado').waitFor({ timeout: 5000 })
    await rowRetailBR.getByText('Rejeitado pelo canal · BUSINESS_REJECTION').waitFor({ timeout: 5000 })

    const shot6c = path.join(outDir, '06c_renderizacao_rejeicao_negocio_business_rejection.png')
    await cardBR.screenshot({ path: shot6c })
    report.screenshots.push(shot6c)

    report.assertions.push('Renderização de rejeição conclusiva de negócio: Lote com item FAILED/BUSINESS_REJECTION exibe "Rejeitado pelo canal · BUSINESS_REJECTION" e item SUCCEEDED exibe "Confirmado".')

    // =========================================================================
    // CASO 2: EXECUTAR LOTE PENDING COM ERRO E RELEITURA PARA PROCESSING (DEFEITO 2)
    // =========================================================================
    console.log('[5/8] Caso 2: Executar lote PENDING com resposta de erro mas mudança de estado para PROCESSING no backend...')
    const batchPendingDef2 = {
      id: 'batch-pending-def2',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PENDING',
      snapshot_version: 1,
      lease_token: null,
      lease_expires_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [
        {
          id: 'item-def2-beauty',
          batch_id: 'batch-pending-def2',
          offer_id: 'off-beauty-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-def2-beauty',
          provider_result_ref: null,
          attempt_count: 0,
          error_code: null,
          error_message: null,
          product_name: 'Batom Matte Longa Duração',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    }
    mockState.batches.unshift(batchPendingDef2)
    await gestoraPage.reload()

    const catalogSectionDef2 = getCatalogSection(gestoraPage)
    await catalogSectionDef2.waitFor({ timeout: 15000 })
    const cardDef2 = getBatchArticle(catalogSectionDef2, 'batch-pending-def2')
    await cardDef2.waitFor({ timeout: 5000 })

    const execBtnDef2 = cardDef2.getByRole('button', { name: 'Executar' })
    await execBtnDef2.waitFor({ timeout: 3000 })

    const executeCallsBefore = mockState.executeCount
    const resumeCallsBeforeC2 = mockState.resumeCount
    const publishCallsBeforeC2 = mockState.publishCount
    const getCallsBefore = mockState.catalogGetCount
    const batchCountBeforeC2 = mockState.batches.length

    // Configura o handler de POST execute para simular persistência da Fase 1 (PROCESSING com lease)
    // seguida de erro antes da conclusão (Fase 3 quebra ou erro de transporte)
    mockState.postExecuteHandler = (route) => {
      // Modifica o estado do banco antes de responder erro
      batchPendingDef2.status = 'PROCESSING'
      batchPendingDef2.lease_token = 'lease-def2-active'
      batchPendingDef2.lease_expires_at = new Date(Date.now() + 60000).toISOString()
      batchPendingDef2.items[0].attempt_count = 1
      return route.fulfill({
        status: 500,
        json: { detail: 'Falha interna na Fase 3 após concessão de execução' },
      })
    }

    const executeResponsePromiseDef2 = gestoraPage.waitForResponse((res) => {
      return res.request().method() === 'POST' &&
             res.request().url().includes(`/channel-catalog/publications/${batchPendingDef2.id}/execute`) &&
             res.status() === 500
    })

    await execBtnDef2.click()
    const execResDef2 = await executeResponsePromiseDef2
    assert.equal(execResDef2.status(), 500)

    // 1. Toast de erro exibido
    await gestoraPage.getByText('Falha interna na Fase 3 após concessão de execução').waitFor({ timeout: 10000 })
    report.assertions.push('Caso 2: Toast de erro da execução exibido.')

    // 2. Releitura do catálogo acionada via finally (getCalls aumentou)
    assert.ok(mockState.catalogGetCount > getCallsBefore, 'Caso 2: Deve haver releitura via onChanged após falha na execução')

    // 3. Exatamente 1 POST execute (sem reenvio automático) e ausência de mutações indevidas
    assert.equal(mockState.executeCount - executeCallsBefore, 1, 'Caso 2: Exatamente um POST execute, sem repetição automática')
    assert.equal(mockState.publishCount - publishCallsBeforeC2, 0, 'Caso 2: Nenhum POST de criação')
    assert.equal(mockState.resumeCount - resumeCallsBeforeC2, 0, 'Caso 2: Nenhum POST de retomada')
    assert.equal(mockState.batches.length, batchCountBeforeC2, 'Caso 2: Ausência de duplicação de lote')

    // 4. Interface atualizou após a releitura: botão Executar sumiu, lote exibe status PROCESSING / Retomar
    await cardDef2.getByText('Em execução').waitFor({ timeout: 5000 })
    assert.equal(await cardDef2.getByRole('button', { name: 'Executar' }).count(), 0, 'Caso 2: Botão Executar não deve mais existir após releitura como PROCESSING')
    report.assertions.push('Caso 2: Releitura pós-erro atualizou o lote para PROCESSING e removeu o botão Executar sem reenvio duplicado (Defeito 2 resolvido).')

    const shot2b = path.join(outDir, '02b_executar_erro_recarrega_processing.png')
    await cardDef2.screenshot({ path: shot2b })
    report.screenshots.push(shot2b)

    mockState.postExecuteHandler = null

    // =========================================================================
    // CASO 3: RETOMAR LOTE PARTIAL COM ERRO E RELEITURA PARA PROCESSING (DEFEITO 2)
    // =========================================================================
    console.log('[6/8] Caso 3: Retomar lote PARTIAL com erro e releitura para PROCESSING...')
    const batchPartialResumeErr = {
      id: 'batch-resume-err-demo',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PARTIAL',
      snapshot_version: 1,
      lease_token: null,
      lease_expires_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [
        {
          id: 'item-resume-err-1',
          batch_id: 'batch-resume-err-demo',
          offer_id: 'off-food-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-resume-err-1',
          provider_result_ref: null,
          attempt_count: 1,
          error_code: null,
          error_message: null,
          product_name: 'Hambúrguer Artesanal Duplo',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    }
    mockState.batches.unshift(batchPartialResumeErr)
    await gestoraPage.reload()

    const catalogSectionResumeErr = getCatalogSection(gestoraPage)
    await catalogSectionResumeErr.waitFor({ timeout: 15000 })
    const cardResumeErr = getBatchArticle(catalogSectionResumeErr, 'batch-resume-err-demo')
    await cardResumeErr.waitFor({ timeout: 5000 })

    const resumeBtnErr = cardResumeErr.getByRole('button', { name: 'Retomar' })
    await resumeBtnErr.waitFor({ timeout: 3000 })

    const resumeCallsBefore = mockState.resumeCount
    const executeCallsBeforeC3 = mockState.executeCount
    const publishCallsBeforeC3 = mockState.publishCount
    const getCallsResumeBefore = mockState.catalogGetCount
    const batchCountBeforeC3 = mockState.batches.length

    // Simula erro na retomada mas após assumir lease e mudar status para PROCESSING
    mockState.postResumeHandler = (route) => {
      batchPartialResumeErr.status = 'PROCESSING'
      batchPartialResumeErr.lease_token = 'lease-resume-active'
      batchPartialResumeErr.lease_expires_at = new Date(Date.now() + 60000).toISOString()
      return route.fulfill({
        status: 500,
        json: { detail: 'Erro simulado durante a retomada do lote' },
      })
    }

    const resumeResponsePromiseC3 = gestoraPage.waitForResponse((res) => {
      return res.request().method() === 'POST' &&
             res.request().url().includes(`/channel-catalog/publications/${batchPartialResumeErr.id}/resume`) &&
             res.status() === 500
    })

    await resumeBtnErr.click()
    const resumeResC3 = await resumeResponsePromiseC3
    assert.equal(resumeResC3.status(), 500)

    await gestoraPage.getByText('Erro simulado durante a retomada do lote').waitFor({ timeout: 10000 })
    assert.ok(mockState.catalogGetCount > getCallsResumeBefore, 'Caso 3: Deve haver releitura via onChanged após falha na retomada')
    assert.equal(mockState.resumeCount - resumeCallsBefore, 1, 'Caso 3: Exatamente um POST resume')
    assert.equal(mockState.executeCount - executeCallsBeforeC3, 0, 'Caso 3: Nenhum POST execute')
    assert.equal(mockState.publishCount - publishCallsBeforeC3, 0, 'Caso 3: Nenhum POST publish')
    assert.equal(mockState.batches.length, batchCountBeforeC3, 'Caso 3: Ausência de duplicação de lote')

    // Após releitura, lote exibe status PROCESSING e item pendente em PROCESSING mostra "Em execução"
    await cardResumeErr.getByText('Em execução').first().waitFor({ timeout: 5000 })
    const itemRowResume = getItemRow(cardResumeErr, 'Hambúrguer Artesanal Duplo')
    await itemRowResume.getByText('Em execução').waitFor({ timeout: 5000 })
    report.assertions.push('Caso 3: Releitura pós-erro da retomada atualizou badge para PROCESSING e item para "Em execução".')

    const shot3b = path.join(outDir, '03b_retomar_erro_recarrega_processing.png')
    await cardResumeErr.screenshot({ path: shot3b })
    report.screenshots.push(shot3b)

    mockState.postResumeHandler = null

    // =========================================================================
    // CASO 4: RETOMADA COM RECUPERAÇÃO PARCIAL PERSISTIDA ANTES DO ERRO DE REENVIO
    // =========================================================================
    console.log('[7/8] Caso 4: Retomar com recuperação parcial já persistida (1 SUCCEEDED, 1 PENDING com attempt_count=0)...')
    const batchPartialRecovery = {
      id: 'batch-partial-recovery-persisted',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PARTIAL',
      snapshot_version: 1,
      lease_token: null,
      lease_expires_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [
        {
          id: 'item-recov-1',
          batch_id: 'batch-partial-recovery-persisted',
          offer_id: 'off-food-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-recov-1',
          provider_result_ref: null,
          attempt_count: 1,
          error_code: null,
          error_message: null,
          product_name: 'Hambúrguer Artesanal Duplo',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          id: 'item-recov-2',
          batch_id: 'batch-partial-recovery-persisted',
          offer_id: 'off-retail-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-recov-2',
          provider_result_ref: null,
          attempt_count: 0,
          error_code: null,
          error_message: null,
          product_name: 'Furadeira de Impacto 500W',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    }
    mockState.batches.unshift(batchPartialRecovery)
    await gestoraPage.reload()

    const catalogSectionRecov = getCatalogSection(gestoraPage)
    await catalogSectionRecov.waitFor({ timeout: 15000 })
    const cardRecov = getBatchArticle(catalogSectionRecov, 'batch-partial-recovery-persisted')
    await cardRecov.waitFor({ timeout: 5000 })

    const resumeBtnRecov = cardRecov.getByRole('button', { name: 'Retomar' })
    await resumeBtnRecov.waitFor({ timeout: 3000 })

    const resumeCallsBeforeRecov = mockState.resumeCount
    const executeCallsBeforeRecov = mockState.executeCount
    const publishCallsBeforeRecov = mockState.publishCount
    const getCallsBeforeRecov = mockState.catalogGetCount
    const batchCountBeforeRecov = mockState.batches.length

    // Simula: Etapa 3 da retomada persistiu item 1 como SUCCEEDED, mas Etapa 4 falhou na intenção de reenvio
    mockState.postResumeHandler = (route) => {
      batchPartialRecovery.items[0].status = 'SUCCEEDED'
      batchPartialRecovery.items[0].provider_result_ref = 'ref-recov-1-ok'
      // item 2 permaneceu PENDING com attempt_count = 0
      batchPartialRecovery.items[1].attempt_count = 0
      batchPartialRecovery.status = 'PARTIAL'
      batchPartialRecovery.lease_token = null
      batchPartialRecovery.lease_expires_at = null
      return route.fulfill({
        status: 500,
        json: { detail: 'Falha na auditoria de intenção do reenvio' },
      })
    }

    const resumeResponsePromiseC4 = gestoraPage.waitForResponse((res) => {
      return res.request().method() === 'POST' &&
             res.request().url().includes(`/channel-catalog/publications/${batchPartialRecovery.id}/resume`) &&
             res.status() === 500
    })

    await resumeBtnRecov.click()
    const resumeResC4 = await resumeResponsePromiseC4
    assert.equal(resumeResC4.status(), 500)

    await gestoraPage.getByText('Falha na auditoria de intenção do reenvio').waitFor({ timeout: 10000 })

    // Contadores comprovando ausência de reenvio automático e ausência de duplicação
    assert.equal(mockState.resumeCount - resumeCallsBeforeRecov, 1, 'Caso 4: Exatamente um POST de retomada')
    assert.equal(mockState.executeCount - executeCallsBeforeRecov, 0, 'Caso 4: Nenhum POST de execução')
    assert.equal(mockState.publishCount - publishCallsBeforeRecov, 0, 'Caso 4: Nenhum POST de criação')
    assert.ok(mockState.catalogGetCount > getCallsBeforeRecov, 'Caso 4: Releitura do catálogo acionada via finally')
    assert.equal(mockState.batches.length, batchCountBeforeRecov, 'Caso 4: Ausência de duplicação de lotes')

    // Confere liberação de busy
    assert.equal(await resumeBtnRecov.isEnabled(), true, 'Caso 4: Botão Retomar deve estar habilitado após releitura')

    // Releitura do catálogo mostra item 1 Confirmado e item 2 Pendente de envio
    const rowRecov1 = getItemRow(cardRecov, 'Hambúrguer Artesanal Duplo')
    const rowRecov2 = getItemRow(cardRecov, 'Furadeira de Impacto 500W')
    await rowRecov1.getByText('Confirmado').waitFor({ timeout: 5000 })
    await rowRecov2.getByText('Pendente de envio').waitFor({ timeout: 5000 })
    report.assertions.push('Caso 4: Releitura pós-erro de recuperação parcial mostra item 1 como "Confirmado" e item 2 como "Pendente de envio", com contadores conferidos (sem reenvio automático e sem duplicação de lote).')

    const shot4b = path.join(outDir, '04b_retomada_parcial_persistida_confirmado_e_pendente.png')
    await cardRecov.screenshot({ path: shot4b })
    report.screenshots.push(shot4b)

    mockState.postResumeHandler = null

    // =========================================================================
    // CASO 5: FALHA NA RELEITURA DE ATUALIZAÇÃO LIBERA CONTROLE DE BUSY
    // =========================================================================
    console.log('[8/8] Caso 5: Falha na releitura de atualização libera controle de busy sem deadlock...')
    mockState.failCatalogReload = true
    const resumeBtnBusyTest = cardRecov.getByRole('button', { name: 'Retomar' })
    await resumeBtnBusyTest.waitFor({ timeout: 3000 })

    const resumeCallsBeforeC5 = mockState.resumeCount
    const executeCallsBeforeC5 = mockState.executeCount
    const publishCallsBeforeC5 = mockState.publishCount
    const getCallsBeforeC5 = mockState.catalogGetCount
    const batchCountBeforeC5 = mockState.batches.length

    const reloadResponsePromiseC5 = gestoraPage.waitForResponse((res) => {
      return res.request().method() === 'GET' &&
             res.request().url().includes('/channel-catalog/catalog') &&
             res.status() === 500
    })

    await resumeBtnBusyTest.click()
    const reloadResC5 = await reloadResponsePromiseC5
    assert.equal(reloadResC5.status(), 500)

    // O toast de erro da falha na releitura deve ser exibido
    await gestoraPage.getByText(/Erro temporário de banco ao consultar catálogo|Falha ao atualizar situação do catálogo/i).waitFor({ timeout: 10000 })

    // Contadores comprovando ausência de reenvio automático e ausência de duplicação
    assert.equal(mockState.resumeCount - resumeCallsBeforeC5, 1, 'Caso 5: Exatamente 1 POST de retomada')
    assert.equal(mockState.executeCount - executeCallsBeforeC5, 0, 'Caso 5: Nenhum POST de execução')
    assert.equal(mockState.publishCount - publishCallsBeforeC5, 0, 'Caso 5: Nenhum POST de criação')
    assert.ok(mockState.catalogGetCount > getCallsBeforeC5, 'Caso 5: Tentativa de releitura do catálogo executada')
    assert.equal(mockState.batches.length, batchCountBeforeC5, 'Caso 5: Ausência de duplicação de lotes')

    // busy deve ser liberado! O botão não pode ficar desabilitado por causa de loading
    assert.equal(await resumeBtnBusyTest.isEnabled(), true, 'Caso 5: Botão Retomar deve estar habilitado e sem lock de busy após erro de releitura')
    report.assertions.push('Caso 5: Falha na releitura de atualização tratada com toast, contadores conferidos (sem reenvio automático e sem duplicação) e busy liberado sem deadlock.')

    const shot5b = path.join(outDir, '05b_falha_releitura_libera_busy.png')
    await cardRecov.screenshot({ path: shot5b })
    report.screenshots.push(shot5b)

    mockState.failCatalogReload = false

    // =========================================================================
    // CASO 8A: RETOMADA CONCORRENTE COM LEASE ATIVO (409) VS EXPIRADO (200)
    // =========================================================================
    console.log('Testando retomada de lote PROCESSING com lease ativo (409) vs lease expirado...')
    const processingBatch = {
      id: 'batch-proc-demo',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PROCESSING',
      snapshot_version: 1,
      lease_token: 'lease-active-xyz',
      lease_expires_at: new Date(Date.now() + 60000).toISOString(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [
        {
          id: 'item-proc-1',
          batch_id: 'batch-proc-demo',
          offer_id: 'off-retail-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-retail-proc',
          provider_result_ref: null,
          attempt_count: 1,
          error_code: null,
          error_message: null,
          product_name: 'Furadeira de Impacto 500W',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    }
    mockState.batches.unshift(processingBatch)
    mockState.leaseActive = true
    await gestoraPage.reload()

    const catalogSectionProc = getCatalogSection(gestoraPage)
    await catalogSectionProc.waitFor({ timeout: 15000 })
    const cardProc = getBatchArticle(catalogSectionProc, 'batch-proc-demo')
    await cardProc.waitFor({ timeout: 5000 })

    const resumeBtnProc = cardProc.getByRole('button', { name: 'Retomar' })
    await resumeBtnProc.waitFor({ timeout: 3000 })
    await resumeBtnProc.click()

    await gestoraPage.getByText('Lote em execução por outro processo (lease ativo até 2026-10-02T10:45:00Z)').waitFor({ timeout: 10000 })
    report.assertions.push('Caso 8: Tentativa de retomada sob lease ativo resulta em 409 tratado com aviso em tela.')

    const shot3 = path.join(outDir, '03_retomada_concorrente_409_lease_ativo.png')
    await cardProc.screenshot({ path: shot3 })
    report.screenshots.push(shot3)

    // Agora simula expiração do lease: retomada é permitida e sucede
    mockState.leaseActive = false
    await resumeBtnProc.click()
    await gestoraPage.getByText('Lote retomado e confirmado com sucesso.').waitFor({ timeout: 10000 })
    report.assertions.push('Caso 8: Retomada após expiração de lease confirmada com sucesso.')

    const shot4 = path.join(outDir, '04_retomada_lease_expirado_sucesso.png')
    await cardProc.screenshot({ path: shot4 })
    report.screenshots.push(shot4)

    // =========================================================================
    // CASO 7: CONEXÃO SUSPENDED E CONNECTED SEM CATALOG_PUBLICATION
    // =========================================================================
    console.log('Caso 7: Testando conexão SUSPENDED e CONNECTED sem CATALOG_PUBLICATION para Publicar, Executar e Retomar...')
    // Prepara lotes na fixture para garantir que Executar e Retomar também estejam presentes
    const batchPendingForDisabledTest = {
      id: 'batch-pending-disabled-test',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PENDING',
      snapshot_version: 1,
      lease_token: null,
      lease_expires_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [
        {
          id: 'item-pending-dt',
          batch_id: 'batch-pending-disabled-test',
          offer_id: 'off-beauty-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-dt-beauty',
          provider_result_ref: null,
          attempt_count: 0,
          error_code: null,
          error_message: null,
          product_name: 'Batom Matte Longa Duração',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    }
    const batchPartialForDisabledTest = {
      id: 'batch-partial-disabled-test',
      tenant_id: 'tenant-test-1',
      store_id: 'store-test-1',
      merchant_connection_id: 'conn-test-1',
      status: 'PARTIAL',
      snapshot_version: 1,
      lease_token: null,
      lease_expires_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [
        {
          id: 'item-partial-dt',
          batch_id: 'batch-partial-disabled-test',
          offer_id: 'off-retail-1',
          status: 'PENDING',
          desired_version: 1,
          provider_operation_key: 'op-dt-retail',
          provider_result_ref: null,
          attempt_count: 1,
          error_code: null,
          error_message: null,
          product_name: 'Furadeira de Impacto 500W',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    }
    mockState.batches.unshift(batchPendingForDisabledTest, batchPartialForDisabledTest)

    // 7A: Conexão SUSPENDED
    mockState.connectionStatus = 'SUSPENDED'
    mockState.connectionCapabilities = ['CATALOG_PUBLICATION', 'ORDER_INGRESS']
    await gestoraPage.reload()

    const catalogSuspended = getCatalogSection(gestoraPage)
    await catalogSuspended.waitFor({ timeout: 15000 })
    await catalogSuspended.scrollIntoViewIfNeeded()

    const warningBanner = catalogSuspended.getByText('Conexão não está ativa ou conector não suporta publicação de catálogo neste ambiente. Ações de envio, execução e retomada ficam desabilitadas.')
    await warningBanner.waitFor({ timeout: 5000 })

    const publishBtnSuspended = catalogSuspended.getByRole('button', { name: /Publicar/ })
    const cardPendingSusp = getBatchArticle(catalogSuspended, 'batch-pending-disabled-test')
    const executeBtnSuspended = cardPendingSusp.getByRole('button', { name: 'Executar' })
    const cardPartialSusp = getBatchArticle(catalogSuspended, 'batch-partial-disabled-test')
    const resumeBtnSuspended = cardPartialSusp.getByRole('button', { name: 'Retomar' })

    const expectedTitle = 'Conexão não está ativa ou conector não suporta publicação de catálogo neste ambiente'

    // Confere presença, disabled e title individualmente para os três botões
    assert.equal(await publishBtnSuspended.count(), 1, 'Publicar deve estar presente em SUSPENDED')
    assert.equal(await publishBtnSuspended.isDisabled(), true, 'Publicar deve estar desabilitado em SUSPENDED')
    assert.equal(await publishBtnSuspended.getAttribute('title'), expectedTitle, 'Publicar deve ter tooltip explicativo')

    assert.equal(await executeBtnSuspended.count(), 1, 'Executar deve estar presente em SUSPENDED')
    assert.equal(await executeBtnSuspended.isDisabled(), true, 'Executar deve estar desabilitado em SUSPENDED')
    assert.equal(await executeBtnSuspended.getAttribute('title'), expectedTitle, 'Executar deve ter tooltip explicativo')

    assert.equal(await resumeBtnSuspended.count(), 1, 'Retomar deve estar presente em SUSPENDED')
    assert.equal(await resumeBtnSuspended.isDisabled(), true, 'Retomar deve estar desabilitado em SUSPENDED')
    assert.equal(await resumeBtnSuspended.getAttribute('title'), expectedTitle, 'Retomar deve ter tooltip explicativo')

    // Prova de 0 mutações ao clicar nos botões desabilitados
    const mutationsBeforeSusp = mockState.publishCount + mockState.executeCount + mockState.resumeCount
    await publishBtnSuspended.click({ force: true }).catch(() => {})
    await executeBtnSuspended.click({ force: true }).catch(() => {})
    await resumeBtnSuspended.click({ force: true }).catch(() => {})
    assert.equal(mockState.publishCount + mockState.executeCount + mockState.resumeCount, mutationsBeforeSusp, 'Nenhuma chamada de mutação com conexão SUSPENDED')

    report.assertions.push('Caso 7: Conexão SUSPENDED exibe banner e desabilita Publicar, Executar e Retomar com tooltip explicativo e 0 chamadas.')

    const shot5 = path.join(outDir, '05_conexao_suspended_acoes_desabilitadas.png')
    await catalogSuspended.screenshot({ path: shot5 })
    report.screenshots.push(shot5)

    // 7B: Conexão CONNECTED mas sem capacidade CATALOG_PUBLICATION
    mockState.connectionStatus = 'CONNECTED'
    mockState.connectionCapabilities = ['ORDER_INGRESS']
    await gestoraPage.reload()

    const catalogNoCap = getCatalogSection(gestoraPage)
    await catalogNoCap.waitFor({ timeout: 15000 })
    await catalogNoCap.scrollIntoViewIfNeeded()

    await catalogNoCap.getByText('Conexão não está ativa ou conector não suporta publicação de catálogo neste ambiente. Ações de envio, execução e retomada ficam desabilitadas.').waitFor({ timeout: 5000 })

    const publishBtnNoCap = catalogNoCap.getByRole('button', { name: /Publicar/ })
    const cardPendingNoCap = getBatchArticle(catalogNoCap, 'batch-pending-disabled-test')
    const executeBtnNoCap = cardPendingNoCap.getByRole('button', { name: 'Executar' })
    const cardPartialNoCap = getBatchArticle(catalogNoCap, 'batch-partial-disabled-test')
    const resumeBtnNoCap = cardPartialNoCap.getByRole('button', { name: 'Retomar' })

    assert.equal(await publishBtnNoCap.isDisabled(), true, 'Publicar deve estar desabilitado sem CATALOG_PUBLICATION')
    assert.equal(await publishBtnNoCap.getAttribute('title'), expectedTitle)

    assert.equal(await executeBtnNoCap.isDisabled(), true, 'Executar deve estar desabilitado sem CATALOG_PUBLICATION')
    assert.equal(await executeBtnNoCap.getAttribute('title'), expectedTitle)

    assert.equal(await resumeBtnNoCap.isDisabled(), true, 'Retomar deve estar desabilitado sem CATALOG_PUBLICATION')
    assert.equal(await resumeBtnNoCap.getAttribute('title'), expectedTitle)

    const mutationsBeforeNoCap = mockState.publishCount + mockState.executeCount + mockState.resumeCount
    await publishBtnNoCap.click({ force: true }).catch(() => {})
    await executeBtnNoCap.click({ force: true }).catch(() => {})
    await resumeBtnNoCap.click({ force: true }).catch(() => {})
    assert.equal(mockState.publishCount + mockState.executeCount + mockState.resumeCount, mutationsBeforeNoCap, 'Nenhuma chamada de mutação sem capacidade')

    report.assertions.push('Caso 7: Conexão CONNECTED sem CATALOG_PUBLICATION desabilita Publicar, Executar e Retomar com tooltip e 0 chamadas.')

    const shot6 = path.join(outDir, '06_conexao_sem_capacidade_acoes_desabilitadas.png')
    await catalogNoCap.screenshot({ path: shot6 })
    report.screenshots.push(shot6)

    await gestoraContext.close()

    // =========================================================================
    // CASO 8B: LEITORA SEM PERMISSÃO DE AÇÃO (RBAC)
    // =========================================================================
    console.log('Caso 8B: Abrindo sessão da Leitora (sem channel.catalog.manage)...')
    mockState.connectionStatus = 'CONNECTED'
    mockState.connectionCapabilities = ['CATALOG_PUBLICATION', 'ORDER_INGRESS']

    const leitoraContext = await browser.newContext({ viewport: { width: 1280, height: 900 } })
    const leitoraPage = await leitoraContext.newPage()

    await leitoraPage.route('**/api/v1/**', async (route) => {
      const url = route.request().url()
      if (url.includes('/capabilities/effective')) {
        return route.fulfill({
          status: 200,
          json: {
            catalog: {},
            delivery_orders: {},
            channel_hub: {},
            permissions: [
              'channel.view',
              // channel.catalog.manage e channel.manage OMITIDAS
            ],
          },
        })
      }

      if (url.includes('/channels/connections')) {
        return route.fulfill({ status: 200, json: [getCatalogPayload().connections[0]] })
      }

      if (url.includes('/channel-catalog/catalog')) {
        return route.fulfill({ status: 200, json: getCatalogPayload() })
      }

      if (url.includes('settlements')) {
        return route.fulfill({ status: 200, json: [] })
      }

      return route.fulfill({ status: 200, json: [] })
    })

    await leitoraPage.goto(appUrl)
    const leitoraSection = getCatalogSection(leitoraPage)
    await leitoraSection.waitFor({ timeout: 15000 })
    await leitoraSection.scrollIntoViewIfNeeded()

    // 1. Confere visualização livre dos dados
    await leitoraSection.getByText('Hambúrguer Artesanal Duplo').first().waitFor()
    await leitoraSection.getByText('Furadeira de Impacto 500W').first().waitFor()
    await leitoraSection.getByText('Batom Matte Longa Duração').first().waitFor()
    report.assertions.push('Caso 8B: Leitora visualiza dados do catálogo e histórico de lotes livremente.')

    // 2. Confere ausência total de botões de mutação
    const actionButtons = [
      leitoraSection.getByRole('button', { name: /Publicar/ }),
      leitoraSection.getByRole('button', { name: 'Retomar' }),
      leitoraSection.getByRole('button', { name: 'Executar' }),
      leitoraSection.getByRole('button', { name: 'Nova oferta' }),
      leitoraSection.getByRole('button', { name: 'Vincular código' }),
    ]
    for (const btn of actionButtons) {
      assert.equal(await btn.count(), 0, 'Leitora não pode ter botões de ação')
    }

    // 3. Ausência de checkboxes para seleção
    const checkboxes = leitoraSection.locator('input[type="checkbox"]')
    assert.equal(await checkboxes.count(), 0, 'Leitora não pode ter checkboxes de seleção')
    report.assertions.push('Caso 8B: Ausência estrita de botões de mutação e controles de seleção para leitora.')

    const shot7 = path.join(outDir, '07_leitora_somente_leitura.png')
    await leitoraSection.screenshot({ path: shot7 })
    report.screenshots.push(shot7)

    await leitoraContext.close()
    console.log('--- Travessia Playwright concluída com sucesso! ---')

    report.finished_at = new Date().toISOString()
    report.status = 'SUCCESS'
    fs.writeFileSync(path.join(outDir, 'walkthrough_report.json'), JSON.stringify(report, null, 2), 'utf8')
    console.log(`Relatório gravado em: ${path.join(outDir, 'walkthrough_report.json')}`)
  } finally {
    await browser.close()
    server.kill()
  }
}

run().catch((err) => {
  console.error('Erro na travessia Playwright:', err)
  process.exit(1)
})
