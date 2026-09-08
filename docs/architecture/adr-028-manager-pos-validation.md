# ADR-028 — Validação gerencial do PDV sem personificação operacional

Status: **aceito**

Data: 1º de setembro de 2026


## Adendo de 07/09/2026 — a autorização presencial

O ADR resolveu o gerente **validar** o PDV sem personificar o operador. Faltava
o caminho inverso, que é o mais comum no balcão: o operador precisa fazer algo
que ele não pode sozinho.

Até aqui havia dois estados, e nenhum deles é a loja. Ou o perfil trazia a
permissão e a pessoa desfazia a venda sem testemunha — o perfil CAIXA saía de
fábrica com `sale.cancel` e `sale.discount` no bolso —, ou não trazia e o botão
ficava apagado, e a saída prática era o supervisor operar no caixa alheio, o
que grava a venda no nome errado.

A decisão: **o botão continua na tela do operador e a autoridade é emprestada
por requisição.** Quem tem autoridade chega ao balcão, digita o próprio código
e PIN no terminal, e a operação acontece com as duas pessoas registradas — quem
pediu no `actor_id`, quem permitiu na trilha de autorização. Nada é gravado no
cadastro do operador: a requisição seguinte volta a ser recusada.

Três limites que a implementação respeita:

* a capability continua fora do alcance de qualquer pessoa — autorizar é
  emprestar autoridade, não contratar módulo;
* a recusa por PIN é genérica e conta tentativa (bloqueio após cinco), como no
  login; a recusa por falta de autoridade diz o nome, porque a identidade já
  foi provada e a pessoa precisa saber que tem de chamar outra;
* o PIN viaja no cabeçalho daquela requisição e não é persistido em lugar
  nenhum do navegador.

A migração 089 tirou `sale.cancel` e `sale.discount` do perfil CAIXA. Não tira
a operação de ninguém: torna-a uma operação de duas pessoas, que é o que ela
sempre foi no balcão.

Percorrido em duas estações simultâneas em 07/09/2026 — ver
[ADR-032](adr-032-available-to-promise.md#homologado-no-balcão-em-duas-estações).

**O que ainda falta:** a autoridade é configurável apenas por perfil e por
concessão pontual, e a tela de acessos da Gestão não mostra nem permite marcar
quais operações cada pessoa faz sozinha. Enquanto isso não existir, mudar quem
pode cancelar é trabalho de quem tem acesso ao banco. A interface está
especificada em [UX-13](../product/ui-ux-implementation-sprints.md#ux-13--quem-pode-o-quê-dito-na-tela-de-acessos).

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

## Nota de 4 de setembro de 2026 — a contradição com o ADR-024 foi resolvida

Esta ADR autoriza mutação real sob autoria gerencial conforme as permissões do
perfil; o ADR-024 exigia assunção operacional para qualquer mutação humana no
PDV. Os dois foram aceitos com um dia de diferença e brigavam. A revisão do
ADR-024 de 4/9/2026 resolve a favor desta: a fronteira é a superfície, não a
pessoa. Na validação a partir da própria sessão web, o gestor abre e fecha o
caixa sob a própria identidade, rastreado e metrificado no perfil dele.

Em consequência, com o caixa fechado a coluna de conferência gerencial passa a
oferecer o campo de fundo de troco e a abertura, para quem tem `cash.open`.

## Fora desta decisão

- separar ou corrigir catálogos associados à atividade comercial errada;
- redesenhar mesas, comandas ou catálogo do PDV;
- criar tenant, unidade ou dados descartáveis de homologação.
