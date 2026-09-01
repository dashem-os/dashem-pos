# Checkpoint técnico — governança Owner e Sprint 5.1

Status: **GO para evoluir a Gestão do tenant; NO GO para storage comercial e piloto**

Data do checkpoint: 31 de agosto de 2026

Próxima execução necessária: **validar a correção arquitetural e executar o gate isolado com objetos reais em dois tenants**

## Decisão de avanço para a Gestão — 01/09/2026

O Dashem Control está funcionalmente suficiente para deixar de ser o caminho
crítico da próxima correção de experiência. Isso significa que já existem
autoridades canônicas para plano, atividades, capabilities, contrato,
solicitação, decisão do Owner, quotas e capacidade física global. Não significa
que o Owner ou o produto estejam completos para produção.

O avanço autorizado é para a Gestão do tenant, em uma trilha corretiva
explicitamente numerada como 5.2–5.4 para não colidir com o roadmap macro:

- 5.2: semântica canônica de MiB, permissão contratual própria e separação entre
  visão operacional e “Plano e solicitações”;
- 5.3: arquitetura de informação do administrador do tenant;
- 5.4: usabilidade, estados de erro/vazio e avaliação técnica externa.

Permanecem gates reais, e não tarefas cosméticas do Owner: objetos reais em
dois tenants para fechar o 5.1, capacidade paga antes de vender storage e
Background Worker antes do pré-piloto ou da primeira jornada assíncrona que o
exija. A especificação executável desta continuação está em
[`tenant-management-correction-sprints.md`](tenant-management-correction-sprints.md).

## Correção de direção — 01/09/2026

A revisão de homologação identificou contradições que impedem aprovar o Sprint
5.1 como produto:

- a tela individual misturava quota contratual do tenant e capacidade física
  global do Supabase;
- o plano atual podia aparecer ao lado de um contrato histórico sem distinguir
  a revisão efetivamente contratada;
- páginas de leitura exibiam mensagens produzidas por uma simulação de comando
  com quantidade zero;
- estados como “reconciliado” eram apresentados em frases conclusivas, em vez
  de expor código, origem e horário fornecidos pela medição;
- a relação entre valor incluído no plano e decisão diferente do Owner não
  ficava persistida no snapshot contratual.

A direção corretiva está formalizada no ADR-026. O Sprint permanece aberto até
que backend, frontend, testes, CI e ambiente publicado comprovem:

1. read models exclusivamente factuais;
2. preflight de command somente para operações concretas;
3. snapshot contratual v4 com procedência `PLAN_INCLUDED` ou `OWNER_OVERRIDE` e
   unidade binária explicitamente nomeada em MiB;
4. revisão contratada separada do catálogo atual;
5. capacidade global em Saúde da plataforma, sem duplicação no tenant;
6. ausência de bloqueio rígido para ativação de planos;
7. inventário real com objetos, isolamento e concorrência validados.

O checkpoint de 31/08 abaixo é evidência de conexão e inventário vazio. Ele não
é homologação comercial nem prova completa do enforcement.

Validação local da correção em 01/09/2026: backend completo 186/186 em API e
PostgreSQL isolados; após a última separação do read model de capacidade física,
21/21 testes diretamente afetados; frontend 66/66 e build de produção. A CI e o
ambiente publicado continuam sendo gates separados e ainda não são declarados
aprovados por este registro.

## Evidência técnica publicada — 31/08/2026

O primeiro checkpoint contra os ambientes publicados foi concluído sem
representar ausência de objetos como uma estimativa:

- a migration restritiva foi aplicada ao schema `storage` do projeto Supabase;
- a chave secreta moderna ficou somente no backend do Render;
- os quatro buckets privados canônicos foram criados ou confirmados;
- o tenant interno de teste recebeu quatro fontes físicas, uma por bucket;
- o inventário administrativo real retornou zero objetos e zero bytes;
- a medição persistida ficou `RECONCILED`, com quatro fontes cobertas e
  watermark explícito para cada namespace vazio;
- o Control separou a quota contratual de 128 MiB da capacidade física
  compartilhada de 1 GB, da margem de 100 MB e dos 900 MB globais disponíveis;
- egress permaneceu visível como `NOT_INSTRUMENTED`;
- uma falha de ordenação temporal encontrada na primeira reconciliação foi
  corrigida de forma idempotente, sem apagar a medição anterior;
- as unidades da franquia do provedor passaram a ser exibidas em base decimal,
  sem alterar a contabilidade contratual interna em bytes.

Evidência de integração: commits `271afad`, `ea270e3`, `f7e4163` e `8f4959a`;
CI público 77–80 concluído com sucesso; backend e frontend publicados; medição
reconciliada às 23:42:29 de 31/08/2026.

Este checkpoint comprova a conexão e o inventário vazio. Ele **não** aprova a
arquitetura de apresentação nem upload, exclusão, concorrência,
thresholds nem isolamento cruzado com objetos reais. Portanto, o Sprint 5.1
continua aberto e storage ainda não está liberado como promessa comercial.

## 0. Atualização da retomada — 31/08/2026

A camada de aplicação do Sprint 5.1 foi implementada sem presumir que o plano
Free está ativo e sem registrar consumo digitado manualmente:

- adapter backend para buckets privados, upload, exclusão e URL assinada;
- prefixo de objeto derivado no servidor a partir do `tenant_id` autenticado;
- validação de bucket, caminho, extensão, MIME, assinatura do conteúdo e tamanho;
- reserva idempotente antes do upload, com quota do tenant e capacidade física
  global avaliadas sob lock;
- timeout e erro 5xx mantêm a reserva conservadora; somente rejeição 4xx
  confirmada libera bytes imediatamente;
- inventário paginado pela API administrativa do Supabase Storage, por tenant
  e para todos os buckets do projeto, com watermark, fingerprint e evidência;
- detecção de objetos órfãos por hashes de caminho, sem exclusão automática;
- migration Alembic `065_supabase_storage` para fatos, reservas e capacidade no
  banco da aplicação;
- migration separada em
  `supabase/migrations/20260831190000_lock_managed_storage_to_backend.sql` para
  bloquear `SELECT`, `INSERT`, `UPDATE` e `DELETE` diretos nos buckets
  gerenciados. O backend com service role permanece a única autoridade;
- painel do Owner separando quota contratual, uso medido, reservas e capacidade
  global. Egress aparece explicitamente como `NOT_INSTRUMENTED`.

Validação local concluída: migration com upgrade/downgrade/upgrade e
`alembic check`; backend 174/174; frontend 66/66 e build de produção. Os testes
do adapter usam um provedor HTTP controlado e não são apresentados como prova
do ambiente real.

O workspace não contém segredos. `SUPABASE_URL`, `SUPABASE_SECRET_KEY` e a
capacidade física foram configurados somente no gerenciador de ambiente do
Render. Os 12 itens do gate com objetos reais abaixo **ainda não foram
declarados aprovados** em conjunto, e o Sprint 5.1 ainda não autoriza storage
comercial.

Para executar o gate, o ambiente técnico deve receber, pelo gerenciador de
segredos e nunca pelo Git:

```text
SUPABASE_URL=<URL real do projeto de teste>
SUPABASE_SECRET_KEY=<service role do backend>
SUPABASE_STORAGE_CAPACITY_BYTES=<capacidade confirmada no plano vigente>
SUPABASE_STORAGE_RESERVED_MARGIN_BYTES=<margem operacional aprovada>
```

Os quatro buckets gerenciados são canônicos e precisam coincidir com a
migration restritiva. O backend falha na inicialização se essa lista divergir,
evitando que um bucket novo seja criado sem política versionada.

## 1. Decisão de pausa

Os Sprints 0 a 5 da trilha corretiva de governança do Owner foram concluídos.
Nenhum Sprint 6, 7 ou 8 foi criado para essa trilha. A numeração S0–S21 do
Roadmap Canônico do Commerce OS é independente e não deve ser misturada com
este ciclo corretivo.

A retomada deve começar pelo Sprint 5.1. Não iniciar configuração de clientes
reais, oferta comercial de storage nem homologação de integrações externas
antes de seu gate de aceite.

## 2. Estado entregue

| Etapa | Resultado persistido | Estado |
|---|---|---|
| Sprint 0 | vocabulário, autoridades, invariantes e plano de migração | concluído |
| Sprint 1 | catálogo persistido de uma ou várias atividades comerciais | concluído |
| Sprint 2 | versão contratual como fonte canônica de activities, capabilities e quotas | concluído |
| Sprint 3 | contagem operacional de usuários, dispositivos e unidades, policy única, avisos e bloqueios | concluído |
| Sprint 4 | solicitação do tenant e decisão auditada do Owner; aprovação cria nova versão contratual | concluído |
| Sprint 5 | modelos, reconciliação, reservas e policy fail-closed de storage independentes de provedor | concluído |

O Sprint 5 não declara que existe consumo medido. Sem fonte física conectada,
o estado correto continua sendo `NOT_MEASURED`, com decisão `UNKNOWN`. Ausência
de inventário nunca equivale a zero bytes utilizados.

## 3. Decisão de infraestrutura

O provedor físico da primeira implementação é o **Supabase Storage**. O
Supabase já utilizado pelo projeto prova identidade. O adapter de objeto e
inventário está conectado no ambiente publicado, com credenciais exclusivas do
backend e capacidade declarada explicitamente no Render.

No plano gratuito, em 31/08/2026, a referência operacional publicada pelo
Supabase é:

- 1 GB de Storage incluído na infraestrutura compartilhada;
- arquivo individual de até 50 MB;
- 5 GB de egress não armazenado em cache e 5 GB de cached egress;
- Image Transformations indisponível.

Esses limites pertencem à infraestrutura Supabase e não concedem 1 GB a cada
tenant do DASHEM. A quota de cada cliente continua sendo uma decisão contratual
do DASHEM, limitada também pela capacidade física global disponível.

Referências sujeitas a revisão antes da retomada:

- <https://supabase.com/pricing>
- <https://supabase.com/docs/guides/storage/security/access-control>
- <https://supabase.com/docs/guides/storage/schema/design>
- <https://supabase.com/docs/guides/storage/serving/bandwidth>

## 4. Escopo obrigatório do Sprint 5.1

### 4.1 Namespace e isolamento

- criar buckets privados por finalidade, não um bucket por tenant sem evidência;
- usar `tenant_id` como primeiro segmento obrigatório do caminho do objeto;
- aplicar RLS em `storage.objects` para `SELECT`, `INSERT`, `UPDATE` e `DELETE`;
- provar que um tenant não lista, lê, sobrescreve, move ou exclui objeto de outro;
- manter credencial de serviço exclusivamente no backend.

Estrutura inicial esperada:

```text
tenant-assets/<tenant_id>/...
tenant-documents/<tenant_id>/...
tenant-exports/<tenant_id>/...
tenant-integrations/<tenant_id>/...
```

### 4.2 Autoridade de upload

- nenhum upload operacional pode contornar o backend e a policy de quota;
- validar MIME type, extensão, tamanho individual e contexto do tenant;
- reservar bytes com `reserve_storage_capacity` antes de autorizar o envio;
- concluir ou liberar a reserva após a resposta do Supabase;
- usar idempotência, auditoria e evidência do objeto criado;
- não aceitar tamanho declarado pelo navegador como medição final.

### 4.3 Medição e reconciliação

- cadastrar o Supabase Storage como `storage_meter_source`;
- agregar o metadata de tamanho retornado pela API administrativa do Storage
  por bucket e prefixo do tenant;
- persistir quantidade de objetos, bytes, fontes, watermark e evidência;
- reconciliar exatamente todas as fontes ativas;
- detectar medição parcial, divergência, fonte alterada e inventário expirado;
- identificar objetos órfãos sem apagar ou reatribuir silenciosamente;
- manter `storage` como schema somente leitura para inventário; mutações passam
  pela API oficial do Storage.

### 4.4 Quota individual e capacidade global

- aplicar a quota da última versão contratual, nunca apenas o teto do plano;
- considerar uso reconciliado mais reservas concorrentes;
- emitir avisos padronizados em 70% e 85%;
- bloquear novas gravações que projetem uso acima de 100%;
- manter margem operacional global no plano Free;
- impedir que a soma das quotas comercialmente concedidas seja apresentada
  como capacidade física garantida sem política explícita de overbooking;
- apresentar separadamente quota do tenant e saúde global da infraestrutura.

### 4.5 Interfaces

O Owner e o administrador do tenant devem ver somente fatos:

- quota contratada;
- uso medido;
- bytes reservados;
- capacidade disponível;
- quantidade de objetos;
- data e watermark do inventário;
- fontes cobertas;
- estado `RECONCILED`, `PARTIAL`, `DIVERGENT`, `UNAVAILABLE` ou `NOT_MEASURED`;
- motivo explícito de aviso ou bloqueio.

Não exibir zero provisório, medição digitada manualmente ou badge que confunda
quota contratual com consumo observado.

## 5. Gate de aceite do Sprint 5.1

O Sprint somente termina quando todos os itens abaixo forem comprovados com
objetos reais de teste no Supabase:

1. dois tenants persistidos recebem namespaces isolados;
2. testes negativos impedem toda forma de acesso cruzado;
3. upload aceito altera o inventário reconciliado do tenant correto;
4. upload concorrente não ultrapassa a quota por corrida;
5. alertas aparecem nos thresholds definidos;
6. upload acima da quota é recusado antes de ocupar storage;
7. exclusão e substituição reconciliam bytes sem inventar resultado;
8. falha, timeout e retry não duplicam reserva ou objeto;
9. fonte ausente, parcial ou expirada desativa o enforcement e bloqueia de
   forma segura operações sujeitas à quota;
10. o limite físico global e a margem operacional aparecem no Control;
11. migrations, rollback, RLS, backend, frontend e E2E ficam verdes no CI;
12. a validação é repetida no deploy publicado.

### Gate operacional do ambiente publicado

Concluir o gate funcional de storage não torna um ambiente automaticamente
apto para clientes reais. No momento da decisão de GO, o deploy publicado deve
provar simultaneamente:

- saúde global `HEALTHY`, sem componente `DEGRADED`, `UNKNOWN` ou
  `NOT_CONFIGURED`;
- worker com heartbeat recente e fila transacional drenando dentro do SLO;
- probe de autenticação com resposta de sucesso;
- nenhum excesso contratual sem decisão explícita do Owner;
- todo tenant no escopo do piloto com contrato, fontes e medição identificados;
- commit publicado identificável e smoke test executado nesse mesmo deploy.

Esses sinais são fatos de runtime. CI verde, texto da interface ou inventário
vazio não substituem nenhuma dessas evidências.

Diagnóstico de 01/09/2026: o processo anterior `app.workers.outbox_worker`
apenas registrava o envelope em log e alterava seu status. Iniciá-lo para zerar
o backlog produziria um verde falso e não seria aceitação.

Correção arquitetural preparada em 01/09/2026, formalizada no ADR-027:

- `outbox_events` permanece como fila transacional;
- o worker adquire lease recuperável com `FOR UPDATE SKIP LOCKED`;
- a publicação cria um recibo canônico e imutável em `published_events`;
- recibo e estado `PUBLISHED` são confirmados na mesma transação;
- falhas transitórias usam backoff limitado e envelopes inválidos são
  colocados em `FAILED` sem inventar publicação;
- `PUBLISHED` significa entrega ao fluxo interno do DASHEM, nunca confirmação
  de adquirente, TEF, marketplace ou delivery.

O gate local específico comprovou cinco cenários: publicação e recibo,
imutabilidade, idempotência, recuperação de lease e falha com retry/quarentena;
migration 066 com downgrade/upgrade e schema sem drift.

Gate remoto concluído para o commit `7d0a789` em 01/09/2026: CI pública
`33536178413` com frontend, backend PostgreSQL/RLS, schema Alembic e E2E
operacional aprovados; deploy automático do backend confirmado pelo read model
publicado contendo `published_receipts: 0`, Auth HTTP 200 e horários rotulados
`UTC−03:00`. O zero é factual: a tabela de recibos acabou de ser criada e o
worker ainda não foi provisionado.

O heartbeat do processo publicado e a drenagem da fila continuam pendentes. O
Render não oferece instância gratuita para Background Worker; a decisão de
compute pago foi conscientemente postergada para o gate de pré-piloto e exige
ação explícita do Owner. Isso não bloqueia a correção do Control, a construção
da camada do tenant nem o gate funcional de storage. O registro de investimento,
configuração, validação e rollback está no
[`runbook do Background Worker`](../operations/background-worker-investment-gate.md).

A sequência aprovada para a fase atual é: tornar o Owner consistente, construir
a camada mínima do tenant, concluir testes internos, receber avaliação técnica
de automação/operação e tratar os achados. O worker hospedado entra depois,
quando uma jornada assíncrona real ou o pré-piloto tornar compute contínuo uma
necessidade demonstrável.

A sonda de Supabase Auth deve enviar a chave server-side somente no header
`apikey`. Uma resposta `401` sem esse header é falha da sonda, não evidência de
indisponibilidade do Auth.

## 6. Condição para clientes reais

O plano Supabase Free serve para desenvolvimento e validação do Sprint 5.1.
Antes do primeiro cliente real, reavaliar preços e limites vigentes do Supabase,
capacidade, egress, backups, continuidade, pausas por inatividade e política de
custos. A decisão esperada é utilizar um projeto de produção em plano pago,
separado do ambiente de testes.

Storage não pode ser anunciado como limite efetivo de um plano comercial até o
gate do Sprint 5.1 estar verde e a capacidade física de produção estar aprovada.

## 7. Integrações posteriores

Omnichannel, TEF/SmartPOS e delivery não fazem parte do Sprint 5.1. Permanecem
na trilha macro de integrações: Checkout/Orchestrator (S8), TEF e SmartPOS (S9),
Channel Hub (S10) e catálogo/reconciliação de canais (S13). Essas integrações só
podem ser anunciadas depois dos respectivos adapters e gates externos reais.
