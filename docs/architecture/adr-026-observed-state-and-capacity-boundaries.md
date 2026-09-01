# ADR-026 — Estado observado, contrato versionado e capacidade física

## Estado

Aceito em 01/09/2026 para correção do Sprint 5.1.

O produto permanece **NO GO para tenants reais e para promessa comercial de
storage** até a conclusão dos gates descritos no checkpoint do Sprint 5.1.

Este ADR complementa o ADR-025. Quando houver conflito de apresentação ou de
read model, esta decisão prevalece.

## Problema confirmado

O Console do Owner misturava quatro fatos independentes:

- valores da revisão atual de um plano comercial;
- direitos congelados em uma versão contratual anterior;
- recursos operacionais configurados pelo administrador do tenant;
- capacidade física compartilhada e inventário do provedor de storage.

Além disso, páginas de consulta reutilizavam avaliações de comandos com uma
operação fictícia de zero unidades. Isso produzia textos prospectivos, como
"após esta operação", em uma tela que deveria apenas observar o estado atual.
Uma interface não pode transformar uma regra, um valor de configuração ou uma
frase estática em evidência de que um fato foi medido.

## Decisão

### 1. Catálogo, revisão e contrato não são intercambiáveis

- O plano atual é catálogo comercial mutável.
- A revisão do plano selecionada na contratação é a referência imutável daquela
  proposta.
- A versão contratual é a única fonte de entitlement em runtime.
- Uma alteração posterior do plano não altera contratos existentes.
- Um limite diferente do valor incluído no plano deve registrar
  `OWNER_OVERRIDE`; um valor igual registra `PLAN_INCLUDED`.
- O snapshot contratual com essa procedência usa `schema_version = 3`.

A interface pode apresentar plano atual e revisão contratada lado a lado, mas
nunca usar o primeiro como se fosse o segundo.

### 2. Query e command usam contratos distintos

Read models respondem somente a perguntas sobre o estado observado:

- contratado;
- configurado;
- reservado, quando o recurso suporta reserva;
- ocupado;
- disponível;
- excedente;
- estado de conformidade;
- origem e horário da observação.

Eles não contêm `requested`, `decision`, `reason` nem texto sobre uma operação
futura. Ausência de medição permanece ausente; não é convertida em zero.

Policies de command recebem a quantidade concreta solicitada e respondem
`ALLOWED`, `WARNING`, `DENIED` ou `UNKNOWN`. Somente essa fronteira autoriza ou
nega uma mutação. Mensagens de bloqueio pertencem à resposta do comando, não ao
painel de consulta.

### 3. Configuração operacional pertence ao tenant

Usuários, dispositivos e unidades configurados são contados nos registros
operacionais do tenant. O Owner observa esses fatos e define a quota contratual,
mas não preenche contadores operacionais no contrato.

Um excesso já existente é exibido como `OVER_LIMIT`, com a quantidade
excedente. A correção não apaga, reduz ou reclassifica dados silenciosamente.
Novas operações são avaliadas pela policy canônica no momento do comando.

### 4. Storage possui dois níveis independentes

No tenant são exibidos somente:

- quota da versão contratual;
- uso e objetos do inventário daquele tenant;
- reservas daquele tenant;
- fontes esperadas e observadas;
- identificador, watermark, horário e código de estado da medição.

Capacidade física do provedor, margem operacional, uso físico global e soma dos
compromissos comerciais são fatos da plataforma. Sua localização canônica é:

`Console do Owner → Saúde da plataforma → Capacidade de storage`.

Essa visão global é técnica e paginada por tenant. Ela não é duplicada no
painel individual e não desaparece da operação do Owner.

### 5. Compromisso comercial não é capacidade física garantida

A soma das quotas contratuais é denominada `commercial_committed_bytes`. Ela é
comparada à capacidade física utilizável apenas como observabilidade. O sistema
não bloqueia publicação ou ativação de planos por essa soma.

Enforcement acontece sobre uma operação concreta, considerando:

- quota da versão contratual do tenant;
- inventário completo, reconciliado e recente;
- reservas concorrentes;
- capacidade física configurada e margem operacional.

Se um requisito de oversubscription comercial for adotado no futuro, ele deve
ser uma policy versionada e auditável, nunca uma condição escondida na tela.

### 6. Texto da interface não constitui evidência

Rótulos podem explicar a natureza de um campo, mas valores e estados factuais
devem vir do backend. Termos como “reconciliado”, “disponível”, “saudável” ou
“aplicado” não podem ser usados como afirmação fixa.

A interface apresenta códigos canônicos recebidos da API e números derivados
dos fatos persistidos. Traduções futuras devem mapear códigos de domínio, sem
inventar sucesso quando o dado estiver ausente.

## Consequências

- O contrato da API de quotas de contagem não reutiliza mais o resultado de
  preflight de uma mutação.
- O contrato da API de storage separa fatos de leitura e avaliação de escrita.
- A revisão contratada e o catálogo atual ficam identificados separadamente.
- A capacidade global passa a ter endpoint e seção próprios na Saúde da
  plataforma.
- O painel do tenant deixa de carregar detalhes físicos globais do provedor.
- Não há trava de ativação de plano adicionada por esta decisão.
- Contradições históricas continuam visíveis como fatos até uma nova decisão
  contratual explícita do Owner.

## Gates antes das integrações externas

Omnichannel, TEF/SmartPOS, delivery e e-commerce dependem destas invariantes:

1. autoridade contratual versionada;
2. configuração operacional isolada por tenant;
3. query sem efeitos e command com policy explícita;
4. idempotência e autoria server-side;
5. medição com fonte, horário e evidência;
6. capacidade física observável sem promessa comercial implícita.

Nenhuma homologação externa será declarada com base apenas em tela, fixture,
mock ou texto estático.
