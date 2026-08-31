# Plano de migração — governança Owner

Este plano é deliberadamente não destrutivo. O Sprint 0 apenas o registra; as
migrations serão implementadas após aprovação dos gates correspondentes.

## Checkpoint de execução

Em 31/08/2026, os Sprints corretivos 0 a 5 foram concluídos e a trilha entrou
em pausa técnica. A próxima execução autorizada é o **Sprint 5.1 — Supabase
Storage por tenant**, especificado em
[`owner-governance-sprint-5-1-checkpoint.md`](../product/owner-governance-sprint-5-1-checkpoint.md).

Não existem Sprints 6, 7 ou 8 aprovados nesta trilha. A numeração S0–S21 do
Roadmap Canônico do Commerce OS representa outra sequência e não altera este
checkpoint.

## 1. Classificar limites legados

Cada tenant será classificado sem alterar seu contrato vigente:

| Classe | Condição | Tratamento futuro |
|---|---|---|
| `INHERITS_PLAN` | campo legado ausente | resolver pela revisão contratada do plano |
| `MATCHES_PLAN` | campo legado igual ao teto da revisão | candidato a entitlement herdado; exige prova da revisão |
| `BELOW_PLAN_REVIEW` | campo legado menor que o teto | revisão do Owner; não assumir negociação nem uso |
| `ABOVE_PLAN_INVALID` | campo legado maior que o teto | bloquear migração e abrir inconsistência |
| `PLAN_UNBOUNDED_REVIEW` | plano sem teto com valor legado | revisão comercial obrigatória |

O resultado da classificação será persistido como evidência de migração, com
timestamp, versão do algoritmo e referências dos fatos consultados.

## 2. Reconstruir configuração operacional

O read model será construído a partir das autoridades operacionais:

- memberships ativas e convites pendentes;
- dispositivos ativos, pausados e revogados;
- unidades ativas e arquivadas;
- nenhuma reconstrução de storage até existir inventário canônico.

Os contadores reconstruídos nunca serão copiados para o contrato.

## 3. Introduzir leitura paralela

Antes da troca de enforcement, o sistema produzirá lado a lado:

- decisão legada;
- entitlement resolvido pelo novo contrato;
- configuração e reserva observadas;
- decisão da nova policy em modo sombra.

Divergências serão registradas sem alterar a operação. O corte somente poderá
ocorrer após reconciliação dos tenants afetados.

## 4. Materializar entitlements explícitos

O Owner revisará os casos ambíguos. A materialização produzirá uma nova versão
contratual com:

- revisão exata do plano;
- todas as atividades contratadas;
- capabilities e suas procedências;
- limites e suas procedências;
- add-ons, exceções e vigências;
- autor, motivo, auditoria e outbox.

Lista vazia será escolha explícita. Herança utilizará um comando distinto e não
será inferida por truthiness.

## 5. Trocar o enforcement

Depois do modo sombra:

- endpoints deixam de consultar campos `contracted_*`;
- `ContractEntitlementResolver` fornece o limite;
- `ResourceUsageProvider` fornece configuração e reserva;
- `QuotaPolicy` produz a decisão;
- frontend recebe fatos e decisão, sem recalcular autorização.

## 6. Retirar o legado

Campos duplicados somente poderão ser removidos quando:

- todos os tenants possuírem contrato reconciliado;
- não houver leitor em produção;
- migrations canônicas e fresh-install convergirem;
- testes de rollback e restauração estiverem aprovados;
- evidência de auditoria estiver preservada.

## Rollback

Até a retirada final, a decisão legada permanece disponível para rollback. O
rollback nunca apaga versões contratuais, solicitações, decisões, auditoria ou
snapshots de reconciliação.
