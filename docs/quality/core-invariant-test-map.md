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

## Regra do gate

Uma mudança que altera estado, isolamento ou cálculo financeiro deve primeiro
atualizar esta matriz e adicionar/ajustar o teste que demonstra a nova regra. O
teste de interface não substitui o teste de domínio/backend para invariantes de
segurança ou dinheiro.
