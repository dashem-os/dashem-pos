# Gate de investimento — Background Worker

Status em 01/09/2026: **INVESTIMENTO POSTERGADO COM SEGURANÇA**

## Decisão atual

O DASHEM não contratará um Background Worker hospedado durante a construção do
Sprint 5.1 e da primeira camada operacional do tenant. A ausência do processo
permanece visível no Control como `UNKNOWN`, e a fila antiga permanece
`DEGRADED`; esses estados não serão escondidos nem convertidos em saúde
simulada.

O investimento será reavaliado no gate de pré-piloto hospedado. Até lá, o
orçamento e a capacidade de trabalho devem priorizar:

1. deixar o Dashem Control consistente e auditável;
2. construir a experiência real do administrador e da operação do tenant;
3. concluir os gates com objetos reais, isolamento e concorrência;
4. submeter o produto à avaliação técnica de automação e operação;
5. corrigir os achados antes de assumir custo recorrente de infraestrutura.

Essa decisão não remove o worker da arquitetura. Ela separa corretamente
**fundação implementada**, **compute continuamente contratado** e
**necessidade comercial comprovada**.

## O que já foi implementado

- migration Alembic `066_published_event_stream`;
- `published_events` como fluxo interno append-only e protegido por RLS;
- um recibo único por `outbox_event_id` e hash SHA-256 do envelope canônico;
- claim concorrente com `FOR UPDATE SKIP LOCKED`;
- lease com recuperação de `PROCESSING` abandonado;
- publicação idempotente e transação única para recibo + `PUBLISHED`;
- retry com backoff limitado e quarentena de envelope inválido;
- heartbeat persistido em `service_heartbeats`;
- métrica factual `published_receipts` no Control;
- cinco testes específicos para recibo, imutabilidade, idempotência, lease,
  retry e quarentena;
- migration validada com downgrade/upgrade e schema sem drift;
- CI pública `33536178413` aprovada em frontend, backend PostgreSQL/RLS,
  Alembic e E2E;
- deploy do backend confirmado com `published_receipts: 0`, Auth HTTP 200 e
  horários rotulados em `UTC−03:00`.

O valor zero é verdadeiro: a tabela foi criada, mas nenhum worker hospedado foi
iniciado para publicar a fila existente. `PUBLISHED` significa disponível no
fluxo interno do DASHEM; nunca significa aceito por TEF, adquirente,
marketplace, iFood, 99Food ou outro canal.

## Por que não financiar agora

Hoje nenhuma jornada vendável depende da conclusão assíncrona desses eventos.
Storage, contrato, quota e telas do Owner podem ser construídos e testados pela
API, PostgreSQL local, Docker e CI. Pagar um processo continuamente ativo agora
apenas transformaria a fila em recibos internos; não criaria tenant vendável,
homologação externa nem receita.

O worker local continua disponível em `docker-compose.yml` para testes. A CI
usa banco e API isolados. Esses ambientes provam comportamento do código sem
apresentar o processo hospedado como operacional.

## Quando o investimento passa a ser obrigatório

O Background Worker hospedado torna-se bloqueador quando todos os itens abaixo
forem verdadeiros:

1. existe um piloto hospedado aprovado ou primeiro cliente em implantação;
2. ao menos uma jornada depende de execução posterior à requisição, como
   webhook, notificação, projeção, sincronização ou integração externa;
3. Dashem Control e a camada mínima do tenant passaram pela revisão técnica e
   os bloqueadores foram tratados;
4. fila, idade máxima, retry, falhas e heartbeat possuem SLO de piloto;
5. há orçamento explícito para compute contínuo e o preço vigente do provedor
   foi aceito pelo Owner.

Independentemente do valor comercial exibido hoje, o preço não é codificado
neste documento porque pode mudar. O Render não oferece instância gratuita para
Background Worker. Antes de qualquer contratação, confirmar novamente oferta,
região, recursos, cobrança e possibilidade de suspensão.

Omnichannel, TEF POS Smart, delivery e e-commerce satisfarão o item 2. Cada
adapter ainda precisará de recibo externo próprio; o worker interno não
substitui homologação nem confirmação do provedor.

## Configuração futura prevista no Render

Criar somente após o gate financeiro e técnico:

```text
Tipo: Background Worker
Repositório: dashem-os/dashem-pos
Branch: main
Root Directory: backend
Runtime: Docker
Dockerfile: ./Dockerfile
Docker Command: python -m app.workers.outbox_worker
Região: a mesma da API e do PostgreSQL
Compute: menor plano pago que atenda ao SLO aprovado
```

Variáveis mínimas, cadastradas apenas no gerenciador de ambiente:

```text
DATABASE_URL=<conexão runtime restrita usada pela aplicação>
SECRET_KEY=<segredo exclusivo do worker>
ENVIRONMENT=production
AUTH_MODE=required
SUPABASE_URL=<URL pública do projeto>
RUNTIME_DB_ROLE=dashem_runtime
DB_POOL_SIZE=1
DB_MAX_OVERFLOW=0
```

O worker não precisa de `SUPABASE_SECRET_KEY`, credenciais de pagamento ou
segredos de canais para publicar no fluxo interno. Consumidores externos terão
serviços e credenciais com escopo próprio.

## Gate de ativação e rollback

Antes de criar o serviço:

1. confirmar que migration 066 está aplicada;
2. registrar commit implantado, pendentes, falhas e recibos publicados;
3. revisar as variáveis sem copiar seus valores para ticket, chat ou Git;
4. confirmar o preço na tela final, sem submissão automática.

Após a ativação:

1. exigir heartbeat `HEALTHY` com idade inferior a 90 segundos;
2. observar a fila reduzir sem apagar registros;
3. conferir crescimento correspondente de `published_receipts`;
4. exigir `failed = 0` ou investigar individualmente cada quarentena;
5. reiniciar uma instância em teste e comprovar recuperação de lease;
6. repetir smoke test no Control e registrar horário em `UTC−03:00`;
7. manter o serviço por uma janela de observação antes do GO do piloto.

Se o worker se comportar incorretamente, suspender o processo e preservar
`outbox_events` e `published_events`. Não truncar a fila, não alterar status
manualmente e não considerar log como recibo. Corrigir, publicar nova revisão e
retomar pelos leases expirados.

## Decisão de GO

- Desenvolvimento do Owner e do tenant: não exige worker pago.
- Homologação local e CI: usa worker local/controlado quando necessário.
- Piloto hospedado com jornada assíncrona: exige worker pago e gate aprovado.
- Cliente pagante ou integração externa: worker é obrigatório, mas não
  suficiente; adapters e confirmações externas também precisam ser homologados.

