# UX-13 — quem pode o quê, dito na tela e obedecido no balcão

Data: 08/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
dependência: [ADR-028](../architecture/adr-028-manager-pos-validation.md).

O ADR-028 tornou cancelar e descontar operações de duas pessoas, e a regra já era
verdadeira no servidor — homologada em duas estações em 07/09/2026. O que não
existia era **mudá-la sem mexer no banco**: a tela de Funcionários e Acessos não
mostrava nem permitia marcar o que a pessoa faz sozinha.

## A marca é da própria permissão

A pergunta "quais operações exigem presença" vivia só nas chamadas do frontend.
A migração `091_permission_needs_presence` a move para a linha da permissão.
Quem tornar outra operação presencial marca a linha; ninguém edita duas listas.

É a mesma decisão da `088` (a palavra do nicho) e da `090` (a área do destino):
**quando a resposta é dado, ela vive no dado.**

O rótulo que a tela mostra também já era dado — `permissions.name` diz "Cancelar
venda" e "Aplicar desconto". A tela nunca mostra `sale.cancel`, e um teste
reprova se mostrar.

## Não há um segundo modelo de permissão

A marcação escreve nas **concessões que já existem** (`permission_grants`), que
é a mesma fonte que `effective_access` consulta ao decidir se o PDV abre o
diálogo. Marcar na Gestão e o PDV mudar de comportamento não são dois efeitos:
são o mesmo, e é por isso que a travessia consegue provar os dois de uma vez.

Uma decisão que evita registro falso: **marcar igual ao perfil apaga a
concessão** em vez de gravar uma exceção que não é exceção. Se o caixa já pedia
autorização pelo perfil, marcar "pede" não cria um `DENY` — remove o que houvesse.

## Duas recusas que importam mais que a funcionalidade

**Ninguém amplia a própria autoridade.** Quem tem a tela de acessos poderia se
conceder o cancelamento e passar a cancelar sozinho — e a autorização presencial
deixaria de ser de duas pessoas para ser de uma. Reduzir a própria continua
permitido: quem abre mão pode abrir mão.

**Só operação marcada como presencial entra aqui.** Aceitar qualquer chave
transformaria a tela num editor de permissão bruta, que é o oposto do enunciado.

## A travessia, ponta a ponta

`frontend/e2e/presentation/ux13_autoridade.cjs` usa o próprio gestor como
sujeito — o caminho mais curto que ainda é honesto. Evidência em
[`evidence/ux-13/`](evidence/ux-13/).

| Etapa | Resultado |
|---|---|
| A marcação aparece na Gestão | coluna "Faz sozinho" com "Aplicar desconto" e "Cancelar venda"; nenhuma chave técnica |
| Tirar a autoridade de cancelar | a tela confirma que a pessoa "passa a pedir autorização" |
| **O PDV obedece** | cancelar passa a abrir o diálogo *Autorização do supervisor* |
| Devolver a si mesmo | recusado: *"Ninguém amplia a própria autoridade: peça a outra pessoa com acesso à Gestão."* |

E no banco, ao fim: um `DENY` para `sale.cancel`, e o evento
`tenant.team.authority_changed` na auditoria com autor, horário, operação,
rótulo, se vinha do perfil e o motivo digitado.

### Os controles

- Removida a guarda de autoampliação, a travessia reprova: a tela deixa de
  recusar e devolve a autoridade a quem pediu.
- A primeira rodada da medida **reprovou o produto por erro meu, duas vezes**: eu
  procurava "Faz sozinho" na forma escrita, e o cabeçalho é maiúsculo por CSS; e
  eu clicava no primeiro botão do diálogo, que é "Aplicar desconto" — o diálogo
  lista em ordem alfabética. O mecanismo estava certo nas duas.

## Portões executados

| Portão | Resultado |
|---|---|
| `ux13_autoridade.cjs` | 4 etapas, 5 telas, 0 falhas — e reprova sem a guarda |
| `pytest` de autoridade | 9 provas, incluindo a autoampliação e a auditoria |
| `ux05_modulos.cjs` | 8 auditados, 0 achados |
| `npm test` · `npm run build` | 198 passando · limpo |
| `alembic check` | sem operações novas |

## O que fica de fora

O aceite pede "criar acesso **com e sem** cada marcação e ver o PDV se comportar
de acordo". A travessia prova a direção que muda o comportamento — tirar — com
um sujeito real. **Conceder a um operador e vê-lo agir sozinho não foi
percorrido**: exige semear credencial operacional com PIN ativado e entrar no
PDV como ele, o que o acervo de homologação não tem. As provas de backend cobrem
o cálculo nos dois sentidos; a tela, só num.

Fica na lista de lacunas de homologação, junto com as da UX-08.
