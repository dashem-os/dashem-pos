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
Mesa 7 (um chopp, R$ 18,00) e fecha a conta.

| Etapa | O que aconteceu | Evidência |
|---|---|---|
| A conta abre | a tela declara **"TEF online · BRIDGE-… · bridge 0.0.0-simulado"** | `02-conta-aberta-com-tef-online.png` |
| Cobrança por Crédito via TEF | *"Transação enviada ao bridge; aguardando resultado ou reconciliação."* | `03-a-cobranca-saiu-e-nao-voltou.png` |
| A parcela na conta | **"Crédito · processando · R$ 18,00"** | idem |
| A frase que o balcão lê | *"Aguardando conciliação há menos de um minuto · a cobrança saiu e o provider ainda não respondeu."* | idem |
| Consultar pagamento | oferecido | idem |
| Cancelar reserva | **não** oferecido | idem |
| Consultar de novo | continua aguardando; nada foi liberado | `05-consultar-nao-solta-a-conta.png` |

**Timeout não virou recusa.** A palavra "falhou" não aparece para esta parcela, e
a travessia reprova se aparecer.

**As duas ações não são simétricas, e a tela não as oferece juntas.** Consultar é
a saída honesta de um estado desconhecido; cancelar devolveria uma linha da conta
que pode estar com o cartão aprovado do outro lado. Só a primeira está lá.

## O defeito que a jornada encontrou

Metade da regra estava cumprida: a tela não oferece **cancelar**. A outra metade
não estava.

Com R$ 18,00 numa cobrança sem resposta, a conta mostrava:

> TOTAL R$ 18,00 · CONFIRMADO R$ 0,00 · **FALTA R$ 18,00**

…propunha R$ 18,00 no campo de valor, e deixava **"Registrar parcela"** aceso.
Quem clicasse recebia do servidor:

> **Parcela excede o saldo reservável de 0.0000.**

O servidor estava certo — a cobrança em voo segura a conta inteira, e não há
como cobrar duas vezes. Errado era o resto: a tela **convidava** a operadora a
uma segunda cobrança e só depois a informava, numa frase que fala de "saldo
reservável" para quem está no balcão. Descobrir pela recusa não é ser avisado.

### A correção

O valor que a tela propõe deixou de ser "o que falta" e passou a ser **o que se
pode cobrar agora** — `remaining − processing` — calculado num lugar só
(`cobravelAgoraDe`) e usado em todos os pontos que propõem valor, inclusive
depois de uma execução TEF, que era o caminho que não recalculava nada.

E a conta ganhou a quarta métrica, que aparece só quando existe cobrança em voo:

> TOTAL R$ 18,00 · CONFIRMADO R$ 0,00 · **EM PROCESSAMENTO R$ 18,00** · FALTA R$ 18,00

Com o botão apagado e a frase, em português de balcão:

> ⚠ Não há valor para cobrar agora: R$ 18,00 desta conta está numa cobrança sem
> resposta. Consulte o pagamento acima antes de cobrar de novo.

`04-nova-cobranca-nao-e-oferecida.png`.

## O que o servidor diz

| Leitura | Resultado |
|---|---|
| Parcela | `PROCESSING`, `awaiting_provider: true` |
| `can_cancel` | **false** |
| `can_query_provider` | true |
| Conta | em processamento **R$ 18,00**, confirmado **R$ 0,00** |
| Cancelar a parcela pela API | **409 `EXTERNAL_CHARGE_IN_FLIGHT`** — *"Existe cobrança externa sem resultado conhecido. Consulte o pagamento antes de decidir sobre esta parcela."* |
| Segunda parcela pelo valor que faltava | **409** — *"Parcela excede o saldo reservável de 0.0000."* |

A tela não oferece, e quem tentar por fora leva a mesma recusa, com o caminho
certo nomeado. Proteção com caminho alternativo não é proteção.

## O controle

Desligando a correção — o valor proposto voltando a ser `remaining`, e a métrica
de processamento removida — a mesma travessia reprova **quatro vezes**: o valor
proposto volta a R$ 18,00, o botão acende, o aviso some e a conta volta a dizer
só "Falta R$ 18,00". A medida mede o que diz medir.

A parte de cancelar também tem o seu controle no registro: a travessia reprova
se `Cancelar reserva` aparecer, e reprova se a chave `EXTERNAL_CHARGE_IN_FLIGHT`
sumir da recusa da API.

## Alcance desta evidência

Percorrido: uma cobrança TEF de crédito numa comanda de mesa, com bridge
declarado online por heartbeat simulado, terminando em `PROCESSING` sem resposta;
consulta ao provedor devolvendo desconhecido; e as duas tentativas de sair do
estado — cancelar e cobrar de novo — recusadas na tela e no servidor.

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
