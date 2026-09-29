# S10.1 — travessia autenticada do Channel Hub — 29/09/2026

O subgate R20 foi executado localmente sobre `ced91a5`, com um ajuste de interface
feito durante a execução. **O S10.1 não está fechado.** R14 continua sem medida,
R11 depende de D1, e D2, D8 e a concessão de perfis da D7 permanecem pendentes.
Nenhum conector real foi usado.

## Ambiente e percurso

- PostgreSQL 15 em container e volume novos, exposto só em `127.0.0.1:5439`;
  Alembic aplicado do zero até `100_the_notice_leaves`. Não foi usado banco de
  produção nem o volume padrão do projeto.
- API local em `AUTH_MODE=test` na porta 8004; frontend Vite na porta 5173;
  fixture gerada por `backend/tests/support/seed_channel_hub_walkthrough.py`.
- `frontend/e2e/presentation/hom09_canais_de_venda.cjs`: 16 etapas, 10 capturas,
  zero falhas na segunda execução. A gestora percorreu pedidos aplicados, em
  quarentena e em revisão, vinculou um código, retomou eventos, reenviou aviso,
  viu prazos e diagnóstico. A leitora entrou com outra sessão e concessões que
  negam gestão; a API devolveu 403 para retomar, reenviar e conectar.
- O canal e a cozinha foram simulados pelo roteiro, usando as rotas reais da API.
  A assinatura do ingresso e o isolamento das permissões foram exercitados;
  iFood, 99Food e adquirentes não participaram.

Na primeira execução, o teste encontrou uma palavra partida dentro de “Aberto
no PDV” em 768 px. O rótulo recebeu `whitespace-nowrap`; o percurso passou em
1366, 1024, 768 e 390 px. O build do frontend passou. Depois, 22 testes focados
de inbox, outbound e fatos da tela passaram com uma segunda API local em
`AUTH_MODE=disabled`, configuração esperada por esses testes.

Evidência guardada: [relatório do percurso](evidence/s10-1-2026-09-29/hom09-canais.json),
[tela da gestora](evidence/s10-1-2026-09-29/1-canais-de-venda.png) e
[tela da leitora](evidence/s10-1-2026-09-29/10-leitora-390.png).
As demais oito capturas foram geradas pelo roteiro, mas não anexadas aqui.

## Limites e próximo portão

O resultado prova o percurso autenticado local com o conector de referência,
sem provar um canal comercial, produção, retenção efetiva ou o efeito de uma
indisponibilidade do canal sobre a venda local. O próximo portão técnico é R14:
medir a venda local contra uma linha de base enquanto os avisos enfrentam um
canal indisponível. A conclusão do S10.1 ainda exige o tratamento de R11/D1 e
as regras de D2 e D8. As quatro permissões da D7 seguem sem concessão; isso
bloqueia piloto com contato de entrega. A purga permanece etapa posterior.
