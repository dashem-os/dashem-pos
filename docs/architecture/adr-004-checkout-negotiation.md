# ADR-004 — CheckoutNegotiation é a autoridade da cobertura financeira

Status: aceito no S8, em 23/08/2026.

## Contexto

`Order` registra intenção e consumo operacional; `Sale` é o fato comercial
materializado. O motor legado de pagamentos estava vinculado diretamente a uma
`Sale`, o que não representava corretamente uma mesa com várias comandas,
parcelas independentes, tentativas que falham e retomada de pagamento.

## Decisão

`CheckoutNegotiation` passa a ser o agregado responsável pelo snapshot da conta
e pela cobertura financeira. Ele referencia uma `TableSession` ou um conjunto de
`Orders`, congela o total calculado pelo servidor e possui versão própria.

Cada tentativa nasce como `PaymentIntent`; cada parte da obrigação coberta é uma
`PaymentAllocation`. Somente intents confirmados reduzem o saldo. Uma tentativa
falha permanece no histórico e não desfaz confirmações anteriores. O valor total,
confirmado, em processamento, falho e restante são projeções do servidor.

Alteração do consumo após a abertura invalida o snapshot, em vez de recalculá-lo
silenciosamente. Duas reservas financeiras concorrentes são serializadas pelo
lock da negociação e não podem ultrapassar o devido.

Saldo zero apenas produz o estado `COVERED`; não libera a mesa. Um comando
idempotente e versionado de finalização materializa exatamente uma `Sale`, seus
snapshots e os registros financeiros compatíveis, encerra Orders e só então
fecha a sessão e libera a mesa.

## Fronteiras

- dinheiro, PIX e cartão manual são confirmações explícitas do operador no S8;
- nenhum provider de teste participa do caminho novo;
- adapters, callbacks, consulta e reconciliação de providers pertencem ao S9;
- indisponibilidade externa futura não pode bloquear dinheiro nem a operação
  local já confirmada;
- estoque, fiscal e produção mantêm agregados e gates próprios.

## Consequências

A interface não calcula saldo financeiro. Retry não duplica intent, allocation,
movimento de caixa ou Sale. Todas as tabelas são isoladas por tenant/store via
RLS, e as mutações exigem permission, capability, ator, idempotência, auditoria e
outbox na mesma transação.
