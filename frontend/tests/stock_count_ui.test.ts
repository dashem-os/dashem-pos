import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import {
  DESTINATIONS_FOR_CONDITION, countPreview, defaultDestination, returnEffect,
} from '../src/domain/stockMovements.ts'

/**
 * Contar estoque informa o total encontrado; o servidor calcula a diferença.
 *
 * A prévia é o que permite decidir sem fazer a conta de cabeça. Ela não é
 * autoridade — ao confirmar, o servidor verifica se o saldo mudou — mas precisa
 * dizer a mesma coisa que vai acontecer.
 */

test('a prévia mostra o que foi contado, o que havia e a diferença', () => {
  assert.equal(
    countPreview(10, 12),
    'Você contou 10 un. O sistema registra 12 un. Diferença: −2 un.',
  )
  assert.equal(
    countPreview(15, 12),
    'Você contou 15 un. O sistema registra 12 un. Diferença: +3 un.',
  )
})

test('contar zero é uma contagem, e a prévia diz o que vai sair', () => {
  assert.equal(
    countPreview(0, 4),
    'Você contou 0 un. O sistema registra 4 un. Diferença: −4 un.',
  )
})

test('contagem que bate não promete movimento nenhum', () => {
  const frase = countPreview(9, 9)
  assert.match(frase, /Confere/)
  assert.match(frase, /sem movimentar estoque/)
  assert.doesNotMatch(frase, /Diferença/)
})

test('a prévia respeita a unidade da mercadoria', () => {
  assert.match(countPreview(2.5, 3, 'kg'), /Você contou 2\.5 kg/)
})

const inventory = readFileSync(
  join(import.meta.dirname, '..', 'src', 'components', 'management', 'InventoryManager.tsx'),
  'utf8',
)

test('a tela manda a versão que a pessoa tinha à vista', () => {
  // E não uma versão inventada: enquanto o saldo não chega, `countBase` é nulo,
  // e nem o envio nem o botão aceitam substituto. Antes o `?? 0` mandava zero
  // por conta própria, e a pessoa levava um conflito que não causou.
  assert.match(inventory, /expected_version: countBase\.version/)
  assert.doesNotMatch(inventory, /countBase\?\.version \?\? 0/)
  assert.match(inventory, /counted === '' \|\| countBase === null/)
})

test('saldo ainda não lido não é exibido como zero', () => {
  // A instância hiberna: essa espera pode durar quase um minuto, e um "0 UN"
  // afirmado nesse intervalo é um número que ninguém verificou.
  assert.match(inventory, /countBase === null \? \(/)
  assert.match(inventory, /Lendo o saldo registrado/)
  assert.doesNotMatch(inventory, /Number\(countBase\?\.quantity \?\? 0\)/)
})

test('o conflito preserva o que foi digitado e pede nova conferência', () => {
  // Nada de setCounted('') no caminho do 409: o número contado permanece.
  const conflito = inventory.slice(inventory.indexOf('reason.status === 409'))
  const ateOFim = conflito.slice(0, conflito.indexOf('} finally'))
  assert.doesNotMatch(ateOFim, /setCounted\(''\)/)
  assert.doesNotMatch(ateOFim, /setCounting\(null\)/)
  assert.match(ateOFim, /setCountConflict\(reason\.message\)/)
  assert.match(ateOFim, /fetchInventoryBalance/)
  // E não reenvia sozinho com a versão nova: quem confirma é a pessoa.
  assert.doesNotMatch(ateOFim, /countStock\(/)
})

test('depois do conflito, confirmar exige um ato deliberado', () => {
  // Reler o saldo não pode transformar a contagem antiga em confirmação válida:
  // sem isto, um clique mandaria o número contado antes da movimentação contra
  // a versão recém-lida, que é a aceitação silenciosa que a versão impede.
  assert.match(inventory, /const \[recounted, setRecounted\] = useState\(false\)/)
  assert.match(inventory, /setCountConflict\(reason\.message\)\s+setRecounted\(false\)/)
  assert.match(inventory, /disabled=\{busy \|\| countBase === null \|\| counted === '' \|\| \(Boolean\(countConflict\) && !recounted\)\}/)
  assert.match(inventory, /Voltei à prateleira/)
})

test('a tela de estoque lê o acervo físico, não o catálogo vendável', () => {
  // Publicação decide onde o item pode ser vendido; não decide se ele existe na
  // prateleira. Ler `products` do contexto escondia do estoque a mercadoria que
  // ninguém tinha publicado ainda.
  assert.match(inventory, /api\.fetchStockHoldings\(headers, store\.id\)/)
  assert.doesNotMatch(inventory, /products\.filter/)
})

test('os indicadores não somam grandezas incompatíveis', () => {
  // Quilo, litro e unidade num número só produzem um total que não é de nada.
  assert.doesNotMatch(inventory, /reduce\(\(sum, item\) => sum \+ Number\(item\.quantity\)/)
  // Os três contadores viraram uma faixa que conclui (ADR-034): o que ela conta
  // continua sendo quantas mercadorias, nunca quanto de mercadoria.
  assert.match(inventory, /acompanhados/)
  assert.match(inventory, /sem estoque/)
  assert.match(inventory, /precisam? de atenção/)
})

test('o resumo obedece ao pior risco, não à média', () => {
  // Um item em falta entre cem saudáveis não pode virar "tudo regular".
  const resumo = inventory.slice(inventory.indexOf('function Resumo'))
  // O contador lê o que a BUSCA deixou, não o que o filtro de atenção deixou.
  // Se lesse `filtered`, ligar o filtro faria o número virar o total dele
  // mesmo — "6 precisam de atenção · 6 acompanhados" — e desligar mudaria o
  // número sem nada ter mudado no estoque.
  assert.match(inventory, /requiringAction\(buscados\)/)
  assert.doesNotMatch(inventory, /requiringAction\(filtered\)/)
  assert.match(resumo, /exigindoAcao === 0/)
  assert.match(resumo, /Estoque saudável/)
  assert.match(resumo, /Nenhum item requer ação agora/)
})

test('o conflito relê também a lista atrás do formulário', () => {
  const handler = inventory.slice(inventory.indexOf('const submitCount'))
  const conflito = handler.slice(handler.indexOf('reason.status === 409'), handler.indexOf('} else {'))
  assert.match(conflito, /await load\(\)/)
})

test('falha de carregamento não se passa por prateleira vazia', () => {
  assert.match(inventory, /setLoadError\(true\)/)
  assert.match(inventory, /Tentar novamente/)
})

test('produto sem referência definida não é chamado de saudável', () => {
  assert.match(inventory, /Sem referência/)
})

test('a tela não tem regra própria de situação', () => {
  // A regra vive em `domain/stockSituation` e é a mesma para a linha e para o
  // resumo — foi tê-la em dois lugares que fez o topo contar o mesmo item duas
  // vezes. Aqui só se verifica que a tela consome a regra, e a regra tem teste
  // próprio em `stock_situation.test.ts`.
  assert.match(inventory, /stockSituation\(item\)/)
  assert.match(inventory, /Atenção · folga de/)
})

test('a ação de contar só aparece para quem tem a permissão de contar', () => {
  // Contar saiu da linha e foi para o menu de ações (ADR-034); o portão é o
  // mesmo, e continua sendo a permissão.
  assert.match(inventory, /canCount = permissions\.includes\('inventory\.count'\)/)
  assert.match(inventory, /\{canCount && \(\s*<RowAction/)
})


/**
 * Devolver mercadoria: a condição é o que a pessoa observa, o destino é a
 * consequência. Mercadoria imprópria não volta ao saldo vendável.
 */

const sales = readFileSync(
  join(import.meta.dirname, '..', 'src', 'components', 'management', 'SalesHistory.tsx'),
  'utf8',
)

test('mercadoria em condição de venda só tem um destino', () => {
  assert.deepEqual(DESTINATIONS_FOR_CONDITION.RESALEABLE, ['SELLABLE_STOCK'])
  assert.equal(defaultDestination('RESALEABLE'), 'SELLABLE_STOCK')
})

test('mercadoria imprópria nunca oferece o saldo vendável como destino', () => {
  assert.ok(!DESTINATIONS_FOR_CONDITION.UNFIT.includes('SELLABLE_STOCK'))
  assert.deepEqual(DESTINATIONS_FOR_CONDITION.UNFIT, ['QUARANTINE', 'DISCARD'])
})

test('a tela diz o que vai acontecer com a mercadoria', () => {
  assert.match(returnEffect('RESALEABLE', 'SELLABLE_STOCK'), /volta ao saldo disponível/)
  assert.match(returnEffect('UNFIT', 'QUARANTINE'), /não entra no saldo de venda/)
  assert.match(returnEffect('UNFIT', 'DISCARD'), /não entra no saldo de venda/)
})

test('trocar a condição leva junto um destino coerente', () => {
  assert.match(sales, /destination: defaultDestination\(condition\)/)
})

test('a devolução parte do item da venda, não do produto solto', () => {
  assert.match(sales, /sale_item_id: returning\.saleItemId/)
})

test('a recusa do servidor fica na tela com o formulário aberto', () => {
  const handler = sales.slice(sales.indexOf('const submitReturn'))
  const corpo = handler.slice(0, handler.indexOf('finally'))
  assert.ok(corpo.indexOf('catch') < corpo.indexOf("showToast('error'"))
  // Nada de fechar o formulário no catch: a recusa explica o limite.
  const doCatch = corpo.slice(corpo.indexOf('catch'))
  assert.doesNotMatch(doCatch, /setReturning\(null\)/)
})


/**
 * Achados da revisão consolidada da branch, fixados para não voltarem.
 */

const catalog = readFileSync(
  join(import.meta.dirname, '..', 'src', 'components', 'management', 'CatalogManager.tsx'),
  'utf8',
)

test('a chave de idempotência sobrevive ao reenvio', () => {
  // Gerar uma nova a cada clique torna a guarda do servidor inalcançável: a
  // resposta perdida seguida de novo envio chega como comando diferente.
  assert.match(inventory, /const \[countKey, setCountKey\] = useState\(''\)/)
  assert.match(inventory, /await api\.countStock\(headers, countKey,/)
  assert.match(sales, /const \[returnKey, setReturnKey\] = useState\(''\)/)
  assert.match(sales, /returnKey,/)
  // O caminho de sucesso usa a chave que veio da abertura, sem inventar outra.
  const envio = inventory.slice(inventory.indexOf('const submitCount'))
  const ateOCatch = envio.slice(0, envio.indexOf('} catch (reason)'))
  assert.doesNotMatch(ateOCatch, /randomUUID/)
})

test('depois do conflito a chave muda, porque o comando mudou', () => {
  // Reaproveitar a chave ali seria reenviar um comando já recusado com outra
  // versão esperada — e o servidor a trataria como conteúdo diferente, que é
  // justamente a recusa que ele dá para chave reusada.
  const envio = inventory.slice(inventory.indexOf('const submitCount'))
  const conflito = envio.slice(envio.indexOf('reason.status === 409'), envio.indexOf('} else {'))
  assert.match(conflito, /setCountKey\(`count-\$\{counting\.product_id\}-\$\{crypto\.randomUUID\(\)\}`\)/)
})

test('o formulário de contagem não abre mostrando o saldo do produto anterior', () => {
  const abertura = inventory.slice(inventory.indexOf('const openCount'))
  const corpo = abertura.slice(0, abertura.indexOf('const submitCount'))
  assert.ok(corpo.indexOf('setCountBase(null)') < corpo.indexOf('await api.fetchInventoryBalance'))
})

test('configurar mínimo não passa por movimentação', () => {
  // Exigência do plano: "configurar mínimo tem ação independente: não obrigar
  // movimentação fictícia". Enquanto o campo do mínimo viveu no formulário de
  // entrada, definir uma política exigia informar uma quantidade recebida — e
  // quantidade recebida que não chegou é saldo errado.
  for (const fonte of [inventory, catalog]) {
    // Recortado no próprio handler: o que vem depois dele é outra operação.
    const envio = fonte.slice(fonte.indexOf('const salvarMinimo'))
    const corpo = envio.slice(0, envio.indexOf('\n  const '))
    assert.match(corpo, /setMinimumStock\(/)
    // A operação de configuração não movimenta: nada de `adjustStock` nem de
    // tipo de movimento no caminho de salvar o mínimo.
    assert.doesNotMatch(corpo, /adjustStock\(/)
    assert.doesNotMatch(corpo, /PURCHASE|LOSS|ADJUSTMENT/)
  }
})

test('o formulário de movimentação não carrega configuração', () => {
  const envio = inventory.slice(inventory.indexOf('const submit = async'))
  const corpo = envio.slice(0, envio.indexOf('// -------'))
  assert.doesNotMatch(corpo, /setMinimumStock\(/)
  assert.doesNotMatch(corpo, /showToast\('success'/)
  const ajuste = catalog.slice(catalog.indexOf('const handleAdjustStock'))
  assert.doesNotMatch(ajuste.slice(0, ajuste.indexOf('const handleQuickAccess')), /setMinimumStock\(/)
})

test('a lista oferece a ação que a leitura exige', () => {
  // Diagnóstico sem remédio é o defeito: onde a tela diz que falta referência,
  // existe caminho para defini-la. No Estoque ela vive no menu de ações; em
  // Produtos, ao lado do número.
  for (const fonte of [inventory, catalog]) {
    assert.match(fonte, /abrirMinimo\(/)
  }
  // Nas duas telas a configuração vive no menu de ações, com o mesmo nome.
  for (const fonte of [inventory, catalog]) {
    assert.match(fonte, /Definir estoque de referência/)
  }
})

test('a garantia do mínimo é comportamento, não texto na tela', () => {
  // O formulário mostra o saldo atual e pede a quantidade. Ele não se explica:
  // a garantia de que nada é movimentado está no caminho da operação, provado
  // em `verificar_minimo.py` contra o banco, e o aviso de conclusão diz o
  // resultado em uma linha.
  for (const fonte of [inventory, catalog]) {
    assert.match(fonte, /Em estoque agora/)
    assert.doesNotMatch(fonte, /nenhuma entrada, perda ou contagem é registrada/)
    assert.match(fonte, /nenhum movimento foi criado/)
  }
})

test('a falha ao salvar o mínimo fica no formulário', () => {
  for (const fonte of [inventory, catalog]) {
    assert.match(fonte, /setMinimoErro\(/)
    assert.match(fonte, /\{minimoErro\}/)
  }
})

test('nenhuma tela oferece o ajuste assinado que a rota comum recusa', () => {
  for (const fonte of [inventory, catalog]) {
    assert.doesNotMatch(fonte, /<option value="ADJUSTMENT"/)
    assert.doesNotMatch(fonte, /<option value="RETURN"/)
  }
})
