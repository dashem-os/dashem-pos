# S25.1 — reinício encenado, contra a pilha real

Data: 6 de setembro de 2026 · commit `05d6eff` · pilha local em contêineres
Roteiro: [`scripts/staged_restart_drill.py`](../../scripts/staged_restart_drill.py)

A matriz de aceite do S25.1 registrava, em três rodadas seguidas, a mesma
lacuna: *"um `docker restart` encenado continua não existindo"*. O que estava
provado era que o estado sobrevive a outra sessão e a outro processo, e que a
falha entre os dois commits é recuperável quando encenada **dentro** do banco.
Nenhum processo tinha sido derrubado de verdade com uma cobrança em aberto.

Este drill derruba. A API e o worker são reiniciados por `docker restart` com uma
cobrança registrada e sem desfecho, e o roteiro fica no repositório para ser
repetido.

## O que o drill dirige, e o que ele explicitamente não é

Nada é simulado por adaptador de teste. `ENVIRONMENT=development` resolve para
o `BridgeQueuedAdapter`, que é o adaptador de produção: ele devolve `PROCESSING`
e nunca presume aprovação. A cadeia montada é a real — configuração de provider,
bridge pareado com heartbeat `ONLINE`, dispositivo de POS e vínculo `TEF_BRIDGE` —
e a resposta entra pelo callback autenticado pelo segredo de pareamento.

**Nenhuma cobrança real acontece, e nenhum comando chega a pinpad nenhum.** Não
poderia: o transporte de comandos ao bridge não existe
([frente A](../product/bridge-command-transport.md)). O que `start` faz é
registrar no servidor uma cobrança cujo desfecho só pode vir de fora; a resposta
que um bridge daria é postada pelo próprio roteiro, com o segredo de pareamento,
pela mesma rota que um bridge real usaria.

O que este drill prova é o **ciclo do servidor** atravessando a queda do
processo: reserva, recusa de liberação, recuperação e conciliação. Não prova
cobrança, não prova adquirente e não prova dispositivo.

## Cenário A — reinício com a cobrança em voo

Uma mesa com quatro itens, uma parcela de R$ 40,00 alocada no Whisky, a cobrança
registrada como em voo e **então** o reinício, antes de qualquer resposta.

| Verificação | Observado |
|---|---|
| cobrança fica em voo e não presume aprovação | transação em `PROCESSING` |
| linha reservada antes da queda | reservado R$ 40,00, disponível R$ 0,00 |
| **`docker restart` da API e do worker, com a cobrança em voo** | contêineres com `StartedAt` novo; API respondendo em 12,7s |
| parcela atravessa a queda aberta | `PROCESSING`, `awaiting_provider: true` |
| reserva atravessa a queda intacta | reservado R$ 40,00, disponível R$ 0,00 |
| cobrança em voo não carrega prazo de expiração | `reserve_expires_at: null` |
| ninguém libera cartão em voo pela mão | `409 EXTERNAL_CHARGE_IN_FLIGHT` |
| a transação continua viva para receber a resposta | callback `CONFIRMED` responde `200` |
| a resposta fecha a parcela que sobreviveu | parcela `CONFIRMED` |
| o item fica quitado, e só ele | Whisky quitado em R$ 40,00; Pizza segue com R$ 60,00 disponíveis |

O ponto do cenário é a recusa no meio: depois de o sistema voltar, um operador
que interpreta o reinício como "a cobrança se perdeu" tenta cancelar a reserva e
é recusado, porque a cobrança continua em voo. O reinício não vira licença para
liberar dinheiro.

## Cenário B — queda entre os dois commits, sem ninguém para consultar

`_apply_result` grava a transação e só depois toca a parcela. A janela entre os
dois commits é encenada gravando o resultado terminal direto no banco, deixando
cobrança `CONFIRMED` ao lado de parcela aberta, e então reiniciando os dois
contêineres. **Ninguém abre a conta depois**: a recuperação tem que partir do
worker.

| Verificação | Observado |
|---|---|
| linhas discordando antes da queda | transação `CONFIRMED` · parcela `PROCESSING` |
| **`docker restart` da API e do worker** | contêineres com `StartedAt` novo; API respondendo em 13,8s |
| a varredura reaplica sem ninguém perguntar | parcela `CONFIRMED`, com o worker recém-subido |
| o item aparece quitado para quem abrir a conta depois | Pizza quitada em R$ 60,00 |
| nada foi perguntado de novo ao provider | uma única `ProviderTransaction` para a parcela |

Sobre o tempo: o roteiro esperava até 180s pela varredura e encontrou a parcela
já conciliada 0,2s depois de `docker restart` retornar. Isso **não** mede a
latência da varredura — ela rodou durante os ~14s em que o roteiro aguardava a
API voltar. O que fica provado é que a recuperação acontece na subida do worker,
sem intervenção; a varredura periódica de 60s é o piso, não o caminho normal.

Confirmado no log do worker que foi ele quem aplicou:
`Recovered 6 provider results that never reached their parcel`.

## Achado operacional aberto

A varredura processou o backlog real do banco de desenvolvimento e encontrou
**12 transações terminais ao lado de parcelas abertas que não podem ser
reaplicadas**, a mais antiga de 24/08/2026. Todas levantam
`Transação sem cadeia de autoridade auditável` em `payment_audit_service.py:110`
e são puladas — o isolamento por linha da terceira rodada do S25.1 funcionando,
e a razão de o cenário B ter conseguido drenar até a sua própria linha.

As doze pertencem a tenants de teste (`Gate D …`, `RefundOpen …`), então isto
não é dinheiro de ninguém. O que o drill expõe é outra coisa: **uma linha que
nunca poderá ser reaplicada é retentada a cada 60 segundos, para sempre, e só
aparece como traceback no log.** O comentário do código diz que ela fica "para
uma pessoa", mas nada avisa pessoa alguma. Fica registrado para a frente de
observabilidade do bridge, com a ressalva de que em produção essa fila seria
composta de parcelas presas segurando linhas de conta.

## O que este drill não prova

- **Não é homologação com provider real.** O desfecho veio do callback do
  bridge, que é o caminho de produção, mas nenhum adquirente foi acionado,
  nenhum pinpad recebeu comando e nenhum valor real transitou;
- **não é aceite em ambiente publicado.** Roda contra a pilha local em
  contêineres, não contra o deploy;
- **não encena queda do Postgres**, nem partição de rede entre API e banco. O
  que foi derrubado foi a API e o worker.
