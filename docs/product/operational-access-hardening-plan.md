# Plano de hardening — Acesso Operacional do Colaborador

Status: **OA-1–OA-3 implementados; OA-4 com CI verde — pré-piloto bloqueado até evidência no deploy**
Data: 26 de agosto de 2026
Autoridade arquitetural: [ADR-024](../architecture/adr-024-operational-employee-access.md)

## Objetivo

Fechar o Gate B pela jornada real, e não apenas por componentes ou endpoints:

```text
gestor entra na Gestão
  → cadastra ou seleciona funcionário
  → concede função, unidades e código operacional
  → funcionário define o próprio PIN
  → gestor autoriza o navegador como terminal POS
  → colaborador informa código + PIN
  → assume o turno
  → PDV abre no tenant, unidade e caixa do terminal
  → cada operação mantém autoria até o encerramento
```

Nenhuma funcionalidade operacional nova entra em execução até esse fluxo passar
no CI e no deploy.

## Estado de partida

| Área | Estado em 25/08/2026 |
|---|---|
| Autoridade server-side e sessão persistida | implementada, requer adaptação ao novo ciclo de ativação |
| Autorização do terminal | implementada |
| Entrada por código + PIN | implementada isoladamente |
| Contexto depois do PIN | reprovado: volta ao seletor organizacional |
| Login administrativo | reprovado: anuncia `/operate` |
| Definição do PIN | reprovada: Gestão conhece o PIN definitivo |
| Interface operacional | parcialmente implementada; aceite visual pendente |
| Teste E2E da jornada | inexistente |
| Gate B | `REOPENED` |
| Piloto | `NO-GO` |

## Estado da execução em 26/08/2026

| Sprint | Implementação | Evidência disponível | Situação |
|---|---|---|---|
| OA-1 | contexto exclusivo de terminal + `OperationalSession`; `/login`, `/operate`, `/pos` e `/manage` separados | backend, contrato API, testes de fronteira e build | concluída no código |
| OA-2 | ativação temporária; PIN criado pelo colaborador; reativação revoga sessões | migration 045, testes de domínio e contrato | concluída no código |
| OA-3 | portão operacional clean, toque, teclado físico, contexto validado sem exposição visual, contraste corrigido e estado offline preservando autoridade | testes estáticos, typecheck e build | corrigida no código; E2E e deploy pendentes |
| OA-4 | matriz, fixture isolado, suíte Playwright e job de CI | CI verde no commit `1f9bb93`; execução assistida no deploy ainda não anexada | repetir no deploy e submeter ao Gate B |

Validação automatizada desta revisão:

- backend em banco PostgreSQL novo e API em modo de teste: `108 passed`;
- migrations em banco vazio com `upgrade → downgrade base → upgrade` e
  `alembic check`: sem divergência;
- frontend: `58 passed`;
- typecheck e build de produção: aprovados;
- a execução OA-4 anterior (`14/14`) cobria o contrato visual substituído e não
  promove esta revisão; a matriz atualizada precisa ser executada novamente.

Esses verdes comprovam a implementação e a jornada no CI. A repetição assistida
no deploy público, com evidências sanitizadas, continua obrigatória. O Gate B
permanece `REOPENED` e o piloto permanece `NO-GO` até essa decisão.

## Sprint OA-1 — Autoridade e contexto únicos

Objetivo: remover a colisão entre autorização do terminal, identidade da pessoa
e seletor organizacional.

Entregas:

- contrato de resposta da entrada operacional contendo a referência da sessão e
  o contexto já resolvido;
- `/pos` operacional inicializado exclusivamente por terminal + sessão;
- remoção do `OperationalContextGate` da jornada por código + PIN;
- `/login` exclusivamente gerencial, com destino autenticado `/manage`;
- `/operate` acessível somente como superfície do terminal autorizado;
- gestor que deseja operar passa pela assunção do colaborador.

Gate:

- depois de código + PIN válidos, nenhum endpoint ou tela solicita tenant,
  unidade, caixa, terminal ou função;
- adulteração de qualquer contexto é recusada no backend;
- logout operacional retorna ao portão de código + PIN e preserva o terminal;
- revogação do terminal interrompe o turno e exige nova autorização gerencial.

## Sprint OA-2 — Ativação e PIN sob controle do colaborador

Objetivo: retirar o segredo definitivo das mãos da Gestão.

Entregas:

- modelo persistido de ativação de credencial com hash, expiração, consumo
  e tentativas; emissor e motivo ficam nos fatos imutáveis de auditoria;
- concessão administrativa de código, função, permissions e unidades sem PIN;
- primeiro acesso para criação e confirmação do PIN pelo colaborador;
- redefinição por nova ativação, revogando sessões e versão anteriores;
- mensagens neutras, rate limit e bloqueio sem enumeração de identidade;
- migration, downgrade e limpeza segura de contratos legados.

Gate:

- API e frontend da Gestão não aceitam nem retornam PIN definitivo;
- ativação expirada, consumida, adulterada ou de outro tenant/unidade é negada;
- o PIN não aparece em logs, eventos, respostas, screenshots ou fixtures fora de
  testes isolados;
- alteração de função, escopo ou estado do funcionário revoga sessões afetadas.

## Sprint OA-3 — Superfície operacional dedicada e acessível

Objetivo: entregar uma experiência de terminal própria do Dashem, distinta da
Gestão e adequada a toque.

Entregas:

- portão clean e compacto; terminal e contexto são validados silenciosamente e
  não aparecem na interface;
- campos separados “Código do colaborador” e “PIN pessoal”;
- função e permissions resolvidas pelo backend, sem seletor no login;
- teclado numérico tátil, suporte a teclado físico e foco previsível;
- ação canônica “Iniciar turno” ou “Assumir operação”;
- estados separados para terminal não autorizado, ativação inicial, entrada,
  bloqueio, offline, sessão expirada e revogação;
- rota gerencial de recuperação discreta e autenticada;
- correção dos contrastes e tokens de cor em todos os avisos do fluxo.

Gate:

- a tela não enumera funcionários e não se parece com o login administrativo;
- a tela não contém propaganda, dados de tenant/unidade/caixa/dispositivo,
  atalho da Gestão ou autofill de e-mail no código do colaborador;
- navegação completa por teclado e alvos de toque adequados;
- contraste WCAG AA medido para texto, controles, foco, erro e aviso;
- viewport de terminal, tablet e desktop sem conteúdo essencial cortado;
- screenshots de todos os estados são anexadas à evidência do gate.

As referências visuais fornecidas orientam ergonomia e dedicação da superfície;
nenhuma interface de terceiro será copiada e nenhum mock substitui comportamento
real.

## Sprint OA-4 — Aceitação E2E e promoção do Gate B

Objetivo: provar a jornada em navegador real e impedir sua regressão.

Entregas:

- suíte Playwright iniciando com banco/fixtures de teste controlados;
- cenários positivos e negativos abaixo;
- execução em CI com traces e screenshots somente em falha;
- execução assistida contra preview/deploy com evidências sanitizadas;
- atualização do runbook e da matriz de invariantes;
- criação posterior da skill `dashem-pos-operational-acceptance`, baseada na
  jornada já estabilizada.

Gate:

- backend, frontend, migrations, typecheck/build e E2E verdes;
- matriz completa aprovada no CI;
- jornada principal repetida em navegador novo, retorno de sessão e troca de
  operador, sem intervenção técnica;
- nenhuma evidência contém PIN, token ou dado pessoal sensível;
- somente então o Gate B muda de `REOPENED` para `ACCEPTED`.

## Matriz mínima de aceitação

| Cenário | Resultado obrigatório |
|---|---|
| Gestor entra por e-mail | chega a `/manage`, nunca ao PDV automaticamente |
| Login público | não anuncia nem navega para `/operate` |
| Navegador sem autorização | não recebe formulário de código + PIN |
| Gestor autoriza POS | contexto é persistido e auditado no servidor |
| Colaborador ativa credencial | define o próprio PIN; ativação torna-se inutilizável |
| Código + PIN válidos | cria sessão e abre `/pos` no contexto do terminal |
| Código ou PIN inválido | mensagem neutra; nenhuma enumeração; rate limit aplicado |
| Operador de outro tenant/unidade | acesso negado sem seletor de contexto |
| Contexto adulterado | backend rejeita antes da mutação |
| Saída do turno | sessão encerra; terminal permanece autorizado |
| Segundo colaborador | assume o mesmo terminal com nova sessão e autoria própria |
| Sessão expirada/revogada | JWT antigo é recusado e volta ao portão operacional |
| Terminal pausado/revogado | sessão é interrompida e nova entrada é bloqueada |
| Função/permissão alterada | autoridade antiga deixa de operar |
| Operador tenta `/manage` | acesso negado |
| Gestor tenta mutação POS sem assunção | acesso negado |
| Avisos e erros | contraste AA, foco visível e leitura clara |

## Evidência obrigatória

Cada execução registra:

- commit e URL do deploy/preview;
- navegador, viewport e data;
- cenário e resultado esperado/observado;
- IDs sanitizados de tenant, unidade, terminal e sessão;
- trace ou screenshot de falha;
- resultado de contraste/acessibilidade;
- responsável pela revisão e decisão `PASS`/`FAIL`.

CI verde sem essa evidência não promove o Gate B nem libera o piloto.
