# Inventário de dívida — governança Owner Sprint 0

Data do snapshot: 30/08/2026.

Este inventário descreve o código encontrado no início do Sprint 0. Ele não
transforma o comportamento atual em regra de negócio.

## Fronteiras atuais

| Área | Implementação atual | Divergência |
|---|---|---|
| Limites contratuais | `OwnerTenantContractUpdate` recebe quotas e grava campos `contracted_*` | O Owner passa a fabricar valores que a UI pode confundir com configuração real |
| Enforcement | `effective_limit` prefere `contracted_*` e usa o plano como fallback | A origem do limite não é apresentada na decisão |
| Uso operacional | Usuários, dispositivos e unidades são contados somente no momento de algumas mutações | Não existe read model consolidado para Owner e tenant |
| UI de limites | `TenantWorkspace` apresenta quota contratual com badge `APLICADO` | O badge não significa configuração nem uso observado |
| Atividades | A lista completa fica no snapshot contratual | A atribuição legada de profile utiliza apenas `selected_niches[0]` |
| Capabilities | `data.capability_keys or plan.capability_keys` resolve a seleção | Lista explicitamente vazia e herança do plano possuem a mesma representação |
| Storage | Plano e contrato guardam MB | Não há inventário, medição, reconciliação, alerta ou bloqueio |
| Alertas | Alguns fluxos retornam conflito ao exceder quota | Não há threshold preventivo nem contrato uniforme de decisão |
| Policy | Regras ficam em endpoints e serviços diferentes | Não há `QuotaPolicy` central nem proteção uniforme de concorrência |

## Autoridades persistidas atuais

- `ServicePlan`: catálogo e tetos do plano;
- `TenantContract`: snapshot versionado, activities/niches, limits e capabilities;
- `TenantSubscription`: plano, cobrança e duplicação de limites contratados;
- `Membership`: configuração real de acesso de pessoas;
- `OperationalDevice`: configuração real de dispositivos;
- `Store`: configuração real de unidades;
- `TenantCapability`: entitlement atualmente consultado pelo runtime;
- `TenantProfileAssignment`: vínculo legado singular de profile;
- storage: sem fato operacional canônico.

## Riscos de migração

1. Um valor `contracted_*` inferior ao teto do plano pode ser uma negociação
   real ou apenas um valor digitado para representar o estado atual.
2. Copiar `contracted_*` para "configurado" inventaria fatos operacionais.
3. Substituir `contracted_*` pelo teto do plano pode ampliar direitos sem
   aprovação.
4. Uma lista vazia de capabilities pode significar escolha explícita ou herança
   acidental.
5. A primeira atividade não representa necessariamente a atividade principal.
6. `128 MB` não prova uso nem limite efetivamente aplicado.

## Bloqueios declarados

- nenhuma migration destrutiva antes da classificação dos dados legados;
- nenhuma UI nova deve reutilizar `APLICADO`;
- nenhum endpoint novo deve consultar `contracted_*` diretamente;
- nenhuma capability nova deve usar lista vazia como comando implícito;
- nenhum fluxo multiatividade deve selecionar automaticamente o primeiro item;
- nenhum produto pode vender storage como medido antes do metering reconciliado.
