# Trilha corretiva — Gestão do tenant

Status: **5.3 publicado, homologação em curso; 5.4 condicionado ao Gate 5.4.0**

Data de referência: 1º de setembro de 2026

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

## Continuação após 5.4

A trilha 5.2–5.4 não substitui os Sprints S0–S21 do roadmap canônico. Após sua
validação, o produto retorna aos gates macro já registrados. Omnichannel,
Integração TEF/SmartPOS e delivery/e-commerce continuam condicionados aos
adapters e homologações reais; não serão apresentados como disponíveis por
texto, fixture ou capability sem execução comprovada.
