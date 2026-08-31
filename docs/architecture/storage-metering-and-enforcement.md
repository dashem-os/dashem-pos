# Storage metering and enforcement

## Estado verificável

Em 31 de agosto de 2026, o DASHEM POS passou a possuir rotas backend para
upload binário, exclusão e download assinado, além de adapter paginado de
inventário do Supabase Storage. `Product.image_url` ainda referencia uma URL
externa e não foi migrado automaticamente. Ausência de credenciais ou de
inventário continua sem ser convertida em `0 bytes utilizados`.

O provedor escolhido para a primeira integração é o Supabase Storage. A
presença do Supabase Auth e do SDK no projeto não configura automaticamente o
produto Storage. A aplicação e as migrations foram preparadas; ainda faltam
aplicar a migration no projeto Supabase real, declarar sua capacidade física,
criar/validar os buckets privados e executar o gate negativo com dois tenants.
O estado verificável está no checkpoint do
[`Sprint 5.1`](../product/owner-governance-sprint-5-1-checkpoint.md).

## Fronteiras canônicas

- `storage_meter_sources`: namespaces físicos que precisam ser inventariados;
- `storage_measurements`: resultados append-only de um adaptador confiável;
- `storage_reservations`: capacidade serializada antes de uma gravação;
- `storage_provider_measurements`: inventário global de todos os buckets do
  projeto, separado da soma das quotas comerciais;
- `storage_quota_service`: única política para leitura, aviso e bloqueio.

Uma medição somente é `RECONCILED` quando cobre exatamente todas as fontes
ativas do tenant, informa bytes e objetos, possui watermark, evidência e
fingerprint calculado no servidor. A medição também precisa estar dentro da
janela configurável `STORAGE_MEASUREMENT_MAX_AGE_HOURS`.

## Regra de segurança

`NOT_MEASURED`, `PARTIAL`, `DIVERGENT`, `UNAVAILABLE` e limite contratual
ausente resultam em decisão `UNKNOWN`. Para operações que produzam storage,
`UNKNOWN` é bloqueio, não autorização. Uma reserva `COMMITTED` permanece
ocupando capacidade até uma medição reconciliada posterior incorporá-la.

## Integração obrigatória de qualquer futuro produtor de arquivos

1. Configurar o namespace físico no Control plane sem persistir credenciais.
2. Executar o adaptador de inventário do provedor e persistir a medição.
3. Antes do upload, chamar `reserve_storage_capacity` na mesma unidade de
   trabalho que autoriza a operação.
4. Após confirmação do provedor, chamar `finalize_storage_reservation` com
   `committed=True`; em falha, liberar com `committed=False`.
5. Reconciliar novamente o inventário. Só essa medição converte os bytes
   confirmados em uso observado.

Nenhuma tela ou módulo pode declarar enforcement ativo lendo apenas o valor do
plano ou do contrato. O banco da aplicação e o banco interno do Supabase são
fronteiras distintas: a aplicação inventaria pela API administrativa oficial;
a política em `storage.objects` é versionada separadamente em `supabase/`.

## Retomada

O Sprint 5 encerrou a fundação independente de provedor. A implementação local
do Sprint 5.1 está pronta, mas ainda precisa provar isolamento, medição,
reserva, aviso e bloqueio com objetos reais no Supabase configurado. Até esse
gate ficar verde, `NOT_MEASURED` permanece o estado correto e storage não pode
ser vendido como limite efetivamente monitorado. Egress permanece explicitamente
`NOT_INSTRUMENTED` e não é deduzido de bytes armazenados.
