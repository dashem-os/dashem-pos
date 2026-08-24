# ADR-017 — Evidência executável de hardening

## Estado

Aceito em 24/08/2026.

## Decisão

Prontidão operacional não será uma lista marcada manualmente. Cada release possui
uma execução persistida com alvo RPO/RTO e nove categorias obrigatórias. Um check
`PASS` precisa satisfazer medidas específicas; falha ou dependência bloqueada
mantém o release `BLOCKED`.

O CI prova schema limpo e migrado, ausência de drift e backup/restore com uma
transação sentinela. Testes combinados continuam sendo a prova de isolamento,
concorrência, retry e autorização. Dependência externa ausente é isolada e
declarada indisponível, nunca substituída por integração fake.

## Consequências

O gate pode ser auditado, repetido e comparado entre releases. A existência de
uma tela, um documento ou um heartbeat isolado não torna o sistema pronto. S21
só poderá avançar ao campo com hardening `PASSED`, e incidente crítico reabre o
gate.
