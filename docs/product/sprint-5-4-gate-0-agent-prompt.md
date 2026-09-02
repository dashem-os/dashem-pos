# Prompt de implementação — Sprint 5.4 / Gate 5.4.0

Trabalhe no repositório DASHEM POS existente e implemente o **Gate 5.4.0 —
Verdade de sortimento por contexto**. Antes de editar, leia integralmente:

- `docs/product/tenant-management-correction-sprints.md`;
- `docs/architecture/adr-025-owner-commercial-governance.md`;
- `docs/architecture/adr-028-manager-pos-validation.md`;
- os modelos, serviços, endpoints, migrations e testes atuais de catálogo,
  produtos vendáveis, pedidos, mesas, capabilities, permissions e Channel Hub.

## Problema a resolver

O mesmo tenant pode contratar mais de uma atividade comercial. Atividade e
capability não podem, porém, publicar automaticamente o catálogo inteiro em
todas as jornadas. Hoje um tenant que possui catálogo de material elétrico e a
capability de mesas pode apresentar os mesmos produtos no contexto de
restaurante. Isso não deve ser escondido com CSS, filtro por nome, categoria,
nicho ou fixture.

Implemente uma fonte canônica que permita resolver:

`Produto mestre → Sortimento/Cardápio → Unidade → Canal → Modo de atendimento`

Os nomes das entidades podem acompanhar a linguagem já existente no projeto,
mas os invariantes abaixo são obrigatórios.

## Invariantes obrigatórios

1. Atividade contratada compõe capabilities; não classifica produto.
2. Capability libera a jornada; não publica produtos nela.
3. O produto mestre não precisa ser duplicado para pertencer a vários
   sortimentos.
4. Balcão, retirada, mesa, delivery e e-commerce possuem escopos explícitos.
5. Não existe fallback silencioso do contexto para o catálogo global.
6. A resolução de produtos vendáveis é feita no backend. O frontend apenas
   apresenta a projeção autorizada.
7. Tenant, unidade, permissions, capabilities e RLS continuam obrigatórios.
8. Toda mutação de sortimento tem ator derivado da identidade autenticada,
   auditoria, outbox quando aplicável, idempotência nas operações repetíveis e
   concorrência otimista nas edições.
9. Não inferir contexto por nome do produto, categoria, SKU, atividade ou
   nicho. Não apagar nem recategorizar dados existentes.
10. Não criar mocks, dados demonstrativos, estados falsos, textos que afirmem
    sincronização inexistente ou atalhos somente no navegador.

## Trabalho esperado

### 1. Auditoria antes da alteração

- verifique o estado do Git e preserve mudanças existentes;
- identifique o head canônico do Alembic;
- mapeie a projeção vendável usada pelo POS e os pontos onde produtos entram em
  pedidos de balcão, retirada e mesas;
- mapeie como unidade, canal, modo, permission e capability chegam ao serviço;
- registre no resumo final as decisões encontradas. Não produza apenas um plano:
  prossiga com a implementação.

### 2. Modelo canônico

Crie um modelo normalizado equivalente a:

- sortimento/cardápio pertencente ao tenant, com código, nome, estado e versão;
- vínculo do sortimento com uma ou mais unidades e contextos de venda;
- vínculo N:N entre produto mestre e sortimento;
- contextos independentes e extensíveis para `COUNTER`, `TAKEAWAY`, `TABLE`,
  `DELIVERY` e `ECOMMERCE`, sem identificadores específicos de iFood, 99Food ou
  adquirentes nesta camada;
- constraints, índices, chaves únicas, timestamps e políticas RLS coerentes com
  os padrões do repositório.

Não adicione campos soltos de nicho em `Product` como substituto do modelo.

### 3. Migração honesta

- preserve todos os produtos e categorias existentes;
- não atribua produtos existentes a mesa, delivery ou e-commerce por suposição;
- se for necessário preservar a publicação atual de balcão/retirada, materialize
  essa origem como sortimento legado explícito e auditável, limitado aos
  contextos que já eram efetivamente servidos pelo POS;
- não use dual-read indefinido nem fallback “se não houver sortimento, retorne
  todos os produtos”;
- tenants novos não recebem produtos, categorias, mesas ou comandas de outro
  tenant e não recebem fixtures comerciais na criação;
- implemente upgrade, downgrade seguro e `alembic check` sem drift.

### 4. Serviços e APIs

- centralize a resolução do sortimento efetivo em um serviço de domínio;
- faça a projeção vendável exigir unidade e contexto de venda explícitos;
- aplique capability e permissions no servidor;
- forneça APIs de Gestão para listar sortimentos, consultar escopos, criar ou
  editar um sortimento e vincular/desvincular produtos;
- use paginação e busca server-side nas listas que possam crescer;
- não aceite `actor_id` como autoridade do cliente; derive e valide a autoria no
  servidor segundo o padrão existente.

### 5. Gestão e POS

- disponibilize na Gestão uma superfície funcional e direta para administrar
  sortimentos, seus contextos e produtos, somente quando a contribuição e a
  permissão efetivas autorizarem;
- exiba estados reais de vazio, loading, erro, conflito e retry;
- no POS, solicite produtos com `COUNTER` ou `TAKEAWAY` conforme o modo atual;
- ao mudar de modo, não mantenha itens incompatíveis silenciosamente;
- prepare o contrato do serviço para `TABLE`, `DELIVERY` e `ECOMMERCE`, mas não
  apresente integrações externas como implementadas;
- não faça um redesenho geral da interface neste gate. A UI deve ser suficiente
  para operar e comprovar a regra; o refinamento visual amplo pertence ao
  restante do Sprint 5.4.

### 6. Testes obrigatórios

Cubra ao menos:

- isolamento de sortimentos e produtos entre dois tenants;
- isolamento entre duas unidades do mesmo tenant;
- produto de `COUNTER` ausente em `TABLE`, `DELIVERY` e `ECOMMERCE` sem vínculo;
- produto compartilhado aparecendo somente nos contextos explicitamente
  vinculados;
- `table_service` ativo sem publicação automática do catálogo em mesas;
- tenant multiatividade com sortimentos distintos e um único produto mestre;
- ausência de fallback para catálogo global;
- autorização e autoria das mutações de Gestão;
- conflito de versão/idempotência conforme o tipo de operação;
- migração dos dados existentes sem perda ou classificação presumida;
- tenant novo vazio e sem vazamento de dados de outro tenant;
- regressão do fluxo operacional por código/PIN e da validação gerencial do
  PDV;
- typecheck, build e testes de frontend;
- testes backend com PostgreSQL/RLS e ciclo canônico do Alembic.

## Restrições de entrega

- não altere nem apague manualmente os produtos elétricos, mesas, comandas ou
  demais dados de homologação;
- não implemente iFood, 99Food, e-commerce, TEF ou SmartPOS neste gate;
- não substitua regras de backend por condicionais de frontend;
- não faça commit, push ou deploy;
- ao terminar, deixe todas as alterações no working tree para auditoria;
- entregue um resumo objetivo, testes executados, limitações reais e a lista de
  arquivos alterados. Se algum teste depender de infraestrutura indisponível,
  informe exatamente qual, sem declarar o gate verde.

Pare após a implementação e a verificação local. O diff será auditado antes de
qualquer commit.
