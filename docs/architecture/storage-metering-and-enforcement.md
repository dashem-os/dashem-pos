# Storage metering and enforcement

## Estado verificável

Em 31 de agosto de 2026, o DASHEM POS não possui rota de upload binário nem
bucket de objetos administrado pela aplicação. `Product.image_url` referencia
uma URL externa e não constitui consumo medido pelo DASHEM. Por isso, ausência
de objetos conhecidos nunca é convertida em `0 bytes utilizados`.

## Fronteiras canônicas

- `storage_meter_sources`: namespaces físicos que precisam ser inventariados;
- `storage_measurements`: resultados append-only de um adaptador confiável;
- `storage_reservations`: capacidade serializada antes de uma gravação;
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
plano ou do contrato.
