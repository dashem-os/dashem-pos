# UX-12 — Diagnóstico do sistema e acesso ao suporte: contrato

Data: 08/09/2026 · trilha: [sprints da experiência](ui-ux-implementation-sprints.md) ·
**estado: aprovado pelo dono em 08/09/2026.**

O dono recomendou o escopo inicial: *"diagnóstico do sistema e acesso ao suporte
— conexão, sincronização e situação dos dispositivos"*, e pediu para alinharmos
antes. Este documento é o alinhamento: o que o inventário achou, o que se
entrega, e as decisões — que já foram tomadas.

## As decisões do dono, em 08/09/2026

| Pergunta | Resposta |
|---|---|
| Aprovação do tenant no acesso assistido | **Obrigatória.** Responsável autorizado do tenant, com escopo, expiração e revogação efetiva |
| Caminho de emergência | **Fora da primeira entrega** |
| Canal de suporte real | Será informado. **Não bloqueia** diagnóstico nem controle de acesso |

A terceira resposta define a fronteira desta entrega: o botão que abre chamado
num canal externo fica de fora até haver canal. O que entra é tudo que não
depende dele.

## O inventário

| Procurado | Encontrado |
|---|---|
| Saúde de componentes | `GET /api/v1/identity/platform/system-health` — API, banco, fila transacional, com latência e limiar. **Só para papéis da plataforma**, com AAL2 |
| Pendência e falha de sincronização | `control_workspace` devolve `backlog`, `failed`, `last_sync_at` e os cinco últimos erros — **por tenant, e só no console do Owner** |
| Situação dos dispositivos | `devices.last_seen_at` e a rota de `heartbeat` existem; nenhuma tela do lojista os apresenta como "está ligado?" |
| Pedir ajuda | `AssistedSupportGrant`, com escopo, motivo, expiração, aprovação e revogação — completo |
| Incidentes | `PlatformIncident`, por tenant |

O que o inventário **não** achou é o que define a sprint: **nada disso chega ao
lojista.** Ele não tem como responder "está tudo funcionando?" sem ligar para
alguém — e é justamente quando não está funcionando que ligar é mais difícil.

## O achado que muda a prioridade

`AssistedSupportGrant` é pedido pela plataforma (`POST /control/tenants/{id}/support`)
e decidido pela plataforma (`PATCH /control/support/{id}`). **O lojista não
aparece em nenhum dos dois lados.**

Ou seja: hoje o suporte pode receber acesso aos dados de um tenant sem que o
dono daquele tenant veja o pedido, aprove, ou consiga revogar. O registro em
auditoria existe — mas auditoria é para depois, e ninguém audita o que não sabe
que aconteceu.

Isso não é uma lacuna de tela. É uma decisão de produto que ficou tomada por
omissão, e o dono decidiu corrigi-la nesta sprint — de propósito, agora.

## O contrato

### Parte 1 — Diagnóstico: "está tudo funcionando?"

Uma tela, no card de Administração, que responde três perguntas do lojista com a
palavra dele:

| A pergunta dele | O que a tela mostra | De onde vem |
|---|---|---|
| "A internet/o sistema está no ar?" | Conexão com o servidor, e há quanto tempo | requisição própria + `/health` |
| "O que eu registrei chegou?" | Se há coisa esperando para sincronizar, quantas e desde quando | `OutboxEvent` do próprio tenant |
| "Meus equipamentos estão vivos?" | Cada terminal, com "visto pela última vez há N minutos" | `devices.last_seen_at` |

Regras fixadas:

- **Estado derivado, nunca gravado.** "Atrasado" é a idade do item mais antigo
  contra um limiar, calculada na hora — a mesma disciplina que a UX-10 aplicou a
  "vencida". Uma coluna gravada precisaria de alguém virando linhas.
- **Nada de jargão.** Não se escreve "outbox", "backlog" nem "AAL2" na tela do
  lojista. Escreve-se "3 registros esperando para sincronizar, o mais antigo há
  12 minutos".
- **Silêncio não é saúde.** Se a consulta falhar, a tela diz que **não
  conseguiu verificar** — nunca mostra tudo verde por falta de resposta. Esta é
  a regra que a UX-10 já aplicou à lista de contas, e vale mais aqui.
- **Sem ação destrutiva.** Diagnóstico informa. Reprocessar fila, revogar
  dispositivo e derrubar sessão continuam onde já estão, com as permissões que
  já têm.
- **Permissão própria**, `diagnostics.read`, para OWNER, TENANT_OWNER, ADMIN e
  MANAGER. Um operador de caixa não precisa disso para vender.

### Parte 2 — Acesso ao suporte: quem entra nos meus dados

- O lojista **vê** os acessos de suporte concedidos ao seu tenant: quem, com que
  escopo, por qual motivo, até quando.
- O lojista **revoga** um acesso ativo, com efeito imediato e registro.
- Um pedido de acesso passa a **exigir aprovação do tenant** antes de valer.
- Pedir ajuda: um canal para abrir o chamado, carregando junto o diagnóstico
  acima — porque a primeira pergunta do suporte é sempre essa.

**A autorização é nominal.** Ela vale para o profissional que pediu, e para
mais ninguém: a porta compara quem está lendo com quem pediu, e a tela do
lojista nomeia essa pessoa. Autorizar uma equipe inteira teria de estar escrito
no pedido e é decisão do dono — o silêncio não autoriza.

**Decidido: aprovação obrigatória, sem caminho de emergência nesta entrega.**
Nenhum acesso assistido passa a valer sem que um responsável autorizado do
tenant aprove, e o que ele aprova é explícito — escopo, prazo e motivo à vista.
Revogar tem efeito imediato.

O caminho de emergência — a loja parada às 20h de sábado, com o dono sem
atender — é real e fica registrado como assunto próprio. Ele não entra agora, e
enquanto não entrar **não existe porta dos fundos**: sem aprovação do tenant,
não há acesso.

### Fora da primeira entrega

| Fora | Por quê |
|---|---|
| Manutenção de **equipamentos** (ordem de serviço, garantia, técnico) | É outro domínio; entra se houver demanda real, não porque a palavra "manutenção" nomeia a sprint |
| Histórico e gráfico de disponibilidade | Diagnóstico responde "agora"; série temporal é insight |
| Reprocessar a fila pela tela do lojista | Ação destrutiva sobre dado transacional, sem contrato definido |
| Chat ao vivo com o suporte | Depende de canal externo contratado |
| **Abrir chamado** num canal | O canal real ainda será informado. O diagnóstico já fica exportável para ser colado onde for |
| **Caminho de emergência** de acesso | Decisão do dono: fora da primeira entrega |

## Aceite

- Abrir o diagnóstico com tudo saudável e ver dito que está saudável, com números.
- Derrubar a sincronização de propósito e ver a tela **acusar**, com quantos
  itens e desde quando — o controle é obrigatório, como nas sprints anteriores.
- Cortar a resposta do servidor e ver "não foi possível verificar", nunca verde.
- Ver um terminal que não dá sinal aparecer como tal.
- Conceder um acesso de suporte, vê-lo na tela do lojista, revogá-lo, e conferir
  que ele parou de valer.
- Um operador sem `diagnostics.read` não alcança a tela.

## O que muda em algo que já roda

Corrigir o fluxo de `AssistedSupportGrant` é mudança de comportamento em código
publicado: hoje a plataforma pede e a plataforma decide. Depois desta sprint, o
pedido continua vindo da plataforma, mas **quem decide é o tenant**.

Isso torna inválido, por construção, qualquer acesso que estivesse valendo sem
aprovação do dono dos dados. A migração trata os pendentes como pendentes — não
os aprova em massa para "não quebrar" — e quem precisar de acesso pede de novo,
agora para quem tem de autorizar.

**E preserva o histórico dessa transição.** Quem aprovou e quando continuam
gravados; duas colunas novas dizem quando e por que aquela aprovação perdeu
validade. Invalidar apagando os campos destruiria o registro exatamente na
migração que existe para dar dono à decisão.

Preservar num momento só, porém, não basta: a **reaprovação** sobrescreve quem
aprovou e limpa a marca da invalidação, porque estado atual é sempre uma coisa
só. Por isso a concessão tem uma **razão de lançamentos**
(`assisted_support_grant_events`): pedido, aprovação, invalidação, nova
aprovação e revogação são linhas, nada é sobrescrito, e o lojista lê a sequência
inteira na tela. A invalidação por regra nova entra sem autor — ela não foi
decisão de ninguém.
