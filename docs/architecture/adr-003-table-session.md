# ADR-003 — Mesa física, sessão de atendimento e pedido são contratos distintos

- Status: aceito e implementado no S7
- Data: 2026-08-23
- Decisores: Dashem Tech

## Contexto

O estado visual de uma mesa não representa sozinho o atendimento. Uma mesa pode
ter várias comandas, receber lançamentos em ondas e continuar ocupada durante o
fechamento. Uma comanda individual também pode existir sem qualquer mesa
física. Vincular diretamente uma mesa a um único `Order` impediria divisão,
junção, transferência e reconstrução histórica.

## Decisão

Três contratos independentes compõem o fluxo:

```text
ServiceTable  recurso físico da unidade
TableSession  ciclo de ocupação/atendimento
Order         comanda operacional e seus itens
```

Uma `TableSession` pode referenciar uma `ServiceTable` ou representar uma
comanda individual sem mesa. Cada sessão nasce com um `Order` e pode agrupar
outros pedidos. `Sale` permanece fora desse agregado e será criada ou vinculada
no fechamento comercial conforme o ADR-001.

Estados físicos da mesa:

```text
AVAILABLE | OCCUPIED | RESERVED | BLOCKED
```

Estados do atendimento:

```text
OPEN | IN_SERVICE | PARTIALLY_PAID | CLOSING | CLOSED | CANCELED
```

`PARTIALLY_PAID` nunca é persistido como estado da mesa física. A disponibilidade
somente muda por comando transacional explícito; saldo zero isoladamente não
libera a mesa.

## Invariantes

1. existe no máximo uma sessão ativa por mesa, tenant e store;
2. abertura e mutações repetíveis exigem chave de idempotência;
3. payload divergente com a mesma chave é conflito;
4. `TableSession.version` protege comandos baseados em estado observado;
5. totais são compostos no backend a partir dos snapshots ativos de `OrderItem`;
6. cada mutação produz histórico, auditoria e outbox na mesma transação;
7. RLS e contexto de store protegem mesas, sessões, eventos, comandos e orders;
8. capability `table_service` e permissions de mesa são avaliadas separadamente.

## Consequências

Transferências e junções futuras não precisarão reescrever silenciosamente a
identidade original do atendimento. O custo é manter uma projeção que reúna
mesa, sessão e comandas para a interface operacional. Essa composição pertence
ao backend e não ao navegador.
