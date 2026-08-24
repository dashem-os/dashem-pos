# Runbook — hardening e prontidão do piloto

## Objetivos de recuperação

- RPO do piloto: até 15 minutos; a prova automatizada do CI usa RPO zero para a
  transação sentinela incluída no dump.
- RTO do piloto: até 60 minutos; cada restore registra duração e revisão Alembic.
- incidente SEV1, perda/duplicidade silenciosa ou quebra de isolamento bloqueiam
  imediatamente o piloto e qualquer expansão.

## Evidências obrigatórias

Uma execução de hardening somente alcança `PASSED` quando os nove checks
persistidos estão em `PASS`: isolamento, concorrência, retry/idempotência,
dependências degradadas, schema/migração, backup/restore, resposta a incidente,
carga representativa e autenticação/sessão. Cada resultado informa referência e
medidas; `{"passed": true}` não é aceito como prova.

## Falha externa

1. confirmar correlation ID e capability afetada;
2. pausar somente configuração/dispositivo/conexão do provider;
3. preservar order, negociação, pagamento confirmado e outbox;
4. usar alternativa manual apenas quando ela estiver explicitamente contratada;
5. abrir incidente sanitizado no Control;
6. recuperar o provider e reconciliar pelo identificador idempotente;
7. repetir o check `degraded_dependencies` antes de encerrar.

TEF, fiscal, canais e e-mail sem homologação/heartbeat permanecem
`UNINSTRUMENTED`; não contam como saudáveis e não são simulados.

## Restore

O CI cria uma transação sentinela, executa `pg_dump`, restaura em banco novo,
confirma a sentinela e a revisão Alembic. Em incidente real, restaure primeiro em
ambiente isolado, valide revisão e contagens, registre RPO/RTO observado e só
então promova conforme o procedimento do provedor gerenciado.

## Segurança

- mutações do Control exigem AAL2;
- PIN operacional possui bloqueio após tentativas inválidas e nunca é login
  global;
- revogação do terminal invalida o contexto operacional;
- respostas `/api` usam `no-store` e correlation IDs não confiáveis são trocados;
- rotação de secrets acontece no gerenciador do ambiente; nenhum segredo entra
  no banco de evidências, logs ou repositório.
