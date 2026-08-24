# ADR-010 — Retaguarda do tenant e fronteiras operacionais

Status: aceito no S13.1.  
Data: 23 de agosto de 2026.

## Decisão

O Dashem Gestão é a superfície administrativa do tenant. Somente ela configura
catálogo, estoque, ambientes, mesas, reservas, caixas, terminais, pontos de
produção, impressão e equipe. O Dashem Control continua sendo o plano interno do
SaaS e não assume a administração cotidiana do cliente.

Gestão pode abrir o PDV para teste ou operação autorizada. POS e KDS não exibem
atalho para Gestão: uma identidade operacional não ganha uma rota de elevação por
conveniência visual. A autorização do servidor continua sendo a autoridade mesmo
quando um elemento não é renderizado.

Mesas físicas são configuração administrativa. A atendente opera mesas já
persistidas e pode sinalizar ou remover impedimento com permission específica e
motivo auditável. Uma reserva mantém identidade própria; a mesa é apresentada
como reservada e somente abre após confirmação explícita daquela reserva.

`OperationalDevice` representa POS, KDS ou impressora. Quando não existe vínculo
prévio, o caixa ou ponto de produção é criado na mesma transação do dispositivo.
Pausa é reversível; revogação exige novo pareamento.

## Consequências

- criar mesa não é uma ação do workspace operacional;
- `table.manage`, `table.state.update` e `table.reservation.manage` são permissões
  distintas;
- não há fallback de favoritos capaz de produzir um catálogo aparentemente vazio;
- uma falha ao provisionar dispositivo não deixa caixa/ponto órfão;
- dados ausentes geram estado vazio orientado, nunca métrica ou integração falsa.
