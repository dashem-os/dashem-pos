# S25.1 — matriz de aceite

Data: 5 de setembro de 2026 · branch `s25-1-payment-recovery`

Esta matriz existe porque CI verde prova os cenários cobertos e nada além. Cada
linha diz o critério, onde ele foi implementado, o teste que o exercita e o
resultado — e a última coluna distingue **prova local** de **homologação real
com provider**, que não foi feita e não pode ser deduzida daqui.

## Critério → implementação → teste → resultado

| Critério | Implementação | Teste | Resultado |
|---|---|---|---|
| Cancelamento autorizado, idempotente e auditado de reserva não enviada | `negotiation_service.cancel_intent`; permission própria `checkout.payment.cancel` (migração `076`); auditoria e outbox por `write_audit_and_outbox` | `test_s25_1_a_reserve_never_sent_is_given_back_and_the_command_is_idempotent` | **local ✓** — item volta a `available`, chave repetida devolve a mesma projeção, chave diferente responde 409 |
| Nunca cancelar pagamento confirmado para liberar saldo | recusa `CONFIRMED_PAYMENT_NEEDS_REVERSAL` em `cancel_intent` | `test_s25_1_a_confirmed_payment_is_never_cancelled_to_free_a_line` | **local ✓** |
| `fail_intent` protegido contra liberação incompatível com cobrança externa | `_refuse_over_external_charge` em `fail_intent`, com `external=True` só para o resultado do provider | `test_s25_1_a_charge_in_flight_blocks_release_and_hand_confirmation` | **local ✓** — 409 `EXTERNAL_CHARGE_IN_FLIGHT` |
| Confirmação manual incompatível com transação externa | mesma guarda em `confirm_intent` | idem | **local ✓** |
| Expiração só com evidência de que nada foi cobrado | `expire_abandoned_reserves`: exige prazo vencido, **rota declarada e não usada** (`payment_device_binding_id`) e nenhuma `ProviderTransaction` | `test_s25_1_expiry_needs_evidence_that_nothing_was_ever_charged` | **local ✓ após a segunda revisão** — a evidência correta é a rota declarada, não a ausência de transação; recebimento manual nunca é expirado |
| Recuperação de `PROCESSING`/desconhecido por consulta, mantendo a reserva | `POST /negotiations/intents/{id}/query` → `provider_service.reconcile_transaction` | `test_s25_1_a_charge_in_flight_blocks_release_and_hand_confirmation` | **local ✓** — resposta `UNKNOWN` mantém a reserva; só o resultado do bridge devolve o item |
| Propagação do cancelamento externo | `CANCELED` passa a chamar `cancel_intent(external=True)` | `test_s25_1_the_provider_closing_the_charge_closes_the_parcel` | **local ✓** — antes caía no `else` e deixava o item preso |
| Estorno não é cancelamento de reserva | confirmada → `REFUND_REQUIRES_REVERSAL`, dinheiro intocado; aberta → `FAILED` com `REFUND_WITHOUT_CAPTURE`, **nunca** `cancel_intent` | `test_s25_1_a_refund_is_a_reversal_and_never_a_released_reserve`, `test_s25_1_a_refund_without_capture_frees_the_line_but_is_not_a_cancellation` | **local ✓ após a revisão** — a primeira rodada convertia estorno em cancelamento de reserva |
| Confirmação tardia registrada e reconciliada, nunca descartada | `record_divergence` com `LATE_CONFIRMATION`; parcela encerrada não é reaberta | `test_s25_1_a_late_or_repeated_answer_is_written_down_and_never_applied` | **local ✓** — o pagamento de quem quitou depois permanece intacto |
| Evento repetido ou fora de ordem | unique `(payment_intent_id, kind, provider_status)` + leitura prévia em `record_divergence` | idem | **local ✓** — três respostas do bridge, uma divergência |
| Corrida entre cancelar e confirmar | ambos travam a parcela com `SELECT FOR UPDATE` | `test_s25_1_cancelling_and_confirming_at_the_same_instant_has_one_winner` | **local ✓** — `asyncio.gather`, um 200 e um 409, linha coerente nos dois desfechos |
| Retomada da mesma tentativa sem criar outra cobrança | `execute_transaction` reconcilia a transação em voo em vez de abrir outra | `test_s25_1_a_lost_answer_is_retried_on_the_same_attempt_not_a_new_charge` | **local ✓** — duas execuções e uma consulta, uma única `ProviderTransaction` |
| Validação do TEF antes de criar a parcela | `assert_executable_binding` em `create_intent`, **e a tela declarando o dispositivo junto com a parcela** | `test_s25_1_an_offline_bridge_leaves_no_reserve_behind` + `checkout-tef-declared-upfront` | **local ✓ após a revisão** — na primeira rodada o guarda existia sem caller; o teste de tela falha se o campo deixar de viajar |
| Reinício do serviço no meio do ciclo | o prazo vive na linha (`reserve_expires_at`), não em memória; a varredura roda em sessão nova | teste de expiração, que executa em `Session` própria depois das chamadas HTTP | **local ✓ parcial** — prova que o estado sobrevive a outra sessão/processo, não um `docker restart` encenado |
| Isolamento tenant/unidade | `scope_tenant_query` nas rotas novas + RLS forçado em `payment_settlement_divergences` | `test_s25_1_a_neighbour_never_cancels_or_queries_this_bill` | **local ✓** — 404 nos dois comandos, reserva intacta |
| Permissões negativas | `route_requirement` mapeia `/cancel` para `checkout.payment.cancel` | `test_s25_1_releasing_money_needs_its_own_permission` | **local ✓ no mapeamento** — a suíte HTTP roda sob `AUTH_MODE=disabled`, então isto prova a regra, não a recusa ponta a ponta (mesma limitação registrada no Gate C) |
| Preservar pagamentos confirmados, produção e histórico | nenhuma alteração de `production_state` nos caminhos novos | `test_s25_gate_closure`, `test_s25_live_settlement`, `test_s12_transfers`, `test_gate_d_*` seguem verdes | **local ✓** |
| Interface com tempo de espera, motivo e ação possível | `ParcelRow`: "Aguardando conciliação há 6 min", "Reservado há 9 min, sem cobrança iniciada", botões vindos de `can_cancel`/`can_query_provider` | `checkout-recovery` no audit responsivo, 7 tamanhos | **local ✓** — e a ausência de "marcar falha" é asserção explícita |

## Bloqueio declarado: estorno

`REFUNDED` sobre uma parcela **já confirmada** não tem para onde ir. O fluxo de
estorno que existe, `payment_service.refund_payment`, opera sobre `Payment`, e
`Payment` só nasce em `finalize_negotiation` — ou seja, depois de a venda ser
materializada. Uma parcela confirmada dentro de uma conta ainda aberta não tem
`Payment`, logo não tem estorno.

Não improvisei baixa financeira. O fato é registrado como
`REFUND_REQUIRES_REVERSAL`, o dinheiro fica onde está, a tela mostra a pendência
e alguém decide.

**Escopo proposto para desbloquear**, fora desta entrega: um estorno de parcela
dentro da negociação aberta, que reverta a alocação por item, devolva o saldo à
linha, escreva movimento compensatório de caixa quando o meio for dinheiro e
mantenha a trilha imutável do Gate D. Isso toca S8, S16 e o ADR-023, e merece
contrato próprio.

## O que esta entrega **não** prova

- **Homologação real de provider.** Todos os desfechos vieram do
  `BridgeQueuedAdapter` e do callback autenticado do bridge, que é o caminho de
  produção — mas nenhum adquirente real foi acionado. Certificação continua
  sendo gate externo do S9/S21;
- **Aceite em ambiente publicado.** Nada aqui foi executado contra o deploy nem
  contra o tenant de homologação. A tela foi vista contra fixtures;
- **Reinício encenado.** O estado sobrevive a outra sessão e a outro processo,
  provado em teste; um `docker restart` no meio de uma cobrança não foi
  encenado;
- **Recebimento manual sem confirmação.** Continua valendo o alerta do dono:
  ausência de confirmação no sistema não prova ausência de dinheiro recebido. O
  cancelamento de reserva não confirmada não afirma que nada foi recebido fora
  do sistema; ele afirma que **este** registro não foi cobrado.

## Segunda rodada — achados da revisão, 05/09/2026

Seis bloqueadores vieram da revisão do PR. Todos se confirmaram no código, e a
matriz acima foi corrigida onde ela descrevia intenção em vez de comportamento.

| Achado | O que estava errado | Correção | Teste |
|---|---|---|---|
| 1. Validação antecipada do TEF desconectada da tela | `create_intent` aceitava `payment_device_binding_id` e **nenhum caller enviava**. O guarda existia e não era alcançado; a tela seguia criando a parcela e só depois conferindo o bridge | a tela declara o dispositivo junto com a parcela; a checagem redundante do cliente saiu | `checkout-tef-declared-upfront` no audit — dirige a tela real, seleciona TEF e afirma o valor no payload. Verificado que **falha** sem a correção |
| 2. `REFUNDED` virava cancelamento de reserva | parcela aberta com estorno externo era fechada por `cancel_intent`, o que afirma que nada foi enviado — falso | fecha como `FAILED`, que é o que é (tentativa sem pagamento aqui), e registra `REFUND_WITHOUT_CAPTURE`; a linha volta a ficar disponível e o movimento fica no registro | `test_s25_1_a_refund_without_capture_frees_the_line_but_is_not_a_cancellation` |
| 3. Resultado externo persistido e não aplicado | `_apply_result` grava a transação e só depois toca a parcela. Morrer entre os dois commits deixava cobrança `CONFIRMED` ao lado de parcela aberta — e `unresolved_charge` só olhava cobranças em voo, então **dava para cancelar reserva de cartão aprovado** | `unresolved_charge` passa a bloquear também resultado terminal não aplicado; `recover_transaction` reaplica a resposta já gravada sem perguntar de novo; varredura do worker faz o mesmo sem ninguém abrir a conta | `test_s25_1_a_crash_between_the_two_commits_never_frees_an_approved_card` — encena a falha exatamente entre os dois commits |
| 4. Regressão de estado por evento atrasado | `transaction.status = result.status` sem guarda: um `UNKNOWN` na fila chegando depois de `CONFIRMED` reabria a cobrança e a reserva | estado terminal não retrocede; `CONFIRMED → REFUNDED` continua permitido; contradição é classificada pelo que aconteceu com o dinheiro (`LATE_CONFIRMATION`) e o resto vira `STATE_REGRESSION_REFUSED` | `test_s25_1_a_stale_answer_never_walks_the_charge_backwards` |
| 5. Nova execução de parcela encerrada | `execute_transaction` conferia o meio, nunca o estado da parcela | recusa `INTENT_NOT_EXECUTABLE` e `CHARGE_ALREADY_SETTLED`, **depois** dos caminhos de replay idempotente e de reconciliação, que seguem funcionando | `test_s25_1_a_settled_parcel_is_never_sent_to_the_card_machine_again` |
| 6. Elegibilidade de expiração | só reserva sem dispositivo declarado ganhava prazo, então **abandono antes do envio ao TEF** era ineternamente inalcançável pela varredura | toda reserva aberta carrega prazo; o prazo é limpo quando a cobrança sai; o que protege a cobrança enviada continua sendo a evidência (`nenhuma ProviderTransaction`), não a ausência de prazo | `test_s25_1_a_reserve_abandoned_before_reaching_the_tef_still_expires` |

### Recebimento manual

O texto da expiração foi escrito com cuidado e é verificado por teste: ele diz
que **nenhuma cobrança foi iniciada por este registro** e que recebimento fora do
sistema, se houve, precisa ser lançado. Expirar não afirma que ninguém entregou
dinheiro no balcão.

### Correção da linha "reinício do serviço"

A matriz acima dizia "prova que o estado sobrevive a outra sessão/processo". Isso
continua verdade, e agora existe a prova que faltava: a falha **entre os dois
commits** é encenada diretamente no banco e recuperada tanto pela consulta quanto
pela varredura. Um `docker restart` encenado continua não existindo.

### O que continua não provado

Nada mudou aqui: **homologação real de provider** e **aceite em ambiente
publicado** seguem por fazer, e o **bloqueio de estorno sobre parcela confirmada**
segue declarado, sem baixa financeira improvisada. `REFUND_WITHOUT_CAPTURE` é
caso diferente — nada foi capturado nesta conta — e não abre exceção àquele
bloqueio.

## Terceira rodada — segunda revisão, 05/09/2026

Três pendências, todas confirmadas. Duas delas corrigem correções da rodada
anterior: eu havia trocado um erro por outro.

| Achado | O que estava errado | Correção | Teste |
|---|---|---|---|
| 1. Expiração de recebimento manual ambíguo | a rodada anterior deu prazo a **toda** reserva aberta. Para dinheiro ou PIX manual, "nenhuma `ProviderTransaction`" não é evidência de coisa alguma — nunca ia existir uma, e o dinheiro pode estar na gaveta com a parcela por confirmar | a parcela passa a registrar a rota para a qual foi criada (`payment_device_binding_id`, migração `078`). Só reserva que **declarou dispositivo e não usou** ganha prazo e é varrida; manual espera uma pessoa, que já tem cancelamento explícito, permissionado e auditado | `..._expiry_needs_evidence_that_nothing_was_ever_charged` — três reservas, e mesmo forçando prazo na manual a varredura a recusa |
| 2. `REFUNDED` liberando saldo sem prova de reversão integral | trocar `cancel_intent` por `fail_intent` mudou o rótulo e manteve o problema: liberava a reserva inteira pela palavra do provider, e estorno pode ser parcial. O contrato do adapter **não carrega valor revertido** | a reserva **permanece**, a divergência `REFUND_WITHOUT_CAPTURE` é registrada, e o cancelamento manual continua recusado pelo mesmo motivo. Nenhuma baixa é improvisada | `..._a_refund_on_an_open_parcel_holds_the_line_until_someone_reconciles` |
| 3. Varredura filtrando depois do `LIMIT` | pegava as transações terminais mais **recentes** e só então descartava as já aplicadas: um backlog maior que a página nunca era alcançado, e a parcela presa há mais tempo era a primeira a ser ignorada | o filtro foi para dentro da consulta, com `join` na parcela, e a ordem passou a ser da **mais antiga** para a mais nova, para o backlog drenar | `..._the_sweep_reaches_the_oldest_stuck_parcel_not_only_the_newest` — pede uma linha só e recebe a mais antiga |

### Achado que só apareceu ao consertar o terceiro

Com o filtro correto, a varredura passou a enxergar o backlog real — e **uma
linha danificada derrubava a fila inteira**. Uma transação sem cadeia de
auditoria levantava exceção e nada atrás dela era processado. Agora cada linha é
isolada: falha é registrada em log, a sessão volta atrás e a fila segue.
Provado em `..._one_damaged_row_does_not_block_the_queue_behind_it`.

### Correção de duas linhas da matriz acima

A linha "Expiração só com evidência" descrevia a evidência errada: ausência de
transação. A evidência correta é **rota declarada e não usada**. E a linha de
estorno dizia que a linha voltava a ficar disponível; ela não volta.

### O que continua não provado

Sem mudança: **homologação real de provider**, **aceite em ambiente publicado**,
**estorno sobre parcela confirmada** e **reinício encenado**. O bloqueio de
estorno agora cobre também a parcela aberta com estorno externo — mesma razão,
mesma recusa em improvisar baixa financeira.
