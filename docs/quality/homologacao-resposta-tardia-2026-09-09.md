# Homologação — a resposta que chegou depois

Data: 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
evidência: [`evidence/hom-07-resposta-tardia/`](evidence/hom-07-resposta-tardia/) ·
roteiro: `frontend/e2e/presentation/hom07_resposta_tardia.cjs` ·
cenário: `backend/tests/support/seed_tef_awaiting_bridge.py`.

A [hom06](homologacao-tef-em-processamento-2026-09-09.md) percorreu a cobrança
que sai e não volta. Falta o outro lado: o provider **responde**, tarde, e
ninguém estava olhando. Três perguntas, todas sobre dinheiro:

1. a resposta tardia fecha a parcela, e a tela retomada mostra isso?
2. o provider repetindo a mesma resposta confirma duas vezes?
3. uma resposta que contradiz a anterior anda para trás e solta saldo?

## Onde cada prova vive

| Assunto | Onde é provado | Por quê |
|---|---|---|
| Resposta tardia, repetida e contraditória, na tela | travessia hom07 | é o que a pessoa vê e decide |
| **Reconciliação pelo worker** | `test_s25_1_payment_recovery.py` | roda sem ninguém olhando, e a janela que conserta é uma queda entre dois commits — isso não se produz por navegador |
| Integração real com provedor | **não percorrida** | nenhum provedor foi contatado; a resposta tardia é enviada por este roteiro, no papel do bridge |

## A jornada, como foi percorrida

A conta da Mesa 7 tem R$ 80,00. A cobrança TEF sai por R$ 18,00 e fica sem
resposta — `01-a-cobranca-em-voo.png`.

O id da transação vem da **recusa de cancelamento**: tentar soltar a parcela
devolve 409 e, no corpo, `provider_transaction_id`. A recusa é, ela própria, a
prova de que a parcela não se solta na mão.

### 1. A resposta tardia, e a retomada da tela

O bridge responde `CONFIRMED`. **A tela aberta não é avisada** — ela continua
mostrando "Aguardando conciliação", porque leu o estado antes. Isso não é falha:
é o que a retomada resolve.

Recarregando e reabrindo a conta — `02-retomada-mostra-a-confirmacao.png`:

| Na tela | Valor |
|---|---|
| Métricas | TOTAL R$ 80,00 · **CONFIRMADO R$ 18,00** · FALTA R$ 62,00 |
| A parcela | **"Crédito · confirmado · R$ 18,00"** |
| "Aguardando conciliação" | sumiu |
| Métrica "Em processamento" | sumiu — ela só existe com cobrança em voo |

No servidor: confirmado **18,0000**, em processamento **0,0000**, falta
**62,0000**.

### 2. A resposta repetida

O bridge manda a **mesma** confirmação mais duas vezes. Depois disso:

| Leitura | Antes de repetir | Depois de repetir |
|---|---|---|
| Confirmado | 18,0000 | **18,0000** |
| Parcelas | 1 | **1** |
| Falta | 62,0000 | **62,0000** |
| Divergências | nenhuma | **nenhuma** |

Repetir não virou dinheiro a mais, nem parcela a mais.

### 3. A resposta que contradiz

O adquirente muda de ideia: `FAILED` **depois** de ter confirmado. Andar para
trás aqui reabriria uma cobrança fechada e, com ela, soltaria a linha da conta.

| Leitura | Resultado |
|---|---|
| Confirmado | **18,0000** — inalterado |
| Falta | **62,0000** — inalterado |
| A parcela | continua **CONFIRMED** |
| Divergência | **`STATE_REGRESSION_REFUSED`** |

E a tela retomada **mostra** o registro, em vez de escondê-lo —
`03-a-contradicao-fica-registrada-na-tela.png`:

> **Pendente de conciliação** · O provider respondeu algo que não pôde ser
> aplicado a esta conta. O registro fica aqui até alguém decidir; nada foi
> liberado nem cobrado por conta disso.

## O controle, e o que ele revelou

Desliguei a guarda que impede a transação de retroceder — `_apply_result` deixou
de lembrar que já havia resposta terminal. **A travessia continuou passando.**

Isso não é falha da medida: é **defesa em profundidade**, e vale registrar qual
é a segunda camada. Uma resposta `FAILED` só derruba parcela que ainda esteja
aberta (`intent.status in OPEN_INTENTS`); parcela já confirmada nunca é reaberta
por resposta de provider, e o fato vira divergência. Com a primeira guarda
desligada, o dinheiro ficou exatamente onde estava — o que mudou foi só a
**classificação**: `LATE_FAILURE` em vez de `STATE_REGRESSION_REFUSED`.

| Guarda | O que ela impede | Divergência que ela produz |
|---|---|---|
| A transação não retrocede | aplicar resposta antiga sobre resposta terminal | `STATE_REGRESSION_REFUSED` |
| A parcela confirmada não reabre | derrubar parcela encerrada por resposta de provider | `LATE_FAILURE` |

As asserções desta travessia são sobre **dinheiro** — confirmado, falta, número
de parcelas, situação da parcela — e é por isso que elas seguraram com uma das
duas guardas desligada. Escrever uma asserção sobre qual guarda atuou faria a
travessia acusar esse controle, e mediria arquitetura em vez de dinheiro.

## A reconciliação pelo worker

Prova nova em `test_s25_1_payment_recovery.py`:
**`test_s25_1_the_sweep_settles_the_parcel_once_and_a_second_sweep_adds_nothing`**.

A janela já tinha prova — `_apply_result` grava a transação antes de tocar a
parcela, e uma queda entre os dois commits deixa cartão aprovado ao lado de
parcela aberta. O que faltava era o **desfecho não assistido**: ninguém abre a
tela, ninguém consulta, e é o varrimento que fecha a conta. E o worker roda em
laço, então a segunda passada importa tanto quanto a primeira.

| Passada | O que acontece |
|---|---|
| Primeira | a linha travada é alcançada, e a parcela vai para `CONFIRMED`; confirmado R$ 40, em processamento R$ 0, mercadoria quitada por uma pessoa |
| Segunda | a linha **não volta** ao varrimento; confirmado, falta, parcelas e divergências ficam idênticos |

**Os dois controles desta prova:**

| O que quebrei | O que aconteceu |
|---|---|
| O varrimento encontra e **não aplica** | reprova em `CONFIRMED != PROCESSING` — precisa, e é a primeira metade |
| Sai o filtro de parcela aberta na consulta do varrimento | reprova — o varrimento passa a devolver linhas já aplicadas e quebra numa delas. A falha é real, mas chega por outro caminho, não pela asserção da segunda passada |

## Alcance desta evidência

Percorrido: cobrança TEF sem resposta; confirmação tardia pelo callback do
bridge; retomada da tela mostrando a confirmação; a mesma confirmação repetida
duas vezes sem duplicar dinheiro nem parcela; recusa chegando depois da
confirmação sem soltar saldo, virando divergência visível na tela; e o
varrimento do worker fechando uma parcela travada e não fazendo nada na segunda
passada.

**Não** percorrido: resposta tardia de **cancelamento** (`CANCELED`) e de
**estorno** (`REFUNDED`) chegando fora de ordem; várias parcelas com respostas
tardias cruzadas na mesma conta; o worker rodando de verdade em laço, com
concorrência entre duas instâncias; e a **integração real com provedor**, que
continua pendência separada, junto com o **vínculo de maquininha percorrido pela
tela**.

Isto é travessia de navegador contra a API local, mais provas determinísticas no
backend. Nenhum provedor externo foi contatado.

## Lacunas de homologação, depois desta

| Lacuna | Estado |
|---|---|
| Dois destinos nunca percorridos | fechada em 09/09/2026 |
| Duas estações, a segunda achando a unidade já reservada | fechada em 09/09/2026 |
| Conceder e retirar autoridade, com sessão aberta | fechada em 09/09/2026 |
| Catálogo volumoso não exercitado | fechada em 09/09/2026 |
| Estado "em processamento" do TEF, incluindo parcial | fechada em 09/09/2026 |
| **Resposta tardia, repetida e reconciliação pelo worker** | **fechada em 09/09/2026** |
| Duas inclusões simultâneas disputando a última unidade | aberta — próxima |
| Propagação da mudança de autoridade para sessão aberta | aberta — próxima |
| Transação real com provedor | aberta, pendência separada |
| Vínculo de maquininha percorrido pela tela | aberta, pendência separada |
