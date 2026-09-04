# Alcançabilidade da superfície — confronto e portão

Data: 4 de setembro de 2026
Método: confronto entre a [auditoria de sprints](sprint-confrontation-audit-2026-09-04.md)
deste agente, a auditoria do Codex sobre S13.1, S16, S17.1 e S17.2, e o código.
Nenhum veredito foi aceito de nenhum dos dois lados sem verificação no repositório.

## 1. O que o confronto resolveu

### Confirmado da auditoria do Codex

- **S13.1 e S16 não têm linha de Estado.** As únicas linhas de estado histórico
  do roadmap são as do S17.1 e do S17.2. S13.1 e S16 vão de *Objetivo* direto
  para *Entregas*.
- **O encerramento do roadmap se contradiz.** A seção 12 diz, em três lugares,
  que o Gate B está reaberto e bloqueia o pré-piloto, que foi promovido a
  `PASSED` em 04/09, e que continua reaberto.
- **Defeito de fuso em `reserved_for`.** Confirmado e maior do que o relatado:
  quatro pontos de tela, não dois.
- **A regra de timestamp não cobria o campo.** A expressão do guard cobria
  apenas sufixos `_at` e `_until`.
- **S13.1 não tem jornada de edição nem de ordenação.** Confirmado e mais
  específico: `updateServiceTable` e `updateServiceArea` são chamados, mas
  **exclusivamente** com `is_active: false`. `name`, `capacity`, `area_id`,
  `kind` e `sort_order` estão na assinatura e nenhuma tela os passa. A linha de
  gate do S13.1 é "somente Gestão pode criar, **editar, ordenar** ou arquivar
  uma mesa": dois dos quatro verbos não existem para quem usa.
- **S16 é parcial em todos os pontos levantados**, e em três deles a situação é
  pior do que "falta tela":
  - o fechamento em duas fases não é caminho legado preterido — `begin-close`
    (com conferência cega) e `finalize-close` (com motivo de divergência) **não
    têm função no cliente da API**. O backend os implementa e o
    `test_s16_financial_reconciliation.py` prova `CLOSING`, o 409 do fechamento
    concorrente e a variance derivada do ledger;
  - a contingência fiscal não tinha nem retomada manual: existe
    `POST /fiscal/documents/{id}/retry` no backend, e o cliente expunha apenas
    `issue`, `cancel` e `get`;
  - o refund de tenant (`POST /payments/{payment_id}/refund`) também não tem
    função no cliente. O único refund do frontend é o do Owner SaaS, outro
    domínio.
- **O gateway fiscal ativo é sempre o falso.** `fiscal_gateway = FakeFiscalGateway()`
  é um singleton de módulo, sem fábrica e sem chave de configuração.

### Onde este agente errou

Duas afirmações da auditoria de sprints eram falsas e foram corrigidas no
próprio documento:

- **S13 — "nenhuma tela consome".** `ChannelHubWorkspace` consome as duas rotas
  de leitura. O correto é que as **seis rotas de escrita** não têm função no
  cliente.
- **S12 — "`mergeSessions` não é chamado por componente nenhum".** Não existe
  `mergeSessions` no cliente. `POST /transfers/merge` e o `GET` de linhagem
  nunca chegaram lá.

E uma terceira, sobre o próprio confronto: este agente ia contestar o veredito
do Codex sobre S17.1/S17.2 alegando contradição substantiva no plano OA. **Não
há.** O plano registra `PASSED` de forma consistente em quatro lugares — tabela
de estado, linha do OA-4, gate do OA-4 e a seção de 03/09 — e a evidência
credenciada existe, com as duas lacunas de captura declaradas honestamente. O
Codex estava certo. Sobraram duas strings desatualizadas: o `Status:` do
cabeçalho do plano e o bullet "a matriz atualizada precisa ser executada
novamente", que é histórico de 26/08 e lê como presente.

## 2. O achado transversal: o instrumento, não as sprints

O padrão "backend pronto, tela ausente" não escapou de cinco auditorias por
descuido. Escapou porque **nada media a metade UI da régua**.

A régua é do próprio roadmap, seção 10 item 7: "implementado" significa UI + API
+ persistência + autorização + testes. A suíte de frontend não tem
`@testing-library`, `jsdom` nem `vitest`: são arquivos de `readFileSync` e regex
sobre o texto-fonte. O teste do S13.1 assere `assert.match(api, /updateOperationalDevice/)`,
que passa igual se nenhuma tela chamar a função.

Isso já estava escrito. A [matriz de invariantes](core-invariant-test-map.md)
registra desde 25/08 que "os testes regulares de frontend continuam
majoritariamente testes de fonte e regras isoladas". O que faltava não era o
diagnóstico — era **medida e portão**. Uma fraqueza conhecida e não medida não
reprova build nenhuma.

### A medida, em 04/09/2026

| Medida | Número |
|---|---|
| Rotas `/api/v1` | 254 |
| Rotas que nenhuma função do cliente alcança | **62** |
| Dessas, superfície de máquina (webhook, bridge) | 4 |
| Dívida | **58** |
| Funções exportadas do cliente | 193 |
| Sem nenhum consumidor no produto | **28** |

Estes são os números **no fim desta rodada**. A medição inicial com verbo + forma
deu 63 sem chamada do cliente, 59 de dívida; fechou em 62 e 58 porque a correção
do item 3 alcançou `POST /fiscal/documents/{id}/retry` e o teste de obsolescência
exigiu a remoção da linha — que é como o baseline deve encolher.

A dívida por módulo, no vocabulário do [ADR-029](../architecture/adr-029-module-boundaries-and-owner-layer.md):

| Módulo | Rotas inalcançáveis | O que isso significa |
|---|---|---|
| `owner` | 28 | pilotos, incidentes, execuções de hardening, contratos e fontes de storage têm endpoint e não têm console; o console lista leads e não cria |
| `finance` | 9 | S16: fechamento em duas fases, refund de tenant, estorno de recebível — e o acordo, que pode ser criado e não pode ser lido de volta |
| `channels` | 7 | S13: toda a escrita de publicação e repasse, inclusive abrir o repasse |
| `identity` | 5 | inclui o heartbeat de dispositivo, que **ninguém envia** — e a tela de Gestão exibe "Presentes agora · heartbeat nos últimos 90 segundos" |
| `catalog` | 5 | combos e modificadores são modelados e não podem ser cadastrados; produto se edita e não se remove |
| `operation` | 3 | S12: junção de mesas e linhagem de transferência |
| `insight` | 1 | fórmulas do BI |

## 3. O que foi construído

### Item 1 — o portão de alcançabilidade

`backend/tests/test_surface_reachability.py`, no mesmo desenho de
`test_module_boundaries.py`: declara o mapa, congela a dívida em baseline,
reprova o que for novo e **também** reprova a linha de baseline que deixou de
ser verdade, para que a lista não vire ficção.

Mede as duas direções:

- rota que nenhuma função do cliente alcança — porta construída sem maçaneta;
- função do cliente que nenhum componente chama — maçaneta presa em porta nenhuma.

O casamento é por **verbo + forma**, e as duas pontas são normalizadas em forma
de rota: `${...}` e `{param}` viram o mesmo curinga, curingas consecutivos
colapsam (o cliente preenche dois parâmetros de storage numa interpolação só) e
o sufixo de query é tolerado. `fetch` sem `method` explícito é `GET`.

Cada uma dessas decisões foi paga com uma medida errada antes de estar certa, e
o registro fica porque a próxima versão do portão vai cair nas mesmas:

A coluna é o total **sem chamada do cliente**, superfícies de máquina incluídas —
não a dívida, que é esse total menos as quatro:

| Versão do casamento | Rotas sem chamada | O que estava errado |
|---|---|---|
| substring | 53 | `/refund` casava dentro de `/refunds` e escondia o refund de tenant |
| regex exata | 64 | acusava cinco rotas que o cliente alcança por caminho construído de outro jeito |
| forma de URL | 59 | **cega para o método**: uma chamada `GET` fazia o `POST` do mesmo caminho parecer construído |
| verbo + forma | 63 | correta; caiu para 62 quando a retry fiscal ganhou cliente |

O cegamento de método escondia quatro rotas atrás das próprias irmãs:
`DELETE /catalog/products/{id}`, `GET /receivables/agreements`,
`POST /channel-catalog/settlements` e `POST /control/leads`. Uma delas contradizia
este mesmo documento: a prosa dizia que as **seis** escritas de `/channel-catalog`
faltavam, e o baseline listava cinco. A prosa estava certa e o portão, não.

Superfície de máquina é conjunto separado do baseline, não linha de dívida: um
webhook de marketplace e os callbacks do TEF Bridge nunca terão função de
cliente, e chamá-los de dívida tornaria a lista permanentemente desonesta.

### Item 2 — o fuso, e a classe do problema

O defeito: `reserved_for` é `sa.DateTime()` naive na migration 029, o serviço
normaliza com `_utc_naive` e a API entrega sem offset. `new Date` sobre isso lê
como hora local. No Brasil, reserva das 19:00 aparecia como 22:00 — inclusive no
diálogo "Confirme antes de abrir", que existe justamente para conferir o horário
antes de sentar o cliente. A escrita estava correta; só a leitura mentia.

Quatro pontos corrigidos para `formatApiDateTime`:

- `ServiceSetupManager.tsx` — cartão da mesa e linha da reserva;
- `TableServiceWorkspace.tsx` — hora no cartão da mesa e diálogo de confirmação.

**A correção que importa não é essa.** Acrescentar `reserved_for` à expressão
seria o mesmo defeito de classe do vocabulário por nicho: resolver o caso que
apareceu e não ter onde declarar o próximo. O contrato tem **20 campos de data
fora da convenção** `_at`/`_until`.

A regra foi invertida. `SERVER_DATE_FIELDS`, no guard do frontend, nomeia os
vinte, e `test_frontend_names_every_server_date_field` os confere contra o
**schema OpenAPI** — o contrato do fio, não uma leitura do código. A lista não
pode envelhecer em nenhuma direção: campo novo fora da convenção que ela não
nomeia reprova, e nome que o contrato não tem mais também.

O valor que a pessoa digita continua legítimo em `new Date`: um campo
`datetime-local` já é hora local. A única exceção existente é nomeada uma a uma
em `TYPED_IN_THE_BROWSER`, como exceção deliberada e não como defeito silenciado.

**O que este guard não é.** Ele casa um caminho pontilhado terminado no nome do
campo, então é análise estática de texto, não de fluxo de dados. Um alias o
contorna sem esforço:

```ts
const value = row.reserved_for
new Date(value)          // passa
```

Cobre o jeito como o defeito de fato apareceu quatro vezes — leitura direta na
tela — e não cobre wrapper nem variável intermediária. Fica declarado aqui em vez
de ser descoberto na próxima reserva com três horas de diferença.

### Item 3 — a promessa da contingência

`FiscalStatusModal` dizia que o cupom emitido offline "será transmitido
automaticamente na retomada da conexão com a SEFAZ". Não há nada que faça isso.

Existe um worker e ele roda: `dashem-pos-worker` é serviço próprio do
`docker-compose.yml`, com `python -m app.workers.outbox_worker`. O que ele faz é
outra coisa — reivindica um evento do outbox, publica e persiste o recibo
imutável. Não chama o gateway fiscal em ponto algum, e a emissão em contingência
grava apenas o evento `fiscal.contingency`, que ninguém consome para
retransmitir. Não há agendador, fila de reprocessamento nem tentativa
temporizada: a retomada só acontece se alguém mandar.

O texto agora diz o que acontece: emitido offline, **ainda não transmitido**, e
a transmissão não é automática.

E a tela deixou de ser um beco sem saída. A contingência ganhou **Tentar
transmitir novamente**, ao lado da chave, por `retryFiscalDocument` →
`POST /fiscal/documents/{id}/retry`. Com isso a rota saiu do baseline do portão,
e o teste de obsolescência **exigiu** essa remoção — é o baseline encolhendo pelo
único jeito legítimo.

**A primeira versão deste botão estava errada, e do mesmo jeito que o texto que
ele veio corrigir.** Ele chamava `issueFiscal()`, ou seja, `/documents/issue`.
Funcionava — `issue_fiscal_document` reaproveita o documento enquanto ele não
estiver `AUTHORIZED` ou `NOT_REQUIRED`, sem duplicar Sale nem FiscalDocument, e
já incrementa `attempt_count` —, mas registrava a retomada **como se fosse a
primeira emissão**. O que se perdia era a trilha que distingue uma coisa da
outra: `RETRY_REQUESTED` no `FiscalEvent`, `fiscal.retry_requested` no outbox e a
ação de auditoria `fiscal.retry`. Trocar uma promessa falsa no texto por uma
trilha de auditoria falsa no botão não é correção. Agora vai pelo endpoint
desenhado para isso — **e o mesmo vale para a rejeição**, cujo botão "Tentar
Novamente" continuava na rota de emissão e perdia exatamente os mesmos eventos.
Rejeição e contingência são o mesmo caso e passaram a compartilhar o handler.

**A trilha específica também não era atômica.** `retry_fiscal_document` chamava
`issue_fiscal_document`, que executa `commit`, e só então gravava
`RETRY_REQUESTED` e `fiscal.retry_requested` num segundo commit: uma falha entre
os dois deixava a tentativa concluída sem a trilha que a distingue. Como
`write_audit_and_outbox` apenas adiciona à sessão, a ordem é o que decide — a
trilha passou a ser escrita **antes** da tentativa, entrando no mesmo commit.

Isso expôs uma corrida que o desenho anterior escondia: se o documento virasse
terminal entre a checagem de estado e o lock, `issue_fiscal_document` retorna sem
commit e a trilha pendente se perderia em silêncio. Agora esse caso devolve o
mesmo `409` da checagem e faz `rollback`, em vez de registrar uma retomada que
não aconteceu.

O rótulo também mudou. **Transmitir à SEFAZ** afirma entrega; o botão comanda
uma tentativa. E há o fato maior, já registrado acima: o gateway ativo é sempre
`FakeFiscalGateway`, que devolve `AUTHORIZED` por padrão — de modo que este
botão, como toda a superfície fiscal do produto, hoje conversa com um simulador.
O rótulo diz o que o comando faz; **o que ele não pode fazer é a homologação
fiscal que continua pendente.**

**Achado colhido na própria correção, duas vezes.** O botão nasceu
`bg-amber-600` com texto branco: **3,19:1**, abaixo do AA de 4,5:1, e `text-xs`
não é texto grande. Trocado por `amber-700` (5,02:1) — e a primeira correção
manteve `hover:bg-amber-600`, devolvendo no hover exatamente os 3,19:1 que o
texto declarava eliminados. O hover agora é `amber-800` (7,09:1), mais escuro que
o repouso.

A medida da classe inteira: a sondagem encontrou **9 pontos** com `text-white`
sobre hover abaixo do AA, incluindo o que esta rodada introduziu. Corrigido esse,
**restam 8**, todos pré-existentes — dois deles no mesmo modal, e em dois
(`emerald-600`, 3,77:1) o repouso já falha.

O `theme_contrast.test.ts` **não pega nenhum deles**: ele defende colisões
estruturais — fundo escuro com texto escuro, claro com claro, preenchimento de
marca sem `text-brand-contrast` — e não mede razão numérica de par arbitrário do
Tailwind, nem olha estado de hover. Fica registrado como lacuna com número: o
critério "contraste WCAG AA **medido**" do gate da OA-3 é hoje verificado por
regra estrutural, e é a terceira vez que contraste regride neste projeto.

## 4. Estado da verificação

Onde cada coisa rodou importa, e a primeira redação desta seção não deixava isso
claro:

- backend, suíte completa **executada no host** (`backend/.venv`), apontando para
  o PostgreSQL do compose (`127.0.0.1:5437`) e a API do compose
  (`127.0.0.1:8002`): **252 passed**;
- frontend: **95 passed**; `tsc --noEmit` e build de produção aprovados;
- fronteiras de módulo: `test_module_boundaries.py` verde — nenhuma travessia
  nova e nenhum baseline obsoleto.

**Armadilha do portão local, encontrada nesta rodada.** Boa parte da suíte fala
com a API por HTTP em `TEST_BASE_URL`, e o `entrypoint.sh` sobe
`uvicorn app.main:app` **sem `--reload`**. O volume `./backend:/app` atualiza o
arquivo dentro do container, mas o processo continua com o módulo carregado na
partida. Uma rodada no host contra a porta 8002 depois de alterar um serviço
testa, portanto, o **código antigo** e passa. Foi o que aconteceu com a primeira
execução verde desta alteração no `fiscal_service`: os mesmos 252 passaram sem
exercitar a mudança. O número acima é de uma execução posterior ao
`docker restart dashem-pos-backend`. Alterou serviço, reinicie o container antes
de acreditar no verde.

**Estes portões não rodam dentro do container de backend.** O compose monta
apenas `./backend:/app`, e sete testes leem a árvore do frontend — os três de
`test_frontend_api_contract.py` e quatro dos cinco de
`test_surface_reachability.py` (`test_every_surface_belongs_to_a_declared_module`
só lê o OpenAPI). Nesse modo eles falham por `FileNotFoundError`. O CI não é
afetado, porque faz checkout do repositório inteiro; mas a consequência é que
**rodar a suíte dentro do container não exercita o portão**, e um verde ali não
significa nada sobre alcançabilidade. Quatro desses sete testes são novos: esta
rodada ampliou uma fragilidade que já existia em três.

Os dois portões novos foram provados a **reprovar**, não só a passar. O de
alcançabilidade, nas quatro direções: rota nova inalcançável (com o módulo
nomeado na mensagem), linha de baseline que virou alcançável, função órfã nova e
linha órfã que ganhou consumidor. O de timestamp, nas duas: defeito reintroduzido
numa tela é apontado com arquivo, linha e expressão; nome retirado da lista é
acusado pelo teste de backend contra o schema. Um portão que só sabe passar é o
que produziu esta dívida.

O E2E operacional não foi executado nesta rodada: continua sendo job próprio do
CI e não é coberto pelo portão local.

## 5. O que continua pendente, e é decisão do dono

Nada aqui promove ou rebaixa sprint. Continuam abertos, por serem ato de
autoridade:

1. linha de Estado para **S13.1** e **S16**;
2. reconciliar as três afirmações sobre o Gate B na seção 12 do roadmap;
3. o `Status:` do cabeçalho do plano OA e o bullet histórico da matriz;
4. a linha de dívida do S12 na seção 9, que ainda descreve mal o que falta.

E, no produto, os achados que este trabalho nomeou e não resolveu:

- a mesa não pode ser editada nem ordenada pela Gestão;
- o "Presentes agora" da tela de dispositivos mede um heartbeat que ninguém envia;
- o S13 mostra publicação e repasse sem deixar publicar nem conciliar;
- **oito pontos de contraste pré-existentes** abaixo do AA no hover, dois deles
  já abaixo no repouso. Corrigi apenas o que eu mesmo introduzi; mexer nos outros
  altera o visual de botões da Gestão e do PDV, e identidade visual é eixo
  governado.

E três decisões de desenho que levantei e não tomei sozinho:

1. **portão de contraste medido**, que calcularia a razão de cada par
   fundo/texto — inclusive `hover:` — em vez da regra estrutural de hoje. É o que
   impediria a quarta regressão;
2. **o que fazer com os sete testes que leem o frontend**: pular com motivo
   declarado quando a árvore não existe (verde com skip no container) ou deixar
   falhar. Pular é mais limpo e corre o risco de esconder um checkout quebrado no
   CI;
3. **homologação do gateway fiscal**, sem a qual `FakeFiscalGateway` faz de toda
   a superfície fiscal um simulador — inclusive o botão que esta rodada
   acrescentou.
