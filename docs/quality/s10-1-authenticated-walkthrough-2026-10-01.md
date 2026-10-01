# S10.1 — Travessia Autenticada do Channel Hub — 01/10/2026

Data: 01 de outubro de 2026  
Commit base: `4b5e312` (em `main`, após publicação de D1/R11 e CI 36861234960)  
Ambiente: PostgreSQL 15 isolado (`127.0.0.1:5439`), API local (`127.0.0.1:8004`, `AUTH_MODE=test`), Frontend Vite (`127.0.0.1:5173`)  
Resultado: **17 etapas · 10 telas capturadas · 0 falhas**  
Evidências salvas: [`docs/quality/evidence/s10-1-2026-10-01/hom09-canais.json`](evidence/s10-1-2026-10-01/hom09-canais.json)

---

## 1. Escopo desta Travessia

Esta execução reavalia o subgate **R20** com autenticação e concessões reais, incorporando formalmente a decisão **D1/R11** (valores e preços declarados externamente pelo canal):

1. **Gestora autenticada (Renata Nogueira):**
   - Acesso via Gestão (`/manage?area=OPERACAO` e `ADMINISTRACAO`);
   - Visualização da caixa de entrada de eventos dos canais, conexões, avisos outbound e painel de prazos de retenção;
   - Vínculo interativo de código externo não mapeado (`BOLINHO-12` -> `Porção de Bolinho de Bacalhau`);
   - Retomada de evento em quarentena (`ITEM_NOT_MAPPED`), promovendo-o a `APPLIED` e abrindo o pedido no PDV (`OPEN`) com preservação do prazo de retenção original;
   - Retomada de cancelamento em revisão (`PREPARATION_STARTED`): confirmação de que o pedido em preparo permanece em `NEEDS_REVIEW` e não é cancelado sozinho (D2);
   - Reenvio de aviso não entregue (`DEAD_LETTER` -> reenvio -> `DEAD_LETTER` com `NOTICE_TYPE_NOT_SUPPORTED`);
   - Inspeção de prazos de dados (contagem agregada, sem dados pessoais, acusando ausência de rotina de limpeza);
   - Abertura do diálogo de nova conexão (apenas identificador da loja e nome do canal, sem aceitar nem solicitar credenciais);
   - Inspeção de integridade tipográfica em 4 larguras: 1366 px, 1024 px, 768 px e 390 px (0 palavras partidas).
2. **Leitora com permissões negadas (Tiago Prado):**
   - Mesma tela percorrida em viewport mobile (390 px);
   - Concessão de vínculo com negação explícita (`DENY`) de `channel.manage`, `channel.configure` e `channel.catalog.manage`;
   - Todos os botões de ação gerencial ausentes na tela (`Retomar`, `Reenviar`, `Nova conexão`, `Vincular código`, `Validar com o canal`);
   - Tentativas diretas na API contra endpoints protegidos devolvendo rigorosamente **HTTP 403 Forbidden**;
   - Nenhum UUID cru exposto na interface.

---

## 2. Separação de Valores e Garantias (D1/R11)

Para não atribuir à interface do navegador asserções que ele não percorreu, separamos estritamente:

### A. Valores Enviados pelo Roteiro Simulador do Canal
- Código do item: `CHOPE-500` (mapeado para Chopp Pilsen 500ml);
- Preço unitário declarado do item: `R$ 18,50`;
- Quantidade declarada: `2`;
- Taxa de entrega declarada: `R$ 7,00`;
- Total declarado do canal: `R$ 44,00` ($2 \times 18,50 + 7,00 = 44,00$);
- Origem de pagamento declarada: `PAID_ONLINE` (normalizada para `MARKETPLACE`).

### B. Valores Efetivamente Verificados pela API neste Roteiro
- Requisição `GET /api/v1/orders/{order_id}` executada contra o pedido criado:
  - `Order.items[0].unit_price == "18.5000"`;
  - `Order.items[0].quantity == "2.0000"`;
- Confirma que o Order Engine absorveu o preço unitário e a quantidade declarados pelo canal no item de pedido.

### C. Garantias Contratuais e Financeiras Demonstradas pelos Testes Backend de R11
As garantias abaixo **não pertencem à travessia visual do navegador** e foram comprovadas nos testes backend automatizados contra PostgreSQL:
1. **Catálogo local preservado:** O preço de venda da loja (`ProductPrice.sale_price == Decimal("18.0000")`) não sofreu mutação com a entrada do preço de R$ 18,50 (comprovado em `test_channel_inbox.py:533`).
2. **Registro de divergências no mapeamento:** `ExternalOrderMapping.difference_amount == Decimal("1.0000")` e `ChannelOrderLine.difference_amount == Decimal("0.5000")` gravados como evidência (comprovado em `test_channel_inbox.py:533`).
3. **Cálculo da obrigação e total:** `_order_amount()` calcula `R$ 44,00` considerando entrega de R$ 7,00 e sem duplicar subsídios informativos do canal (comprovado em `test_channel_inbox.py:767` e `:1163`).
4. **Bloqueio de cobrança local indevida:** Tentativa de abrir negociação de checkout local para o pedido resulta em HTTP `409 ORDER_PAID_IN_MARKETPLACE`; pedidos com origem desconhecida resultam em HTTP `409 ORDER_PAYMENT_ORIGIN_UNKNOWN` (comprovado em `test_channel_inbox.py:767`).
5. **Garantia transacional sem deadlocks:** Serialização de reduções e proteção sob concorrência comprovadas sem deadlocks `40P01` através da ordem canônica de bloqueios (comprovado em `test_r11_concurrency_matrix.py`, 7 testes).

---

## 3. Limites Declarados e Camadas da Execução

- **Autenticação:** A sessão foi injetada no navegador via chave de sessão contendo JWT de teste assinado localmente com `AUTH_TEST_SECRET`, contra API executando em `AUTH_MODE=test` e permissões efetivas lidas do banco PostgreSQL isolado (`127.0.0.1:5439`). Esta execução **não comprova o fluxo de login interativo** (formulário com usuário/senha ou Magic Link) nem a disponibilidade dos servidores do Supabase Auth em produção.
- **Responsividade e Layout:** A varredura nas larguras 1366 px, 1024 px, 768 px e 390 px afere exclusivamente a ausência de quebras no meio de palavras (`palavrasPartidas`); **não atesta a ausência universal de defeitos de layout**, alinhamentos visuais gerais ou sobreposições de outros elementos sem outras verificações.
- **Canal Externo:** Simulado pelo conector de referência (`CONTRACT_TEST`) com ingressos autenticados por assinatura HMAC-SHA256 derivada de `SECRET_KEY`.
- **Cozinha (KDS):** Simulada pelo roteiro utilizando as rotas reais de despacho de produção (`/api/v1/production/orders/{id}/dispatch`) e aceite de ticket (`/api/v1/production/tickets/{id}/transition` com status `ACCEPTED`).
- **Canais Comerciais:** **Não contatados.** Nenhum canal real (iFood, 99Food, Rappi) participou desta execução.

---

## 4. Registro Fotográfico da Execução

As 10 telas capturadas durante o percurso encontram-se arquivadas em `docs/quality/evidence/s10-1-2026-10-01/`:
1. `1-canais-de-venda.png`: Visão geral gerencial com pedidos aplicados, em quarentena e em revisão humana.
2. `2-vincular-codigo.png`: Diálogo de mapeamento associando `BOLINHO-12` ao produto canônico.
3. `3-quarentena-retomada.png`: Evento retomado com sucesso, aplicando e abrindo o pedido no PDV.
4. `4-revisao-continua-com-uma-pessoa.png`: Cancelamento sob preparo mantido em `Precisa de uma pessoa`.
5. `5-aviso-reenviado.png`: Aviso rejeitado pelo canal permanecendo em `Não entregue` com código explícito.
6. `6-prazos.png`: Painel agregador de contagem de retenção e ausência de rotina de limpeza.
7. `7-nova-conexao.png`: Formulário de conexão exigindo apenas identificadores de negócio, sem credenciais.
8. `8-canais-390.png`: Tela de canais adaptada à largura mobile (390 px) sem quebras de palavras.
9. `9-diagnostico.png`: Aba de diagnóstico de sistema confirmando integridade e contagens de canal.
10. `10-leitora-390.png`: Visão da leitora com ausência total de controles de mutação e HTTP 403 verificado.
