# Etapa 1 do plano de estoque — levantamento, reprodução e correção

Estado: **PARCIAL**. O que falta está na seção "O que ainda não está fechado".

Referência: [plano corretivo de estoque e almoxarifado](../product/inventory-operational-correction-plan.md).
Data: 06–07/09/2026. Ambiente: **desenvolvimento local**. Nenhum dado de produção
foi lido ou alterado.

Esta etapa responde a uma pergunta só: **recebi, vendi ou perdi — quanto ficou?**
Ela não responde *quando* nem *quanto* comprar. Nada aqui calcula ponto de
reposição, estoque de segurança, lote econômico ou previsão de demanda; corrigir
a integridade do movimento não é entregar planejamento de reposição, e este
documento não deve ser lido como se fosse.

## Registro exigido antes da etapa 1

### Commit-base

`07ae804` — *Merge pull request #8 from dashem-os/team-operational-journey*,
06/09/2026 21:31 −03. Todo o levantamento e toda a reprodução abaixo foram
feitos sobre ele.

### Caminhos de fechamento de venda que deveriam tocar estoque

| Caminho | Onde | Chama estoque? |
|---|---|---|
| Venda direta quitada | `payment_service.confirm_payment` → `SaleStatusEnum.PAID` | **Sim**, item a item, para item com `tracks_inventory_snapshot` |
| Finalização de negociação | `negotiation_service.finalize_negotiation` cria a `Sale` já `PAID`/`COMPLETED` | **Não. Nenhuma chamada de estoque existe nesse caminho** |

**Corrigido em 07/09/2026.** O primeiro registro deste documento tratou o caso
como bloqueio, por leitura errada do ADR-001: ele não proíbe a baixa vinculada à
`Sale` criada na finalização — o que ele não atribui é movimento de estoque ao
`OrderItem`, e essa fronteira continua intacta. Quem move estoque é a venda, com
item de venda, ator e motivo, pelo mesmo serviço da venda de balcão.

A baixa acontece dentro da transação que a finalização já compunha, depois de os
itens de venda serem criados. Cobertura pelos endpoints autenticados em
`backend/tests/test_negotiation_sale_stock.py`:

| Cenário | O que prova |
|---|---|
| Mesa fechada pela negociação | Saldo cai, movimento assinado, aritmética do livro fecha |
| Comanda de balcão | Mesmo caminho, mesma baixa |
| Repetição da finalização | Um movimento só; a chave de idempotência devolve a projeção antes de chegar à baixa |
| Falta de saldo no segundo item | Nada sobrevive: sem venda, sem baixa do primeiro item, pedido aberto e negociação não finalizada — lido por sessão nova |
| Crediário | Venda sai `COMPLETED` e baixa igual: o prazo muda quando o dinheiro entra, não se a mercadoria saiu |
| Serviço na mesa | Nenhum movimento; a finalização não inventa saldo físico |
| Retomada depois da falta coberta | Recebimento anterior intacto; ao repor e finalizar de novo, uma venda, um pagamento, uma entrada de caixa e uma baixa de cada item |

São sete, e o primeiro relato disse cinco enquanto listava seis — a contagem
estava errada nos dois sentidos.

**O que não sobrevive à falha é a transação da finalização, e só ela.** O
dinheiro recebido antes é fato anterior e consumado: a intenção de pagamento
confirmada e o movimento de caixa que ela gerou continuam de pé, porque desfazer
recebimento por falta de estoque seria apagar dinheiro que entrou. O teste
confere as duas metades — o que precisa desaparecer e o que precisa permanecer —
e depois repõe a mercadoria, finaliza de novo e verifica que ninguém foi cobrado
nem baixado duas vezes.

Reserva durante o pedido e consumo por ficha técnica continuam fora: são a
extensão da etapa 3 e exigem decisão arquitetural própria.

### Clientes da API de movimentação

`POST /api/v1/inventory/adjust` tem um único cliente de produção:
`api.adjustInventory`, em `frontend/src/services/api.ts`, chamado de
`PosContext.adjustStock` e de `PosContext.createNewProduct`. Ambos enviavam
**magnitude positiva**, sem sinal.

Clientes que enviavam quantidade assinada, inventariados:

| Cliente | O que enviava | Situação |
|---|---|---|
| `payment_service.confirm_payment` | `quantity=-item.quantity` | Corrigido: envia magnitude |
| `backend/tests/test_pos1_gates.py` | `movement_type: SALE, quantity: -3.0` | Corrigido: `LOSS` com `3.0`, mesmo efeito medido pelo gate |

Nenhum cliente externo consome essa rota. A mudança de contrato não quebra
integração publicada conhecida — o que não substitui o inventário de clientes
no ambiente alvo, listado abaixo como dependência de liberação.

## Reprodução dos defeitos

`backend/tests/test_inventory_movement_integrity.py`, executado contra `07ae804`
antes de qualquer correção: **16 falharam, 5 passaram**. As falhas são os
defeitos; os 5 que passaram são o comportamento que já estava correto e que a
correção não podia quebrar.

**Defeito de sinal** — perda de 3 unidades sobre saldo 10:

```
E  AssertionError: assert Decimal('13.0000') == Decimal('7.0000')
```

O saldo subiu para 13. O movimento gravado dizia `LOSS · 3` na mesma linha.

**Falha transacional** — venda de dois itens, o segundo sem estoque, lida por uma
**sessão nova** depois do erro:

```
E  AssertionError: o primeiro item continuou baixado depois do erro no segundo
E  assert Decimal('8.0000') == Decimal('10.0000')
```

A requisição respondeu 400 e, ainda assim, o primeiro item ficou baixado e a
venda ficou marcada como paga. A causa: `sale.status = PAID` era gravado antes do
laço e o `session.commit()` de dentro de `adjust_stock`, no primeiro item,
persistia tudo o que estivesse pendente na sessão.

**Ambiguidade de contrato** — dez ocorrências de `DID NOT RAISE HTTPException`:
quantidade negativa aceita em operação direcional, quantidade zero aceita em
todos os tipos, e `POST` manual com `movement_type: SALE` aceito como se fosse
baixa de venda.

## O que foi corrigido

| Correção | Onde |
|---|---|
| O tipo da operação decide o efeito; entrada soma, saída subtrai | `inventory_service.signed_variation` |
| Quantidade assinada em operação direcional é recusada, não invertida em silêncio | idem |
| Quantidade zero e não finita são recusadas | idem |
| `ADJUSTMENT` permanece a única operação com sinal próprio, declarada como a diferença apurada | idem |
| Saída maior que o saldo é recusada em **toda** operação, não só na venda | `inventory_service.adjust_stock` |
| O commit sai do serviço: quem coordena a operação inteira confirma a transação | idem, mais a rota e `payment_service` |
| Movimentação manual não pode se passar por baixa de venda | `POST /api/v1/inventory/adjust` |
| A baixa da venda informa magnitude; o sinal é do servidor | `payment_service.confirm_payment` |
| A recusa chega a quem chamou, em vez de virar sucesso silencioso | `PosContext.adjustStock` |
| O formulário não fecha nem limpa sobre uma recusa | `CatalogManager.handleAdjustStock` |
| A mensagem de sucesso só aparece depois de o servidor aceitar, e sem vocabulário interno | `InventoryManager.submit` |
| O motivo sugerido acompanha a operação, em vez de gravar "Entrada de mercadoria" numa perda | `domain/stockMovements.ts`, lido pelas duas telas |
| A recusa do servidor chega inteira à tela, com mercadoria e números | `api.adjustInventory`, via `apiError` |
| A frase de recusa deixou de carregar o código interno `INSUFFICIENT_STOCK` | `inventory_service.adjust_stock` |

Invariante preservada em toda a cadeia: `saldo anterior + variação assinada =
saldo posterior`. A coluna `quantity` do movimento guarda a **variação assinada**,
que é o que faz a soma do livro bater com o saldo; a quantidade informada é a sua
magnitude, recuperável sem perda.

## Diagnóstico histórico

`scripts/inventory_integrity_diagnosis.py` — **somente leitura**. Procura quatro
assinaturas: saída com variação positiva, aritmética quebrada na própria linha,
saldo divergente da soma do livro, e venda paga com item controlado sem baixa.

Execução local, 07/09/2026:

| Assinatura | Achados |
|---|---|
| Saída com variação positiva | 31, em 31 lojas |
| Aritmética quebrada | 0 |
| Saldo divergente do livro | 492, em 80 lojas |
| Venda paga com item controlado sem baixa | 96, em 52 lojas |

**Estes números não dizem nada sobre produção, e quase nada sobre este banco.**
A maior parte dos 31 achados de sinal foi escrita hoje pelas próprias execuções
de reprodução — os motivos gravados são "Avaria no transporte", "Perda maior que
o saldo", "Movimento da série". O banco de desenvolvimento acumula anos de dado
de teste. O valor do roteiro está em ele encontrar a assinatura quando ela
existe, o que os testes provam plantando cada uma; o valor do *número* só
aparece quando ele roda contra o ambiente publicado.

O roteiro não corrige nada e não deve corrigir: movimento confirmado não é
reescrito, e a correção de um saldo errado é movimento compensatório vinculado,
com justificativa e responsável, decidido tenant a tenant. Inverter linhas em
massa transformaria histórico errado em histórico falsificado.

## Verificação

| O quê | Resultado |
|---|---|
| `backend/tests` completo | 511 passaram, 1 pulado (a guarda de CI, fora de CI) |
| `test_inventory_movement_integrity.py` | 30 passaram (eram 16 falhas em `07ae804`) |
| `test_negotiation_sale_stock.py` | 7 passaram |
| `test_inventory_count.py` | 37 passaram |
| `test_linked_sale_return.py` | 35 passaram |
| `test_inventory_http_contract.py` | 14 passaram, contra servidor autenticado |
| `test_inventory_integrity_diagnosis.py` | 7 passaram |
| `frontend` — `npm test` | 137 passaram |
| `tsc --noEmit` | limpo |
| `npm run build` | construído |
| Recusa exercitada na tela | `npm run e2e:stock-refusal` |
| Contagem exercitada na tela | `npm run e2e:stock-count` |

Dois testes que passavam antes falharam com a correção, e é sinal de que ela
alcançou o que precisava alcançar: `test_pos1_gates` mandava `SALE` com `-3.0`
pela rota manual, e `test_s12_transfers` vendia pela mesa uma mercadoria que
nunca havia sido recebida. Os dois foram corrigidos no propósito que mediam.

### A recusa exercitada na interface

`frontend/e2e/stock-refusal.spec.mjs` monta o `CatalogManager` real dentro do
`PosProvider` real, contra o backend real, e registra uma perda de 50 unidades
sobre um saldo de 5. Verificado: a frase do servidor aparece na tela, o
formulário **não** fecha, a quantidade digitada continua lá e o saldo não muda.

A bancada dispensa a tela de login, e só ela: o ambiente local não tem projeto
Supabase configurado. Isso é uma dependência declarada, não uma escolha —
entrar pela porta da frente exige `VITE_SUPABASE_URL` e
`VITE_SUPABASE_PUBLISHABLE_KEY` do projeto de homologação, mais um usuário com
`inventory.adjust` no tenant de homologação.

O exercício encontrou dois defeitos que nenhum teste de backend pegaria.

O primeiro: a camada de API do frontend descartava o `detail` do servidor e
lançava um texto fixo, "Erro ao ajustar estoque". A pessoa via a recusa sem o
motivo. Corrigido com o `apiError` que o resto do arquivo já usava, e a mensagem
do servidor deixou de carregar `INSUFFICIENT_STOCK`, que ia inteiro para a tela.

O segundo apareceu na captura: com "Perda / Avaria / Vencimento" selecionado, o
campo Motivo continuava com "Entrada de mercadoria". Não é acabamento — esse
texto vai para o histórico, e uma perda justificada como entrada é um livro que
contradiz o próprio movimento. Corrigido em `domain/stockMovements.ts`, um lugar
só, lido pelas duas telas que movimentam estoque: o motivo sugerido acompanha a
operação, e o que a pessoa escreveu de próprio punho nunca é sobrescrito. A
bancada confere isso junto com a recusa.

## Gates

| Gate | Estado | O que falta |
|---|---|---|
| **Integridade** | Evidência produzida, **aceite não declarado** | Ver as lacunas abaixo |
| **Operação** | **Pendente** | O ciclo de 8 passos pela interface, executado por pessoa representativa do cliente sem dica do desenvolvedor |
| **Apresentação** | **Pendente** | Capturas nos tamanhos definidos, nas quatro superfícies |
| **Liberação** | **Pendente** | Diagnóstico no ambiente publicado, decisão sobre os dados e verificação do commit implantado |

### O que fechou no gate de integridade

| Exigência do gate | Onde |
|---|---|
| Recebimento aumenta, perda diminui, entrada inválida é recusada sem efeito | `test_a_loss_takes_goods_out_of_the_balance` e a série de recusas |
| Venda de dois itens com falha no segundo reverte a operação composta | `test_a_failure_on_the_second_item...` e o equivalente na negociação |
| Retry de pagamento e chamada repetida após timeout | `test_confirming_the_same_payment_twice_takes_the_stock_out_once`, `test_the_same_movement_sent_twice...`, `test_repeating_the_finalization...` |
| Duas vendas concorrentes não vendem a mesma última unidade | `test_two_confirmations_do_not_sell_the_same_last_unit` |
| Escopo de outra loja, produto de outro tenant, ator forjado, perfil sem permissão | quatro testes próprios, o último pelo caminho autenticado |
| Devolução física e estorno financeiro exercitados **separadamente** | `test_a_financial_refund_does_not_put_the_goods_back_on_the_shelf` e `test_a_physical_return_is_the_one_that_puts_the_goods_back` |
| Serviço não cria saldo | dois testes, um deles pela mesa |
| Item fracionado mantém precisão | `test_a_fractional_item_keeps_every_decimal_it_was_given` |
| Mudança de mínimo não cria movimento | `test_changing_the_minimum_is_a_parameter_and_never_a_movement` |
| Testado pelos endpoints autenticados, além da unidade de serviço | `test_negotiation_sale_stock.py` inteiro, mais a rota em `test_inventory_movement_integrity.py` |

### O que ainda não está fechado

Por isso a etapa é **parcial**, e o gate não é declarado aprovado:

- **devolução física vinculada à venda.** `RETURN` entra no saldo e está testado
  como fato separado do estorno, mas não há vínculo com a venda de origem nem
  verificação de aptidão do item devolvido — o passo 7 do ciclo de operação
  ainda não é executável como o plano o descreve;
- **soma de unidades diferentes.** O cartão "Unidades em saldo" da tela de
  estoque ainda soma quilo, litro e unidade num número só, contra a invariante 8.
  A precisão por movimento está provada; a apresentação, não.

O primeiro é **requisito do gate de integridade**, não item de acabamento:
implementá-lo junto da etapa 2 é decisão de sequência, e o gate só é declarado
aprovado quando ele estiver coberto. O segundo pertence ao gate de apresentação,
e continua aberto lá.

## Contar estoque — 07/09/2026

A operação cotidiana passou a existir. Ela informa **o total encontrado** e o
servidor calcula a diferença; `ADJUSTMENT` continua sendo a diferença assinada, e
deixou de ser alcançável por quem apenas movimenta estoque.

### O desenho

Três rotas, porque são três autoridades. Chamar `ADJUSTMENT` de "operação técnica
restrita" na documentação não restringia acesso nenhum — a separação agora está
no motor de permissão:

| Rota | Permissão | Operações |
|---|---|---|
| `POST /inventory/adjust` | `inventory.adjust` | `PURCHASE`, `LOSS`, `RETURN`, por magnitude |
| `POST /inventory/count` | `inventory.count` | total encontrado; o servidor calcula a diferença |
| `POST /inventory/technical-adjustment` | `inventory.adjust.technical` | `ADJUSTMENT`, a diferença assinada |

`inventory.count` foi para OWNER, TENANT_OWNER, ADMIN e MANAGER — quem já
movimentava estoque. `inventory.adjust.technical` ficou em OWNER, TENANT_OWNER e
ADMIN: lançar diferença à mão passa por cima da conferência da prateleira, e isso
responde pela administração do tenant, não pela operação de loja. A migração 082
cria as duas permissões e as concede; `CASHIER` e `OPERATOR` não alcançam nenhuma
das duas rotas.

### As cinco exigências, e como cada uma é provada

| Exigência | Como |
|---|---|
| Versão alterada por **toda** movimentação | O `UPSERT` que grava o saldo incrementa `version` na mesma instrução. Teste parametrizado nos cinco tipos: venda, entrada, perda, devolução e ajuste |
| Conferência e gravação **atômicas** | `SELECT … FOR UPDATE` no saldo, mantido até o fim da transação. Provado com duas sessões: enquanto a contagem não confirma, uma venda na mesma linha espera e estoura `lock_timeout`. O teste prova que **uma linha existente fica bloqueada neste cenário** — não ausência de janela em geral; o primeiro saldo é caso à parte, com teste próprio |
| Contagem **zero** válida | Campo obrigatório e não negativo: `0` é achado, e não preencher é recusado pelo próprio contrato. Contar zero esvazia a prateleira e registra a saída |
| Contagem **igual ao saldo** | Registra a conferência em `inventory_counts` com diferença zero, `movement_id` nulo, e **não** move a versão de quem não movimentou nada |
| **Conflito** compreensível | `409` com o estado atual — versão esperada, versão atual e saldo atual. A tela mantém o número digitado, relê o saldo e pede nova conferência; nunca reenvia sozinha com a versão nova |
| **Reenvio** sem duplicação | Chave de idempotência com unicidade por tenant na própria tabela de contagens: a guarda é a linha gravada, não um cache que expira |

O bloqueio não é recusa: um segundo teste mostra a venda que esperou passando
depois, sobre o saldo já conferido.

### A conferência é fato próprio

`inventory_counts` guarda o que foi encontrado, o que o sistema tinha, a
diferença, o ator, o motivo e as versões antes e depois. Contar e bater é
informação — alguém olhou a prateleira naquele dia — e não podia virar movimento
inventado só para deixar rastro.

### Na tela

A tela de estoque ganhou **Contar estoque** ao lado de Movimentar, com o saldo
registrado à vista e a prévia antes de confirmar: *"Você contou 10 un. O sistema
registra 12 un. Diferença: −2 un."* Quando a contagem bate, a prévia diz que a
conferência fica registrada sem movimentar estoque.

O ajuste técnico também ganhou superfície, e não por escolha: o portão de
alcançabilidade recusou a rota sem tela — "backend pronto e tela ausente" é
exatamente o que ele existe para pegar, e ele pegou. A ação aparece apenas para
quem tem `inventory.adjust.technical`, com o aviso de que ela não passa pela
conferência da prateleira. `fetchInventoryBalance`, que estava na lista de
funções órfãs do cliente, saiu dela: a contagem passou a usá-la.

### Quatro casos levantados na revisão — 07/09/2026

A primeira versão da contagem passava nos cinco requisitos e ainda deixava quatro
buracos. Todos fechados, cada um com o teste que o expõe:

**Primeiro saldo.** `FOR UPDATE` não bloqueia linha que não existe, então um
produto nunca movimentado não tinha o que travar: uma contagem e um primeiro
recebimento simultâneos passariam os dois. A contagem agora materializa a linha
com saldo e versão zero antes de travá-la, por `INSERT … ON CONFLICT DO NOTHING`
— duas transações concorrentes serializam no `FOR UPDATE` seguinte. Provado com
duas sessões, como no caso da linha existente. A linha criada nasce em zero, que
é verdade, e contar zero sobre ela é conferência, não movimento.

**Mesma chave, conteúdo diferente.** Unicidade não distingue reenvio de
reaproveitamento — ela deixaria a mesma chave devolver o resultado de outra
contagem, confirmando algo que ninguém fez. A contagem guarda o hash do comando
(loja, produto, quantidade, versão) e recusa com `409` quando a chave volta com
conteúdo diferente. Teste parametrizado nos três campos: quantidade, versão e
produto.

**Precisão.** A coluna é `Numeric(14,4)` e aceitava mais casas, deixando o banco
arredondar em silêncio — `0,00005` virava `0,0001` sem ninguém ficar sabendo.
Agora a quantidade além da quarta casa é recusada com a régua explícita, na
movimentação e na contagem. Um teste confere que contado, diferença e movimento
batem até a última casa, e que a aritmética do livro fecha nelas.

Uma correção do meu próprio relato: eu escrevi que dois desses achados "não
seriam encontrados por teste de backend nenhum". **Está errado.** A versão
incorreta do saldo ausente é alcançável por um `GET /inventory/balance` sobre
produto sem movimento — e esse teste agora existe, em
`test_inventory_http_contract.py`. Era lacuna de cobertura, não impossibilidade.
Só a chave de idempotência recriada a cada clique exige exercitar o cliente.

**Conflito na tela.** Reler o saldo transformava a contagem antiga em confirmação
válida: um clique mandava o número contado *antes* da movimentação contra a
versão recém-lida. O número digitado continua preservado, mas confirmar passou a
exigir um ato deliberado — "Voltei à prateleira e confirmo a quantidade acima" —
e o botão fica desabilitado até lá.

Essa marcação **registra uma declaração; ela não comprova uma nova contagem.** O
que sustenta a correção é a versão, revalidada a cada envio: o segundo envio leva
a versão relida e o servidor a confere de novo, sob o mesmo bloqueio de linha. Se
o estoque andar outra vez entre a marcação e o clique, a confirmação é recusada
outra vez. A caixa é o ato explícito que impede a aceitação por inércia, não uma
prova de que alguém voltou à prateleira.

### A bancada com contexto de permissões

`frontend/e2e/stock-count.spec.mjs` percorre o caminho pela tela: abre a
contagem, lê o saldo registrado, digita, confere a prévia, sofre uma entrada de
mercadoria no meio, recebe o conflito e só confirma depois da nova conferência.
Verificado: a prévia anuncia a diferença, o número digitado sobrevive ao
conflito, o botão fica travado, e o saldo final é o contado.

Duas coisas ficam de fora, e só elas: a tela de login — sem projeto Supabase
local — e as permissões, fornecidas pelo roteiro interceptando
`capabilities/effective` **no navegador da bancada**. Isso não altera permissão
de produto nenhuma: o backend continua exigindo o que exige, e um pedido sem
autorização real continuaria sendo recusado por ele. **Não substitui o teste
autenticado e não homologa a tela** — o gate de operação continua exigindo pessoa
representativa do cliente percorrendo a navegação completa.

### Dois achados da bancada — obrigatórios na próxima entrega

- **A tela de estoque lista o catálogo vendável, não o acervo.** Uma mercadoria
  cadastrada, com saldo recebido e controle de estoque ativo, **não aparece**
  na tela de estoque enquanto não estiver publicada em algum sortimento — foi
  preciso publicá-la para a bancada rodar. Publicação é decisão comercial e não
  governa a existência física da mercadoria. Já constava do plano como trabalho
  da etapa 2; agora tem evidência.
- **Dois saldos na mesma tela.** Durante o conflito, a linha da tabela continua
  mostrando o saldo antigo enquanto o modal já mostra o novo. A lista só recarrega
  após uma contagem bem-sucedida. Mostrar dois saldos sem dizer qual está
  desatualizado compromete a própria conferência: a pessoa não sabe contra qual
  número está conferindo.

Os dois são **obrigatórios na próxima entrega**, e não achados a registrar e
deixar. O primeiro já constava do plano; a bancada confirmou o efeito.

**A tela ainda não é homologada**, e o limite é o de sempre: exercitá-la pela
navegação real depende das credenciais Supabase já listadas como dependência.

## Devolução vinculada à venda — 07/09/2026

`RETURN` era entrada de estoque solta: quantidade, motivo em texto livre, nenhum
vínculo com a venda de onde a mercadoria saiu. Nada impedia devolver dez unidades
de um item vendido duas vezes, e mercadoria que voltou quebrada somava saldo
vendável igual à que ainda podia ser vendida.

| Ponto do contrato | O que passou a valer | Prova |
|---|---|---|
| **Origem** | `sale_item_returns` liga a devolução à venda e ao item | Item de outro tenant e venda de outra unidade não são encontrados |
| **Teto** | Vendido menos já devolvido, apurado sob `FOR UPDATE` do item de venda | Duas solicitações simultâneas: a segunda espera e estoura o `lock_timeout`; depois é recusada pelo teto já atualizado |
| **Reenvio** | Chave de idempotência com hash do comando | Repetir devolve a mesma devolução; trocar quantidade ou condição responde `409` |
| **Condição e destino** | `RESALEABLE` → saldo vendável; `UNFIT` → quarentena ou descarte | Imprópria não gera movimento e o saldo não sobe — e ainda assim **conta contra o teto**, porque também saiu da venda |
| **Separação** | Nenhum caminho chama o outro | Devolução física não estorna; estorno não cria devolução nem entrada; os dois coexistem com rastros próprios |
| **Autorização** | `inventory.adjust` na rota; tenant e loja no escopo da consulta | `CASHIER` recusado pelo caminho autenticado; ator forjado recusado |

**Onde a devolução mora.** O portão de fronteiras de módulo recusou a primeira
versão: eu havia posto o serviço em `inventory_service`, e o `catalog` passou a
importar modelos de `operation` — o ADR-029 permite a dependência na direção
oposta, nunca nessa. O portão estava certo, e a correção não é declarar dívida: a
devolução **é fato da venda**, porque é do item vendido que sai o teto. O serviço
foi para `sale_service` e a rota para `/api/v1/sales/returns`, de onde o estoque
é chamado na direção legal. A autoridade continua sendo `inventory.adjust`, porque
ela acompanha o efeito — receber mercadoria de volta é trabalho de loja — e não o
caminho da URL.

Uma correção de rota: a checagem explícita de loja que eu havia escrito era código
morto — `scope_tenant_query` já filtra tenant e unidade ativa, então a venda de
outra loja não é encontrada. Removida. A recusa passou a ser `404`, que também é
melhor: ela não confirma que a venda existe em outro lugar.

A tela vive no histórico de vendas, no item — que é onde a pessoa encontra o que
foi vendido. Ela nomeia o estado da mercadoria em vez do código interno, e diz o
que vai acontecer antes de confirmar. A recusa do servidor permanece na tela com
o formulário aberto, porque é ela que explica o limite.

**Só volta o que saiu.** A primeira versão aceitava devolver item de venda em
qualquer situação, inclusive venda ainda aberta — e como nada tinha sido baixado
do estoque, a "devolução" criava saldo do nada. Venda aberta e venda cancelada
passaram a ser recusadas com `409`: o cancelamento antes da baixa não vira
devolução fictícia. `PARTIALLY_REFUNDED` e `REFUNDED` continuam elegíveis, porque
estorno é fato financeiro — quem teve o dinheiro de volta pode trazer a
mercadoria depois, e é esta operação que a recebe.

**A devolução não tem caminho alternativo.** A rota comum de estoque aceitava
`RETURN` sem venda, sem item de origem e sem teto — de modo que a devolução
vinculada recusava o que não tinha baixa comprovada e uma segunda chamada
acrescentava a mesma mercadoria mesmo assim. Proteção com porta paralela não é
proteção, e isso não podia ficar como limite declarado.

`RETURN` saiu da rota comum, e a recusa aponta o **fluxo normal** — o histórico da
venda de origem — em vez da exceção. Nomear o ajuste técnico ali teria o mesmo
efeito que teve na devolução vinculada: oferecido na porta, ele vira rotina. O
procedimento excepcional continua existindo, restrito e justificado, e é
apresentado ao responsável autorizado depois da conferência, não antes. Dois testes fecham o contorno: um tenta a rota comum diretamente, e
outro reproduz o caso inteiro — recusa pela devolução vinculada, seguida da
mesma quantidade pela rota comum, com o saldo intacto nas duas.

### Quarentena: o que existe e o que não existe

Registrar `QUARANTINE` mantém a mercadoria fora do saldo vendável, e isso está
provado. **Mas não constitui controle de mercadoria em quarentena**, e não deve
ser lido como tal. Hoje:

| O que existe | O que não existe |
|---|---|
| O fato registrado: quantidade, produto, venda de origem, ator, motivo e data | **Um saldo de quarentena** — não há onde consultar quanto está separado, por produto ou por unidade |
| A garantia de que o saldo vendável não sobe | **Destinação posterior** — nada registra o que aconteceu com o lote depois: descarte formal, devolução ao fornecedor, retorno à venda após avaliação |
| Uma linha por devolução, consultável apenas por consulta direta ao banco | **Qualquer superfície** que mostre isso a uma pessoa |

Consultar hoje exige ler `sale_item_returns` filtrando `destination` no banco. Um
saldo por destino, a tela que o mostra e o registro da destinação posterior são
trabalho da etapa de almoxarifado ampliado, onde quarentena já está prevista.
**Nada disso pode ser apresentado como almoxarifado completo.**

## Confronto com as exigências do plano

Concluir a devolução **não aprova o gate**. Este é o confronto de cada exigência
do gate de integridade contra a evidência que existe hoje.

| Exigência do plano | Estado | Evidência |
|---|---|---|
| Recebimento aumenta, perda diminui, entrada inválida recusada sem efeito | ✔ | `test_inventory_movement_integrity.py` |
| Venda de dois itens com falha no segundo reverte a operação composta | ✔ | Venda direta e finalização de negociação, lidas por sessão nova |
| Retry de pagamento e chamada repetida após timeout | ✔ | Confirmação repetida, movimentação repetida, finalização repetida |
| Duas vendas concorrentes não vendem a mesma última unidade | ✔ | `test_two_confirmations_do_not_sell_the_same_last_unit` |
| Contagem com versão desatualizada não apaga movimento concorrente | ✔ | Conflito recusado, e a venda concorrente preservada |
| Escopo de outra loja/tenant, ator forjado, perfil sem permissão | ✔ | Em movimentação, contagem e devolução |
| Devolução física e estorno exercitados separadamente | ✔ | Três testes: cada um sozinho e os dois juntos |
| Serviço não cria saldo | ✔ | Movimentação, mesa e devolução |
| Itens fracionados mantêm precisão | ✔ | Recusa além da quarta casa; contado, diferença e movimento na mesma casa |
| Mudança de mínimo não cria movimento | ✔ | `test_changing_the_minimum_is_a_parameter_and_never_a_movement` |
| Movimento confirmado não é reescrito; correção é compensatória | **✘ sem teste** | Não existe caminho de escrita que altere movimento, mas nenhum teste fixa isso |
| Cancelamento antes da baixa não cria devolução fictícia | ✔ | Venda aberta e venda cancelada recusadas com `409`; o saldo não se move |
| Testar pelos endpoints autenticados, além da unidade de serviço | **parcial** | Negociação, mesa e comanda por HTTP real; contagem e devolução pela função da rota com sessão real, mais `authorize_tenant_context` para a permissão — não por HTTP |
| Não somar kg, litros e unidades num cartão | **✘** | O cartão "Unidades em saldo" ainda soma |

**Portanto: gate de integridade PENDENTE.** Um item sem evidência, um parcial e
um comportamento contrário à invariante 8. Gates de operação, apresentação e
liberação seguem intocados — o ciclo pela navegação real não foi executado por
ninguém, e depende das credenciais listadas abaixo.

## Os cinco itens — 07/09/2026

### 1. Estoque consulta o acervo físico

`GET /api/v1/inventory/holdings` devolve o que a unidade controla, publicado ou
não. A tela lia o catálogo vendável — a projeção de venda por contexto — e por
isso uma mercadoria cadastrada, com recebimento registrado e controle ativo,
**não aparecia no estoque** enquanto ninguém a publicasse num sortimento. Foi o
que obrigou a bancada a publicar o produto para conseguir rodar.

A busca do servidor cobre o que a tela promete: nome, SKU e código de barras.

### 2. Tabela e modal coerentes após o conflito

O `409` da contagem agora relê **as duas coisas**: o saldo do formulário e a
lista atrás dele. O aviso mostra o saldo relido ao lado do número digitado, para
que não haja dois números na tela sem dizer qual está velho.

Falha de carregamento também deixou de se passar por prateleira vazia: a tela diz
que não conseguiu ler e oferece tentar de novo.

### 3. Indicadores sem grandezas incompatíveis

O cartão "Unidades em saldo" somava quilo, litro e unidade num número que não era
de nada. Saiu. No lugar: **mercadorias controladas**, **sem estoque** e **abaixo
do mínimo** — três contagens de produtos, sem conversão. Cada saldo continua
aparecendo com a sua unidade na linha.

A situação passou a ter quatro estados em vez de dois. "Sem estoque" e "abaixo do
mínimo" são coisas diferentes, e produto **sem mínimo definido** não é regular
nem irregular: não há política contra a qual julgá-lo, e chamar isso de "Regular"
escondia justamente o que precisa de decisão.

### 4. Preservação dos movimentos, e o que status não prova

**Preservação:** um teste relê o movimento original depois de uma correção e
confronta id, tipo, quantidade, saldos, motivo e data. A correção deixa linha
própria; o original fica intacto; cada linha continua fechando a aritmética. Uma
varredura de fonte complementa como alarme barato, e está nomeada como tal.

**Status não comprova saída de estoque.** Uma venda pode estar `PAID` e não ter
baixado nada — foi o caso de toda venda fechada pela negociação antes de
07/09/2026, e é o caso de qualquer linha anterior a este vínculo. A migração 084
liga o movimento ao item de venda que o causou, e a devolução ao saldo vendável
passou a exigir **baixa provada**, não situação da venda:

| Caso | Resposta |
|---|---|
| Venda finalizada, baixa não comprovável | `409` pedindo conferência |
| A mesma venda, devolução imprópria | Aceita — não há saldo a criar, e a mercadoria voltou de fato |
| Vendeu 3, baixou 2 | O teto é 2, não 3 |
| Venda aberta ou cancelada | `409`: nada saiu para poder voltar |

**A mensagem foi corrigida.** A primeira versão dizia "devolver ao saldo vendável
criaria mercadoria que nunca saiu" — e isso afirma um fato que ninguém verificou.
Ausência de vínculo prova menos: prova que **não há como comprovar a baixa por
aqui**. A recusa passou a dizer isso e a pedir conferência.

Ela também deixou de apontar o ajuste técnico. Indicar a exceção na própria
recusa, sem procedimento de investigação, transforma a exceção em rotina — que é
o oposto do que uma operação restrita deve ser. Um teste fixa as duas coisas:
a frase não afirma que a mercadoria ficou, e não oferece o atalho.

### 5. Contagem e devolução por HTTP autenticado

`test_inventory_http_contract.py` roda contra um servidor em `AUTH_MODE=test`, o
modo isolado que a CI já usa, com tokens assinados por papel. O que só existe no
caminho HTTP e agora está exercitado:

| Exercitado | Resultado |
|---|---|
| Sem token | `401` |
| `CASHIER` na contagem e na devolução | `403` do motor de permissão, não de um `if` no teste |
| Cabeçalho de idempotência ausente | `422` pela assinatura da rota |
| `counted_quantity` negativo | `422` pelo Pydantic, antes do serviço |
| Versão desatualizada | `409` com o estado atual no corpo |
| Reenvio da mesma contagem | Uma diferença só |
| Ator forjado no corpo | `403` |
| Teto e coerência de condição na devolução | `400` |
| Acervo com mercadoria não publicada | Aparece |

**E essa cobertura é obrigatória, não opcional.** Pular em silêncio deixaria a
suíte verde sem a cobertura, que é pior do que não ter o teste. O job de backend
passou a subir uma segunda instância em `AUTH_MODE=test` na porta 8004, e uma
guarda **obrigatória em CI e opcional localmente** falha quando
`TEST_AUTH_BASE_URL` e `AUTH_TEST_SECRET` faltam — verificado simulando o job sem
elas:

```
E   AssertionError: TEST_AUTH_BASE_URL e AUTH_TEST_SECRET não estão configurados:
    a cobertura de contagem e devolução por HTTP autenticado seria pulada em silêncio.
1 failed, 13 skipped
```

Numa máquina de desenvolvimento sem o servidor, a configuração continua opcional
e o comando para subi-lo está no cabeçalho do arquivo.

## Confronto atualizado do gate

| Exigência | Estado |
|---|---|
| Recebimento aumenta, perda diminui, entrada inválida recusada sem efeito | ✔ |
| Falha no segundo item reverte a operação composta | ✔ venda direta e negociação |
| Retry de pagamento e chamada repetida após timeout | ✔ |
| Duas vendas concorrentes não vendem a mesma última unidade | ✔ |
| Contagem com versão desatualizada não apaga movimento concorrente | ✔ serviço e HTTP |
| Escopo de loja/tenant, ator forjado, perfil sem permissão | ✔ serviço e HTTP |
| Devolução física e estorno exercitados separadamente | ✔ |
| Serviço não cria saldo | ✔ |
| Itens fracionados mantêm precisão | ✔ |
| Mudança de mínimo não cria movimento | ✔ |
| Movimento confirmado não é reescrito | ✔ leitura das linhas após correção |
| Cancelamento antes da baixa não cria devolução fictícia | ✔ |
| Testar pelos endpoints autenticados, além da unidade de serviço | ✔ contagem, devolução e acervo por HTTP com token |
| Não somar kg, litros e unidades num cartão | ✔ o cartão saiu |

| Devolução não tem caminho alternativo | ✔ `RETURN` saiu da rota comum, com dois testes de contorno |

**O que continua fora do gate de integridade, e por quê:**

- **Quarentena não é controle.** O fato é registrado e o saldo vendável não sobe,
  mas não há saldo de quarentena consultável, nem destinação posterior, nem tela.
  Pertence ao almoxarifado ampliado;
- **Não há procedimento de investigação** para a venda cuja baixa não se
  comprova. A recusa pede conferência e a conferência não existe como fluxo —
  hoje ela acontece fora do sistema, e o ajuste técnico é a única correção
  possível depois dela. Enquanto isso não for desenhado, o caminho de exceção
  depende de disciplina de quem opera;
- **A tela não foi homologada.** A bancada exercita comportamento; o gate de
  operação exige pessoa representativa do cliente pela navegação real, e isso
  depende das credenciais Supabase — dependência de ambiente, separada deste
  trabalho local.

Com os cinco itens entregues e o contorno fechado, **o gate de integridade pode
ser avaliado**. Não está aprovado por mim: quem aprova é quem confere as
evidências. E ter evidência para cada exigência não é o mesmo que ter todos os
caminhos alternativos protegidos — foi por um deles que a devolução vazava.

## Diagnóstico no banco publicado — 07/09/2026

Executado com o código deste commit, por papel `SELECT`-only criado no Supabase
para esta finalidade. O ambiente publicado está na migração
`081_plan_revision_no_nfce` — três migrações atrás desta entrega.

### O que o levantamento encontrou

| Assinatura | Ocorrências |
|---|---|
| Saída com variação positiva | **nenhuma encontrada** |
| Aritmética quebrada na própria linha | **nenhuma encontrada** |
| Venda paga com item controlado sem baixa | **nenhuma encontrada** |
| Saldo divergente da soma do livro | 6 produtos, 1 loja |
| Item vendido sem vínculo de baixa | 1 item, 1 loja |

**"Nenhuma encontrada" não é "nunca aconteceu".** O levantamento procura marcas
que sobreviveram até hoje; ele não reconstrói o passado. Um movimento com sinal
invertido pode ter sido corrigido depois, um saldo pode ter sido reescrito por
outro caminho, e um dado pode ter sido apagado. O que está provado é que **as
assinaturas não estão lá agora** — e é sobre isso, e só sobre isso, que a decisão
de liberar se apoia.

### A conta não é exclusivamente de homologação

Foi verificado, porque a conclusão mudaria conforme a resposta:

| Tenant | Situação | Vendas | Movimentos |
|---|---|---|---|
| Dashem Retail Store | **ACTIVE** | 0 | 12 |
| Test Tenant - McMarcelo's | TRIAL | 5 | 10 |
| Tenant de Homologação | TRIAL | 2 | 1 |

Há um tenant **ACTIVE**, e portanto não se pode dizer que o ambiente contém
apenas dado de teste. O que se pode dizer é mais estreito: ele não registrou
venda nenhuma, e **os sete achados estão todos em `Test Tenant - McMarcelo's`**,
que é TRIAL. Nenhum achado toca o tenant ativo.

### Tratamento dos seis saldos iniciais

Os seis são o mesmo padrão: saldo positivo — 40, 40, 60, 120, 60 e 30 unidades —
com **zero movimentos** por trás. É estoque escrito por fora do livro, anterior à
disciplina de movimentação, e não é sintoma de nenhum defeito desta entrega.

**Eles não podem ser "corrigidos" sem falsificar alguma coisa**, e é importante
dizer por quê:

* lançar um movimento de entrada para explicar o saldo **somaria ao saldo** —
  40 viraria 80. Isso duplica estoque que já está lá;
* editar os movimentos para que a soma bata é reescrever o livro, que esta
  entrega inteira existe para impedir;
* zerar e relançar destrói a única informação verdadeira que existe ali, que é o
  saldo.

O tratamento é **documentar, não consertar**: contar a prateleira pela operação
de contagem. Se o contado bater com o saldo, a diferença é zero, nenhum movimento
é criado, e fica registrada uma conferência com data, quantidade encontrada e
responsável. Se não bater, a diferença vira um ajuste com origem explicada. Nos
dois casos o saldo passa a ter alguém respondendo por ele a partir daquela data —
que é o máximo que se pode obter honestamente sobre um número cuja origem
ninguém observou.

A divergência continuará aparecendo no levantamento, porque a soma do livro
seguirá menor que o saldo. Isso é correto: ela descreve um fato histórico, e
apagá-la seria o mesmo que apagar o próprio problema.

### Tratamento do item sem vínculo

Um item: venda `COMPLETED` de 22/08 com 1 unidade de *Fita Isolante 3M Imperial
20m*, no tenant TRIAL. É a única devolução que passaria a exigir conferência.

**Não há nada a fazer antes da liberação.** Se alguém devolver essa unidade, a
tela pede conferência — e conferir uma unidade é o que qualquer loja faz sem
esforço. Não é necessária janela de tolerância, migração de dados nem exceção no
código.

**E o vínculo histórico não deve ser preenchido por migração.** Casar movimentos
antigos a itens de venda por semelhança — mesmo produto, mesma quantidade, data
próxima — produziria um vínculo que ninguém verificou, com a aparência de prova.
A migração 084 cria a coluna e deixa o histórico nulo de propósito: **ausência de
vínculo é a verdade sobre o que se sabe**, e é por isso que a recusa pede
conferência em vez de afirmar que a mercadoria ficou.

### Proposta de decisão sobre os sete achados

O tratamento acima descreve *como* mexer. Isto é o que proponho **fazer**, para
sua decisão:

| Achado | Proposta | Quando |
|---|---|---|
| 6 saldos com livro vazio, tenant TRIAL | **Não corrigir.** Contar a prateleira quando o tenant voltar a operar, o que registra conferência com data e responsável sem inventar movimento | Na próxima operação do tenant, não antes do merge |
| 1 item vendido sem vínculo, tenant TRIAL | **Não fazer nada.** Se devolverem, a tela pede conferência de 1 unidade | Nenhuma ação prévia |

**Nenhum dos sete bloqueia o merge**, e a razão é verificável: todos estão em
`Test Tenant - McMarcelo's`, que é TRIAL; o único tenant `ACTIVE` não tem venda
nem achado. Não há cliente exposto ao comportamento novo.

**O que essa proposta assume, e que você pode recusar:** que dado de tenant TRIAL
não precisa de correção retroativa. Se a intenção for tratar o ambiente publicado
como se fosse produção plena, a alternativa é contar os seis produtos antes do
merge — o que é meia hora de trabalho de alguém com acesso à unidade, e não muda
nada no código.

### Um achado fora do escopo desta branch, encontrado ao investigar

Investigando uma falha local de `test_s25_1_payment_recovery`, encontrei um
mecanismo real na varredura de recuperação de pagamento — **anterior a esta
branch** e não introduzido por ela:

`recover_unapplied_results` devolve como "recuperadas" linhas que continuam na
fila. No banco local, 42 transações `REFUNDED` com parcela `PROCESSING` são
reprocessadas a cada varredura e nunca saem: aplicar o resultado não move a
parcela para fora do conjunto aberto. Como a fila é varrida **da mais antiga para
a mais nova** e com lote limitado, um acúmulo dessas linhas **inanição as mais
novas** — que é exatamente o que quebrava o teste.

As 42 linhas são artefato das minhas execuções, e o ambiente publicado não tem
nenhuma. O mecanismo, porém, não depende de quem criou as linhas: qualquer par
`REFUNDED` + `PROCESSING` fica na fila para sempre e consome um lugar do lote.

**Não corrigi**, e a razão é de escopo: mexer na recuperação de pagamento dentro
de uma branch de estoque escaparia da revisão que esta entrega recebeu. Fica
registrado para uma decisão própria.

O teste teve o isolamento corrigido sem perder cobertura: em vez de um lote fixo
de 50, ele mede a fila e pede um lote que a cubra. Continua provando o mesmo — a
linha danificada é pulada, a saudável atrás dela é aplicada — sem depender de
quantas linhas alheias existem no banco.

### O que este diagnóstico não decide

* **Não mede comportamento sob volume.** Sete vendas no ambiente inteiro. Os
  números dizem que ninguém está exposto hoje; não dizem como o sistema se
  comporta com movimento real;
* **Não substitui a homologação pela interface.** Continua pendente, e continua
  dependendo das credenciais listadas abaixo.

## Dependências registradas

1. **Acesso ao ambiente publicado.** O diagnóstico histórico precisa rodar contra
   o banco de produção, com o código deste commit, por quem tenha acesso de
   leitura:
   ```
   DATABASE_URL=<produção> PYTHONPATH=backend \
     python scripts/inventory_integrity_diagnosis.py --csv diagnostico-producao.csv
   ```
   Preciso do acesso de leitura ou do CSV gerado. É a segunda pendência parada
   pelo mesmo motivo — a da regra FOOD é a primeira.
2. **Credenciais do Supabase de homologação**, para percorrer a interface pela
   navegação real: `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` e um
   usuário com `inventory.adjust` no tenant de homologação. Sem isso o gate de
   operação não pode ser executado por ninguém neste ambiente, e a bancada
   entrega evidência de comportamento, não o gate.
3. **Etapa 3 sem algoritmo definido.** O plano coloca reposição assistida na
   etapa 3, mas não especifica os algoritmos nem os critérios de aceite. Um
   planejamento real exige ponto de reposição, estoque de segurança calculado
   sobre variação de demanda e de prazo, lote econômico com suas premissas, e
   previsão de demanda avaliada contra métodos simples e com erro medido —
   descontando dias sem estoque, porque venda zero não é demanda zero. Para FOOD
   entram ainda validade, rendimento de receita, ingredientes e desperdício: um
   lote economicamente ótimo pode vencer antes de ser consumido. A entrega
   cobrada é recomendação explicável ("comprar 24: há 8 disponíveis, 12
   encomendadas, e a demanda prevista até a próxima entrega com a reserva de
   segurança é 44"), não um aviso fixo de "Repor". **Nada disso foi feito nem
   especificado.**
