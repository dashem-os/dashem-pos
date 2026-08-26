# Runbook — hardening e prontidão do piloto

Status em 26/08/2026: **NO-GO — Gate B reaberto**. OA-1 e OA-2 estão
implementadas e verdes; OA-3 e a matriz OA-4 passaram localmente em Chromium,
mas o novo job ainda precisa passar no CI e a revisão ainda precisa ser
publicada e repetida no deploy. Nenhuma validação comercial
começa antes da aprovação integral do
[`ADR-024`](../architecture/adr-024-operational-employee-access.md) e do
[`plano OA-1–OA-4`](../product/operational-access-hardening-plan.md).

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

Além dos nove checks, a promoção para piloto exige uma execução da jornada de
acesso operacional em navegador real:

1. navegador novo não oferece código + PIN antes da autorização;
2. gestor entra por e-mail e chega à Gestão;
3. gestor concede código, função, unidades e ativação sem conhecer o PIN;
4. colaborador define o próprio PIN;
5. gestor autoriza o navegador em um POS e caixa específicos;
6. colaborador assume o terminal com código + PIN;
7. `/pos` abre no contexto assinado sem seletor de tenant/unidade/caixa/função;
8. operação de teste registra colaborador, sessão, unidade, terminal e caixa;
9. saída encerra somente a sessão da pessoa;
10. revogação e expiração negam imediatamente o token anterior.

Cada passo registra commit, deploy, viewport, resultado, trace/screenshot de
falha e IDs sanitizados. PINs e tokens nunca entram na evidência.

Execução local de 26/08/2026: banco PostgreSQL isolado, API em modo de teste e
Chromium cobriram `14/14` cenários, incluindo login público exclusivo da Gestão,
navegador não autorizado, autorização gerencial do POS, ativação do PIN pelos
dois colaboradores, troca de operador, adulteração de contexto, saída e pausa
do terminal. A execução final não gerou screenshot porque evidências visuais são
capturadas somente em falha. Esse resultado não substitui CI nem deploy.

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
- código + PIN pessoal possuem bloqueio após tentativas inválidas e nunca são
  login global;
- a Gestão emite ativação temporária, mas não define, visualiza ou redefine o
  PIN definitivo do colaborador;
- revogação do terminal invalida o contexto operacional;
- respostas `/api` usam `no-store` e correlation IDs não confiáveis são trocados;
- rotação de secrets acontece no gerenciador do ambiente; nenhum segredo entra
  no banco de evidências, logs ou repositório.

## Decisão de liberação

- `PASS`: todos os checks de hardening, matriz OA-4, acessibilidade e execução no
  deploy estão aprovados;
- `FAIL`: qualquer divergência de contexto, autoria, revogação, contraste ou
  jornada mantém o Gate B aberto;
- CI verde sem E2E não altera `NO-GO`;
- Gates C e D implementados não compensam falha do Gate B;
- feedback de usuário piloto não substitui defeitos estruturais que a equipe
  consegue reproduzir antes do campo.
