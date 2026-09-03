# Trilha corretiva — Gestão do tenant

Status: **5.4.0–5.4.3 publicados com CI verde; 5.4.4 aberto; OA-4 parcialmente executado no deploy e Gate B ainda `REOPENED`**

Data de referência: 1º de setembro de 2026 · última atualização de estado: 3 de setembro de 2026

## Decisão de arquitetura

A Gestão não é uma extensão visual do Dashem Control. O Control governa oferta,
contrato, capacidade global e decisões comerciais; a Gestão administra a
operação de uma organização. Dados podem ter a mesma origem, mas não devem ser
misturados na mesma jornada.

O feedback de usabilidade confirmou três problemas concretos:

1. a visão geral operacional continha um formulário de expansão contratual;
2. códigos internos como `RECONCILED`, `WITHIN_LIMIT` e `READY` apareciam como
   linguagem de negócio;
3. a navegação longa não distinguia operação cotidiana de administração da
   empresa.

Esta trilha corrige essas fronteiras sem criar um segundo contrato, inventar
medição ou duplicar regras no frontend.

## Prontidão do Owner

O Owner está **suficiente para avançar à Gestão**, porque já possui fonte
canônica para:

- plano e revisão da oferta;
- uma ou várias atividades comerciais contratadas;
- composição e decisão de capabilities;
- versão contratual auditada;
- quota contratada e uso operacional observado;
- solicitação do tenant e decisão auditada do Owner;
- capacidade física global separada dos compromissos comerciais.

O Owner **não está completo para produção**. Permanecem fora desta decisão:

- gate do Sprint 5.1 com objetos reais e isolamento entre dois tenants;
- contratação de capacidade adequada antes da venda de storage;
- Background Worker e drenagem da outbox antes do pré-piloto ou de uma jornada
  assíncrona real;
- homologações externas de pagamento, SmartPOS, delivery e e-commerce.

## Sprint 5.2 — Semântica e fronteiras

Objetivo: remover ambiguidade de unidade e separar governança comercial da
visão operacional.

Entregas:

- migration do catálogo `storage_limit_mb` para `storage_limit_mib` sem
  conversão numérica;
- contrato v4 escrevendo `storage_mib`/`limit_mib`;
- adaptador único e somente de leitura para snapshots históricos v1–v3;
- permissão `contract.request`, sem reutilizar `team.manage`;
- destino próprio “Plano e solicitações” na navegação da Gestão;
- remoção da solicitação comercial da visão geral de BI;
- tradução dos estados técnicos na camada de apresentação;
- códigos, identificadores e watermark preservados apenas em detalhes técnicos;
- módulo selecionado preservado na URL e sempre condicionado às contribuições
  autorizadas pelo backend.

Aceite:

- nenhuma API ou gravação nova usa os nomes semânticos antigos;
- a visão geral contém somente informação operacional;
- um administrador autorizado solicita mudança, mas não ganha acesso por isso;
- perfis sem `contract.request` apenas consultam o histórico;
- migrations, frontend, backend e CI ficam verdes.

## Sprint 5.3 — Arquitetura de informação do administrador

Objetivo: reduzir densidade e organizar a Gestão pelo trabalho que o cliente
precisa executar.

Escopo:

- permitir que administrador/gestor valide o PDV com a própria identidade
  gerencial, sem assumir código, PIN, função ou produtividade de colaborador;
- manter essa validação sobre dados reais e operações auditadas, sem criar modo
  demonstração, usuário fictício ou autorização decidida por query string;
- revisar os grupos de navegação em Operação, Financeiro, Mercadorias,
  Relacionamento e Administração;
- criar visão de configuração inicial com pendências factuais por empresa,
  unidade, equipe e terminal;
- separar “Equipe e acessos”, “Unidades e operação” e “Terminais” sem duplicar
  autoridade de dados;
- exibir alertas somente quando houver ação possível para o perfil atual;
- definir prioridade e comportamento responsivo da navegação em desktop,
  tablet e celular;
- preservar filtros e contexto de unidade ao alternar módulos.

Aceite:

- **Validar no PDV** não encerra a Gestão nem redireciona o administrador para
  a entrada de turno;
- o backend continua exigindo `management.read`, tenant, unidade, terminal e
  permissões efetivas; a sessão gerencial não é contabilizada como turno;
- tarefas administrativas principais são alcançadas sem percorrer a visão de
  BI;
- nenhuma tela depende de ordem arbitrária ou do primeiro tenant/unidade;
- cada vazio, falha e falta de permissão possui estado explícito;
- não há cards decorativos, métricas fictícias ou módulos-placeholder.

### Evidência adiada, sem mutação no Sprint 5.3

As imagens de homologação mostram catálogo de material elétrico junto de uma
jornada de mesas/comandas. Isso pode ser dado de teste contaminado, composição
de atividades incorreta ou ausência de filtro por atividade. O Sprint 5.3 não
apagará, recategorizará nem esconderá esses registros sem determinar a origem.
A correção exige uma reconciliação posterior, auditada, entre atividades
contratadas, capabilities efetivas, catálogo, unidade e superfícies
operacionais. Até lá, o problema permanece registrado e não será tratado com
texto, fixture ou filtro cosmético.

## Sprint 5.4 — Usabilidade e validação técnica

Objetivo: transformar a nova arquitetura em evidência de uso, não em aprovação
por aparência.

### Gate 5.4.0 — Verdade de sortimento por contexto

Este é o primeiro gate do Sprint 5.4 e deve ficar verde antes de qualquer
polimento visual ou homologação de usabilidade.

Decisão:

- atividade comercial contratada define composição e elegibilidade de
  capabilities, mas não deve ser usada como categoria implícita de produto;
- capability habilita uma jornada, como mesas ou delivery, mas não publica
  automaticamente todo o catálogo nessa jornada;
- a visibilidade comercial deve ser resolvida por uma relação canônica entre
  produto, sortimento/cardápio, unidade, canal e modo de atendimento;
- balcão, retirada, mesa, delivery e e-commerce não podem receber o catálogo
  global por fallback silencioso;
- toda resolução ocorre no servidor, sob tenant, unidade, permissions,
  capabilities e RLS; filtros de frontend não constituem isolamento;
- dados existentes não podem ser classificados por nome, categoria ou nicho
  presumido. A migração deve preservar sua origem em estado explícito e exigir
  decisão administrativa para qualquer nova publicação contextual;
- um tenant novo começa sem produtos, categorias, mesas ou comandas copiadas de
  outro tenant e sem conteúdo demonstrativo apresentado como dado real.

Aceite do gate:

- um produto publicado para balcão não aparece em mesa, delivery ou e-commerce
  sem vínculo persistido para esse contexto;
- contratar `table_service` não publica produtos no atendimento de mesa;
- um tenant com mais de uma atividade consegue manter sortimentos distintos
  sem duplicar o cadastro mestre do produto;
- a Gestão permite consultar e alterar os vínculos com permissão efetiva,
  autoria, auditoria e concorrência controlada;
- POS e consumidores futuros recebem somente a projeção vendável do contexto
  solicitado, sem fallback para o catálogo completo;
- migrations, testes de isolamento entre tenants e modos, frontend e CI ficam
  verdes.

Prompt de execução e critérios técnicos:
[`sprint-5-4-gate-0-agent-prompt.md`](sprint-5-4-gate-0-agent-prompt.md).

**Estado em 03/09/2026 — verde, com dívida registrada.**

Entregue: a migração 069 materializou `LEGACY-DEFAULT` preservando a publicação
pré-existente sem classificar por nome, categoria ou nicho presumido, como o
gate exigia.

Observado na validação de 02–03/09/2026: esse mesmo conjunto legado é o caminho
pelo qual material elétrico chegava ao PDV de um tenant contratado apenas como
`FOOD_SERVICE`. Não é contradição do gate — ele mandou preservar a origem em
estado explícito — mas expôs que faltava a decisão administrativa prevista aqui
para reclassificar ou aposentar esse conjunto.

Entregue em 03/09/2026, commits `1399c38` e `dc3dc5a`: `assortments.business_activity`
(migration 070), a atividade como dimensão da cadeia de resolução, e a ação de
Gestão que publica o conjunto da atividade contratada e desativa os conjuntos
ativos que publicam na mesma unidade sem declarar atividade. Nada é apagado: o
conjunto aposentado mantém produtos e pode ser reativado.

Dívida aberta: essa ação cria conteúdo demonstrativo. Hoje ela é restrita a
tenant `INTERNAL` ou em fase `TEST` e o conjunto é rotulado como homologação,
mas a regra deste gate diz que nenhum tenant recebe conteúdo demonstrativo
apresentado como dado real. A reconciliação definitiva pertence ao Gate 5.4.4,
que substitui o catálogo embutido no código por biblioteca de conteúdo.

### Gate 5.4.1 — Elegibilidade da jornada por área de atuação

Este gate corrige uma contradição de autorização descoberta na validação do
tenant. A capability `table_service` não é suficiente para publicar mesas:
ela só é elegível quando o snapshot contratual da unidade contém
`FOOD_SERVICE`. A regra vale para API, navegação de Gestão, botão do PDV e
rota operacional; permissão ou registro legado não pode reabrir a jornada.

- `FOOD_SERVICE` + `table_service` + permissão efetiva: mesas e reservas são
  publicadas;
- atividades sobrepostas (por exemplo `FOOD_SERVICE` + `RETAIL`) continuam
  permitidas, respeitando os vínculos de sortimento de cada contexto;
- somente `RETAIL`, somente `BEAUTY_RESELLER` ou snapshot sem atividades não
  exibem nem aceitam mesas;
- tenants pré-contrato permanecem no caminho de compatibilidade explicitamente
  identificado, sem que o sistema invente uma área de atuação;
- combinação contratual incoerente não é escondida por CSS: a capability é
  removida da resolução efetiva e a API responde indisponibilidade da jornada.

O gate é pré-requisito para a avaliação visual do restante do Sprint 5.4. A
mistura de produtos elétricos em uma tela de mesas é um problema separado de
sortimento persistido e não será corrigida por filtro visual ou texto fixo.

**Estado em 03/09/2026 — verde para mesas; estendido para catálogo.**

Já estava entregue: elegibilidade de mesas condicionada a `FOOD_SERVICE` no
snapshot contratual, valendo para API, navegação, botão do PDV e rota.

Entregue em 03/09/2026: a previsão acima de que a mistura seria resolvida por
sortimento persistido foi implementada. A atividade passou a ser propriedade do
conjunto curado, e não do produto, porque o mesmo produto pode ser vendido por
operações de nichos diferentes. A projeção vendável aceita a atividade em
operação, recusa com `403` uma atividade não contratada e resolve apenas os
conjuntos daquela atividade mais os deliberadamente abertos a todas. As abas de
categoria do PDV passaram a derivar da projeção, para não anunciar "Perfumaria"
dentro de um balcão de alimentação.

Seletor de negócio: o PDV exibe a escolha da atividade somente quando o tenant
contratou mais de uma; a Gestão configura os conjuntos e o operador consome.
A troca segue a mesma regra que já bloqueia a troca de modo com venda aberta.

A refatorar: a atividade ativa vive em estado de cliente. Ela ainda não é
persistida na sessão operacional nem registrada na auditoria, então a escolha
não sobrevive a uma nova sessão nem é atribuível. Deve ser resolvida junto com
o contrato de sessão operacional do Gate B.

### Gate 5.4.2 — Verdade temporal e navegação de validação

Este gate corrige duas falhas observadas na validação publicada: horários eram
renderizados no fuso do navegador e a validação gerencial oferecia duas ações
para retornar à Gestão. Também elimina a falsa impressão de que uma projeção
foi atualizada a partir de dados de origem quando o tenant não possui fatos
persistidos.

- os indicadores e evidências temporais cobertos por este gate usam a regra
  canônica `UTC−03:00`, independentemente do fuso do dispositivo;
- `source_watermark` é o maior timestamp dos fatos persistidos que participaram
  da projeção; quando não há fatos, permanece ausente;
- o painel distingue o instante de geração da projeção da última origem
  observada e não chama ausência de dados de "atualização";
- a validação gerencial mantém uma única ação de retorno para a Gestão;
- o selo de conectividade descreve somente alcançabilidade da API/rede, não
  homologação ou conexão de provedor externo.

Este gate não é o redesign visual completo. Densidade, responsividade e
hierarquia do PDV permanecem como trabalho de UI/UX posterior, sem misturar
sortimento de atividades distintas nem introduzir dados demonstrativos.

### Gate 5.4.3 — Leitura e responsividade do PDV

O primeiro incremento visual deve melhorar a leitura do fluxo de venda sem
alterar a autoridade dos dados. O escopo é deliberadamente pequeno e
verificável:

- cartões de produto têm área de toque e tipografia suficientes para leitura em
  telas menores, sem truncar silenciosamente o nome da mercadoria;
- a busca principal permanece visível e utilizável por toque, teclado e leitor
  de código de barras;
- a grade se adapta a larguras intermediárias antes de formar duas colunas;
- o carrinho continua separado do catálogo e acessível no mobile;
- nenhum texto novo afirma integração, estoque ou venda que não esteja presente
  na projeção persistida.

Este gate não reorganiza categorias, não classifica produtos pelo nicho e não
introduz mesas para atividades que não as contrataram. A validação deve cobrir
larguras de 360px, 768px e 1280px, além de contraste e foco de teclado.

Escopo:

- roteiro assistido para administrador do tenant e operador;
- validação desktop/tablet/mobile e contraste/densidade;
- testes da matriz de perfis e permissões;
- cenários de loading, vazio, erro, indisponibilidade, retry e conflito;
- avaliação do Wesley sobre automação, operação e pontos de integração;
- registro dos achados por severidade, responsável e evidência de correção;
- repetição dos fluxos no deploy publicado.

Aceite:

- os fluxos críticos são executáveis sem orientação do desenvolvedor;
- problemas P0/P1 identificados na avaliação estão corrigidos e retestados;
- achados externos não são fechados sem evidência;
- a decisão seguinte distingue claramente desenvolvimento interno, pré-piloto
  e homologação externa.

**Estado em 03/09/2026 — incremento técnico entregue; aceite assistido pendente.**

Entregue: tabela vira lista de cartões abaixo de `md` por primitivo
compartilhado, em catálogo, estoque, clientes e equipe; piso tipográfico de
12 px para texto de conteúdo, com 10 e 11 px restritos a rótulos em caixa alta;
alvo de toque de 44 px; grades de conteúdo com escada de colunas; cabeçalho do
PDV que não empurra a página na horizontal. Verificado em 360, 390, 768, 1024,
1280 e 1440 px, incluindo contra o deploy publicado.

Contraste e foco deixaram de depender de inspeção manual: `frontend/tests/theme_contrast.test.ts`
reprova fundo escuro com texto escuro, fundo claro com texto claro, branco sobre
preenchimento de marca e gradiente que atravessa claro e escuro.

A refatorar: `DashboardBI` mantém tabela com largura mínima de 760 px; os
módulos do Owner não entram neste escopo por decisão do dono do SaaS, que
mantém identidade visual própria no Dashem Control.

Pendente do aceite original: roteiro assistido com administrador e operador,
avaliação externa, registro de achados por severidade e repetição dos fluxos no
deploy com pessoas reais. O incremento técnico não substitui esse aceite.

### Gate 5.4.4 — Vocabulário, conteúdo e mídia por atividade

Este gate nasce de uma constatação registrada em 03/09/2026: correções feitas
fora da trilha resolveram o caso relatado sem resolver a classe do problema. O
rótulo do módulo de sortimento foi ajustado por condicional binário entre
alimentação e o resto, o catálogo inicial por atividade vive em constante no
código, e a foto do produto entrou como endereço avulso. Cada um atende o nicho
de hoje e cobra outro toque no código no próximo nicho.

Decisão:

- vocabulário do console é dado da atividade de negócio, não condicional no
  servidor nem texto fixo no componente; acrescentar um nicho não pode exigir
  alteração de código de apresentação;
- conteúdo inicial por atividade é dado versionado e auditável, não constante
  compilada, e continua restrito a tenant interno ou em fase de teste, jamais
  apresentado a um cliente como dado real;
- mídia de produto tem duas origens legítimas: uma biblioteca do sistema
  disponível a todos os tenants e o acervo próprio do tenant;
- isolamento de condomínio é inegociável: um inquilino nunca lista, busca ou
  referencia mídia de outro inquilino, apenas a própria e a do sistema;
- arquivo binário não é embutido no registro do produto; a imagem é objeto
  persistido com referência, e não conteúdo em base64 dentro da linha.

Entregas:

- catálogo de vocabulário por atividade, com chave, termo e origem, consumido
  pela resolução de acesso efetivo e pelas telas, substituindo o condicional
  atual e o texto fixo do cabeçalho;
- conteúdo inicial por atividade migrado da constante em código para dado
  versionado, mantendo a restrição a tenant interno ou de teste;
- biblioteca de mídia do sistema, legível por qualquer tenant e não gravável
  por eles;
- upload de mídia própria do tenant no bucket `tenant-assets`, com quota,
  tipo permitido e caminho isolado por tenant;
- referência de mídia no produto apontando para objeto persistido, com
  fallback explícito quando não houver imagem;
- atividade ativa do PDV persistida na sessão operacional e registrada na
  auditoria, encerrando a dívida do Gate 5.4.1.

Aceite do gate:

- acrescentar uma quarta atividade de negócio não exige alterar código de
  apresentação nem de resolução de acesso para que o console fale a língua
  correta;
- um tenant de beleza não lê "cardápio" em nenhuma superfície;
- listar ou buscar mídia em um tenant nunca retorna objeto de outro tenant,
  provado por teste negativo entre inquilinos;
- produto sem foto exibe fallback determinístico, sem espaço quebrado na grade;
- nenhum registro de produto carrega binário embutido;
- a escolha de atividade no PDV sobrevive a uma nova sessão e é atribuível a
  um operador.

Dependência externa declarada: o upload gerenciado recusa toda gravação
enquanto o contrato do tenant não declara limite de storage, respondendo
"Limite contratual de storage não informado". Definir esse entitlement é
decisão comercial no Dashem Control e antecede a entrega de upload.

Estado: **aberto, não iniciado**. O que existe hoje das três frentes está
registrado como dívida nos Gates 5.4.0, 5.4.1 e nas linhas correspondentes do
roadmap canônico.

## Continuação após 5.4

A trilha 5.2–5.4 não substitui os Sprints S0–S21 do roadmap canônico. Após sua
validação, o produto retorna aos gates macro já registrados. Omnichannel,
Integração TEF/SmartPOS e delivery/e-commerce continuam condicionados aos
adapters e homologações reais; não serão apresentados como disponíveis por
texto, fixture ou capability sem execução comprovada.

Com o CI verde do commit `a6cab8e`, o ciclo autorizado continua sendo o OA-4 do
plano de hardening operacional: repetir a jornada em navegador e no deploy
publicado, anexar evidências sanitizadas e então submeter a decisão do Gate B.
Isso não autoriza ainda piloto comercial nem uma nova funcionalidade de
integração.

Estado do OA-4 em 03/09/2026: a primeira execução assistida contra o deploy
cobriu os cinco cenários alcançáveis sem credencial e todos passaram
([evidência](../quality/oa4-deploy-acceptance-2026-09-03.md)). Os catorze
cenários credenciados continuam pendentes, porque exigem terminal autorizado,
código ativado e PIN pessoal em produção. O Gate B segue `REOPENED`.

O Gate 5.4.4 fica registrado como destino do trabalho de vocabulário, conteúdo
e mídia executado em paralelo à trilha. Ele não corre antes da decisão do Gate
B, e não deve ser executado como sequência de correções pontuais: a regra é
resolver a classe do problema, não o caso relatado.
