# Supabase — observações de segurança e Data API (24/08/2026)

## Log `pg_pgrst_no_exposed_schemas`

O repositório não consulta nem cria esse schema. Segundo a documentação oficial
do Supabase, a mensagem aparece quando a Data API está desativada porque o
PostgREST ainda permanece em execução. O provedor informa que isso não prejudica
o projeto, embora gere ruído nos logs.

Não aplicar SQL corretivo automaticamente em produção. Se o ruído impedir a
operação, seguir o procedimento reversível documentado pelo Supabase e registrar
a mudança como manutenção de infraestrutura:

https://supabase.com/docs/guides/troubleshooting/schema-pg_pgrst_no_exposed_schemas-does-not-exist

## Proteção contra senhas vazadas

O Security Advisor informa que o recurso está desativado. A documentação do
Supabase informa que a proteção usa a base Pwned Passwords e está disponível no
plano Pro ou superior. Enquanto o projeto permanecer no plano Free:

- manter mínimo de 12 caracteres e composição forte na aplicação;
- manter redefinição por link seguro e MFA para acessos privilegiados;
- não marcar o alerta como resolvido nem ocultá-lo;
- habilitar a proteção do provedor quando o plano contratado disponibilizá-la.

Referência: https://supabase.com/docs/guides/auth/password-security
