# Homologação — conceder e retirar autoridade, com a sessão do operador aberta

Data: 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
evidência: [`evidence/hom-04-autoridade/`](evidence/hom-04-autoridade/) ·
roteiro: `frontend/e2e/presentation/hom04_autoridade_do_operador.cjs`.

A UX-13 provou a direção que **tira** autoridade e deixou registrado que
conceder — e ver o operador agir sozinho na tela — não fora percorrido. Esta
travessia percorre as duas direções, e faz a pergunta que o dono formulou:

> uma permissão retirada continua utilizável por dados antigos da sessão?

## Por que a pergunta tem fundamento

O PDV lê `permissions` **uma vez**, ao abrir a sessão operacional, e decide por
essa lista se pede a segunda pessoa. Uma mudança feita depois não chega àquela
tela. As duas direções erram, e não erram igual:

| Direção | Efeito na tela aberta | Gravidade |
|---|---|---|
| Concessão que não chegou | mais **restritiva** que a realidade: pede autorização que já não seria necessária | incomoda |
| Retirada que não chegou | mais **permissiva** que a realidade: deixa agir sozinho quem já não pode | é aqui que o servidor precisa recusar |

**As duas direções foram resolvidas.** A tela reconfere a própria autoridade a
cada 30 segundos, pelo mesmo caminho por onde a leu ao entrar
(`/capabilities/effective`), e avisa **só quando muda**. Não é o encanamento do
turno operacional: a Gestão passa pelo mesmo contexto, então a mudança alcança
as duas telas. E não substitui nada — quem decide continua sendo o servidor, a
cada requisição.

## A jornada, como foi percorrida

| Etapa | O que aconteceu | Evidência |
|---|---|---|
| Sem autoridade, cancelar | a operadora CAIXA recebe o pedido de autorização do supervisor | `02-sem-autoridade-pede-supervisor.png` |
| A gestora concede | `PUT /team/{vínculo}/autoridade`, 200 | — |
| **A concessão alcança a sessão aberta** | a tela avisa sozinha, em **15885ms**, **sem recarregar** | — |
| Cancelar de novo | agora sem diálogo nenhum | `03-com-autoridade-cancela-sozinha.png` |
| A gestora retira | 200 | — |
| **Na janela antes da próxima batida** | a tela ainda acha que pode, tenta, e o **servidor recusa** | `04-retirada-com-sessao-aberta.png` |
| **A retirada alcança a sessão aberta** | em **20038ms** a tela volta a pedir supervisor, sozinha | `05-retirada-chega-e-a-tela-volta-a-pedir-supervisor.png` |

**A resposta à pergunta é a boa.** Com a autoridade retirada e a sessão ainda
aberta, a tela mandou o cancelamento sem cabeçalho de supervisor — porque ainda
acreditava que podia — e o servidor recusou. Permissão retirada **não** fica
utilizável por dado antigo de sessão: quem decide é o servidor, a cada
requisição.

### A tela diz uma coisa; o servidor é quem confirma

"1 item no carrinho" é a tela da operadora — e a tela é justamente a parte cuja
palavra está em dúvida aqui. Então a travessia pergunta ao servidor, pela
sessão da gestão, quantas vendas existem em cada situação:

| Leitura | Resultado |
|---|---|
| `GET /sales?status=DRAFT` | **1** — a venda que a recusa deixou aberta |
| `GET /sales?status=CANCELED` | **1** — só a que ela cancelou **quando tinha** a autoridade |
| Carrinho na tela | 1 item, R$ 8,00 |

**O controle.** Deixando a autoridade no lugar — a "retirada" concedendo em vez
de retirar — a mesma travessia acusa quatro vezes: o carrinho esvazia, a recusa
some, as abertas caem para **0** e as canceladas sobem para **2**. Os números do
servidor se mexem quando a regra muda, então eles estão medindo a regra.

## O defeito que a jornada encontrou

A recusa que apareceu para a operadora era:

> **Missing permission: sale.cancel**

Inglês e chave de permissão, na tela de quem está no balcão. O produto proíbe
isso em outros lugares — a UX-12 tem teste que reprova jargão na tela do
lojista — e aqui ele escapava pela mensagem de erro do servidor.

O cadastro de permissões já tem o nome da operação em português: é o mesmo que a
tela de acessos mostra desde a UX-13. A recusa passou a usá-lo:

> **Você não tem autorização para cancelar venda. Peça a quem tem.**

A travessia reprova se a chave em inglês voltar — mas travessia é coisa que se
roda à mão, e por isso a correção também virou portão da suíte. Cinco provas
que antes **fixavam** a chave em inglês passaram a exigir o contrário: a recusa
é exatamente a frase em português, e não contém nada com forma de chave
(`algo.algo`). São elas, em `test_permission_engine.py` e
`test_supervisor_authorization.py`, cobrindo `catalog.update`, `sale.cancel`,
`team.manage` e `contract.request`.

Devolvendo a mensagem em inglês de propósito, as cinco reprovam. Sem esse
controle, elas seriam cinco linhas verdes que não medem nada.

> Fora do alcance, de propósito: a recusa do **console da plataforma**
> (`require_platform_permission`) continua em inglês com a chave. Ela é lida por
> quem opera a Dashem, não por quem está no balcão.

## Alcance desta evidência

Percorrido: concessão e retirada de `sale.cancel` para uma operadora CAIXA, com
a sessão operacional aberta durante as duas mudanças, e conferência **no
servidor** de que a venda não foi cancelada.

Isto é travessia de navegador contra a API local, com semeadura própria — não é
simulação de tela, e não é integração com serviço externo, que aqui não existe.

**Não** percorrido: o mesmo com `sale.discount`; retirada durante uma requisição
já em voo; e propagação para uma aba que o navegador colocou em segundo plano,
onde o relógio do temporizador é do navegador, não do produto.

### O controle da propagação

Desligando a reconferência — o temporizador continua batendo e não pergunta nada
— a travessia **para exatamente onde deveria**: *"a tela precisa perceber a
concessão sem recarregar, e não percebeu em 60007ms"*, e então interrompe.

Interromper ali é deliberado. Na primeira tentativa deste controle a travessia
seguiu adiante, encontrou a tela pedindo supervisor onde já não devia, empilhou
diálogos e reprovou quatro vezes por motivos que **não** eram o que se media.
Uma reprovação legível vale mais que quatro embaralhadas.

O código também tem portão próprio em `frontend/tests/shell_boundaries.test.ts`:
a travessia é rodada à mão, e a conferência periódica não pode sumir em silêncio.

## Lacunas de homologação, depois desta

| Lacuna | Estado |
|---|---|
| Dois destinos nunca percorridos | fechada em 09/09/2026 |
| Duas estações, a segunda achando a unidade já reservada | fechada em 09/09/2026 |
| **Conceder e retirar autoridade, com sessão aberta** | **fechada em 09/09/2026** |
| **Propagação da mudança de autoridade para sessão aberta** | **fechada em 09/09/2026**, nos dois sentidos |
| Catálogo volumoso não exercitado | fechada em 09/09/2026 |
| Estado "em processamento" do TEF | fechada em 09/09/2026 |
| Resposta tardia e reconciliação pelo worker | fechada em 09/09/2026 |
| Duas inclusões simultâneas disputando a última unidade | fechada em 09/09/2026, por prova determinística |
| Transação real com provedor | aberta, pendência separada |
| Vínculo de maquininha percorrido pela tela | aberta, pendência separada |
