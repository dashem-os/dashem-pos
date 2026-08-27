# OWNER-P0 — provisionamento do cliente SaaS

## Fronteira do Owner

O Platform Owner administra a relação SaaS, não a operação interna do cliente.
Ele enxerga dados cadastrais, cobrança, contrato, nicho, plano, quotas,
entitlements, ciclo de vida e o primeiro administrador. Ele não enxerga nem
administra garçons, caixas, atendentes, supervisores, vendas, sessões de caixa
ou estoque do tenant.

Filiais e identidades operacionais são administradas no Dashem Gestão. O Owner
registra a matriz inicial e a quota de unidades contratada.

## Jornada canônica

Existe um único provisionamento público:

`Novo cliente → cadastro e cobrança → nicho → plano → capabilities filtradas → limites → administrador inicial → provisionar`.

O provisionamento persiste na mesma unidade de trabalho:

- empresa, responsável contratual, cobrança e matriz;
- exatamente um nicho;
- plano ativo;
- quotas de usuários, dispositivos, unidades e storage, sem exceder o plano;
- capabilities base e add-ons permitidos pelo nicho;
- snapshot versionado do contrato;
- entitlements efetivos;
- atribuição versionada do perfil;
- primeiro acesso administrativo;
- auditoria e outbox.

Não existe rota pública para criar tenant comercial incompleto.

## Nichos iniciais

### `FOOD_SERVICE`

Inclui delivery. Mesas e KDS são add-ons possíveis e só existem quando forem
explicitamente contratados.

### `RETAIL`

Inclui estoque, checkout e canal de e-commerce. Nunca admite Mesas ou KDS.

### `BEAUTY_RESELLER`

Inclui catálogo e pedidos online. Nunca admite Mesas ou KDS.

O catálogo global de capabilities não é exibido ao Owner. A API retorna somente
a base e os add-ons permitidos para o nicho selecionado, e repete a validação no
servidor antes de persistir qualquer entitlement.

## Gate de aceite

O OWNER-P0 só fica verde quando a jornada completa cria um tenant coerente para
cada um dos três nichos e a projeção de Gestão/POS recebe somente os
entitlements persistidos. A existência isolada de endpoint, tabela ou função não
aprova o gate.
