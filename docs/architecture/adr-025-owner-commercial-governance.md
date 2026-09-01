# ADR-025 — Governança comercial do Owner e observação operacional do tenant

## Estado

Aceito em 30/08/2026.

Complementado pelo ADR-026 em 01/09/2026, que define as fronteiras entre query
e command, revisão contratada e catálogo atual, além da localização canônica da
capacidade física global.

Substitui as partes do ADR-016 e da especificação OWNER-P0 que permitiam tratar
um profile como autoridade suficiente para conceder ou retirar entitlements.
Preserva a separação entre capability e permission definida pelo ADR-002.

## Contexto

O Console do Owner passou a reunir plano, atividades comerciais, capabilities,
limites, cobrança e dados operacionais do tenant. A implementação atual, porém,
mistura fatos que possuem autoridades diferentes:

- o Owner grava `contracted_user_limit`, `contracted_device_limit` e
  `contracted_store_limit` no contrato;
- a mesma interface apresenta esses valores como "aplicados", embora eles não
  representem os recursos configurados pelo administrador do tenant;
- o contrato persiste várias atividades comerciais, mas um vínculo legado de
  profile considera somente a primeira;
- uma lista vazia de capabilities pode ser interpretada como solicitação para
  herdar todas as capabilities do plano;
- storage possui referência comercial sem medição operacional.

Essas ambiguidades impedem afirmar se um valor é contratado, configurado,
reservado ou medido.

## Decisão

O DASHEM adota três autoridades independentes.

### Autoridade comercial: Owner

Somente o Owner pode:

- publicar planos e revisões;
- definir uma ou várias atividades comerciais do tenant;
- conceder capabilities, add-ons e exceções;
- definir limites, preços, descontos e vigência;
- aprovar ou recusar solicitações comerciais;
- criar uma nova versão contratual.

Plano e atividades compõem uma proposta inicial. A proposta não se torna
autorização até o Owner revisar e persistir um snapshot contratual explícito.
Depois de persistido, alterar o catálogo não altera contratos existentes.

### Autoridade operacional: administrador do tenant

O administrador do tenant configura os recursos operacionais permitidos pelo
contrato, incluindo usuários, convites, dispositivos e unidades. Ele pode
solicitar ampliação ou uma nova capability, mas não concede direitos ao próprio
tenant e não altera suas atividades comerciais contratadas.

O Console do Owner observa essa configuração; não a fabrica nem a sobrescreve.

### Autoridade de medição e enforcement: sistema

Somente o sistema:

- conta recursos configurados e reservados;
- mede consumo quando existe instrumento confiável;
- avalia limites;
- emite alertas;
- bloqueia operações;
- registra divergência, indisponibilidade ou ausência de medição.

Ausência de medição nunca é convertida em zero.

## Vocabulário obrigatório

- **teto do plano**: máximo permitido pela revisão do plano;
- **limite contratado**: direito persistido na versão contratual;
- **configurado**: recurso criado pelo administrador do tenant;
- **reservado**: operação pendente que ocupa capacidade;
- **utilizado**: consumo observado por instrumento do sistema;
- **disponível**: capacidade restante calculada pela policy vigente.

O termo "aplicado" não faz parte do contrato de domínio.

## Atividades e capabilities

Um cliente comercial deve contratar uma ou várias atividades. Tenant interno de
teste pode permanecer sem atividade somente por exceção explícita e justificada
do Owner. Nenhuma atividade possui precedência implícita e nenhuma implementação
pode reduzir a lista à primeira atividade.

O catálogo comercial resolve plano, atividades, add-ons e exceções em uma
proposta. O contrato registra explicitamente o resultado e a procedência de cada
capability. Nicho ou atividade não concede entitlement em runtime por inferência.

## Solicitações comerciais

O tenant pode submeter uma solicitação. Aprovação e recusa pertencem ao Owner.
Uma aprovação que altera direitos produz uma nova versão contratual na mesma
unidade lógica, com autor, motivo e auditoria. Uma recusa preserva a solicitação
e exige motivo.

## Consequências

- endpoints operacionais consultarão um resolvedor único de entitlement e uma
  policy única de quota;
- o Owner receberá um read model com contratado, configurado, reservado,
  utilizado e disponível;
- contadores operacionais deixarão de ser campos editáveis do contrato;
- storage permanecerá "não medido" até existir metering e reconciliação;
- dados legados serão classificados e reconciliados, nunca reinterpretados
  silenciosamente;
- integrações futuras serão capabilities contratuais: o Owner concede o direito
  e o administrador do tenant configura a conexão autorizada.

## Fora do escopo deste ADR

Este ADR não altera tabelas, endpoints nem comportamento de produção. Ele define
os contratos e gates que antecedem as migrations dos sprints seguintes.
