# ADR-016 — Capability profiles e module contributions

> Parcialmente substituído pelo ADR-025 em 30/08/2026. Profiles continuam
> compondo propostas e contributions, mas atividades comerciais e entitlements
> são definidos pelo Owner em contrato explícito. Um profile não concede nem
> retira entitlement por inferência e uma operação multiatividade não possui
> "primeiro profile" implícito.

## Estado

Aceito em 24/08/2026.

## Decisão

Verticais são composições versionadas de capabilities, e não forks de código.

- `FOOD_SERVICE`, `RETAIL` e `GROCERY` são revisões persistidas; somente revisões
  `ACTIVE` podem ser atribuídas;
- o profile é um atalho de configuração: contrato, entitlement e grant continuam
  sendo autoridades independentes;
- uma capacidade somente pode ser ativada quando há implementação registrada;
- dependências são resolvidas antes da ativação e conflitos possuem contrato
  persistido;
- a troca de revisão encerra a atribuição anterior e desabilita entitlements fora
  do novo perfil sem remover fatos históricos;
- contribution points de navegação, health e reporting são filtrados no servidor
  por capability efetiva e permission;
- o frontend registra componentes que sabe renderizar, mas não inventa menus nem
  decide autorização.

`GROCERY` permanece em rascunho porque `weighted_products` e `batch_tracking`
ainda não possuem implementação. Isso é um bloqueio honesto, não uma tela
cosmética anunciada como produto.

## Consequências

Um tenant pode migrar de vertical por uma transição auditável, preservando dados
e revogando superfícies que deixaram de estar contratadas. Uma permission sem
entitlement e um entitlement sem grant continuam insuficientes. O mesmo contrato
de composição passa a atender backend, UI e observabilidade.
