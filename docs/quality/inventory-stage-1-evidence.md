# Etapa 1 do plano de estoque — levantamento, reprodução e correção

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

O segundo achado é registrado como **bloqueio de homologação**, não corrigido
aqui: o plano manda preservar os contratos existentes na etapa 1 e, se um
caminho ficar sem baixa adequada, registrá-lo em vez de apresentá-lo como
atendido. Alterar o momento da baixa exige mapear cada fechamento — mesa,
pagamento parcial, crediário, produção — e decidir com o ADR-001, que hoje não
atribui movimento de estoque ao `OrderItem`.

Consequência prática enquanto isso não for decidido: **toda venda fechada pela
negociação de checkout — que é o caminho de comanda e mesa — não baixa estoque.**

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
| `backend/tests` completo | 405 passaram |
| `test_inventory_movement_integrity.py` | 21 passaram (eram 16 falhas em `07ae804`) |
| `test_inventory_integrity_diagnosis.py` | 5 passaram |
| `frontend` — `npm test` | 108 passaram |
| `tsc --noEmit` | limpo |
| `npm run build` | construído |

## Gates

| Gate | Estado | O que falta |
|---|---|---|
| **Integridade** | Evidência produzida, **aceite não declarado** | Ver as lacunas abaixo |
| **Operação** | **Pendente** | O ciclo de 8 passos pela interface, executado por pessoa representativa do cliente sem dica do desenvolvedor |
| **Apresentação** | **Pendente** | Capturas nos tamanhos definidos, nas quatro superfícies |
| **Liberação** | **Pendente** | Diagnóstico no ambiente publicado, decisão sobre os dados e verificação do commit implantado |

### Lacunas dentro do próprio gate de integridade

Não declaro o gate aprovado. Falta:

- **devolução física vinculada à venda** — o passo 7 do ciclo de operação. Existe
  `RETURN` como entrada de estoque, mas não há vínculo com a venda nem verificação
  de aptidão do item devolvido;
- **contagem de estoque com verificação de versão** — a operação "Contar estoque"
  não existe; hoje só há `ADJUSTMENT` por diferença. A concorrência de contagem
  não tem como ser exercitada;
- **precisão fracionada e unidades** — a coluna é `Numeric(14,4)`, mas não há
  teste de item fracionado, e o cartão "Unidades em saldo" da tela de estoque
  ainda soma quantidades de unidades diferentes num número só;
- **escopo entre lojas e tenants** — a recusa existe em `adjust_stock`, e a
  cobertura vem de outros arquivos de teste, não deste.

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
2. **Decisão sobre a baixa na finalização de negociação.** Comanda e mesa fecham
   venda sem baixar estoque. É bloqueio de homologação daquele caminho.
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
