# OWNER-P0 — provisionamento do cliente SaaS

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
- zero, um ou vários tipos de negócio;
- plano, valor mensal negociado, dia e estado da cobrança;
- limites de usuários, dispositivos, unidades e storage;
- capabilities efetivamente escolhidas;
- snapshot versionado do contrato e dos entitlements;
- primeiro acesso administrativo;
- auditoria e outbox.

Campos obrigatórios são validados ao tentar avançar. Não há asteriscos
espalhados: o campo recebe borda âmbar `#ffbf00`, mensagem específica e foco.

## Tipos de negócio e capabilities

`FOOD_SERVICE`, `RETAIL` e `BEAUTY_RESELLER` são perfis de recomendação,
não barreiras comerciais. Um cliente pode combinar perfis — por exemplo,
confeitaria e revenda de cosméticos — e alterá-los depois da contratação.

Os perfis sugerem capabilities e fornecem uma prévia. A contratação final é a
seleção explícita de capabilities, validada apenas por dependências técnicas.
Gestão e POS recebem exclusivamente os entitlements persistidos. Assim, Mesas
ou KDS nunca aparecem por inferência em um retail, mas podem ser contratados
quando a operação híbrida realmente exigir.

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
