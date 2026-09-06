# ADR-031 — Prontidão verificável por capability

**Status:** aceito — direção aprovada pelo dono do SaaS em 06/09/2026, com quatro ressalvas incorporadas abaixo
**Data:** 2026-09-06
**Origem:** recomendação do dono do SaaS em 06/09/2026, depois do achado da TEF
**Relacionado:** [capability-mesh](capability-mesh.md), [ADR-029](adr-029-module-boundaries-and-owner-layer.md), [ADR-005](adr-005-payment-provider-bridge.md), [lacuna do bridge](../product/bridge-command-transport.md)

## Contexto

O Mesh centraliza definição e disponibilidade: `CAPABILITY_REGISTRY` é
arquitetura executável, `resolve_dependencies` fecha o grafo, e a contratação
por tenant vive no banco. O comentário do próprio registro já diz a coisa certa:

> *A contract may be designed before its executable module exists. Commercial
> activation is allowed only for this audited list; planned contracts remain
> visible to architecture tooling but cannot be sold as working software.*

A lista é `IMPLEMENTED_CAPABILITIES`, e ela é **um booleano só**. Em 06/09/2026
a TEF mostrou o que esse booleano não consegue carregar. `tef` está lá, marcada
como vendável, e três coisas diferentes são falsas ao mesmo tempo:

1. **não é contratável**: nenhum dos quatro planos semeados na migração `056`
   inclui `tef` em `capability_keys`, então a tela de capabilities do Control
   nunca a oferece, e `provider.read/configure/execute` — todas com
   `capability_key = 'tef'` — são negadas por capability não contratada;
2. **a integração não está completa**: o servidor enfileira a cobrança e recebe
   o resultado, mas não existe caminho para o bridge **receber** o comando;
3. **não há homologação**: nenhum adquirente atestou coisa alguma.

Um único `frozenset` disse "pronta" sobre três perguntas independentes, e nenhuma
delas tinha resposta afirmativa. Não é um erro de digitação na lista: é o formato
da lista que não comporta a verdade.

## Decisão

### 1. Prontidão tem três eixos independentes, não um

| Eixo | A pergunta | Estados | Onde vive |
|---|---|---|---|
| elegibilidade | consegue chegar a **este** tenant, com **esta** composição? | `REACHABLE` · `IN_DEVELOPMENT` · `NOT_IN_PLAN` · `NOT_OFFERED_BY_ACTIVITIES` | `eligibility.py`, calculada na pergunta |
| implementação | o código faz o trabalho inteiro do contrato dela? | `NONE` · `PARTIAL` · `COMPLETE` | `readiness.py`, declarada com evidência |
| homologação | um terceiro atestou, **e sobre qual integração**? | `NOT_APPLICABLE` · `PENDING` · `CERTIFIED`, por integração | `readiness.py` |

Eles não se ordenam e não se resumem a um número. Uma capability pode estar
`COMPLETE` e fora de todo plano (pronta e não vendida) ou vendida e `PARTIAL` — o
pior dos casos, e exatamente onde a TEF estaria se algum plano a incluísse hoje.

**A elegibilidade é contextual, e não tem resposta absoluta.** Não existe "esta
capability está disponível": existe "está disponível para este tenant, com este
plano e estas atividades, hoje". Guardá-la como atributo global seria repetir o
defeito em outro campo.

**A ordem das razões não é arbitrária.** `IN_DEVELOPMENT` vence as razões
comerciais, porque mudar o plano não faz existir o que não foi construído. Dizer
"fora do plano" para algo incompleto manda o Owner resolver o problema errado.

**E ela enxerga dependências.** Uma capability que se apoia em algo incompleto
não é entregável, por mais pronto que esteja o código dela; a resposta diz qual
dependência travou (`blocked_by`), em vez de um "em desenvolvimento" que
esconderia onde está a dívida de verdade. O grafo é fechado por
`resolve_dependencies`, então a checagem é transitiva.

### 2. `offer` é **derivado**, nunca declarado

Este é o ponto que muda o resultado. Uma capability é `REACHABLE` quando, e
somente quando, **existe plano ativo que a inclui e existe atividade que a
oferta** — uma consulta sobre dados que já temos, não uma opinião mantida à mão.

Declarar teria repetido o defeito: foi um humano marcando `tef` como implementada
que produziu o estado de hoje. Derivar faz a lacuna aparecer sozinha, no dia em
que ela nasce, sem depender de alguém lembrar de desmarcar.

### 2.1. Homologação é por integração, nunca por capability

Homologar TEF com um adquirente não diz nada sobre outro, e emitir NFC-e contra a
SEFAZ de um estado não atesta os demais. Por isso o registro guarda uma lista de
`Homologation(integration, state, evidence, certified_on)`, e o estado da
capability é a leitura dessa lista — nunca um campo solto.

Consequência prática: a TEF pode ficar `CERTIFIED` com um adquirente e continuar
`PENDING` com o seguinte, sem que o registro precise mentir em nenhum dos dois
sentidos.

### 3. `implementation` é declarado, mas **com evidência nomeada**

Não existe como derivar "o código faz o trabalho inteiro". Então continua sendo
declaração — com duas exigências que a tornam verificável:

- `PARTIAL` **obriga** a nomear o que falta, em texto e com link. `tef` é
  `PARTIAL` com "transporte de comandos ao bridge"
  ([frente A](../product/bridge-command-transport.md));
- todo estado aponta para **evidência que existe**: um teste pelo nome, um
  documento de aceite com data, uma matriz. O CI falha se a evidência apontada
  não existir no repositório.

Vale aqui a regra que o runbook do piloto já fixou para os nove checks de
hardening: `{"passed": true}` não é aceito como prova. Um campo que só diz "sim"
é a mesma dívida em outro lugar.

**E a evidência é vinculada à versão avaliada.** Cada registro carrega
`evaluated_version`, e um teste de arquitetura recusa qualquer divergência contra
a versão do contrato no `CAPABILITY_REGISTRY`. Subir a versão de uma capability
invalida a prontidão dela até alguém reavaliar — é isso que impede a declaração
de envelhecer em silêncio enquanto o código muda embaixo dela.

### 3.2. Homologação pendente não rebaixa implementação — e nem sempre é ela que falta

Classificar `fiscal_nfce` como completa "esperando a SEFAZ" estava errado, e o
erro é instrutivo: o único emissor que existe é o `FakeFiscalGateway`, ligado
como singleton global, que **fabrica a chave de acesso com `uuid4`** e devolve
uma URL de DANFE inexistente. Nenhuma certificação conserta um emissor que
inventa a chave.

A regra que fica: antes de atribuir a falta ao eixo de homologação, olhar se o
que existe é o módulo ou um substituto. NFC-e é `PARTIAL` por falta de gateway
real, **e** tem homologação SEFAZ pendente — duas faltas, em dois eixos.

### 3.1. O caminho explícito para exercitar o que ainda está sendo construído

Um gate que só sabe recusar cria o incentivo errado: para conseguir testar, a
saída mais curta passa a ser mentir na declaração de prontidão — que é
exatamente como `tef` foi parar na lista de vendável.

Então existe um caminho nomeado. Um tenant em **fase de teste**
(`lifecycle_phase = TEST`) pode habilitar capability com implementação
incompleta, declarando `homologation_override` na chamada, e a recusa para os
demais diz isso com todas as letras, incluindo o que falta.

Quatro coisas fazem dele uma exceção, e não uma porta dos fundos:

1. **ele alcança o tenant de homologação como ele é.** Todo tenant de
   homologação tem contrato versionado, e a rota recusava qualquer alteração de
   capability nesse caso — o caminho existia só onde não fazia falta. Agora a
   exceção atravessa aquela recusa, e **somente ela**: alteração comum de
   capability continua sendo pelo editor de contrato;
2. **ela não é contratação, e a leitura não as confunde.** `enabled` continua
   dizendo o que o contrato diz; a exceção tem campo próprio
   (`homologation_override`) no catálogo e na tela. A própria linha de
   `TenantCapability` declara que existe por exceção, e é isso que
   `effective_capabilities` exige para dar efeito a ela — sem isso o caminho
   existiria só no papel, porque a leitura efetiva vem do snapshot do contrato;
3. **ela nunca concede o que está por baixo.** `tef` depende de `payments`: numa
   conta onde pagamentos não vale, ligar o TEF por exceção seria conceder
   pagamentos de graça. A exceção só vale quando tudo de que ela depende já está
   valendo, e só para capability **fora** da lista de vendáveis;
4. **ela tem fim.** Conceder, usar, revogar e sair. A revogação passa pelo mesmo
   caminho da concessão — o guarda de contrato versionado recusava a saída, e um
   ciclo pela metade é como uma exceção temporária vira permanente. E sair da
   fase de teste **encerra todas as exceções do tenant**, porque uma exceção que
   sobrevive à promoção seria exatamente o contrário do que ela existe para
   fazer: software incompleto valendo em piloto ou produção;
5. **ela não mexe em mais nada.** A concessão toca **uma** capability. Resolver
   dependências ali criaria ou reativaria linhas de capabilities contratadas — a
   exceção alterando o contrato pela porta de trás;
6. **ela está dita na trilha.** A auditoria usa ação própria
   (`platform.tenant.capability_homologation_override`) e grava o estado de
   implementação, o que falta, a versão do contrato e a fase do tenant. Sem
   isso, uma leitura futura veria a capability ligada e concluiria que ela foi
   vendida. E ela não serve de atalho para limites: mexer em
   `contract_limits` por essa via é recusado.

### 4. O que cada eixo governa

- **ativação comercial** — hoje governada por `IMPLEMENTED_CAPABILITIES` — passa
  a exigir `implementation = COMPLETE`. Vender software que não faz o trabalho é
  o que a lista existia para impedir, e é o que ela deixou passar. A exceção é o
  tenant em fase de teste, acima;
- **elegibilidade** não é gate: é diagnóstico. Uma capability `COMPLETE` fora de
  todo plano não está errada — está fora de catálogo, o que é decisão comercial
  legítima. Mas precisa **aparecer** como tal, em vez de sumir;
- **`homologation`** é gate de operação real para quem depende de terceiro —
  `tef`, `fiscal_nfce`, `fiscal_nfe`, `pix`. `PENDING` não impede contratar nem
  configurar; impede declarar operação homologada.

### 5. Onde isso aparece

- no Control, o grupo "Não disponíveis nesta composição" da tela de capabilities
  passa a dizer o motivo **certo**: hoje ele diz "exige outro plano" para a TEF,
  quando a razão mais forte é que a integração está incompleta;
- em "Saúde da plataforma", a lista de capabilities com `implementation`
  diferente de `COMPLETE`, para que a dívida tenha um lugar onde ser vista;
- e no próprio Mesh, como fonte única — nenhum consumidor recalcula prontidão.

## Como foi implementado

- `backend/app/modules/capabilities/readiness.py` — o registro, com validação no
  próprio dataclass: `PARTIAL` sem dizer o que falta e declaração sem evidência
  levantam erro na importação;
- `backend/app/modules/capabilities/eligibility.py` — a função contextual;
- `IMPLEMENTED_CAPABILITIES` passou a ser **derivado** de
  `sellable_capabilities()`, então os seis consumidores continuam funcionando
  sem saber que a fonte mudou;
- `backend/tests/test_capability_readiness.py` — nove testes, entre eles o que
  abre cada caminho de evidência declarado e o que compara a versão avaliada
  contra o registro. Roda no grupo que enxerga o repositório inteiro, ao lado de
  `test_surface_reachability.py`;
- `commercial_offer_service.resolve_offer` devolve a elegibilidade do catálogo
  inteiro para a composição proposta, e a tela do Control **lê** essa resposta
  em vez de repetir a regra em TypeScript — que é como duas verdades começam a
  divergir, e a versão do navegador nem enxergava dependências;
- as homologações viajam uma a uma, com a integração que cada uma atesta, do
  registro até o cartão na tela;
- na tela do Control, os três eixos aparecem separados no cartão, e
  "em desenvolvimento" deixou de se confundir com "fora do plano".

### 6. Prontidão governa contratar de novo, nunca continuar existindo

Reclassificar uma capability é descobrir uma verdade sobre o produto, não desfazer
um contrato assinado. Então a queda da NFC-e para `PARTIAL`:

- **não desliga quem já a contratou.** `effective_capabilities` lê o snapshot do
  contrato, e o que foi contratado continua valendo;
- **não trava a manutenção desse contrato.** O que o tenant já tem atravessa a
  cadeia **inteira** de composição e validação, senão trocar uma quota passaria a
  ser impossível para quem carrega a capability reclassificada. São três recusas
  diferentes no caminho, e todas precisavam saber do direito histórico: a
  prontidão (`selected_entitlement_keys`), a cobertura do plano — cuja versão
  corrente deixou de listar a capability — e a conferência final entre a seleção
  explícita e a proposta resolvida. Provado pela rota real de edição em
  `test_a_contract_carrying_nfce_can_still_be_edited_after_the_plan_dropped_it`;
- **não contamina o resto.** Um tenant no plano antigo segue contratando todas as
  demais capabilities normalmente;
- **impede contratá-la de novo**, que é o que o gate existe para fazer.

E a oferta corrente muda **por nova versão de plano**, nunca por edição do
passado: a migração que semeou os planos não é reescrita, e a nova revisão sai ao
lado da antiga, que continua existindo para os contratos que a assinaram. Quando
o gateway real existir, a NFC-e volta à oferta pela mesma porta — outra versão.

O caminho de volta é igualmente estreito: o downgrade reverte **somente** os
planos cuja versão corrente é a que a própria migração publicou, reconhecida pela
marca no motivo. Deduzir pela ausência da capability teria devolvido a NFC-e a um
plano que a retirou por conta própria antes — um downgrade que faz mais do que o
upgrade fez não é reversão, é edição. E o snapshot publicado não é apagado: a
tabela de revisões é append-only por gatilho, e uma oferta que foi publicada
continua tendo sido publicada; o que volta é o ponteiro do plano.

## Consequências

- `IMPLEMENTED_CAPABILITIES` deixa de ser um `frozenset` e vira um registro por
  capability. Os seis pontos que hoje o consultam
  (`commercial_requests`, `control`, `identity`, `niches`) passam a perguntar
  pelo eixo que lhes interessa, e não por um booleano genérico;
- **`tef` sai da lista de vendável** enquanto o transporte não existir. Isso é
  uma mudança de fato comercial, não de código, e é a razão de este ADR estar
  proposto e não aceito;
- capabilities já contratadas por algum tenant não são revogadas por este ADR.
  Prontidão governa o que pode ser **vendido de agora em diante**; retirar algo
  de um tenant vivo é decisão comercial com aviso, não efeito colateral de uma
  refatoração.

## O que este ADR não faz

Ele **não** encapsula cada capability em um módulo próprio. Essa é a dívida de
organização registrada no [ADR-029](adr-029-module-boundaries-and-owner-layer.md),
e continua de pé: o comportamento operacional segue distribuído pelos serviços e
telas dos domínios.

São problemas ortogonais, e vale não confundi-los: encapsular muda **onde o
código mora**; prontidão muda **o que o sistema afirma sobre si mesmo**. A
segunda é muito mais barata, não depende da primeira, e é a que teria evitado o
achado de hoje — porque nenhuma reorganização de pastas faria a TEF parar de se
declarar implementada.
