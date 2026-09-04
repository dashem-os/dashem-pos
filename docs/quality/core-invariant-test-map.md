# Matriz de proteção dos invariantes — baseline S0

| Invariante | Proteção automatizada |
|---|---|
| JWT obrigatório, expiração e modo de teste | `test_auth_rbac_foundation.py` |
| Membership/store impedem acesso cruzado | `test_auth_rbac_foundation.py` |
| Platform membership não implica tenant access | `test_auth_rbac_foundation.py` |
| RLS forçada em tabelas tenant-aware | `test_capability_mesh.py` |
| Vizinho não lê tenant/store alheios | `test_capability_mesh.py` |
| SaleItem herda fronteira da Sale | `test_capability_mesh.py` |
| Provisionamento Owner é atômico e auditado | `test_owner_console.py` |
| OWNER-P0 persiste nicho, plano, quotas, entitlements e administrador em uma jornada | `test_owner_p0.py` |
| Governança Owner separa entitlement, configuração, reserva e medição; multiatividade não possui primária implícita | `test_owner_governance_sprint0.py` |
| Retail/Beauty nunca recebem Mesas/KDS; Food recebe somente por add-on | `test_owner_p0.py` |
| Owner não recebe lista de operadores do tenant | `test_owner_p0.py` |
| Mutação do Control exige AAL2 | `test_owner_console.py` |
| Capability resolve dependências e auditoria | `test_capability_mesh.py`, `test_owner_console.py` |
| Outbox, correlação e idempotência concorrente | `test_pos0_gates.py` |
| Estoque mantém ledger/saldo sob concorrência | `test_pos1_gates.py`, `test_pos3_gates.py` |
| Backend decide preço e snapshot do item | `test_pos2_gates.py` |
| Checkout concorrente não duplica efeitos | `test_pos2_gates.py` |
| Pagamento, caixa e fiscal respeitam gates | `test_pos4_gates.py` |
| Item, desconto, cancelamento e split | `test_pos5_operational_flows.py` |
| Rotas críticas frontend/FastAPI permanecem alinhadas | `test_frontend_api_contract.py` |
| Login, rota, contexto único, carrinho, split e caixa | `frontend/tests/*.test.ts` |
| Rota do backend que nenhuma tela alcança não cresce; função do cliente sem consumidor não cresce | `test_surface_reachability.py` |
| Guard de timestamp conhece todo campo de data do contrato, não só os sufixos `_at`/`_until` | `test_frontend_api_contract.py`, `frontend/tests/api_timestamps.test.ts` |

## Lacunas bloqueadoras reabertas em 25/08/2026

Os testes regulares de frontend continuam majoritariamente testes de fonte e
regras isoladas. A OA-4 acrescenta uma suíte Chromium com banco e API isolados;
ela passou localmente, mas ainda precisa produzir execução verde no CI e
evidência contra o deploy antes da promoção.

| Invariante exigido pelo ADR-024 | Proteção obrigatória | Estado |
|---|---|---|
| `/login` é exclusivamente gerencial e envia gestor a `/manage` | teste de rota + Playwright | superfície pública aprovada localmente; login real no deploy pendente |
| `/operate` não oferece credencial sem terminal autorizado | backend negativo + Playwright | aprovado localmente; deploy pendente |
| Gestão nunca recebe PIN definitivo | contrato API + backend + frontend | presente |
| colaborador define o PIN por ativação única | backend + Playwright | aprovado localmente; CI/deploy pendentes |
| código + PIN herdam contexto do terminal | backend cruzado + Playwright | aprovado localmente; CI/deploy pendentes |
| `/pos` não abre seletor organizacional após autenticação | Playwright | aprovado localmente; deploy pendente |
| gestor sem assunção não executa mutação humana do POS | backend negativo + Playwright | backend aprovado; jornada local parcial; deploy pendente |
| saída troca a pessoa sem desautorizar o terminal | backend + Playwright | aprovado localmente; CI/deploy pendentes |
| revogação/expiração interrompem JWT ainda válido | `test_operational_pin_identity.py` + Playwright | pausa aprovada localmente; expiração no backend; deploy pendente |
| operador não alcança `/manage` | backend + Playwright | aprovado localmente; deploy pendente |
| contraste, foco e toque cumprem aceite | axe/medição + inspeção no navegador | medição local aprovada; inspeção no deploy pendente |
| jornada completa gera evidência sanitizada | CI/Playwright + runbook | suíte e runbook presentes; CI/deploy pendentes |

Nenhuma linha marcada como ausente pode ser convertida em “verde” por inspeção
de string no código-fonte.

## Regra do gate

Uma mudança que altera estado, isolamento ou cálculo financeiro deve primeiro
atualizar esta matriz e adicionar/ajustar o teste que demonstra a nova regra. O
teste de interface não substitui o teste de domínio/backend para invariantes de
segurança ou dinheiro.
