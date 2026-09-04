# ADR-008 — Transferências com conservação e linhagem

Status: aceito no S12.

Itens transferidos não mudam silenciosamente de `order_id`. A origem é mantida e
um item derivado, com o mesmo snapshot de preço e vínculo imutável no
`TransferRecord`, assume a quantidade no destino. Transferência parcial reduz a
quantidade ativa da origem; transferência integral a cancela com motivo. Sessões
são bloqueadas em ordem estável e exigem versões esperadas.

Transferir quantidade cria um item derivado; por isso itens cobertos por
pagamento, materializados em venda, prontos ou entregues são bloqueados e a
produção anterior ainda não pronta sinaliza compensação. Mover uma comanda
inteira ou uma sessão conserva os mesmos IDs de Order e OrderItem e mantém os
tickets de produção vinculados, portanto não exige recriar nem estornar o item.
Junções são comandos explícitos, fecham a origem, preservam o registro e nunca
criam duas sessões ativas para uma mesa. Separar uma comanda para mesa livre
cria a sessão de destino na mesma transação.
