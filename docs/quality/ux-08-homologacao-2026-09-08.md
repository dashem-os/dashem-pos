# UX-08 — a volta inteira, e o que só ela encontrou

Data: 08/09/2026 · base: [UX-07](ux-07-pagamento-2026-09-08.md) ·
trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md).

As sete sprints anteriores mediram cada superfície por si. Esta percorre a volta
que o lojista faz de verdade: cadastrar a mercadoria na Gestão, publicá-la,
vendê-la no balcão, e voltar à Gestão para conferir que a venda e o estoque
contam a mesma história.

O enunciado é explícito — *captura bonita não substitui comportamento correto* —
então cada etapa afirma um número que veio do servidor.

## A volta, com os números

`frontend/e2e/presentation/ux08_homologacao.cjs`. Evidência em
[`evidence/ux-08/`](evidence/ux-08/).

| Etapa | O que a medida devolve |
|---|---|
| Gestão: cadastrar e publicar | `CAN-613688`, publicado no Cardápio Principal |
| Gestão: disponível antes | **4** |
| Operação: vender uma unidade | a mercadoria cadastrada chegou ao balcão e foi vendida |
| Gestão: disponível depois | **3** |
| Gestão: a venda aparece em Vendas | sim, e com vírgula |

## O defeito que só a volta encontrou

A tela de Vendas mostrava **"R$ 25.00"**, com ponto, enquanto o PDV ao lado
mostrava "R$ 80,00", com vírgula. `SalesHistory` escrevia dinheiro à mão —
`R$ ${Number(x).toFixed(2)}` — em oito lugares, e `CashManager` em dois, embora
`formatCurrency` exista desde sempre e fale `pt-BR`.

**Nenhuma auditoria por tela perguntava isso.** A da UX-02 mede título, moldura
e cor; a da UX-05 mede as mesmas coisas nos oito módulos. Foi a travessia
integrada, indo do balcão à conferência, que pôs os dois números lado a lado.

Dez ocorrências passaram a usar o formatador, e `design_tokens.test.ts` ganhou o
guarda que impede a volta — mais a verificação de que o formatador continua
falando `pt-BR`/`BRL`, para ninguém "consertar" o helper.

## Os quatro tamanhos e a acessibilidade

| Tamanho | Transbordo horizontal |
|---|---|
| 1366×768 | 0 px |
| 1366×640 | 0 px |
| 834×1112 | 0 px |
| 390×844 | 0 px |

Foco depois de navegar: aterrissa no `H1` da tela, dentro do `main`.
Controles sem nome acessível: **nenhum**.

## Comparação com a UX-00

| O que a UX-00 mediu | Agora |
|---|---|
| 5 de 13 destinos abaixo da dobra em 1366×640 | 7 áreas, 0 abaixo da dobra |
| Voltar caía em `?module=subscription` | volta ao hub, depois à entrada |
| Foco ficava no botão da barra | entra no conteúdo |
| Filtro sumia ao retornar | sobrevive |
| URL inválida caía calada na visão geral | diz o que houve |
| URL não autorizada abria tela em branco | diz o que houve |
| Escape não fechava a gaveta do celular | a gaveta deixou de existir |

## Checklist por área

| Área | Estado | Onde |
|---|---|---|
| Operação — Vendas, Caixas, Canais | auditada e consolidada; Vendas percorrida na volta integrada | UX-05, UX-08 |
| Mercadorias — Produtos, Catálogos, Categorias, Estoques | jornada percorrida; estoque orientado à ação | UX-03, UX-04 |
| Estrutura — Terminais | auditada | UX-05 |
| Estrutura — Ambientes e Mesas | **não auditada**: exige `FOOD_SERVICE` | — |
| Pessoas — Funcionários e acessos | auditada | UX-05 |
| Relacionamento — Clientes | auditada | UX-05 |
| Financeiro — Crediário e recebíveis | auditada | UX-05 |
| Financeiro — Provedores de pagamento | **não auditada**: exige `tef` | — |
| Administração — Plano e solicitações | auditada | UX-05 |
| PDV — seleção e disponibilidade | escada de avisos percorrida | UX-06 |
| PDV — pagamento | cobrança carimbada, com timeout forçado | UX-07 (parcial) |

## Riscos remanescentes

1. **Estado "pendente de confirmação" sem representação visual** (UX-07). Quem
   reenvia hoje acerta pelo carimbo, não porque a tela explicou. É o maior risco
   aberto, e depende de decisão de produto.
2. **Dois destinos nunca percorridos** — Ambientes e Mesas, e Provedores de
   pagamento — porque o acervo de homologação não contrata `FOOD_SERVICE` nem
   `tef`. Não estão declarados validados em lugar nenhum.
3. **Catálogo volumoso não exercitado**: seis produtos no acervo. Busca e grade
   não foram medidas sob carga.
4. **Concorrência de duas estações** sobre a mesma mercadoria não foi percorrida
   pela tela; a idempotência cobre o reenvio, não o encontro simultâneo.
5. **Etapas 3.2 a 3.4 do plano de estoque** seguem futuras: "Atenção" é a faixa
   manual do ADR-033, não previsão.

## Procedimento de retorno

Cada sprint é um commit único em `main`, e a publicação é o merge. Voltar uma
sprint é `git revert` do seu commit:

| Sprint | Commit |
|---|---|
| UX-00 | `0046376` |
| UX-01 | `b46011e` |
| UX-02 | `149681d` |
| UX-03 | `053c202` |
| UX-04 | `8a2e51a` |
| UX-05 | `ba52c55` |
| UX-06 | `9aeff3f` |
| UX-07 | `6ab651d` |

Duas migrações acompanham a trilha e **não** são revertidas junto: a `090`
grava a área de cada destino na malha, e um `downgrade` existe nela. Reverter a
UX-01 sem desfazer a `090` deixa dado a mais que ninguém lê — inofensivo. O
caminho inverso, desfazer a `090` mantendo o código, apaga a navegação: se for
preciso, reverter o código primeiro.

Nenhuma migração desta trilha apaga dado do lojista.

## Portões executados

| Portão | Resultado |
|---|---|
| `ux08_homologacao.cjs` | 9 etapas, 10 telas, 0 falhas — e reprova com o dinheiro à mão de volta |
| `ux05_modulos.cjs` | 8 auditados, 0 achados |
| `responsive_audit.cjs` | 20 de 20 medições, 0 achados |
| `npm test` | 197 passando, 0 falhas |
| `npm run build` | limpo |

**Esta sprint não declara a trilha homologada.** Ela registra a volta que
funciona, os dois destinos que ninguém percorreu, e o risco financeiro que
continua aberto. A liberação segue a autorização vigente na tarefa de execução.
