# ADR-009 — Catálogo por canal e repasse de marketplace

Status: aceito no S13.

O produto Dashem mantém uma identidade canônica. IDs externos pertencem a
`ChannelCatalogMapping`, por merchant e tipo de entidade. Preço, disponibilidade
e estoque publicáveis vivem em `ChannelCatalogOffer`; cada alteração incrementa
a versão desejada.

Publicações são lotes com itens independentes e uma chave de operação estável por
oferta/versão. Falha parcial não promove o lote nem os demais itens por
suposição. Backlog e erro do provider permanecem observáveis.

`MarketplaceSettlement` é um documento financeiro separado do Order e do
pagamento operacional. Bruto, comissão, taxa, promoção, ajuste, líquido esperado
e pagamentos recebidos preservam a referência do documento do provider e podem
ficar pendentes, parciais, pagos ou divergentes.
