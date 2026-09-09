# Homologação — os dois destinos que nunca tinham sido percorridos

Data: 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
evidência: [`evidence/hom-01-mesas/`](evidence/hom-01-mesas/) e
[`evidence/hom-02-provedores/`](evidence/hom-02-provedores/).

A UX-05 auditou oito módulos e deixou dois de fora — **Ambientes e Mesas** e
**Provedores de pagamento** — com a razão registrada de que "o acervo de
homologação não contrata `FOOD_SERVICE` nem `tef`". Estas são as duas jornadas,
percorridas.

## O que o acervo realmente exigia

A razão antiga estava perto, e não era exata:

- **`table_service` já estava semeado** como entitlement no acervo de
  homologação, e mesmo assim não chegava ao acesso efetivo.
  `capability_allowed_by_activity` recusa atender mesa a quem não declarou food
  service, e o acervo não declarava **atividade nenhuma**. Faltava atividade,
  não capability;
- **`tef` não é vendável.** Ele entra pelo caminho que o ADR-031 abriu:
  `homologation_override` na configuração do entitlement, com a capability fora
  da lista de implementadas e as dependências dela já valendo. Ligar TEF onde
  pagamentos não vale continua sendo recusado.

O roteiro `backend/tests/support/seed_food_service_walkthrough.py` monta isso
pelos mecanismos do próprio produto: atribui a revisão de perfil `FOOD_SERVICE`
— é dela que a atividade é lida quando não há contrato versionado — e concede o
override de homologação para o TEF.

## O defeito que a homologação encontrou

Com a atividade declarada, o servidor passou a autorizar `table_service` e a
devolver o card de Ambientes e Mesas. **E a tela continuou escondendo o card.**

Duas leituras da mesma pergunta discordavam:

| Quem pergunta | De onde lia | Resposta |
|---|---|---|
| `capability_allowed_by_activity` (o portão) | `tenant_activity_keys` — cai no perfil declarado quando não há contrato | `FOOD_SERVICE` |
| `GET /capabilities/effective` (a resposta à tela) | só `contract_snapshot.activity_keys` | `[]` |

E o `ManagementLayout` filtra o card de mesas por
`activities.includes('FOOD_SERVICE')`. Resultado: para todo tenant com perfil
declarado e sem contrato versionado — que é exatamente o caso legado que o
backend decidiu honrar — **a jornada existia, era autorizada, e não tinha como
ser alcançada**.

A resposta passou a ler da mesma fonte que o portão. É a correção que abriu o
primeiro destino.

## Jornada 1 — Ambientes e Mesas

`frontend/e2e/presentation/hom01_ambientes_e_mesas.cjs` — 7 etapas, 8 telas, 0 falhas.

| Etapa | Evidência |
|---|---|
| O card aparece em Estrutura, com a frase de tarefa do mapa | `1-card-em-estrutura.png` |
| Cadastrar um ambiente, e ele dizer que ainda não tem mesas | `3-ambiente-cadastrado.png` |
| Cadastrar uma mesa nele, nascendo disponível | `4-mesa-no-mapa.png` |
| Sinalizar impedimento com motivo, e o motivo ficar à vista | `5-mesa-impedida.png` |
| Liberar, e o motivo sair junto | `6-mesa-liberada.png` |
| **Recusa:** ambiente com mesa não se arquiva | `7-ambiente-com-mesa.png` |
| **Permissão:** vê o mapa, não configura | `8-ve-o-mapa-sem-configurar.png` |

### A prova de permissão, e por que ela não é com um caixa

A primeira tentativa usou um perfil de caixa, e ela não serve: **caixa não entra
na Gestão** — a tela recusa com "terminal não autorizado", porque a entrada dele
é a operação, com terminal autorizado. E dentro da Gestão nenhum perfil de
sistema tem `table.read` sem `table.manage`.

A distinção existe de verdade por **concessão**: uma gerente com `table.manage`
negado na própria linha de vínculo — o mesmo mecanismo que a UX-13 usa para
autoridade presencial, e o jeito real de um lojista tirar uma permissão de
alguém. Na tela, ela vê o mapa com o ambiente e a mesa, e recebe apenas
"Bloquear": nada de "Novo ambiente", "Nova mesa", "Editar" ou "Arquivar".

## Jornada 2 — Provedores de pagamento

`frontend/e2e/presentation/hom02_provedores_de_pagamento.cjs` — 9 etapas, 7 telas, 0 falhas.

**Contratar `tef` no acervo não comprova, sozinho, uma transação TEF.** São três
camadas, e misturá-las é como um cadastro vira "integração pronta" num
relatório:

| Camada | Estado | O que a evidência mostra |
|---|---|---|
| **Configuração na tela** | percorrida | provedor cadastrado, bridge pareado, código de pareamento gerado uma única vez |
| **Simulação de bridge** | percorrida | o heartbeat foi enviado **por este roteiro**, no papel do Dashem TEF Bridge |
| **Integração real com provedor** | **não percorrida** | nenhuma transação TEF foi executada e nenhum provedor foi contatado |

| Etapa | Evidência |
|---|---|
| O card existe em Financeiro | `1-card-em-financeiro.png` |
| A tela parte dizendo que a conexão TEF ainda não está disponível | `2-tela-sem-provedor.png` |
| Configurar provedor, e a tela manter a ressalva sobre cadastro | `3-provedor-configurado.png` |
| Parear bridge: código mostrado uma vez, com o aviso de que não volta | `4-codigo-de-pareamento.png` |
| Pareado **não** é conectado: versão do bridge "ainda não informada" | `5-bridge-pareado-sem-conexao.png` |
| **Um bridge que fala não é um bridge que serve** | `6-bridge-fala-e-nao-serve.png` |
| Com o protocolo certo: Online, e "última operação: —" | `7-conexao-relatada-pelo-bridge.png` |

### A falha que vale mais que um verde

O heartbeat foi enviado duas vezes de propósito. Na primeira, com protocolo
incompatível: **a API aceitou a chamada (200) e a tela marcou o terminal como
"Com falha", nomeando `PROTOCOL_VERSION_MISMATCH`**. Chegou mensagem, e não está
funcionando — são coisas diferentes, e a tela sabe distingui-las.

Na segunda, com o protocolo que o terminal declara, o estado virou "Online" com
a versão relatada. E mesmo Online, a tela continua dizendo **"Última operação:
—"** e mantendo a frase *"Cadastro ativo não comprova conexão, homologação ou
aprovação de cobrança"*. Conectado e nunca transacionado é exatamente o estado
em que a homologação parou.

## O que fica registrado como não provado

- **Transação TEF real**, com provedor de verdade. Depende de credencial de
  homologação de um provedor e de um bridge instalado. Nada aqui substitui isso.
- **SmartPOS**: a própria tela declara "somente cadastro; execução indisponível
  até existir um adapter homologado". Não foi exercitado além do cadastro.
- **Vínculo de maquininha** (POS ligado a caixa e provedor): não percorrido
  nesta rodada; a jornada de bridge foi a escolhida para provar a distinção
  entre as camadas.

## Lacunas de homologação que continuam abertas

Estas duas saem da lista. Continuam abertas, e cada uma espera a sua prova:

| Lacuna | Estado |
|---|---|
| Catálogo volumoso não exercitado | aberta |
| Concorrência de duas estações pela tela | aberta |
| Estado "em processamento" do TEF sem tela | aberta — e agora com um bridge simulado que pode ajudar a produzi-lo |
| Conceder autoridade a um operador e vê-lo agir sozinho | aberta |
| Transação TEF real com provedor | aberta, nomeada aqui pela primeira vez |
