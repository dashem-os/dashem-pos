# ADR-028 — Validação gerencial do PDV sem personificação operacional

Status: **aceito**

Data: 1º de setembro de 2026

## Contexto

O administrador do tenant precisa conferir no PDV o catálogo, os preços, o
caixa e as permissões que acabou de configurar. Obrigá-lo a informar código e
PIN de colaborador cria uma identidade falsa, atribui trabalho ao atendente
errado e torna a validação cotidiana artificial.

O código e o PIN continuam necessários para a assunção de uma operação humana
por caixa, supervisor ou atendente. Eles não são a identidade correta para uma
validação administrativa.

## Decisão

A Gestão oferece **Validar no PDV** como uma entrada distinta:

1. usa a sessão gerencial existente e a identidade retornada pelo backend;
2. carrega somente tenant, unidade e terminal autorizados;
3. exige `management.read` e as permissões efetivas de cada ação;
4. não cria sessão operacional, papel fictício, código, PIN ou registro de
   produtividade de colaborador;
5. informa que os dados e as ações são reais e auditados;
6. mantém o fluxo público `/operate` e o acesso normal ao `/pos` protegidos por
   terminal autorizado e sessão operacional persistida.

O parâmetro `access=management` escolhe apenas a composição da interface. Ele
não concede autoridade. O token, o membership, o contexto e as permissões são
validados pelo backend.

## Consequências

- o gestor consegue validar a configuração sem personificar um atendente;
- mutações feitas na validação têm autoria gerencial real no servidor;
- métricas por operador e turno continuam derivadas somente de sessões PIN;
- não existe sandbox implícito: testar uma venda, caixa ou estoque altera dados
  reais conforme as permissões do perfil;
- colaboradores continuam sem acesso à Gestão e não podem transformar uma
  sessão comum em sessão gerencial pela URL.

## Nota de 3 de setembro de 2026 — invariante que foi violado

A decisão do dono do SaaS de exigir sessão operacional para **abrir e fechar
caixa** (matriz de OA-4, cenário 14) foi implementada retirando esses controles
da identidade administrativa. O efeito colateral desfez esta ADR: como a área
operacional do PDV só era desenhada com o caixa aberto, e o gestor deixou de
poder abrir o caixa, **Validar no PDV** passou a exibir apenas um cartão de
caixa fechado. A entrada continuou existindo e parou de servir para o que
existe.

Fica explícito o invariante, para que possa ser verificado:

> A conferência gerencial nunca depende do estado do caixa. O que a matriz
> restringe são **mutações** — abrir e fechar caixa, e vender, que exige caixa
> aberto para qualquer perfil. Ver catálogo, preços, ambientes, mesas e
> permissões é a finalidade da entrada e não é restringível por turno.

Com o caixa fechado, a identidade administrativa recebe o PDV completo em modo
de conferência, com a coluna de venda substituída pela explicação do estado.
Coberto por `frontend/tests/shell_boundaries.test.ts`.

## Fora desta decisão

- separar ou corrigir catálogos associados à atividade comercial errada;
- redesenhar mesas, comandas ou catálogo do PDV;
- criar tenant, unidade ou dados descartáveis de homologação.
