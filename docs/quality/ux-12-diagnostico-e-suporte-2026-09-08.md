# UX-12 — o lojista vê o próprio estado, e manda em quem entra nos dados

Data: 08/09/2026, com a revisão do dono em 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
contrato: [UX-12](../product/ux-12-diagnostico-e-suporte-contrato.md) ·
evidência: [`evidence/ux-12/`](evidence/ux-12/).

Duas metades. A primeira é uma tela que faltava. **A segunda é uma correção de
segurança**, e é ela que dá o nome à sprint.

## O que o inventário achou

Saúde de componentes, pendência de sincronização e sinal de dispositivo já
existiam — todos do lado do Owner. Nenhum chegava ao lojista, que não tinha como
responder "está tudo funcionando?" sem ligar para alguém. E é justamente quando
não está funcionando que ligar é mais difícil.

E achou isto:

> `assisted_support_grants` era **pedido pela plataforma e decidido pela
> plataforma.** O dono dos dados não via o pedido, não aprovava e não revogava.

Pior: a política da tabela era `platform_only`. O lojista não conseguia nem
**ler** a linha que fala do acesso aos dados dele. Não era falta de tela — era o
banco dizendo que aquilo não era assunto dele.

## Parte 1 — está tudo funcionando?

Uma tela no card de Administração que responde as perguntas dele com a palavra
dele — e só afirma o que cada verificação mediu:

| A pergunta dele | O que ele lê |
|---|---|
| O sistema está no ar? | *"O sistema respondeu agora."* |
| O banco responde? | *"Conexão com o banco respondendo."* |
| Há envio parado no servidor? | *"1 envio saindo da fila do servidor agora."* |
| Meus equipamentos deram sinal? | *"Terminal do balcão — nunca deu sinal"* |

Quatro regras, e cada uma tem prova:

- **Estado derivado, nunca gravado.** "Atrasado" é a idade do item mais antigo
  contra um limiar, calculada na hora — a mesma disciplina de "vencida" na
  UX-10.
- **Silêncio não é saúde.** Verificação que falha responde `NAO_VERIFICADO`, e a
  tela diz *"não foi possível verificar"*. Nunca verde por falta de resposta. Um
  equipamento que nunca deu sinal também é `NAO_VERIFICADO`, não "saudável" — e
  a situação geral segue a **pior** parte, porque média de saúde esconde
  exatamente o que precisa de decisão.
- **Nada de jargão.** Um teste reprova se "outbox", "backlog", "AAL2",
  "payload" ou "queue" aparecerem no texto que o lojista lê.
- **Cada frase afirma só o que a sua medição comprova.** Esta regra veio da
  revisão do dono, e ela estava sendo quebrada em dois lugares: um `SELECT 1`
  virava *"leitura e gravação respondendo normalmente"* — duas afirmações com a
  prova de uma — e a fila do servidor virava *"tudo o que você registrou já foi
  enviado"*, que não alcança o que ainda estiver num aparelho desconectado.
  Agora são *"Conexão com o banco respondendo"* e *"Nenhum envio pendente na
  fila do servidor"*, e a abrangência da medição vai no próprio dado.

## Parte 2 — quem entra nos meus dados

Decisão do dono, em 08/09/2026: **aprovação obrigatória do responsável
autorizado do tenant**, com escopo, expiração e revogação efetiva. Caminho de
emergência fica fora da primeira entrega.

O que mudou:

| Antes | Agora |
|---|---|
| A plataforma pedia e a plataforma aprovava | A plataforma pede; **aprovar é do tenant** |
| O lojista não via a linha (RLS `platform_only`) | Ele lê e decide as próprias autorizações |
| Revogar era decorativo: nada consultava a concessão | Revogar corta na leitura seguinte |
| Não se sabia quem cortou | `revoked_by` responde |
| **A autorização era anônima e valia para qualquer um** | **É nominal: vale para quem pediu, e a tela diz quem é** |

### O defeito que a revisão do dono encontrou

A primeira versão da porta conferia tenant, situação, prazo e escopo — e **não
conferia quem estava lendo**. Uma autorização dada a uma pessoa abria o estado
operacional para qualquer profissional que alcançasse o console da plataforma.
E a resposta enviada ao lojista trazia motivo, escopo e prazo, sem identificar
ninguém: ele autorizava um pedido anônimo, sob um título que promete dizer
"quem tem acesso aos seus dados".

Agora a porta compara o leitor com `requested_by`, e a tela nomeia o
solicitante com nome e e-mail, dizendo que autorizar libera **só aquela
pessoa**. Autorizar uma equipe inteira seria outra coisa, teria de estar escrita
no pedido, e é decisão do dono — não se deduz do silêncio.

### A migração preserva, em vez de apagar

A consequência deliberada continua: **toda autorização aprovada sem o tenant
volta a pendente.** Mas a primeira versão fazia isso limpando `approved_by` e
`approved_at`, o que destruía o registro de quem aprovou e quando — justamente
na migração que existe para dar dono à decisão.

A 095 passou a preservar nas próprias colunas: os dois campos originais ficam
onde estavam, e `invalidated_at` e `invalidated_reason` dizem quando e por que
aquela aprovação perdeu validade.

### E a razão, porque preservar num momento só não bastava

A segunda revisão do dono achou o buraco que sobrava: **isso resolvia a
invalidação em massa, e não resolvia o momento seguinte.** Quando o responsável
aprova de novo, `approved_by` e `approved_at` são sobrescritos e a marca da
invalidação é limpa — porque estado atual é sempre uma coisa só. A transição
sumia, e o evento de auditoria daquela aprovação nem sequer dizia o que ele
estava substituindo. Meu comentário no código afirmava que "o histórico fica na
auditoria", e o trecho ao lado não registrava nada disso.

A concessão ganhou o que as contas a pagar têm desde a UX-10: **uma razão de
lançamentos** (`assisted_support_grant_events`, migração 096). Cada decisão é
uma linha — pedido, aprovação, invalidação, nova aprovação, revogação — nada é
sobrescrito, e o histórico se lê de ponta a ponta na tela do lojista. O que já
estava gravado nas colunas virou linha na migração, para o histórico não
começar do zero naquela data.

Duas escolhas que o formato obrigou a tomar:

- **a invalidação não tem autor.** Ela veio de uma regra, não de alguém, e o
  campo fica vazio. Inventar um autor seria pior do que admitir que não há —
  e é por isso que a tela escreve "Perdeu a validade", não "cancelado";
- **o nome de quem agiu é gravado no lançamento**, não só o identificador. O
  cadastro pode sumir; o histórico não pode ficar sem dono por causa disso.

E o evento de auditoria da nova aprovação passou a carregar `substituiu`, com
quem havia aprovado, quando, e por que aquilo tinha caído.

### A ressalva que não pode ser omitida

Hoje **nenhuma rota de plataforma atravessa para dentro da operação do tenant**:
não há impersonação, e o console do Owner não lê venda, cliente nem pagamento. A
autorização governa o único lugar em que a plataforma lê estado operacional do
tenant — o bloco de operações do `control_workspace` — e é a porta única por
onde qualquer acesso assistido futuro tem de passar.

Dizer mais do que isso seria vender uma proteção maior do que a que existe. A
função `autorizacao_assistida_valida` é essa porta, e ela está escrita para ser
chamada, não para decorar.

## A travessia na tela

`frontend/e2e/presentation/ux12_diagnostico.cjs` — 7 etapas, 7 telas, 0 falhas.

| Etapa | Evidência |
|---|---|
| O card existe em Administração, com a frase de tarefa do mapa | `1-card-em-administracao.png` |
| O diagnóstico responde, sem jargão e sem prometer mais do que mediu | `2-diagnostico.png` |
| O pedido do suporte chega, com escopo, motivo e prazo | `3-pedido-esperando-decisao.png` |
| Autorizar, e ele passar para "valendo agora" | `4-acesso-autorizado.png` |
| **O histórico na tela**: quem pediu, e quem autorizou | `5-historico-do-acesso.png` |
| Cortar, e ele sair de "valendo" para "encerrados" | `6-acesso-cortado.png` |
| O corte entrar no histórico, sem apagar o que veio antes | `7-historico-apos-o-corte.png` |

O pedido é semeado por `backend/tests/support/seed_support_request.py`, que faz
o que o suporte faria — com usuário de plataforma e segundo fator. Inventar a
linha na mão provaria a tela contra um dado que nenhum caminho do produto
produz.

## Os controles

Dez regras desfeitas de propósito, dez reprovações:

| O que foi desfeito | O que reprovou |
|---|---|
| A recusa de aprovação pela plataforma | a plataforma voltou a aprovar sozinha, e o teste do S18 também acusou |
| A porta no bloco de operações | o estado operacional abriu sem autorização, e o escopo virou decorativo |
| A conferência de expiração na porta | uma autorização vencida continuou abrindo o acesso |
| "Nunca deu sinal" contar como saudável | o equipamento mudo passou a verde |
| O efeito da revogação | a travessia acusou: depois de cortar, o acesso continuou valendo |
| **O vínculo nominal** (`requested_by` na porta) | a autorização de uma pessoa abriu o acesso para outra |
| A identificação de quem pede | a tela voltou a mostrar um pedido anônimo |
| Os textos limitados ao que foi medido | as duas frases voltaram a prometer mais do que a medição entrega |
| **O lançamento da aprovação na razão** | a reaprovação apagou a invalidação e o histórico ficou sem ela |
| O `substituiu` no evento de auditoria | a auditoria deixou de dizer que havia uma aprovação anterior |

E o guarda de datas do repositório acusou o campo `em` do lançamento: um nome
curto demais para ser protegido — pô-lo na convenção casaria com qualquer
palavra terminada assim, e enfraqueceria a regra em vez de estendê-la. Virou
`ocorreu_em`, que é o padrão da casa e diz o que aconteceu.

**Uma prova minha não servia, e o controle mostrou.** A primeira versão do teste
de expiração só cobria "não dá para aprovar fora do prazo" — e passava mesmo com
a conferência removida da porta. Faltava o caso real: uma autorização **aprovada
dentro do prazo, que vence enquanto está valendo**. Sem ela, "expira em 4 horas"
seria só um texto na tela.

E uma reprovação foi erro de medida, pela segunda vez na mesma trilha: os
rótulos de seção são maiúsculos por CSS, e `innerText` devolve
"ESPERANDO A SUA DECISÃO". Procurar a forma escrita reprovava o produto por um
defeito que era do roteiro.

## Portões executados

| Portão | Resultado |
|---|---|
| `pytest tests/test_the_shop_sees_its_own_state.py` | 17 provas, incluindo as seis das duas revisões |
| `pytest` completo | **588 passando**, 15 pulados, 1 xfailed, 0 falhas |
| `npm test` | 198 passando |
| `npm run build` | limpo |
| `alembic check` | sem operações novas |
| `ux12_diagnostico.cjs` | 7 etapas, 7 telas, 0 falhas — e reprova sem o efeito da revogação |

Um guarda do repositório precisou ser reescrito, não afrouxado:
`keeps technical diagnostics outside the tenant management shell` proibia a
palavra "Diagnóstico" na Gestão. O que ele protege é o painel **técnico** da
plataforma — componente, latência, versão, nível de autenticação — e não o
diagnóstico do lojista que esta sprint entrega. A regra passou a nomear o que
proíbe, e continua acusando: pôr "API conectada" na tela reprova.

## O que continua aberto, e de que tipo

Classificação combinada com o dono em 09/09/2026 — as quatro linhas não são a
mesma coisa, e tratá-las como se fossem esconde o que falta de verdade:

| Item | Como tratar |
|---|---|
| **Canal real de suporte** | Pendência para concluir "pedir ajuda". Depende da definição do dono |
| **Caminho de emergência** | Fora do escopo por decisão. **Não impede fechar a primeira versão** |
| **Autorização de equipe** | Evolução possível, sem necessidade de implementar agora |
| **Lacunas de homologação** | Trabalho pendente a executar |
| **UX-11** | Depende dos exemplos de cálculo do dono |

As lacunas de homologação da UX-08 seguem abertas até serem verificadas na
tela: dois destinos nunca percorridos, catálogo volumoso não exercitado,
concorrência de duas estações, o estado "em processamento" do TEF, e conceder
autoridade a um operador e vê-lo agir sozinho.

## O que fica de fora por decisão
- Manutenção de equipamentos, histórico de disponibilidade e reprocessar fila
  pela tela — todos com o porquê no [contrato](../product/ux-12-diagnostico-e-suporte-contrato.md).
