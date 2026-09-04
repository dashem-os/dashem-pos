# ADR-029 — Fronteiras de módulo e o Owner como camada

Status: **aceito**

Data: 4 de setembro de 2026

## Contexto

O roadmap coloca entre suas obrigações fundadoras "a obrigação de modularizar
desde o início, sem microserviços prematuros", e a seção 4.2 declara que "os
limites modulares passam a valer imediatamente".

O que a auditoria de confronto de 4/9/2026 encontrou foi outra coisa:
`app/modules/` contém **dois** módulos — `capabilities` e `governance` —
enquanto vinte domínios cresceram planos sob `app/services` e `app/models`.
Nada declarava qual módulo é dono de qual tabela, e nada impedia um serviço de
importar o modelo de qualquer outro.

A medição, porém, trouxe uma notícia melhor do que o diagnóstico sugeria.
Confrontando os 31 serviços contra os 25 arquivos de modelo, existem hoje
**oito** travessias de fronteira. O grafo de dependência entre serviços é quase
acíclico: quase tudo depende apenas de `reliability`, que é infraestrutura.

**As fronteiras já existem de fato. O que faltava era declará-las e defendê-las.**

## Decisão

### 1. O Owner é uma camada, não um módulo irmão

Dashem Control governa tenants: define capabilities, contratos, limites,
faturamento e medição de storage. Ele está **acima** dos módulos de produto, não
ao lado deles.

Consequência dura, sem baseline e sem exceção prevista: **nenhum serviço do lado
tenant lê uma tabela da camada Owner.** O tenant consulta seus direitos por
contrato — `capabilities` e `contract_entitlement` — e nunca pela tabela de
quem os concedeu. O caminho inverso é permitido de forma restrita: o Owner
enxerga tenant e loja, porque precisa nomeá-los, e nada além disso.

O módulo `governance`, já existente, é o embrião dessa camada e sua descrição
("pure domain contracts for Owner governance") permanece válida.

### 2. O mapa de módulos

| Módulo | Modelos | Papel |
|---|---|---|
| `shared` | `reliability` | outbox, auditoria, idempotência, heartbeat |
| `owner` | `platform`, `owner_finance`, `storage`, `commercial_catalog` | governo do SaaS |
| `identity` | `identity`, `device` | tenant, unidade, pessoa, credencial, sessão, terminal |
| `catalog` | `catalog`, `assortment` | produto, preço, estoque, sortimento |
| `operation` | `order`, `sale`, `table_service`, `transfer`, `production` | o que acontece no salão e no balcão |
| `finance` | `payment`, `negotiation`, `provider`, `receivable`, `reconciliation`, `fiscal` | dinheiro, do caixa ao fiscal |
| `channels` | `channel`, `channel_hub`, `channel_catalog` | ponte com canais externos |
| `insight` | `bi`, `intelligence` | projeções de leitura |

### 3. A direção da dependência

```text
insight  ─── lê ──▶ todos
channels ─── usa ─▶ operation ─▶ catalog ─▶ identity ─▶ shared
finance  ─── usa ─▶ operation ─▶ catalog ─▶ identity ─▶ shared
owner    ─── usa ─▶ identity  ─▶ shared
```

Nada aponta para cima. `operation` nunca alcança `finance`; `identity` não
conhece ninguém além da infraestrutura; `insight` lê e não escreve.

### 4. A fronteira é defendida por teste, não por intenção

`backend/tests/test_module_boundaries.py` declara o mapa, a direção e um
**baseline** com as oito travessias existentes. Uma travessia nova reprova a
build. Uma linha do baseline que deixou de existir também reprova, para que a
lista de dívida não vire ficção.

Isso muda a direção **agora**, sem depender de uma refatoração que ninguém
termina. Remover uma linha do baseline é como a migração avança.

## As oito travessias, e o que elas revelam

Cinco das oito não são acoplamento de domínio. São **dois modelos morando no
arquivo errado**:

- **`Register`** — o ponto de caixa físico de uma unidade — vive em `payment.py`
  ao lado de `CashSession` e `Payment`. Ele pertence à unidade, junto de `Store`
  e `OperationalDevice`. É por isso que `device`, `operational_access` e `order`
  precisam alcançar o módulo de finanças só para enxergar um caixa.
- **`SalesChannel`** — a dimensão comercial de uma venda — vive em `channel.py`
  ao lado do hub de integração externa. São coisas diferentes: uma é atributo do
  pedido, a outra é a ponte com iFood e afins. Daí `order` e `assortment`
  atravessarem para `channels`.

As três restantes são acoplamento real, a resolver por contrato:

- `device -> production`: o terminal consulta o ponto de produção para saber se
  um KDS tem destino;
- `sale -> payment`: herança do fluxo anterior ao S8, que o `CheckoutNegotiation`
  deve substituir;
- `transfer -> negotiation`: a transferência recusa mover item já coberto por
  `PaymentAllocation`. A regra é legítima; lê-la direto da tabela de finanças
  não é. Deve ser uma pergunta ao módulo dono.

## Ordem de migração

1. **Separar `Register` de `payment.py`** para o módulo `identity`, e
   **`SalesChannel` de `channel.py`** para `operation` ou `catalog`. Resolve
   cinco das oito travessias e não muda comportamento — é movimentação de
   modelo com migração de schema apenas se o nome da tabela mudar, o que não é
   necessário.
2. **Publicar contratos de módulo** para as três travessias restantes, no padrão
   já usado por `capabilities/contracts.py`: tipos puros, sem persistência.
3. **Mover os arquivos** para `app/modules/<módulo>/`, um módulo por vez, com o
   teste de fronteira verde a cada passo.
4. **Declarar dono por tabela** na documentação de cada módulo.

Nenhum passo depende do seguinte para valer. O teste protege desde o primeiro.

## Consequências

- a fronteira passa a ser verificável, e a build reprova quem a cruzar;
- o Owner deixa de ser "mais um domínio" e passa a ser camada, com uma regra
  que não admite exceção;
- a migração é incremental e reversível, sem big bang sobre 60 arquivos;
- o custo é honesto: enquanto o baseline tiver linhas, o sistema não está
  modularizado — está sob contenção, com a dívida visível e contada.

## Fora desta decisão

- microserviços, filas entre módulos ou bancos separados por módulo;
- reescrita de qualquer domínio a pretexto da fronteira;
- modularização do frontend, que tem shells independentes e merece decisão
  própria.
