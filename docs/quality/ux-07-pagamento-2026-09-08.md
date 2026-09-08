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

`frontend/e2e/presentation/ux07_pagamento.cjs` monta uma venda e força o
timeout. Evidência em [`evidence/ux-07/`](evidence/ux-07/).

| Medida | Resultado |
|---|---|
| Carimbo na criação | um só, e é o mesmo em qualquer tentativa da mesma intenção |
| Carimbo na confirmação | derivado dele, com sufixo `-confirm` |
| O que ficou no banco | **1 pagamento, R$ 32,00 confirmados, venda paga** |

O roteiro **deixou de reenviar** depois que a conduta mudou: consultar
substituiu cobrar de novo. O carimbo continua sendo a rede de segurança de quem
insistir, e o teste HTTP no backend continua provando que a mesma intenção
reenviada não abre um segundo pagamento.

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

## A pendência ficou visível, e a ação é consultar

*Direção do dono em 08/09/2026: consultar primeiro; timeout não significa
recusa; reenvio só com idempotência garantida; cancelamento só depois de
confirmação efetiva.*

**A auditoria da integração veio antes do desenho**, e mudou o desenho. O que a
integração de pagamento sabe fazer hoje:

| Capacidade | Existe? |
|---|---|
| Consultar o pagamento registrado no Dashem (`GET /payments?sale_id=`) | **sim** |
| Interrogar um adquirente externo sobre a transação | **não** — o provedor em uso é `ManualOperatorPaymentProvider`, sem contraparte externa |
| Reconciliar uma execução TEF (`POST /providers/transactions/{id}/reconcile`) | sim, mas o PDV não usa esse caminho |
| Ler o estado de uma execução por `GET` | **não existe rota** |

Então "consultar a transação existente" é, hoje, consultar **o registro
autoritativo do próprio Dashem** — e isso basta para separar os três casos que
decidem a conduta do operador: já confirmada, existe e aguarda, ou nunca
existiu.

Quando a resposta não volta, a tela deixa de dizer "erro" e passa a dizer:

> **Pendente de confirmação** — A resposta da cobrança de R$ 32,00 não voltou.
> Isso **não quer dizer que ela foi recusada** — pode ter sido confirmada.
> Consulte antes de qualquer outra coisa.  → **Verificar pagamento**

E a consulta resolve, com o título acompanhando o estado apurado:

| O que a consulta apura | O que a tela passa a dizer |
|---|---|
| Pagamento confirmado | **Cobrança confirmada** — "tinha sido confirmada: R$ 32,00 recebidos. Nada a refazer." |
| Pagamento pendente | **Cobrança registrada, ainda sem confirmação** — consulte de novo; não cobre outra vez |
| Nenhum pagamento | **Nenhuma cobrança foi registrada** — é seguro tentar novamente |
| Consulta indisponível | **Não foi possível consultar** — leve para conferência antes de cobrar de novo |

Três decisões que sustentam isso:

- **`consultarPagamentosDaVenda` falha alto.** A função que já existia devolvia
  lista vazia quando a chamada não dava certo — aceitável ao montar a tela, e
  perigoso numa consulta: "não consegui perguntar" ficaria indistinguível de
  "nada foi cobrado".
- **Consultar nunca cobra.** Um teste estático verifica que a função de consulta
  não chama `createPayment` nem `confirmPayment`.
- **Nenhuma nova cobrança nem cancelamento é oferecido** enquanto a pendência
  não se resolve. Cancelar só se anunciaria depois de confirmação efetiva, e a
  integração não dá essa confirmação hoje.

### A prova, com o timeout de verdade

O roteiro deixa a requisição de confirmação **chegar ao servidor** e descarta a
resposta — que é o timeout que importa, não o que nunca saiu. Resultado:

| Medida | Resultado |
|---|---|
| A tela mostra pendência, não erro | "Pendente de confirmação… não quer dizer que ela foi recusada" |
| A consulta resolve | "Cobrança confirmada… R$ 32,00 recebidos. Nada a refazer." |
| O que ficou no banco | **1 pagamento, R$ 32,00 confirmados, venda `PAID`** |

Controle: removida a pendência, o roteiro reprova por não achar "Verificar
pagamento". E o olho pegou o que a medida não perguntava — o título continuava
"Pendente de confirmação" depois de a consulta resolver, contradizendo o texto
abaixo dele. Agora o título acompanha o estado, e a medida exige isso.

## Portões executados

| Portão | Resultado |
|---|---|
| `ux07_pagamento.cjs` | 5 medidas, 4 telas, 0 falhas, com o timeout de verdade |
| `ux05_modulos.cjs` | 8 auditados, 0 achados |
| `npm test` | 198 passando, 0 falhas |
| `npm run build` | limpo |
| `pytest` do backend | 543 passando, com os dois servidores no ar |

## O que continua fora

O estado **em processamento** — a cobrança em curso num terminal TEF — não tem
representação, porque o PDV não usa o caminho de execução de provedor. Quando
usar, ele terá de distinguir esse quarto estado, e aí a rota de consulta por
`GET` de execução, que hoje não existe, passa a fazer falta.
