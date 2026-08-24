# ADR-018 — Piloto comercial baseado em evidência de campo

## Estado

Aceito em 24/08/2026.

## Decisão

O S21 separa prontidão técnica de execução comercial. Um dossiê de piloto só
pode nascer quando:

- a release possui hardening `PASSED`;
- o tenant e a unidade estão ativos;
- o profile `FOOD_SERVICE` está vigente;
- o escopo respeita 1–3 caixas, 5–15 pessoas, balcão, mesas e cozinha;
- TEF está homologado e canais externos estão certificados quando incluídos.

`READY_FOR_FIELD_VALIDATION` não significa piloto concluído. Observações só são
aceitas após início formal do campo e carregam tipo de tarefa, referência de
origem, medidas e responsável. A conclusão exige cobertura de venda, produção,
pagamento, transferência e recuperação. Incidente SEV1 ou SEV2 bloqueia a
expansão até resolução registrada.

## Consequências

O sistema está preparado para conduzir e medir o primeiro piloto, mas o marco
comercial permanece pendente até existir estabelecimento parceiro e operação
observada. Ausência de cliente, hardware, TEF ou canal certificado nunca será
substituída por fixture, mock ou status verde presumido.
