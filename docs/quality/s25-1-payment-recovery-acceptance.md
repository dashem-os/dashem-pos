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
| Expiração só com evidência de que nada foi cobrado | `expire_abandoned_reserves`: exige `reserve_expires_at` vencido **e** nenhuma `ProviderTransaction`; varredura no `outbox_worker` a cada 60 s | `test_s25_1_expiry_needs_evidence_that_nothing_was_ever_charged` | **local ✓** — a reserva sem cobrança expira; a que foi enviada não expira nem com o relógio forçado ao passado |
| Recuperação de `PROCESSING`/desconhecido por consulta, mantendo a reserva | `POST /negotiations/intents/{id}/query` → `provider_service.reconcile_transaction` | `test_s25_1_a_charge_in_flight_blocks_release_and_hand_confirmation` | **local ✓** — resposta `UNKNOWN` mantém a reserva; só o resultado do bridge devolve o item |
| Propagação do cancelamento externo | `CANCELED` passa a chamar `cancel_intent(external=True)` | `test_s25_1_the_provider_closing_the_charge_closes_the_parcel` | **local ✓** — antes caía no `else` e deixava o item preso |
| Estorno não é cancelamento de reserva | `REFUNDED` sobre parcela confirmada gera `REFUND_REQUIRES_REVERSAL` e **não** mexe no dinheiro | `test_s25_1_a_refund_is_a_reversal_and_never_a_released_reserve` | **local ✓ com bloqueio declarado** (ver abaixo) |
| Confirmação tardia registrada e reconciliada, nunca descartada | `record_divergence` com `LATE_CONFIRMATION`; parcela encerrada não é reaberta | `test_s25_1_a_late_or_repeated_answer_is_written_down_and_never_applied` | **local ✓** — o pagamento de quem quitou depois permanece intacto |
| Evento repetido ou fora de ordem | unique `(payment_intent_id, kind, provider_status)` + leitura prévia em `record_divergence` | idem | **local ✓** — três respostas do bridge, uma divergência |
| Corrida entre cancelar e confirmar | ambos travam a parcela com `SELECT FOR UPDATE` | `test_s25_1_cancelling_and_confirming_at_the_same_instant_has_one_winner` | **local ✓** — `asyncio.gather`, um 200 e um 409, linha coerente nos dois desfechos |
| Retomada da mesma tentativa sem criar outra cobrança | `execute_transaction` reconcilia a transação em voo em vez de abrir outra | `test_s25_1_a_lost_answer_is_retried_on_the_same_attempt_not_a_new_charge` | **local ✓** — duas execuções e uma consulta, uma única `ProviderTransaction` |
| Validação do TEF antes de criar a parcela | `provider_service.assert_executable_binding` chamado por `create_intent` antes de reservar | `test_s25_1_an_offline_bridge_leaves_no_reserve_behind` | **local ✓** — bridge offline responde 503 e a conta fica sem parcela alguma |
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
