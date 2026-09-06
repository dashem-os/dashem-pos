# Transporte de comandos do bridge TEF — trabalho interno

Status: **aberto, não iniciado** · registrado em 06/09/2026
Origem: revisão das pendências de S23/S25/S25.1 em 06/09/2026

## A lacuna, dita sem rodeio

O servidor sabe pedir uma cobrança e sabe receber a resposta. Ele **não sabe
entregar o pedido**.

- `BridgeQueuedAdapter.start` devolve `PROCESSING` e diz, no próprio docstring,
  que enfileira o trabalho — mas não existe fila que o bridge possa ler;
- o bridge tem `POST /bridge/terminals` (pareamento),
  `POST /bridge/terminals/{id}/heartbeat` (presença) e
  `POST /bridge/terminals/{id}/transactions/{id}/result` (resposta);
- **não existe** rota pela qual o bridge descubra que um comando foi emitido, nem
  entrega por outbox. Uma varredura por `poll`, `pending_command` ou `/commands`
  em `backend/app` não encontra nada.

Consequência prática: hoje, com adquirente contratado e pinpad na mão, nenhuma
cobrança sairia. A máquina nunca ficaria sabendo que foi pedida.

Isso não é gate externo esperando terceiro. É trabalho nosso, e ele vem **antes**
de qualquer conversa de homologação, porque a certificação testa exatamente esse
caminho.

## Achado de 06/09/2026: a superfície de configuração também está inalcançável

Antes ainda do transporte, existe um degrau menor e mais simples de corrigir: **a
capability `tef` não pode ser contratada por nenhum tenant hoje.**

- a navegação "Provedores de pagamento" (`/manage/payment_providers`, migração
  `072`) é oferecida pela capability `tef`;
- as permissões `provider.read`, `provider.configure` e `provider.execute` têm
  `capability_key = 'tef'`, então sob `AUTH_MODE=required` elas são negadas com
  "Capability is not contracted" mesmo por API;
- três atividades comerciais oferecem `tef` como **OPCIONAL** (`FOOD_SERVICE`,
  `RETAIL`, `BEAUTY_RESELLER`, migração `060`);
- mas a tela de capabilities do Control só mostra um add-on quando a atividade o
  sugere **e** o plano o torna elegível — e **nenhum dos quatro planos semeados
  na migração `056` inclui `tef`** em `capability_keys`.

O resultado é uma capability que existe, é ofertada por três atividades, tem
navegação, permissões e código — e nunca chega a um tenant.

**Saída, sem tocar em código:** em *Planos comerciais → Editar plano*, marcar TEF
em "Capabilities incluídas no plano" e salvar a nova versão; depois, no tenant,
reselecionar o plano e marcar TEF na aba Capabilities. Vale conferir se a versão
nova do plano é a que a proposta do tenant está lendo.

**Saída definitiva:** semear `tef` nos planos em que ele faz sentido comercial, em
migração própria, para que o degrau não reapareça em cada tenant novo. Fica como
primeiro item desta frente, porque nem a frente B nem a C podem ser exercitadas
sem ele — e porque ele bloqueia hoje o aceite dos cenários de cartão do S25.1 no
ambiente publicado.

## Três frentes que não devem ser tratadas como uma

Elas foram sendo faladas como se fossem "homologação com provider real". Não são,
e misturá-las é o que faz a última parecer bloqueada por dinheiro quando está
bloqueada por código.

| # | Frente | Natureza | Depende de terceiro? |
|---|---|---|---|
| A | **Transporte de comandos** — o bridge recebe o que foi pedido e devolve o que aconteceu | interna, nossa | **não** |
| B | **Integração ao SDK** do adquirente escolhido — o agente local fala com o pinpad | interna, por provider | escolha do provider e SDK |
| C | **Certificação e homologação** — o adquirente atesta a integração | externa | **sim** |

A é testável ponta a ponta sem nenhum adquirente, com um bridge de referência
nosso. B só começa depois que A existe, e depois que o provider está escolhido.
C só começa depois de B, e é a única que exige contrato comercial.

## Frente A — critérios de aceite

Cada critério vale por prova executável, não por leitura de código. Nenhum deles
precisa de adquirente.

1. **Entrega dirigida.** Um bridge pareado obtém os comandos destinados àquele
   terminal, e somente a ele. Terminal de outro tenant, de outra unidade ou de
   outro caixa não vê o comando, e a recusa não revela que ele existe.
2. **Uma cobrança, um comando.** Reentregar o mesmo comando não abre segunda
   `ProviderTransaction` nem segunda cobrança. A idempotência é a que já existe
   em `execute_transaction`, exercida agora pelo transporte.
3. **Comando perdido volta.** Um comando entregue e não confirmado retorna à fila
   depois do lease vencido, e o retorno reconcilia a transação em voo em vez de
   criar outra — o mesmo desenho de `claim_next_event` na outbox (ADR-027).
4. **Ordem por terminal.** Comandos do mesmo terminal chegam em ordem, e um
   comando novo nunca ultrapassa um que está em voo naquele pinpad.
5. **Offline não perde.** Bridge que cai e volta recebe o que ficou pendente para
   ele; nada é descartado pelo relógio. Vale a regra do S25.1: ausência de
   resposta nunca é prova de ausência de cobrança.
6. **Estorno viaja pelo mesmo caminho.** Reversão e cancelamento são comandos
   como a cobrança, e a resposta de estorno carrega `refunded_amount`, sem o qual
   nenhuma baixa acontece ([ADR-030](../architecture/adr-030-open-account-parcel-reversal.md)).
7. **Autoridade do dispositivo.** A autenticação é o segredo de pareamento que já
   autentica o callback. Terminal pausado ou revogado não recebe comando, e o
   segredo é rotacionável sem reparear o pinpad.
8. **Nada sensível na carga.** Nenhum PAN, trilha, senha ou segredo entra no
   comando, no log ou na evidência. O que trafega é identificador, valor e rota.
9. **Latência medida.** O tempo entre emitir o comando e ele estar disponível ao
   bridge é medido e registrado, com alvo declarado. Um operador não fica
   olhando para o pinpad sem saber se o pedido saiu.
10. **A fila é visível para uma pessoa.** Comando parado e resultado que não pôde
    ser aplicado aparecem em alguma tela, não só em log. O drill de reinício de
    06/09 encontrou 12 transações terminais ao lado de parcelas abertas que a
    varredura retenta a cada 60 segundos, para sempre, e que só existem como
    traceback ([evidência](../quality/s25-1-staged-restart-drill.md)). O código
    diz que a linha "fica para uma pessoa"; nada avisa pessoa alguma.

### Decisão de desenho a tomar dentro da frente A

Recomendação: **long-poll HTTP de saída, iniciado pelo bridge**. O bridge vive na
rede do lojista, atrás de NAT, sem endereço estável; ele já fala com o servidor
por heartbeat e por callback. Inverter isso exigiria abrir porta no
estabelecimento, que é pior de operar e pior de defender. WebSocket resolveria o
mesmo problema com mais estado a manter e sem ganho no volume de um PDV.

A decisão merece registro próprio quando a frente começar; não está tomada.

## Frente B — o que ela é, para não ser confundida com A

Um agente local que fala com o SDK do adquirente escolhido e traduz os comandos do
transporte em chamadas ao pinpad. É código nosso, mas é **por provider**, e a
forma dele depende do SDK: alguns são DLL Windows, outros serviço local, outros
biblioteca em outra linguagem. Nada disso condiciona a frente A, e é por isso que
elas estão separadas.

## Frente C — o gate externo

Contrato com adquirente, terminal físico homologado, bateria de certificação do
provider. É a única frente que depende de decisão comercial, e a única em que o
DASHEM não controla o cronograma.

## O que este documento não faz

Não estima prazo, não escolhe provider e não abre a frente. Ele registra a lacuna
como trabalho interno com critérios próprios, para que ela pare de aparecer
escondida dentro de "homologação com provider real" — que é a frente C, e que
não pode nem começar enquanto a A não existir.
