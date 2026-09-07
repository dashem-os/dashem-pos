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
| `backend/tests` completo | 421 passaram |
| `test_inventory_movement_integrity.py` | 30 passaram (eram 16 falhas em `07ae804`) |
| `test_negotiation_sale_stock.py` | 7 passaram |
| `test_inventory_integrity_diagnosis.py` | 5 passaram |
| `frontend` — `npm test` | 113 passaram |
| `tsc --noEmit` | limpo |
| `npm run build` | construído |
| Recusa exercitada na tela | `npm run e2e:stock-refusal` |

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

- **contagem de estoque com verificação de versão.** A operação "Contar estoque"
  não existe — hoje só há `ADJUSTMENT` por diferença, que é a operação técnica.
  Sem ela não há como exercitar "contagem com versão desatualizada não apaga
  movimento concorrente". É entrega da etapa 2, e o gate de integridade só fecha
  quando ela existir;
- **devolução física vinculada à venda.** `RETURN` entra no saldo e está testado
  como fato separado do estorno, mas não há vínculo com a venda de origem nem
  verificação de aptidão do item devolvido — o passo 7 do ciclo de operação
  ainda não é executável como o plano o descreve;
- **soma de unidades diferentes.** O cartão "Unidades em saldo" da tela de
  estoque ainda soma quilo, litro e unidade num número só, contra a invariante 8.
  A precisão por movimento está provada; a apresentação, não.

Os dois primeiros são **requisitos do gate de integridade**, não itens de
acabamento. Implementá-los na etapa 2 é decisão de sequência: ela não transfere a
pendência para outro gate nem a dispensa, e o gate de integridade só é declarado
aprovado quando os dois estiverem cobertos. O terceiro pertence ao gate de
apresentação, e continua aberto lá.

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
