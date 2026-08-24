# ADR-022 — Gate C: dispositivo de pagamento vinculado e verificável

Status: aceito no Gate C, em 24/08/2026.

## Decisão

Uma execução de cartão não aceita do navegador um provider, um bridge ou um
pinpad escolhidos livremente. Ela recebe somente o identificador de um
`PaymentDeviceBinding` persistido. O backend revalida, na mesma transação:

1. tenant e unidade da parcela;
2. caixa e `OperationalDevice` POS vinculados;
3. configuração de provider ativa da mesma unidade;
4. modo de execução e, para TEF, o `TefBridgeTerminal` pareado ao mesmo caixa e
   provider;
5. para um turno PIN, o dispositivo da sessão operacional deve ser exatamente o
   dispositivo do vínculo.

`TEF_BRIDGE` conserva o contrato do Dashem TEF Bridge: somente o processo local
pareado conversa com SDK, DLL e pinpad. O bridge continua uma identidade de
serviço, diferente da pessoa que iniciou a venda.

`SMARTPOS` é um modo de vínculo, não uma promessa de integração. Enquanto não
existir adapter homologado e pareamento real do equipamento, sua execução é
recusada explicitamente; nunca cai em cartão manual, aprova valor fictício ou
simula uma maquininha conectada.

`ProviderTransaction` passa a guardar o vínculo usado. Registros históricos
podem permanecer sem ele, mas toda nova execução pelo endpoint exige o vínculo.

## Critérios de aceite fixos

1. novo pagamento por provider exige `payment_device_binding_id`;
2. provider, POS, caixa, tenant e unidade divergentes são recusados pelo
   servidor;
3. um turno PIN só executa pelo POS presente na sua própria sessão;
4. bridge TEF offline não bloqueia dinheiro, PIX, cartão manual, crediário ou
   outra parcela independente;
5. SmartPOS sem adapter/pareamento homologado é visível como indisponível e não
   gera autorização falsa;
6. toda criação, pausa, revogação e execução gera auditoria com identidade
   server-side;
7. tentativas entre tenants, unidades, caixas, dispositivos e sessões falham;
8. migration, rollback, testes backend, typecheck/build frontend e verificação
   de drift Alembic permanecem verdes.

## Consequências

- A UI do PDV mostra TEF somente quando existe vínculo persistido e elegível;
- o bridge já existente é preservado e não recebe PIN humano;
- uma futura homologação SmartPOS adiciona adapter ao vínculo, sem reescrever o
  Payment Orchestrator nem o histórico financeiro.
