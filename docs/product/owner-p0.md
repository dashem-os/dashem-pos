# OWNER-P0 — provisionamento do cliente SaaS

> Direção comercial atualizada pelo ADR-025 em 30/08/2026: atividades comerciais,
> capabilities e limites são definidos pelo Owner e persistidos em versão
> contratual. O tenant pode solicitar mudanças, mas não concede direitos a si
> próprio. Usuários, dispositivos e unidades configurados pertencem à operação
> do tenant e são apenas observados pelo Owner.

## Fronteira do Owner

O Platform Owner administra a relação comercial e contratual do SaaS. Ele
enxerga cadastro, responsável, cobrança, contrato, tipos de negócio, plano,
limites, entitlements, fase do relacionamento e o primeiro administrador. Ele
não administra garçons, caixas, atendentes, supervisores, vendas, sessões de
caixa ou estoque do tenant.

Filiais posteriores e identidades operacionais pertencem ao Dashem Gestão. O
Owner registra a matriz inicial e o limite de unidades contratado.

## Jornada canônica

`Novo cliente → cadastro e cobrança → tipos de negócio → plano → capabilities → limites → administrador inicial → provisionar`.

O fluxo persiste na mesma unidade de trabalho:

- empresa ou profissional, com CPF ou CNPJ validado por dígito verificador;
- responsável contratual, contato de cobrança e matriz;
- tipo de tenant separado da fase do relacionamento;
- uma ou várias atividades comerciais para clientes; tenant interno sem
  atividade exige exceção explícita e justificada do Owner;
- plano, valor mensal negociado, dia e estado da cobrança;
- limites de usuários, dispositivos, unidades e storage;
- capabilities efetivamente escolhidas;
- snapshot versionado do contrato e dos entitlements;
- primeiro acesso administrativo;
- auditoria e outbox.

Campos obrigatórios são validados ao tentar avançar. Não há asteriscos
espalhados: o campo recebe borda âmbar `#ffbf00`, mensagem específica e foco.

## Tipos de negócio e capabilities

`FOOD_SERVICE`, `RETAIL` e `BEAUTY_RESELLER` são atividades comerciais
combináveis. O Owner define uma ou várias durante a contratação e somente uma
nova versão contratual pode alterá-las. O tenant pode solicitar a mudança, mas
não a aprova nem a executa diretamente.

Plano, atividades, add-ons e exceções produzem uma proposta inicial de
capabilities. O Owner revisa essa proposta e persiste a seleção final com a
procedência de cada entitlement. Gestão e POS recebem exclusivamente os
entitlements persistidos; nenhuma capability aparece por inferência de runtime.

## Edição e legado

Cadastro, tipo, fase, perfis, plano, mensalidade, limites e capabilities são
editáveis no workspace da organização. Cada alteração contratual cria nova
versão auditada. Tenants antigos sem contrato podem ser regularizados pelo mesmo
workspace, e um ADMIN já existente conta como administrador entregue.

## Cobrança e futuro Financeiro SaaS

O OWNER-P0 administra o acordo comercial por organização: plano, mensalidade
negociada, dia de vencimento e estados da assinatura e da cobrança. A data de
cada fatura é derivada da competência e desse único dia contratual.
Isso não substitui um razão financeiro.

O contexto Owner Financeiro é separado do financeiro dos tenants e cobre
faturas, cobranças, recebimentos, inadimplência, conciliação, MRR, churn,
impostos e integrações de pagamento referentes exclusivamente à receita do
SaaS. Faturamento, lucro, vendas, caixas, estoque, unidades em operação e quadro
de funcionários do tenant não atravessam essa fronteira e permanecem sob
responsabilidade do Gestor no Dashem Gestão.

A especificação funcional, técnica, os indicadores e os gates de privacidade
estão em [`owner-financeiro-saas.md`](owner-financeiro-saas.md).

## Gate de aceite

O gate fica verde somente quando a jornada completa provisiona, reabre, edita e
versiona um tenant coerente; aceita CPF e CNPJ válidos; suporta perfis híbridos;
reconhece administradores legados; e entrega a Gestão/POS somente os
entitlements persistidos. Endpoint ou função isolada não aprova o gate.
