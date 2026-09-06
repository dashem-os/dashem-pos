# Revisão de segurança — 06/09/2026

**Escopo:** achados da auditoria lida com o dono do SaaS em 05/09/2026, tratados
em 06/09 na branch `security-review-2026-09-06`.

**Sanitização.** Este documento não contém segredo, senha, chave, token nem dado
pessoal. Onde um valor seria necessário para entender o achado, aparece o **nome
da variável** (`AUTH_MODE`, `SUPABASE_URL`, `BIND_HOST`) e nunca o conteúdo dela.
Nenhum identificador de tenant, usuário ou terminal foi transcrito.

## Situação

| # | Severidade | Achado | Situação |
|---|---|---|---|
| 1 | **ALTA** | `AUTH_MODE` protegido por denylist de nomes de ambiente | **corrigido** |
| 2 | MÉDIA | Mapa de permissão por string rebaixa a regra com barra final | **em aberto**, com a suposição que o mantém inofensivo pinada por teste |
| 3 | MÉDIA | Compose publica Postgres e API em `0.0.0.0` | **corrigido** |
| 4 | BAIXA | Aviso conhecido do dev server (via `esbuild`) | **mitigado**; atualização de major fica para decisão à parte |
| 5 | BAIXA | `assert` no caminho de segurança | **corrigido** no núcleo, com escopo declarado |
| 6 | BAIXA | Conversão para `float` na escrita de saldo `Numeric(14,4)` | **corrigido** |

Três observações minhas, fora do relatório original, estão no fim.

---

## 1 · ALTA — a proteção do `AUTH_MODE` era uma lista de exceções

`Settings.validate_auth_configuration` exigia `AUTH_MODE=required` quando
`ENVIRONMENT` fosse `production` ou `prod`. Qualquer outro nome — `staging`,
`qa`, `uat`, `homolog`, ou um nome digitado errado como `producton` — aceitava
`AUTH_MODE=disabled`. E nesse modo o cabeçalho `X-User-ID` identifica o usuário
**sem token nenhum**.

O agravante estava do lado de dentro: o contêiner de desenvolvimento roda com
`AUTH_MODE=disabled` todos os dias, então o modo perigoso não era hipotético, era
o cotidiano — faltava só um ambiente com nome diferente para levá-lo adiante.

**Correção.** A regra virou allowlist: `RELAXED_AUTH_ENVIRONMENTS` lista os dois
ambientes que de fato existem no repositório (`development`, `test`), e qualquer
outro exige `required`. O nome também passa por `strip()`, porque um espaço à
esquerda contornava a comparação anterior. `SUPABASE_URL` passou a ser exigido em
todo ambiente fora da allowlist, e não apenas em produção.

Proteger por exceções exige acertar o futuro; proteger por permissões exige
apenas listar o presente. Um ambiente novo agora nasce fechado, e abri-lo é um
ato deliberado em `config.py`.

**Evidência:** `test_relaxed_authentication_is_allowed_only_where_it_was_declared`,
`test_an_environment_nobody_listed_refuses_to_relax_authentication` (inclui nome
com erro de digitação e com espaço) e
`test_identity_provider_is_required_wherever_authentication_is`.

## 2 · MÉDIA — barra final rebaixa a permissão exigida

`route_requirement` casa a rota por comparação de string. Com barra final, o
caminho deixa de casar com a regra específica e cai no ramo genérico:

| Caminho | Permissão exigida |
|---|---|
| `…/intents/{id}/refund` | `checkout.payment.refund` |
| `…/intents/{id}/refund/` | `checkout.payment` |
| `…/intents/{id}/cancel/` | `checkout.payment` |

Ou seja: uma barra trocaria a autoridade de **devolver dinheiro** pela de criar
parcela.

**Por que continua em aberto.** Hoje não é alcançável. A autorização roda como
dependência, e o roteador responde `307` para a barra final **antes** de qualquer
dependência executar. O que protege não é a regra — é o roteamento.

A correção combinada é mover a autorização para as próprias rotas, eliminando a
comparação de string. Isso é contrato próprio, não remendo: um `rstrip` aqui
esconderia a fragilidade em vez de removê-la, e deixaria a próxima regra sujeita
ao mesmo erro.

**Enquanto isso**, a suposição que mantém o achado inofensivo está pinada por
teste: `test_permission_mapping_downgrades_on_a_trailing_slash_and_routing_is_what_saves_it`
falha se alguém desligar o redirecionamento do roteador ou registrar uma rota com
barra final — as duas formas de tornar o rebaixamento real.

## 3 · MÉDIA — o compose publicava tudo na rede local

Postgres e API subiam em `0.0.0.0`, alcançáveis por qualquer máquina do mesmo
Wi-Fi. Somado ao achado 1, isso significava: uma API que aceita `X-User-ID` sem
token, exposta à rede.

**Correção.** As duas portas passaram a ser publicadas no loopback por padrão,
com variável `BIND_HOST` documentada em `.env.example`. Abrir continua possível —
é necessidade real testar um PDV de outro dispositivo —, mas deixou de ser o
padrão e passou a ser um ato explícito.

**Verificado:** `docker ps` mostra `127.0.0.1:…->…` nas duas portas.

## 4 · BAIXA — aviso do dev server

`npm audit --omit=dev` reporta **zero** vulnerabilidades: o pacote afetado entra
por `vite`/`esbuild` e **não faz parte do bundle publicado**. O aviso vale para o
servidor de desenvolvimento, e a correção completa exige subir `vite` de major,
o que é mudança quebrável e não pertence a uma varredura de segurança.

**Mitigação aplicada agora:** o dev server estava configurado com
`host: '0.0.0.0'`, o que é justamente o que torna o aviso alcançável a partir da
rede. Passou a usar o loopback por padrão, com a mesma variável `BIND_HOST` do
compose.

**Fica para decisão à parte:** atualizar `vite` de major.

## 5 · BAIXA — `assert` no caminho de segurança

`assert` desaparece com `python -O`. O repositório tem 49 ocorrências, e a
análise separou duas situações:

- **núcleo de segurança** (`core/access.py`, `core/context.py`): cinco
  ocorrências, todas estreitando tipo depois de chamadas que já levantam. Sob
  `-O` produziriam `500` no meio de uma decisão de autorização, não um bypass;
- **endpoints**: as demais, no padrão `assert actor is not None` logo após
  `require_platform_role`, que levanta sozinha. Ruído de tipagem, não controle.

O serviço **não** roda com `-O` hoje (`uvicorn` sem otimização), o que confirma a
severidade baixa. O risco real é futuro e silencioso: basta alguém ligar a
otimização.

**Correção.** As cinco do núcleo viraram recusa explícita — `403` quando a
identidade não resolve, `400` quando falta o tenant. As dos endpoints ficaram
como estão, de propósito: reescrever 44 narrowings de tipo adicionaria ruído sem
fechar risco. A classe está travada por
`test_the_security_core_does_not_lean_on_assert`, que lê a AST do núcleo e falha
se um `assert` voltar a aparecer ali.

## 6 · BAIXA — `float` na escrita de um `Numeric(14,4)`

`inventory_service` montava `Decimal(str(quantity))` com cuidado e convertia para
`float` na hora de enviar ao banco. É o único `float` do repositório que
**escreve** saldo; os demais são serialização de projeção para leitura.

**Correção.** O `Decimal` vai direto ao driver, que o adapta nativamente para
`numeric`.

---

## Observações fora do relatório

**A rota `/intents/{id}/query` cai no ramo genérico de permissão.** Diferente do
achado 2, isto não é barra final: a rota simplesmente nunca ganhou mapa próprio e
resolve para `checkout.payment`. Consultar o provider mantendo a reserva é ação
de recuperação, e merece decidir-se qual autoridade ela exige — provavelmente a
mesma de cancelar. Fica junto do contrato do achado 2, que é onde o mapa de
permissões será redesenhado. *(A rota `/refund` do ADR-030 já nasceu com
mapeamento explícito.)*

**Portas e `AUTH_MODE` juntos.** Os achados 1, 3 e 4 pareciam três coisas e eram
uma: a superfície de desenvolvimento inteira — banco, API sem autenticação e
interface — publicada na rede local. Corrigidos juntos, o que resta exposto é
apenas o loopback.

**Isolamento das tabelas de pagamento — auditado agora.** Nenhuma tabela de dados
de tenant está sem RLS. As de pagamento, incluindo
`payment_settlement_divergences` e as duas criadas pelo ADR-030, têm
`ROW LEVEL SECURITY` **e** `FORCE`, ou seja, a política vale inclusive para o
dono da tabela. As 22 tabelas sem RLS são todas da camada Owner — planos,
permissões, catálogo de capabilities, usuários e identidades — que não são dados
de tenant e por isso não têm coluna de escopo. Coerente com o
[ADR-029](../architecture/adr-029-module-boundaries-and-owner-layer.md).

## O que esta revisão não fez

- não redesenhou o mapa de permissões (achado 2), que tem contrato próprio;
- não atualizou `vite` de major (achado 4);
- não auditou dependências do backend, superfície de deploy na Render/Vercel, nem
  configuração do Supabase — nada disso estava no relatório original;
- não é teste de intrusão. O que existe aqui é leitura de código e verificação
  contra a pilha local.
