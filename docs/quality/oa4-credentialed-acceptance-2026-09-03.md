# OA-4 — Cenários credenciados no deploy publicado

Data de início: 3 de setembro de 2026
Commit: `bf5a1dd`
Deploy do app: `https://dashem-pos.vercel.app`
API de produção: `https://dashem-pos-api.onrender.com`
Tenant: Tenant de Homologação · unidade Matriz Homologação
Executor: Marcelo (gestor e colaboradores), com condução do agente Claude (Opus 5)
Decisão: **em execução**

Complementa a rodada não credenciada registrada em
[`oa4-deploy-acceptance-2026-09-03.md`](oa4-deploy-acceptance-2026-09-03.md),
que aprovou os cinco cenários alcançáveis sem credencial.

## Identidades usadas

| Papel | Referência | Observação |
|---|---|---|
| Administrador contratual | acesso por e-mail | entra por `/login` |
| Colaborador A | Supervisor Homologação · matrícula 0020 | função Supervisor |
| Colaborador B | Atendente OP · matrícula 0040 | função Atendente |
| Terminal | criado na unidade Matriz Homologação | autorizado pelo gestor |

Nenhum PIN, token, código de ativação ou identificador completo é registrado
neste documento. Identificadores aparecem truncados quando necessários.

## Resultado por cenário

| # | Cenário | Resultado obrigatório | Observado | Veredito |
|---|---|---|---|---|
| 1 | Gestor entra por e-mail | chega a `/manage`, nunca ao PDV automaticamente | janela anônima em `/login`; após autenticar parou em `/manage`, sem desvio para o PDV | PASS |
| 2 | Gestor autoriza POS | contexto persistido e auditado no servidor | `Validar no PDV` abriu `/pos?access=management` com contexto Matriz Homologação · Caixa 01 · gestor identificado, faixa de acesso gerencial e caixa fechado. O terminal já existia de execução anterior, então o caminho de provisionamento confirmado não foi exercitado aqui; ele foi verificado contra a pilha local no commit `bf5a1dd` | PASS |
| 3 | Colaborador ativa credencial | define o próprio PIN; ativação torna-se inutilizável | — | pendente |
| 4 | Código + PIN válidos | cria sessão e abre `/pos` no contexto do terminal | — | pendente |
| 5 | Código ou PIN inválido | mensagem neutra, sem enumeração, com rate limit | — | pendente |
| 6 | Operador de outro tenant/unidade | acesso negado sem seletor de contexto | — | pendente |
| 7 | Contexto adulterado | backend recusa antes da mutação | — | pendente |
| 8 | Saída do turno | sessão encerra; terminal permanece autorizado | — | pendente |
| 9 | Segundo colaborador | assume o mesmo terminal com sessão e autoria próprias | — | pendente |
| 10 | Sessão expirada ou revogada | JWT antigo recusado; volta ao portão operacional | — | pendente |
| 11 | Terminal pausado ou revogado | sessão interrompida e nova entrada bloqueada | — | pendente |
| 12 | Função ou permissão alterada | autoridade antiga deixa de operar | — | pendente |
| 13 | Operador tenta `/manage` | acesso negado | — | pendente |
| 14 | Gestor tenta mutação no POS sem assunção | acesso negado | **FAIL na primeira execução**: com identidade administrativa e caixa fechado, informar R$ 100,00 abriu o turno ("Caixa aberto com saldo inicial de R$ 100,00"). O produto autorizava por permissão, sem exigir sessão operacional. Decisão do dono do SaaS em 03/09/2026: seguir a matriz para abertura e fechamento de caixa. Corrigido no commit `f8d6246`. **Reexecução no deploy**: com identidade administrativa, fechar o caixa foi recusado com "Fechar o caixa exige uma sessão operacional. Assuma o turno com código e PIN pessoal no terminal autorizado." A recusa de abertura será reexecutada depois que o turno órfão for encerrado por um colaborador | PARCIAL: fechamento recusado conforme a matriz; abertura a reexecutar |

## Evidência de estados (exigida pelo gate do OA-3)

| Estado | Captura | Observação |
|---|---|---|
| Terminal não autorizado | — | pendente |
| Ativação inicial do colaborador | — | pendente |
| Entrada por código e PIN | — | pendente |
| Erro de credencial | — | pendente |
| Offline preservando autoridade | — | pendente |
| Sessão expirada ou revogada | — | pendente |

## Decisão do Gate B

Preenchida ao final, somando esta rodada à rodada não credenciada. Enquanto
qualquer cenário permanecer pendente ou reprovado, o Gate B continua `REOPENED`
e o piloto continua `NO-GO`.
