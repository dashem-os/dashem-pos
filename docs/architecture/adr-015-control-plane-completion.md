# ADR-015 — Conclusão do Dashem Control

## Estado

Aceito em 24/08/2026.

## Decisão

O plano de controle usa contratos persistidos próprios, expostos por
`/api/v1/control`, e não reaproveita a administração cotidiana do tenant.

- leads só são convertidos quando vinculados a um tenant já provisionado;
- cada alteração contratual cria uma nova versão e só inclui capabilities com
  entitlement vigente;
- onboarding registra estado e evidências, não apenas um percentual visual;
- entrega de identidade guarda destinatário mascarado, provider, resultado e
  detalhe sanitizado, nunca token ou segredo;
- suporte assistido exige motivo, escopo, aprovação e expiração;
- incidentes têm severidade, componente, correlação e resolução auditável;
- saúde sem heartbeat é `UNINSTRUMENTED`, não verde;
- erros expostos ao Control são truncados e sanitizados.

O Resend continua uma dependência externa futura: até domínio, SPF, DKIM, DMARC
e webhooks estarem validados, sua capability não pode ser anunciada como pronta.

## Consequências

O cliente opera sem acessar o Control e o Platform Owner não ganha autoridade
para criar ou administrar a equipe cotidiana. O Control mantém a fronteira
comercial, de implantação, suporte e observabilidade da plataforma.
