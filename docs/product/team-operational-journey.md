# Jornada operacional da equipe — auditoria e contrato proposto

Status: **pendência funcional registrada**, contrato proposto · 06/09/2026
Origem: pedido do dono do SaaS em 06/09/2026

O produto sabe quem fez cada coisa. O que ele não sabe é **contar o trabalho de
uma pessoa** — e essas duas afirmações convivem sem se contradizer, porque
autoria é um fato por linha e trabalho é uma leitura por pessoa ao longo de um
turno. Este documento audita o que existe, nomeia o que falta, e propõe o
contrato da jornada que falta.

## O que já existe, e é sólido

| Peça | Onde | O que sustenta |
|---|---|---|
| Autoria por item | `OrderItem.added_by`, `canceled_by`, `cancellation_reason` | quem lançou e quem cancelou cada linha da comanda |
| Autoria por ação | `OrderCommand.actor_id`, `NegotiationEvent.actor_id`, `TableSessionEvent.actor_id`, auditoria e outbox | quem executou cada comando, com trilha imutável |
| Ator não declarável | Gate A: `resolve_actor` recusa ator declarado diferente do autenticado | a autoria é do servidor, não do cliente |
| Cadeia de pagamento | `PaymentExecutionEvent` (Gate D) | tenant, loja, caixa, dispositivo, sessão e ator de cada cobrança |
| Vendedor da venda | `Sale.seller_id` | quem vendeu no balcão |
| Sessão operacional | `OperationalSession` — `started_at`, `last_seen_at`, `ended_at`, `end_reason` | quando a credencial esteve ativa num terminal |
| Fechamento de caixa | `CashSession` | abertura e conferência **do caixa**, com saldo apurado |

**A autoria por item e por ação, que o pedido menciona, já existe.** Ela é
server-authoritative e imutável. O que não existe é onde lê-la.

E isso tem uma consequência prática que o contrato abaixo não deve esconder:
**uma primeira leitura por pessoa já é construível hoje**, sem esperar nada. Itens
lançados, itens cancelados com motivo, e comandos executados — tudo isso já está
gravado com autor. Uma tela de "o que eu lancei hoje" não depende de nenhum dos
seis contratos; depende de consultar o que já existe.

O que ela **não** conseguirá dizer sem os contratos é quanto disso é atendimento,
quanto tempo durou, e quanto do valor é de quem. Entregar a leitura possível cedo,
dizendo com clareza o que ela ainda não responde, vale mais do que esperar o
conjunto inteiro.

## As duas armadilhas, confirmadas pela auditoria

**O painel do Gate D não é produtividade do atendente.**
`OperationalProductivityProjection` conta `requested`, `approved`, `executed`,
`confirmed`, `failed` e os valores correspondentes — tudo isso é **cadeia de
pagamento**. Por construção ele só enxerga quem operou a cobrança. Um atendente
de salão que abriu a mesa, lançou quarenta itens e passou o atendimento antes do
fechamento aparece com **zero**. Usar esse painel como produtividade premiaria
quem fica no caixa e apagaria quem trabalha no salão. Ele responde bem a outra
pergunta — "quem autorizou este dinheiro" — e deve continuar respondendo só ela.

**Sessão conectada não é jornada trabalhada.** `OperationalSession` tem
`started_at` e `last_seen_at`, mas isso é heartbeat de credencial, não trabalho:
a sessão expira sozinha, cai quando o gestor pausa o terminal, é revogada por
troca de função, e a mesma pessoa em dois terminais gera duas sessões. Somar
sessão daria número para quem esqueceu a tela aberta e tiraria de quem trocou de
terminal no meio do turno.

## O que não existe

1. **Atendimento não é um fato.** `TableSession` não tem responsável. Existem
   mesa aberta e itens lançados; não existe "atendimento" como coisa contável.
   Sem isso, "meus atendimentos" não tem o que contar.
2. **Não há superfície do operador.** O único painel de produtividade é de
   Gestão, por operador e turno, e conta pagamento. A pessoa não tem onde ver o
   próprio dia.
3. **Não há passagem de atendimento.** O S12 transfere **itens** entre comandas e
   mesas; ninguém transfere **responsabilidade** entre pessoas. Quem assume uma
   mesa no meio do turno não herda nada, e quem sai continua figurando como autor
   de tudo o que virá depois na leitura por mesa.
4. **A prestação de contas é do caixa, não da pessoa.** Duas pessoas no mesmo
   caixa num turno não conseguem responder cada uma pelo que recebeu. O estorno
   do [ADR-030](../architecture/adr-030-open-account-parcel-reversal.md), que
   tira dinheiro da gaveta, entra no mesmo bolo.
5. **Não existe taxa de serviço.** Nada: nem cobrança, nem recusa pelo cliente,
   nem base de cálculo, nem rateio, nem o que acontece com ela num estorno. Para
   um PDV brasileiro que atende mesa, isso é lacuna de produto, não detalhe.

## Contrato proposto

Seis contratos, na ordem em que se sustentam. Os três primeiros são fundação; os
três últimos só fazem sentido sobre eles.

### 1. Atendimento — o fato que falta

Uma pessoa responsável por uma mesa ou comanda durante um intervalo. Abre quando
alguém assume, fecha quando passa adiante ou quando o atendimento encerra. Uma
mesa pode ter vários atendimentos em sequência; um atendimento tem sempre uma
pessoa.

É isto que torna "meus atendimentos" contável, e é o lastro da passagem. Sem ele,
os outros cinco não têm sobre o que se apoiar.

**Duas contagens, não uma.** *Período de responsabilidade* e *mesa atendida* são
grandezas diferentes, e somá-las como se fossem a mesma coisa infla o indicador:
uma mesa que passou por três pessoas viraria três atendimentos, e o total da
equipe mostraria o triplo do salão que existe. A leitura precisa dizer as duas —
quantas mesas a pessoa atendeu, e por quantos períodos respondeu — e nunca
apresentar a segunda com o nome da primeira.

**Invariante:** o atendimento **não** reescreve autoria. O item que eu lancei
continua meu depois de eu passar a mesa. Responsabilidade e autoria são coisas
diferentes, e confundi-las apagaria o trabalho de quem saiu.

### 2. Passagem de atendimento

Transferir responsabilidade é fato próprio: quem passou, quem recebeu, quando, e
o que estava aberto naquele instante. Fecha um atendimento e abre outro na mesma
transação.

**Invariante:** a passagem não move dinheiro nem itens. Quem recebe assume o que
vem **a partir dali**; o que já aconteceu continua com quem fez.

### 3. Jornada declarada, separada da sessão

Começo e fim por ato explícito, com pausa, sobrevivendo a troca de terminal e a
expiração de sessão. A sessão continua sendo o que **autentica**; a jornada passa
a ser o que se **mede**.

**Invariante:** jornada é declarada, nunca inferida de heartbeat. Uma tela
esquecida aberta não gera jornada, e uma pessoa que trocou de terminal não gera
duas.

**E declarada é tudo o que ela é.** A jornada registra o que alguém afirmou, não
o que aconteceu — tornar a declaração obrigatória melhora a cobertura do dado e
**não** torna o tempo confiável por si só. Quem esquece de encerrar continua
gerando jornada longa demais; quem esquece de abrir some do relatório. Se o
número precisar sustentar decisão de pagamento, ele terá que ser confrontado com
outra evidência — atividade registrada no período, por exemplo — e essa
confrontação é contrato à parte, não efeito colateral da obrigatoriedade.

### 4. Minhas vendas e atendimentos

Projeção do lado do operador, reconstruível a partir dos eventos imutáveis que já
existem, cobrindo pelo menos: itens lançados, atendimentos conduzidos, vendas em
que participou, valores que recebeu, e tempo de jornada. Nunca só pagamento.

**Invariante:** é leitura, não fonte. Como a projeção do Gate D, precisa ser
reconstruível — e reconstruir precisa dar o mesmo número.

### 5. Prestação de contas por pessoa

O que passou pelas mãos de cada um dentro de um caixa: recebido em dinheiro,
estornado, sangria, suprimento. Fecha por pessoa e **concilia** com o fechamento
do caixa, que continua sendo do caixa.

**Invariante:** a soma das prestações de contas de um turno bate com o
fechamento daquele caixa, ou a divergência é registrada como fato — a mesma
regra que o S25.1 aplicou a pagamento.

### 6. Ciclo da taxa de serviço

Cobrança sugerida sobre uma base declarada, recusa do cliente registrada como
fato (e não como valor apagado), rateio entre quem atendeu, e comportamento
definido no estorno — se o cliente recebe de volta, a taxa correspondente
também volta.

**Invariante:** a taxa é sugerida e recusável. Registrar a recusa importa tanto
quanto registrar a cobrança, porque é dela que sai a conversa com a equipe sobre
o que foi rateado.

## Decisões que são do dono, não minhas

1. **A taxa de serviço é rateada como?** Por atendimento conduzido, por valor
   atendido, por tempo de jornada, ou igualmente entre quem estava no turno? A
   escolha muda o contrato 6 inteiro, e muda o incentivo da equipe.
2. **Passar atendimento exige aceite de quem recebe**, ou o gestor empurra? Vale
   lembrar a revendedora que trabalha sozinha: uma cerimônia de duas pessoas não
   pode ser regra universal.
3. **A jornada declarada é obrigatória** para operar, ou opcional? Obrigatória
   melhora a **cobertura** do dado — menos gente de fora do relatório — e cria
   fricção no balcão de uma pessoa só. O que ela **não** faz é tornar o tempo
   confiável: continua registrando o que foi declarado, e quem esquece de
   encerrar segue produzindo jornada longa demais.
4. **Quem vê o quê.** "Minhas vendas" é do próprio operador; o consolidado da
   equipe é de quem? Isso decide permissões, e é o tipo de coisa que não se
   descobre depois.
5. **Como se conta participação compartilhada, cancelamento e estorno.** Uma mesa
   atendida por duas pessoas não pode contar o valor cheio para as duas — a soma
   da equipe passaria a ser maior que o faturamento, e qualquer prêmio calculado
   sobre isso pagaria duas vezes o mesmo dinheiro. As três perguntas são a mesma
   pergunta:
   - **compartilhado** — rateio proporcional ao que cada um lançou, divisão por
     período de responsabilidade, ou crédito integral para quem fechou?
   - **cancelamento** — o item cancelado sai do total de quem o lançou, de quem o
     cancelou, ou de ninguém?
   - **estorno** — o valor devolvido reduz o total de quem recebeu, e a taxa de
     serviço correspondente volta atrás junto?

   Sem essa decisão, cada leitura escolheria sozinha, e duas telas do mesmo
   produto dariam números diferentes para a mesma pessoa.

## Prontidão, para não repetir o erro da TEF

Se esta jornada ganhar capability própria, ela nasce
`implementation: NONE` no registro do
[ADR-031](../architecture/adr-031-capability-readiness.md) — nada aqui está
construído. Nenhum plano deve oferecê-la antes de existir, e a tela do Control
dirá "em desenvolvimento" em vez de "fora do plano".

## O que este documento não faz

Não implementa nada, não estima prazo e não escolhe entre as cinco decisões
acima. Ele registra a pendência com contorno suficiente para ser contratada — e
deixa explícito o que **não** pode ser usado como atalho: o painel do Gate D não
vira produtividade do atendente, e sessão conectada não vira jornada trabalhada.
