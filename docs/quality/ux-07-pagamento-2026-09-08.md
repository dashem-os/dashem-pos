# UX-07 — o reenvio depois do timeout parou de cobrar duas vezes

Data: 08/09/2026 · base: [UX-06](ux-06-pdv-2026-09-08.md) ·
trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md).

O aceite proíbe "segunda cobrança por ambiguidade" e nomeia o cenário: *timeout
após envio, retomada e cancelamento*. Auditando antes de mexer, o cenário estava
aberto.

## O que estava aberto, e o que não estava

Duas guardas **já existiam** e continuam:

- confirmar o mesmo pagamento duas vezes é seguro — `payment_service` retorna
  cedo quando o status já é `CONFIRMED`;
- criar pagamento numa venda já `PAID` é recusado — *"Cannot add payment to sale
  in status 'PAID'"*.

O que faltava era o meio do caminho. **`POST /api/v1/payments` não era
idempotente.** Se a criação passa e a confirmação estoura — o timeout depois do
envio —, a venda continua `AWAITING_PAYMENT`: repetir a operação criava um
**segundo** pagamento e o confirmava, enquanto o primeiro ficava pendente. Se o
provedor capturou o primeiro, são duas cobranças.

Em pagamento **dividido** é pior: entre as parcelas a venda nunca chega a `PAID`,
então nenhuma das duas guardas existentes atrapalha a repetição.

E a chave que a tela mandava na confirmação era
`pay-idemp-${pay.id}-${Date.now()}` — **nova a cada tentativa**. Carimbo por
tentativa não protege reenvio nenhum.

## A correção, dos dois lados

**No servidor**, `POST /api/v1/payments` passou a aceitar `Idempotency-Key`,
espelhando exatamente o que `/confirm` e `/inventory/adjust` já fazem com
`reliability_service`. Vale para qualquer cliente, não só para esta tela.

**Na tela**, uma chave por intenção, usada nos dois passos — criar e confirmar.
E a decisão que custou uma rodada: **a chave não pode nascer de um efeito**.
Efeito roda de novo quando o React quer, e o carimbo trocava entre a tentativa
que falhou e o reenvio. Ela passou a ser derivada do que define a intenção:

    método : valor : quantas parcelas já foram confirmadas

Método e valor porque cobrar R$ 25 no cartão é outra coisa que R$ 25 em
dinheiro. E a contagem de parcelas porque **duas parcelas de R$ 25 na mesma
venda são duas intenções** — sem isso, a segunda seria deduplicada como
repetição da primeira, e metade do dinheiro sumiria. Uma tentativa que falha não
mexe em nenhum dos três, então o reenvio reusa o mesmo carimbo, que é o que se
quer.

## Um defeito que eu mesmo introduzi, e a medida pegou

Ao adicionar a idempotência à criação, a rota passou a responder `{}` — corpo
vazio. O `session.commit()` expira a instância do SQLModel, e o FastAPI
serializava um objeto já sem atributos. O corpo passou a ser serializado
**antes** do commit e devolvido como corpo, igual ao caminho do cache. Sem o
diagnóstico passo a passo, isso teria ido para produção como "pagamento
funciona, resposta vazia".

## O que a medida devolve

`frontend/e2e/presentation/ux07_pagamento.cjs` monta uma venda, **aborta a
confirmação na rede** — o timeout depois do envio, forçado — e reenvia.
Evidência em [`evidence/ux-07/`](evidence/ux-07/).

| Medida | Resultado |
|---|---|
| Carimbo na criação | `46e846fe…` nas duas tentativas — o mesmo |
| Carimbo na confirmação | `46e846fe…-confirm` nas duas — derivado da mesma intenção |
| O que ficou no banco | **1 pagamento, R$ 32,00 confirmados, venda `COMPLETED`** |

E quatro provas HTTP no backend: a mesma intenção reenviada não abre um segundo
pagamento; sem chave, o reenvio abre dois — que é por que a chave existe do lado
do cliente; intenções diferentes continuam sendo pagamentos diferentes, e a
soma bate com o total; confirmar duas vezes continua confirmando uma.

### Os controles

- Removi a verificação de idempotência da criação: a prova acusou dois
  identificadores diferentes de pagamento para a mesma intenção.
- A primeira versão da chave, nascida de um efeito, **foi reprovada pela própria
  medição** antes de eu perceber o problema — o roteiro mostrou dois carimbos
  distintos entre a tentativa e o reenvio.

## Portões executados

| Portão | Resultado |
|---|---|
| `ux07_pagamento.cjs` | 3 medidas, 4 telas, 0 falhas, com o timeout forçado |
| `ux05_modulos.cjs` | 8 auditados, 0 achados |
| `npm test` | 195 passando, 0 falhas |
| `npm run build` | limpo |
| `pytest` do backend | suíte completa, com os dois servidores no ar |

## O que fica nomeado, não entregue

O enunciado também pede distinguir na tela **recusado, em processamento,
confirmado e pendente de confirmação**. Hoje a tela distingue confirmado de
falha, e o "pendente de confirmação" — o pagamento criado cuja confirmação não
voltou — existe no banco e **não tem representação visual**: quem reenvia hoje
acerta por causa do carimbo, não porque a tela lhe explicou o estado.

Essa é a metade não entregue da UX-07, e ela precisa de decisão de produto sobre
o que oferecer nesse estado (reenviar, consultar o provedor, cancelar). Fica
registrada aqui em vez de ser declarada pronta. O que esta sprint fechou foi o
buraco por onde saía a segunda cobrança.
