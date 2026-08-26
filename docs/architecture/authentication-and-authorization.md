# Authentication and authorization contract

Status: accepted and implemented as the first security foundation.

## Boundary

Supabase Auth proves identity and owns credentials, sessions, recovery and MFA.
FastAPI and the Dashem PostgreSQL schema own authorization: platform roles,
tenant memberships, site scope and business permissions.

Transactional email is a separate delivery boundary. Resend is the adopted
provider for invites, recovery and confirmation messages. The built-in
Supabase SMTP service is not production infrastructure and must not be used for
tenant onboarding or production support flows. See
[`identity-email-delivery.md`](identity-email-delivery.md).

The JWT `sub` is mapped through `auth_identities`; it is not used as the
primary key of the business user. This keeps the domain portable to another
OIDC provider or enterprise SSO.

## Request contract

Authenticated calls send:

```http
Authorization: Bearer <supabase-access-token>
X-Tenant-ID: <tenant-uuid>
X-Store-ID: <store-uuid> # when operating in a site
```

`X-User-ID` and `X-Role` are never trusted in authenticated mode. The backend
resolves the user from the validated token and the role from an active database
membership. The selected store must be active and belong to the selected
tenant.

## Access rules

Papéis agora apontam para perfis canônicos de permissions; não são mais a
decisão final por prefixo de rota. Grants `ALLOW`/`DENY` podem especializar uma
membership em tenant ou store, com `DENY` prevalecendo. Cada operação exige no
servidor: contexto válido, capability contratada e permission efetiva.

O Tenant Administrator administra equipe, perfis e escopos em `/api/v1/team`.
O Dashem Control entrega apenas o administrador contratual e pode suspender ou
revogar uma membership como ação explícita de segurança, sem redefinir papel ou
escopo operacional.

Platform membership does not silently grant access to customer data. A future
support-access workflow must be explicit, time-bound and audited.

## Environment policy

- Production: `AUTH_MODE=required` is enforced at startup.
- Test: `AUTH_MODE=test` accepts only locally signed test JWTs.
- Local prototype: `AUTH_MODE=disabled` is an explicit compatibility switch.
  It must never be configured in Render or another production environment.

## Provisioning

1. Confirm that Resend Custom SMTP and the official redirect URLs are healthy.
2. Create or invite the person in Supabase Auth.
3. Create the internal `users` record without a password.
4. Create `auth_identities(provider='supabase', provider_subject=<auth user id>)`.
5. Create a platform membership or one or more tenant memberships.
6. Require MFA (`aal2`) for privileged Console Owner operations.

The initial link can be created without handling any password:

```bash
python -m app.scripts.provision_access \
  --subject <supabase-auth-user-id> \
  --email owner@example.com \
  --name "Platform Owner" \
  --platform-role PLATFORM_OWNER
```

Run this only with `DATABASE_URL` explicitly pointing to the intended database.

## Application routing

The public application uses one origin and resolves the destination from the
authenticated identity. It does not expose a separate Owner domain.

| State | Destination |
|---|---|
| No valid session | `/login` |
| Platform Owner or Platform Admin | `/owner` |
| Tenant Administrator/Manager autorizado | `/manage` |
| Operador/Caixa autorizado | `/pos` |
| Produção autorizada | `/kds` |
| Authenticated without an active authorization record | access-pending screen |

`/operate` não é um destino resolvido por uma identidade administrativa nem um
atalho do login público. É a superfície de um navegador previamente autorizado
como terminal POS. Código + PIN pessoal criam uma `OperationalSession` cujo
tenant, unidade, caixa e dispositivo vêm da autorização server-side do terminal.
O operador nunca escolhe esse contexto.

Uma sessão por e-mail autoriza ações administrativas e a autorização física do
terminal, mas não substitui a sessão operacional em mutações humanas do PDV. Um
administrador ou gerente que também opere deve possuir ficha de colaborador,
função operacional, código e PIN próprios. O ciclo completo está no
[`ADR-024`](adr-024-operational-employee-access.md).

The frontend route is only a navigation decision. Every privileged API route
still validates the JWT, the platform or tenant membership, the requested
scope and, where required, `aal2` on the backend.

## First Platform Owner

There is intentionally no public sign-up for a Platform Owner. The first
access is bootstrapped once by an operator with access to Supabase Auth and the
production database:

1. Verify Custom SMTP, the sender domain and the recovery flow before sending
   any invitation. Do not use the built-in Supabase SMTP for this procedure.
2. In Supabase Auth, invite or create the Owner user. Prefer an email invitation
   so the person chooses the password; never exchange the password with Dashem.
3. Copy the Auth user UUID shown by Supabase. This is the JWT `sub`, not an API
   key and not the user's email.
4. Run `provision_access` with `DATABASE_URL` pointing to the intended database,
   using the Auth UUID as `--subject`.
5. Open the normal application URL. The application sends an unauthenticated
   visitor to `/login`; after authentication it recognizes the platform role
   and sends the Owner to `/owner`.
6. Email/password Owners must set a strong password on first access. All Owner
   and Platform Admin accounts must then enroll or verify TOTP MFA before the
   Console or its privileged endpoints are released.

The initial link command is idempotent for the same provider subject:

```bash
python -m app.scripts.provision_access \
  --subject <supabase-auth-user-uuid> \
  --email <owner-email> \
  --name "<owner-name>" \
  --platform-role PLATFORM_OWNER
```

The password policy must also be configured in Supabase Auth because Supabase,
not the Dashem database, is the credential authority. Use at least 12
characters and require uppercase, lowercase, number and symbol. Enable TOTP
MFA. The frontend mirrors the same password requirements for immediate user
feedback, while Supabase remains the enforcement point.

## Production configuration checklist

Frontend (Vercel):

```dotenv
VITE_API_URL=https://dashem-pos-api.onrender.com
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-or-anon-key>
```

Backend (Render):

```dotenv
AUTH_MODE=required
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_JWT_AUDIENCE=authenticated
CORS_ORIGINS=["https://dashem-pos.vercel.app","http://localhost:5173","http://127.0.0.1:5173"]
```

Supabase Auth URL configuration:

- Site URL: `https://dashem-pos.vercel.app`
- Redirect URL: `https://dashem-pos.vercel.app/login`
- Local redirect URL: `http://localhost:5173/login`

Never put the Supabase `service_role` key in Vercel, a `VITE_*` variable or
browser code.

Supabase Auth email delivery:

- provider: Resend via Custom SMTP;
- sender: `Dashem Segurança <acesso@auth.dashem.tech>`;
- dedicated sending domain: `auth.dashem.tech`;
- SPF, DKIM and DMARC must be healthy before invites are enabled;
- SMTP credentials remain only in server-side provider settings;
- delivery, bounce and complaint webhooks feed the Dashem audit trail;
- Google and Microsoft buttons remain hidden until their providers are
  configured and validated.
