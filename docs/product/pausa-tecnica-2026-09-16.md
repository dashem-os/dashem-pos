# Pausa técnica — DASHEM POS — 16/09/2026

Registro histórico. O ponto de retomada mais recente está em
[29/09/2026](pausa-tecnica-2026-09-29.md).

O S10.1 avançou até o passo 7 estrutural, mas ainda não está fechado. Os commits
`02b5e4a` (avisos ao canal, migração 100) e `ced91a5` (tela estrutural) estão na
`main`, com quatro jobs verdes em cada commit. O portão local informado passou
com 630 testes de backend, 43 verificações de repositório, 204 testes de
frontend e build.

As rotas de avisos e `GET /channels/deadlines` aparecem na API publicada, e o
cadastro de conexão não aceita credencial enviada pelo lojista. A aplicação da
migração 100 em produção continua sendo inferência; as rotas não provam a versão
do banco.

O gate final ainda falta: travessia autenticada com uma gestora e uma leitora sem
permissão de gestão. Os roteiros `backend/tests/support/seed_channel_hub_walkthrough.py`
e `frontend/e2e/presentation/hom09_canais_de_venda.cjs` estão fora do commit e
não foram executados. A bancada com permissões simuladas não substitui essa
homologação.

Continuam pendentes D1, D2, D8 e a concessão da D7. R14, impacto do canal
indisponível na venda local, ainda não foi medido. Nenhum dado foi removido:
retenção tem prazos e tela, mas purga não implementada. A limpeza depende também
do ciclo de backup do Supabase.

Para a retomada: executar o gate autenticado, medir R14, decidir D1/D2/D8 e
conceder D7 somente com perfis e auditoria definidos. Não declarar S10.1,
retenção ou integração de canal como concluídos antes dessas provas.
