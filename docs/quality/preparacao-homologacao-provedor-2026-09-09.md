# Preparação — homologação real com provedor

Data: 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md).

Este documento não é evidência de nada percorrido. Ele existe para responder
duas perguntas antes de marcar homologação com um provedor: **o que já está
pronto** e **o que falta**, com os buracos nomeados em vez de descobertos no dia.

O vínculo de maquininha pela tela foi percorrido em
[09/09/2026](homologacao-vinculo-de-maquininha-2026-09-09.md) e sai da lista de
pendências. O que resta é a integração real.

## O que já existe

| Peça | Estado | Onde se comprova |
|---|---|---|
| Configurar provedor na unidade | pronto, percorrido pela tela | [hom02](homologacao-destinos-nunca-percorridos-2026-09-09.md) |
| Parear terminal de bridge, com código mostrado uma vez | pronto, percorrido | hom02 |
| Heartbeat do bridge, com versão de protocolo conferida | pronto; **protocolo incompatível é aceito e marcado como falha** | hom02 |
| Vincular maquininha ao caixa, pausar e reativar | pronto, percorrido pela tela | [hom08](homologacao-vinculo-de-maquininha-2026-09-09.md) |
| Cobrança enfileirada com resposta pendente | pronto | [hom06](homologacao-tef-em-processamento-2026-09-09.md) |
| Limite parcial na tela, com validação do servidor | pronto | hom06 |
| Callback de resultado do bridge | pronto | [hom07](homologacao-resposta-tardia-2026-09-09.md) |
| Resposta tardia, repetida e contraditória | pronto | hom07 |
| Reconciliação pelo worker, sem tela | pronto | hom07 |
| Consulta ao provider a partir da parcela | pronto | hom06 |

## O que falta — e o primeiro item é bloqueador

### 1. O bridge não tem como saber que existe uma cobrança esperando por ele

Hoje existem **quatro** rotas de bridge, e nenhuma entrega comando:

| Rota | Quem chama | Para quê |
|---|---|---|
| `POST /providers/bridge/terminals` | Gestão | parear |
| `GET /providers/bridge/terminals` | Gestão | listar |
| `POST /providers/bridge/terminals/{id}/heartbeat` | **o bridge** | dizer que está vivo |
| `POST /providers/bridge/terminals/{id}/transactions/{tx}/result` | **o bridge** | informar um resultado |

Quando uma cobrança sai, o `BridgeQueuedAdapter` grava
`sanitized_payload = {"bridge_command": "START", "correlation_id": ...}` na
transação — e para por aí. **Nada expõe esse comando a um bridge.** Nas
travessias isso não apareceu porque o roteiro conhecia o `transaction_id` por
outro caminho (a recusa de cancelamento, que devolve `provider_transaction_id`);
um bridge de verdade não tem esse atalho.

Falta uma rota de retirada de comandos — algo como
`GET /providers/bridge/terminals/{id}/commands`, autenticada pelo mesmo segredo
de pareamento do heartbeat, devolvendo o que está pendente para aquele terminal.
Sem ela, a cobrança sai do Dashem e **não chega à maquininha**.

> Decisão de arquitetura pendente, e não é minha: **polling** pelo bridge (mais
> simples, combina com o heartbeat que já existe) ou **conexão persistente**. A
> segunda muda o desenho do bridge e do servidor; a primeira cabe no que já está
> de pé. Não escolhi.

### 2. Credenciais e ambiente de homologação do provedor

Nada disso existe no repositório, e nada deve existir: são segredos.

| O que é preciso | Quem fornece | Onde entra |
|---|---|---|
| Provedor/adquirente escolhido | dono | define o adapter a escrever |
| Credenciais de homologação | provedor | `credentials_ref` aponta para o cofre; o valor **nunca** no banco nem no repositório |
| Endereço do ambiente de homologação | provedor | configuração do adapter |
| Cartões de teste e resultados esperados | provedor | roteiro abaixo |
| Versão de protocolo do bridge homologada | provedor/integrador | `protocol_version` do terminal |

### 3. O bridge instalado

Não existe binário do Dashem TEF Bridge neste repositório. Em toda evidência
até aqui, **o papel do bridge foi feito pelos roteiros de travessia**. Para a
homologação real é preciso: máquina com o bridge instalado, maquininha física
pareada com a adquirente, e a versão de protocolo que o servidor aceita.

### 4. Um adapter real

`resolve_adapter` devolve `BridgeQueuedAdapter` para qualquer código que não seja
`CONTRACT_TEST`. Ele enfileira e **nunca aprova** — é honesto, e é o que torna as
travessias possíveis sem provedor. Um adapter real precisa ser escrito contra o
protocolo do provedor escolhido.

### 5. SmartPOS continua só cadastro

A própria tela declara: *"SmartPOS: somente cadastro. A execução de cobranças
está indisponível até existir um adapter homologado."* Vincular em modo SmartPOS
não é caminho de execução, e a homologação real não deve começar por ele.

## O roteiro da homologação, quando houver provedor

Os cenários abaixo já têm equivalente percorrido **com bridge simulado**. O que
muda na homologação real é o outro lado do fio: cada linha precisa ser refeita
com provedor de verdade, e o resultado comparado com o que se conhece.

| # | Cenário | Equivalente simulado | O que conferir com provedor real |
|---|---|---|---|
| 1 | Cobrança aprovada | — | NSU e código de autorização chegam e ficam na parcela |
| 2 | Cobrança recusada pelo cartão | hom07 (`FAILED` em parcela aberta) | a recusa libera a linha da conta e nomeia o motivo |
| 3 | **Resposta tardia** — aprovação depois do timeout | hom07 | a parcela fecha; a tela retomada mostra; nada duplica |
| 4 | **Resposta repetida** | hom07 | dinheiro e parcelas não dobram |
| 5 | **Resposta contraditória** | hom07 (`FAILED` após `CONFIRMED`) | a parcela confirmada não reabre; vira divergência |
| 6 | **Cancelamento** antes da resposta | — · **não percorrido nem simulado** | cancelar no provider e ver a parcela seguir |
| 7 | **Cancelamento fora de ordem** | — · **não percorrido** | `CANCELED` chegando depois de `CONFIRMED` |
| 8 | **Estorno integral** | ADR-030, com adapter de contrato | valor revertido declarado pelo adquirente |
| 9 | **Estorno parcial** | ADR-030 | baixa só com quantia; "estornado" sem valor não é prova |
| 10 | **Estorno fora de ordem** | — · **não percorrido** | `REFUNDED` chegando antes da confirmação ser aplicada |
| 11 | **Recuperação** — queda entre os dois commits | hom07, determinístico | o varrimento fecha sozinho, e a segunda passada não refaz |
| 12 | **Bridge offline no meio da cobrança** | parcial (hom02 mostra offline antes) | a cobrança em voo não é perdida nem duplicada na volta |
| 13 | **Maquininha pausada durante uma cobrança em voo** | — · **não percorrido** | pausar não pode soltar cobrança já enviada |
| 14 | Cartão de crédito e de débito | só crédito, em hom06 e hom07 | débito percorre o mesmo caminho |

As linhas 6, 7, 10 e 13 não têm equivalente nenhum hoje: são **buracos de
cobertura**, e é melhor descobri-los aqui do que no dia da homologação.

## Limites de cobertura que permanecem abertos

Nomeados nas entregas anteriores e repetidos aqui para não sumirem do
planejamento. **Não são bloqueios**; são o que a evidência atual não cobre:

| Limite | De onde vem |
|---|---|
| Cancelamento e estorno chegando fora de ordem | hom07 |
| Várias parcelas com respostas tardias cruzadas na mesma conta | hom07 |
| Concorrência entre duas instâncias do worker de reconciliação | hom07 |
| Classificação da divergência como requisito próprio, com prova dirigida | hom07 |
| Débito via TEF | hom06 |
| Cobrança em processamento numa venda de balcão, e não em comanda | hom06 |
| Consulta de autoridade falhando por rede, e aba em segundo plano | [hom04](homologacao-autoridade-do-operador-2026-09-09.md) |
| Catálogo acima de 1.203 produtos, e com imagens reais | [hom05](homologacao-catalogo-volumoso-2026-09-09.md) |

## O que decidir antes de marcar a homologação

1. **Provedor/adquirente**, que determina o adapter;
2. **Entrega de comando ao bridge**: polling ou conexão persistente;
3. Quem instala e opera o **bridge** durante a homologação;
4. Se a **classificação de divergência** é requisito com prova própria, ou só o
   valor financeiro;
5. Se **débito** entra na primeira homologação ou fica para depois.
