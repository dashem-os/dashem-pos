# Homologação — a cobrança TEF que saiu e não voltou

Data: 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
evidência: [`evidence/hom-06-tef-em-processamento/`](evidence/hom-06-tef-em-processamento/) ·
roteiro: `frontend/e2e/presentation/hom06_tef_em_processamento.cjs` ·
cenário: `backend/tests/support/seed_tef_awaiting_bridge.py`.

A [UX-08](ux-08-homologacao-2026-09-08.md) registrou isto como **o maior risco
aberto**: *"estado pendente de confirmação sem representação visual. Quem
reenvia hoje acerta pelo carimbo, não porque a tela explicou."* A regra do dono,
na UX-07, é o que esta travessia cobra:

> não tratar timeout como recusa, nem oferecer nova cobrança ou cancelamento sem
> resolver o estado anterior.

## O que esta travessia é, e o que ela não é

| Camada | Estado | O que a evidência mostra |
|---|---|---|
| **Configuração** | percorrida | provedor, bridge e vínculo de maquininha, montados pelas rotas do produto |
| **Simulação de bridge** | percorrida | o heartbeat sai do roteiro de cenário, no papel do Dashem TEF Bridge |
| **Integração real com provedor** | **NÃO percorrida** | o adaptador é o `BridgeQueuedAdapter`: enfileira e não aprova. Nenhum provedor foi contatado, nenhum cartão passou, nenhum dinheiro se moveu |

O adaptador enfileirado é o que torna esta travessia possível **sem** provedor
real: `start` devolve `PROCESSING` e `query` devolve `UNKNOWN`. Esse é
exatamente o estado de uma cobrança sem resposta — e é dele que a tela precisava
saber falar.

> O **vínculo de maquininha** aparece aqui como configuração feita pela rota do
> produto, não como jornada percorrida na tela. Ele continua sendo pendência
> separada, junto com a transação real.

## A jornada, como foi percorrida

Bruna Salles assume a operação do salão com código e PIN num terminal
autorizado — a Gestão entra por e-mail, e o salão não. Ela abre o caixa, abre a
Mesa 7 — um chopp de R$ 18,00 e uma porção de R$ 62,00, **R$ 80,00** na conta —
e fecha a conta.

| Etapa | O que aconteceu | Evidência |
|---|---|---|
| A conta abre | a tela declara **"TEF online · BRIDGE-… · bridge 0.0.0-simulado"** | `02-conta-aberta-com-tef-online.png` |
| Cobrança por Crédito via TEF | *"Transação enviada ao bridge; aguardando resultado ou reconciliação."* | `03-a-cobranca-saiu-e-nao-voltou.png` |
| A parcela na conta | **"Crédito · processando · R$ 18,00"** de uma conta de R$ 80,00 | idem |
| A frase que o balcão lê | *"Aguardando conciliação há menos de um minuto · a cobrança saiu e o provider ainda não respondeu."* | idem |
| Consultar pagamento | oferecido | idem |
| Cancelar reserva | **não** oferecido | idem |
| Consultar de novo | continua aguardando; nada foi liberado | `06-consultar-nao-solta-a-conta.png` |

**Timeout não virou recusa.** A palavra "falhou" não aparece para esta parcela, e
a travessia reprova se aparecer.

**As duas ações não são simétricas, e a tela não as oferece juntas.** Consultar é
a saída honesta de um estado desconhecido; cancelar devolveria uma linha da conta
que pode estar com o cartão aprovado do outro lado. Só a primeira está lá.

## O defeito que a jornada encontrou

Metade da regra estava cumprida: a tela não oferece **cancelar**. A outra metade
não estava.

Com parte da conta numa cobrança sem resposta, a tela continuava propondo cobrar
**o que falta** — que inclui o que já está em voo — e deixava **"Registrar
parcela"** aceso. Quem clicasse recebia do servidor:

> **Parcela excede o saldo reservável de 62.0000.**

O servidor estava certo, e continua sendo ele quem decide. Errado era o resto: a
tela **convidava** a operadora a uma cobrança que não cabia, e só depois a
informava — numa frase que fala de "saldo reservável" para quem está no balcão.
Descobrir pela recusa não é ser avisado.

### A correção

O valor que a tela propõe deixou de ser "o que falta" e passou a ser **o que se
pode cobrar agora** — `remaining − processing` — calculado num lugar só
(`cobravelAgoraDe`) e usado em todos os pontos que propõem valor: ao abrir a
conta, ao confirmar, ao consultar, ao cancelar, ao estornar, no rateio por
pessoa e **depois de uma execução TEF**, que era o caminho que não recalculava
nada.

A conta ganhou a quarta métrica, que aparece só quando existe cobrança em voo, e
o campo de valor ganhou teto.

## Processamento parcial

A conta desta travessia tem **R$ 80,00** (chopp R$ 18,00 e porção R$ 62,00). A
cobrança TEF sai por R$ 18,00 e não volta. Sobra parte cobrável — e é aí que o
limite precisa ser dito **antes** do envio.

| O que a tela faz | Valor |
|---|---|
| Métricas | TOTAL R$ 80,00 · CONFIRMADO R$ 0,00 · **EM PROCESSAMENTO R$ 18,00** · FALTA R$ 80,00 |
| Valor proposto | **R$ 62,00** — o que sobra, não o que falta |
| Frase do teto | *"Máximo a cobrar agora: R$ 62,00. Os outros R$ 18,00 desta conta estão numa cobrança sem resposta."* |
| Digitando R$ 70,00 | botão apagado e *"R$ 70,00 passa do que dá para cobrar agora (R$ 62,00). Reduza o valor ou consulte a cobrança que está sem resposta."* |
| O servidor, se alguém passar por fora | **409** — *"Parcela excede o saldo reservável de 62.0000."* |

`04-acima-do-teto-e-bloqueado-antes-do-envio.png`.

**A validação do servidor continua sendo a que decide.** A tela poupa a
tentativa; ela não substitui a regra, e a travessia confere as duas coisas na
mesma execução.

Cobrando os R$ 62,00 restantes, a conta inteira passa a estar em voo e o caminho
fecha: valor proposto R$ 0,00, botão apagado, e

> ⚠ Não há valor para cobrar agora: R$ 80,00 desta conta está numa cobrança sem
> resposta. Consulte o pagamento acima antes de cobrar de novo.

`05-nova-cobranca-nao-e-oferecida.png`.

## O que o servidor diz

| Leitura | Resultado |
|---|---|
| Parcela | `PROCESSING`, `awaiting_provider: true` |
| `can_cancel` | **false** |
| `can_query_provider` | true |
| Conta, ao fim | em processamento **R$ 80,00**, confirmado **R$ 0,00** |
| Cancelar a parcela pela API | **409 `EXTERNAL_CHARGE_IN_FLIGHT`** — *"Existe cobrança externa sem resultado conhecido. Consulte o pagamento antes de decidir sobre esta parcela."* |
| Cobrar R$ 70,00 com R$ 18,00 em voo | **409** — *"Parcela excede o saldo reservável de 62.0000."* |

A tela não oferece, e quem tentar por fora leva a mesma recusa, com o caminho
certo nomeado. Proteção com caminho alternativo não é proteção.

## O controle

Desligando a correção — o valor proposto voltando a ser `remaining` — a mesma
travessia reprova **sete vezes**: o valor proposto vira R$ 80,00 em vez de
R$ 62,00, a frase do teto some, o botão aceita R$ 70,00, a explicação some, e no
fim a tela volta a propor R$ 80,00 com a conta inteira em voo.

Nesse mesmo controle o servidor **continuou recusando** com 409 e "saldo
reservável de 62.0000": a validação dele não depende da tela, e é isso que a
correção não pode ter enfraquecido.

A parte de cancelar também tem o seu controle no registro: a travessia reprova
se `Cancelar reserva` aparecer, e reprova se a chave `EXTERNAL_CHARGE_IN_FLIGHT`
sumir da recusa da API.

## Alcance desta evidência

Percorrido: numa comanda de R$ 80,00, uma cobrança TEF de crédito de R$ 18,00
com bridge declarado online por heartbeat simulado, terminando em `PROCESSING`
sem resposta; **processamento parcial** com o restante cobrável, teto dito antes
do envio e valor acima do teto barrado na tela e recusado no servidor; a segunda
cobrança levando a conta inteira a ficar em voo; consulta ao provedor devolvendo
desconhecido; e o cancelamento recusado na tela e no servidor.

**Não** percorrido: a resposta chegando **depois** (confirmação ou recusa tardia,
que é o caminho das divergências); reconciliação pelo worker; débito via TEF;
cobrança em processamento numa venda de balcão em vez de comanda; e a
**transação real com provedor**, que continua pendência separada — assim como o
**vínculo de maquininha** percorrido pela tela.

Isto é travessia de navegador contra a API local, com cenário próprio montado
pelas rotas do produto. Não envolve provedor externo.

## Lacunas de homologação, depois desta

| Lacuna | Estado |
|---|---|
| Dois destinos nunca percorridos | fechada em 09/09/2026 |
| Duas estações, a segunda achando a unidade já reservada | fechada em 09/09/2026 |
| Conceder e retirar autoridade, com sessão aberta | fechada em 09/09/2026 |
| Catálogo volumoso não exercitado | fechada em 09/09/2026 |
| **Estado "em processamento" do TEF** | **fechada em 09/09/2026** |
| Duas inclusões simultâneas disputando a última unidade | aberta, pendência específica |
| Propagação da mudança de autoridade para sessão aberta | aberta |
| Resposta tardia do provedor e reconciliação pelo worker | aberta, nomeada aqui |
| Transação real com provedor | aberta, pendência separada |
| Vínculo de maquininha percorrido pela tela | aberta, pendência separada |
