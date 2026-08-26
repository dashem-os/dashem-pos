# ADR-014 — Autorização de terminal antes da identidade operacional

Status: aceito no S17.3; aceite de produto reaberto pelo ADR-024 em 25/08/2026.

## Contexto

Supervisor, caixa e atendente não possuem login por e-mail. Ainda assim, aceitar
código e PIN em qualquer navegador exigiria que o cliente informasse tenant,
unidade e caixa, criando um seletor de escopo inseguro e incompatível com o
isolamento multi-tenant.

## Decisão

Código e PIN são uma troca de identidade dentro de infraestrutura já confiável,
e não um login global. Um administrador ou gerente autenticado autoriza o
navegador contra um `OperationalDevice` do tipo POS, ativo e vinculado a um
`Register`. O servidor emite uma credencial assinada de terminal com
`device_id`, `tenant_id`, `store_id` e `register_id`.

O endereço `/operate` pertence à superfície do terminal e não é anunciado no
login público de Gestão. Ele somente apresenta a identificação do colaborador
quando essa credencial é válida. O endpoint de troca deriva o contexto
exclusivamente dos claims assinados, revalida dispositivo e caixa no banco sob
RLS e então verifica a credencial individual. O token operacional resultante é
curto, individual e permanece em `sessionStorage`; a autorização de terminal
fica em `localStorage` até expirar ou ser invalidada.

Pausar ou revogar o dispositivo, desativar o caixa ou alterar qualquer vínculo
nega imediatamente novas trocas. Nenhum nome de funcionário é enumerado na tela
pública. O bloqueio por tentativas continua pertencendo à credencial individual.

## Consequências

- um operador não escolhe nem envia o próprio tenant/unidade/caixa;
- sair do turno não desautoriza o ponto físico;
- gestores por e-mail podem abrir a superfície do PDV, mas uma operação humana
  exige assunção por colaborador com código + PIN pessoal;
- o login público permanece exclusivamente gerencial;
- reautorizar o navegador exige uma identidade gerencial e gera auditoria;
- revogação do dispositivo é também revogação da entrada operacional daquele
  ponto, sem armazenar PIN ou senha no navegador.
