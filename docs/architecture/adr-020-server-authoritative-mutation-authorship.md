# ADR-020 — Autoria de mutações é autoridade do servidor

Status: aceito no Gate A, em 24/08/2026.

## Contexto

Vários contratos antigos ainda transportavam `actor_id`, `operator_id` ou
`seller_id` no corpo da requisição. Esses campos podem ser úteis como dados de
negócio ou como asserções de compatibilidade, mas não podem decidir quem será
gravado em auditoria, idempotência, caixa, fiscal, estoque ou eventos de
domínio. Um navegador adulterado poderia atribuir uma ação a outra pessoa.

## Decisão

Toda mutação humana resolve seu autor a partir do `TenantContext` autenticado:

- tokens Supabase resolvem o usuário interno e sua membership no servidor;
- tokens operacionais resolvem o colaborador validado por código e PIN no
  terminal autorizado;
- qualquer `actor_id` recebido do cliente é apenas uma asserção temporária de
  compatibilidade e precisa ser idêntico ao usuário autenticado;
- divergência é recusada com `403` antes da escrita; ausência de identidade é
  recusada com `401`;
- o modo local com autenticação explicitamente desativada possui um ator
  determinístico, não nulo, restrito à suíte de integração;
- integrações recebem service actors persistidos e emitidos pelo servidor (o
  terminal TEF usa sua própria identidade persistida). O
  evento externo nunca escolhe esse identificador.

`seller_id`, `attendant_id`, dispositivo, provider e canal continuam podendo
ser dimensões do negócio. Eles não substituem a autoria humana ou sistêmica do
evento.

## Superfícies cobertas

O resolvedor canônico foi aplicado aos módulos de vendas, caixa, pagamentos,
estoque, fiscal, conciliação, mesas, pedidos, transferências, produção,
dispositivos, recebíveis, negociação, catálogo, canais e BI. A ativação por PIN
é auditada como o colaborador cuja credencial foi validada; channel webhooks
usam o service actor da conexão persistida.

## Consequências

- o frontend não é autoridade sobre autoria;
- registros de auditoria deixam de aceitar UUID zero ou ator arbitrário;
- chamadas antigas podem continuar enviando o campo durante a migração, sem
  ganhar poder para alterá-lo;
- remoção definitiva desses campos dos DTOs públicos fica para uma evolução de
  contrato posterior e não reduz a proteção já vigente;
- qualquer novo serviço de mutação deve chamar `resolve_actor` antes da
  primeira escrita ou usar um service actor emitido por um fluxo autenticado.

## Prova automatizada

`test_gate_a_server_authoritative_actor.py` cobre identidade autenticada,
tentativa de spoofing, anonimato, bypass local explícito, resolvedores de
domínio e entradas diretas de mutação antes do acesso ao banco.
