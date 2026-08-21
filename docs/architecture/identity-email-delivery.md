# Identity and transactional email delivery

Status: decisão arquitetural aceita. Resend adotado; configuração operacional
pendente antes de novos convites ou pilotos.

## 1. Decisão

O Supabase Auth é o Identity Provider da Dashem e permanece responsável por:

- credenciais e política de senha;
- sessões, access tokens e refresh tokens;
- recuperação e confirmação de identidade;
- OAuth e MFA;
- geração e validação dos tokens de autenticação.

O SMTP padrão do Supabase não integra a infraestrutura de produção. Ele possui
restrições adequadas apenas a demonstrações e não atende uma plataforma
multi-tenant.

O Resend será o provedor de e-mail transacional. A Dashem será responsável pelo
domínio remetente, reputação, configuração DNS, observabilidade e capacidade de
envio.

## 2. Fronteiras

```text
Identity Plane
└── Supabase Auth
    └── identidade, tokens, sessões, OAuth e MFA

Delivery Plane
└── Resend
    └── SMTP, entrega, bounce, complaint e webhooks

Control Plane
└── Dashem Owner Console
    └── tenants, convites, suporte, auditoria e diagnóstico
```

Trocar o provedor de e-mail não altera a identidade nem a autorização. Trocar o
Identity Provider no futuro não deve alterar os usuários internos porque o
vínculo externo permanece em `auth_identities`.

## 3. Domínio remetente

```text
dashem.tech
├── app.dashem.tech
├── api.dashem.tech
├── auth.dashem.tech
│   └── acesso@auth.dashem.tech
└── status.dashem.tech
```

`auth.dashem.tech` é dedicado a autenticação. Marketing e campanhas não podem
usar o mesmo stream ou reputação.

Registros obrigatórios:

- SPF para autorizar o provedor;
- DKIM para assinatura das mensagens;
- DMARC para política e relatórios de falsificação;
- return path conforme instruções do Resend.

O remetente inicial será:

```text
Dashem Segurança <acesso@auth.dashem.tech>
```

## 4. Configuração operacional

Ordem obrigatória:

1. Criar o domínio no Resend.
2. Publicar os registros DNS indicados pelo Resend.
3. Confirmar SPF e DKIM e publicar política DMARC progressiva.
4. Criar uma credencial exclusiva para o Supabase Auth.
5. Configurar Custom SMTP no Supabase Auth.
6. Ajustar o limite de e-mails para a capacidade contratada.
7. Personalizar templates e links para os domínios oficiais.
8. Desabilitar link tracking se ele modificar URLs de autenticação.
9. Executar a matriz de testes deste documento.
10. Rotacionar imediatamente qualquer credencial exposta.

Credenciais SMTP são segredos server-side. Elas não pertencem a `.env` do
frontend, variáveis `VITE_*`, logs, capturas ou documentação versionada.

## 5. Eventos e observabilidade

O Console Owner não deve inferir entrega a partir da criação do convite. Ele
exibe eventos comprovados pelo Identity Provider, backend e Resend.

Estados iniciais:

```text
REQUESTED
IDENTITY_PREPARED
PROVIDER_ACCEPTED
DELIVERED
BOUNCED
COMPLAINED
DEFERRED
USED
EXPIRED
CANCELLED
```

Um registro de operação de acesso deve guardar:

- `correlation_id`;
- `tenant_id`, quando aplicável;
- usuário, destinatário normalizado e tipo da operação;
- `provider_message_id`;
- estado atual e timeline imutável;
- timestamps de ocorrência e recebimento;
- código e motivo normalizado da falha;
- número de tentativas e expiração real;
- ator que solicitou, reenviou ou cancelou.

Nunca guardar access token, refresh token, OTP ou URL completa de confirmação.

“Delivered” significa que o servidor destinatário aceitou a mensagem; não
significa que a pessoa leu o conteúdo. A UI deve usar linguagem precisa.

Webhooks precisam de:

- validação de assinatura;
- idempotência por identificador do evento;
- persistência antes do processamento assíncrono;
- retries com backoff;
- dead-letter ou fila de falhas;
- correlação com tenant e operação de acesso;
- auditoria de reprocessamento manual.

## 6. Experiência do Console Owner

```text
CONVITE DE ACESSO

Marcelo Carvalho
marcelo@empresa.com.br
Loja Centro — Administrador

✓ Identidade preparada             18:02:14
✓ Mensagem aceita pelo Resend       18:02:15
✓ Servidor destinatário aceitou     18:02:17
○ Convite ainda não utilizado

Enviado há 37 segundos
Expira conforme a política vigente
```

Ações permitidas, sempre auditadas:

- reenviar com cooldown e idempotência;
- cancelar um convite ainda não utilizado;
- copiar diagnóstico sem incluir segredos;
- corrigir endereço por um fluxo explícito;
- abrir incidente de entrega;
- revogar sessões quando necessário.

Platform Owners podem observar toda a plataforma. Administradores de tenant
veem somente eventos do próprio tenant. Suporte assistido exige escopo, prazo e
motivo.

## 7. Multi-tenancy

A identidade do usuário é global e pode possuir memberships em mais de um
tenant. Recuperação de senha pertence à identidade, enquanto convites e
onboarding carregam o contexto do tenant solicitante.

Na primeira fase, os e-mails usam a marca Dashem. White-label por tenant não é
requisito inicial. Se for adotado, deverá usar Auth Hook ou serviço de entrega
da Dashem para selecionar template, idioma, remetente e provedor sem permitir
que um tenant afete a reputação ou os dados de outro.

## 8. Matriz mínima de testes

- convite válido e utilização única;
- convite expirado;
- reenvio sem duplicação;
- recuperação de senha válida e expirada;
- revogação das sessões anteriores após troca de senha;
- destinatário inexistente;
- bounce temporário e permanente;
- complaint;
- webhook repetido e fora de ordem;
- indisponibilidade temporária do Resend;
- rate limit por usuário, IP e projeto;
- tentativa de observar evento de outro tenant;
- ausência de tokens ou URLs sensíveis em logs;
- TOTP MFA obrigatório para papéis de plataforma.

## 9. Evolução

Fase inicial:

- Resend via Custom SMTP do Supabase;
- templates e remetente Dashem;
- webhooks de entrega persistidos pelo backend;
- timeline no Console Owner.

Evolução posterior:

- Send Email Auth Hook;
- fila própria e templates versionados;
- fallback para um segundo provedor;
- políticas por região e idioma;
- white-label controlado;
- métricas, alertas e automação de suporte.
