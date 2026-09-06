# ADR-030 — Estorno de parcela em conta aberta

**Status:** aceito
**Data:** 2026-09-06
**Decisão de produto ratificada por:** dono do SaaS, 06/09/2026
**Relacionado:** [ADR-004](adr-004-checkout-negotiation.md), [ADR-005](adr-005-payment-provider-bridge.md), [ADR-023](adr-023-immutable-payment-audit-productivity.md), [S25.1](../quality/s25-1-payment-recovery-acceptance.md)

## Contexto

O S25.1 fechou com um bloqueio declarado, e ele é estrutural: `REFUNDED` sobre
uma parcela **já confirmada** não tinha para onde ir. O estorno que existe,
`payment_service.refund_payment`, opera sobre `Payment`, e `Payment` só nasce em
`finalize_negotiation`. Uma parcela confirmada dentro de uma conta ainda aberta
— a mesa que continua servindo depois que o primeiro amigo pagou a sua parte —
não tem `Payment`, logo não tinha estorno.

O que o sistema fazia era o mínimo honesto: registrava `REFUND_REQUIRES_REVERSAL`,
não mexia no dinheiro e esperava uma pessoa. Duas rodadas de revisão do S25.1
recusaram atalhos que teriam liberado saldo pela palavra do provider — inclusive
uma correção minha que trocava o rótulo do erro e mantinha o problema.

Este ADR dá o lugar que faltava, sem afrouxar nenhuma daquelas recusas.

## Decisão

Estorno de parcela é um **fato próprio**, não uma mutação da parcela. A parcela
confirmada continua confirmada, com o valor, o autor e a data que sempre teve; o
estorno é escrito ao lado e o saldo da conta passa a ser lido como
`confirmado − revertido`.

### 1. Autoridade

Permissão própria, `checkout.payment.refund`, distinta de `checkout.payment`
(criar parcela) e de `checkout.payment.cancel` (devolver reserva não enviada).
Semeada em OWNER, TENANT_OWNER, ADMIN e MANAGER.

**CASHIER fica de fora, e isso é uma decisão em aberto, não um esquecimento.**
`checkout.payment.cancel` foi concedida a CASHIER, e a primeira versão desta
migração copiou aquela lista. Copiar estava errado, porque o argumento que
dispensa a segunda pessoa não se estende a esse perfil: quem ele protege é a
revendedora que trabalha sozinha, e ela não é um CASHIER — é a dona, e entra por
OWNER ou ADMIN. O perfil CASHIER só existe onde **há equipe**, que é justamente
o caso em que dinheiro saindo da gaveta pela mão de uma pessoa só merece ser
decidido de propósito.

Conceder depois é uma linha de migração. O contrário — descobrir que se concedeu
sem decidir — custa mais.

**Não existe aprovação obrigatória de uma segunda pessoa.** Quem tem a permissão
estorna sozinho. A revendedora que trabalha sozinha é a própria gerente, e uma
cerimônia de dois nomes só a impediria de devolver dinheiro ao cliente na frente
dele. O contrapeso é a trilha: autor nomeado, motivo obrigatório, auditoria e
outbox — não uma segunda pessoa que não existe.

### 2. Valor comprovadamente revertido

Um estorno **pedido** nunca move saldo. Só o valor **provado como revertido**
move, e o que conta como prova depende da rota pela qual o dinheiro entrou:

| Rota da parcela | Prova aceita | Efeito |
|---|---|---|
| `CASH` | o movimento compensatório de caixa, com o dinheiro saindo da gaveta | confirma no ato |
| rota de provider (cartão/TEF) | a resposta do provider **declarando o valor revertido** | confirma quando a resposta chega |
| manual (PIX na mão, sem dispositivo declarado) | a declaração de quem estorna, nomeada e auditada | confirma no ato |

A simetria é deliberada: o que confirma a entrada do dinheiro é o que comprova a
sua saída. Dinheiro na gaveta entrou por movimento de caixa e sai por movimento
de caixa. PIX na mão entrou pela palavra de uma pessoa e sai pela palavra de uma
pessoa, com nome. Cartão entrou pela resposta do adquirente e só sai por ela.

Enquanto a prova não chega, o estorno fica `PENDING`: **nada é liberado, nada é
improvisado**. É a mesma recusa da terceira rodada do S25.1, agora com um lugar
para esperar em vez de uma divergência sem desfecho.

### 3. Valor declarado pelo provider

O contrato do adapter passa a carregar `refunded_amount`. Sem ele, "estornado" é
uma palavra sem quantia, e foi exatamente por isso que a terceira rodada do S25.1
recusou liberar a reserva inteira pela palavra do provider: estorno pode ser
parcial.

- resposta com valor declarado → estorno confirmado por aquele valor;
- resposta sem valor → **continua** virando divergência, e o saldo não se move.

### 4. Parcela aberta com estorno externo

Para parcela ainda **não confirmada**, a reserva é tudo ou nada: ela segura uma
linha inteira da conta, e não existe meia reserva. Então:

- reversão declarada **igual** ao valor da parcela → a parcela fecha como
  `FAILED` com `REFUND_WITHOUT_CAPTURE` e a linha volta a ficar disponível;
- reversão **parcial** ou sem valor → a reserva **permanece** e a divergência
  segue esperando uma pessoa.

### 5. Estorno parcial de parcela confirmada

Suportado. O estorno carrega as suas próprias alocações por item, espelhando as
da parcela:

- por item, o revertido nunca passa do que **aquela parcela** alocou nele;
- por parcela, a soma dos estornos confirmados nunca passa do valor da parcela;
- a parcela sem alocação de item — quem pagou a conta toda em vez da sua parte —
  estorna sem alocação, e o valor sai do montante não atribuído.

O item volta a ficar disponível na medida do que foi revertido, e outra pessoa
pode pagá-lo. É o mesmo saldo por item do S25, lido com uma subtração a mais.

### 6. Caixa aberto, da mesma unidade

Estorno em dinheiro exige sessão de caixa **aberta** e **da mesma unidade** da
negociação, porque o dinheiro sai fisicamente de uma gaveta que alguém vai
conferir no fechamento. Sem caixa aberto, a recusa é explícita
(`REFUND_NEEDS_OPEN_REGISTER`) e o estorno não é registrado como pendente: não
há nada esperando, há uma condição a satisfazer.

Estorno por cartão e por rota manual não dependem de caixa: nenhum dos dois
mexe na gaveta.

### 7. Idempotência

`Idempotency-Key` obrigatório, com hash do corpo, no mesmo padrão de
`create_intent` e `cancel_intent`: a mesma chave com o mesmo comando devolve a
mesma projeção; a mesma chave com comando diferente responde `409`. Dois toques
no botão são um estorno.

### 8. Preservação da trilha financeira

Nada é apagado nem reescrito:

- a `PaymentIntent` confirmada mantém `amount`, `confirmed_by` e `confirmed_at`;
- as `PaymentAllocation` da parcela não são tocadas;
- o movimento de caixa da entrada permanece; a saída é um movimento `REFUND`
  novo, com origem apontando para o estorno;
- a cadeia do Gate D ([ADR-023](adr-023-immutable-payment-audit-productivity.md))
  recebe o estágio do estorno como evento **anexado**, nunca como correção de um
  evento anterior;
- auditoria e outbox saem na mesma transação, por `write_audit_and_outbox`.

Uma conta que teve estorno mostra as duas coisas: que o dinheiro entrou, e que
voltou. Nenhuma leitura futura consegue confundir isso com "nunca entrou" — que é
precisamente a mentira que o S25.1 se recusou a contar quando tratava estorno
como cancelamento de reserva.

## Consequências

- `finalize_negotiation` passa a materializar a venda pelo líquido: confirmado
  menos revertido. Uma conta estornada até zero volta a dever o que devia;
- a projeção ganha, por parcela, `refunded_amount` e `can_refund`, e a tela deixa
  de precisar deduzir autoridade;
- `REFUND_REQUIRES_REVERSAL` deixa de ser um beco: a divergência é resolvida pelo
  estorno que a originou, e permanece no histórico como o fato que foi;
- o `refunded_amount` no contrato do bridge é mais uma razão para o transporte de
  comandos existir antes de qualquer homologação com adquirente
  ([lacuna do bridge](../product/bridge-command-transport.md));
- estorno **depois** de `finalize_negotiation` continua sendo o fluxo antigo,
  sobre `Payment`. Este ADR não o substitui; ele cobre a janela em que a conta
  ainda está aberta, que era a janela sem saída;
- a tabela nova é `payment_intent_refunds`. `payment_refunds` já existia desde a
  migração `033` para o estorno da venda finalizada, e os dois convivem de
  propósito: são janelas diferentes da mesma história.

### Limite conhecido, deixado aberto de propósito

A `TableSession` marcada `PARTIALLY_PAID` pela primeira confirmação **não volta**
para `IN_SERVICE` quando a conta é estornada até zero. A mesa continua viva e
operável nos dois estados, e nenhuma decisão financeira depende disso — o saldo
é lido da negociação, não da sessão. Reclassificar estado de mesa a partir de
movimento financeiro é decisão de serviço, não de pagamento, e não se resolve
dentro deste contrato.

## O que este ADR não decide

- estorno de venda finalizada, que já tem dono em `payment_service`;
- devolução de mercadoria, estoque ou nota fiscal: reverter dinheiro não é
  desfazer consumo, e a mesa que bebeu o whisky continua tendo bebido;
- cancelamento de item, que é do S12 e mexe na comanda, não no pagamento.
