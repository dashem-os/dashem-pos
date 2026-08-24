from collections.abc import Iterable

from app.modules.capabilities.contracts import CapabilityContract, CapabilityScope


def _contract(key: str, name: str, scope: CapabilityScope, description: str, *requires: str) -> CapabilityContract:
    return CapabilityContract(key, name, "1.0.0", scope, description, tuple(requires))


# This registry is executable architecture, not tenant data. Commercial
# entitlements and per-site configuration live in PostgreSQL.
CAPABILITY_REGISTRY: dict[str, CapabilityContract] = {
    item.key: item for item in (
        _contract("catalog", "Catálogo", CapabilityScope.TENANT, "Produtos, serviços, preços e categorias."),
        _contract("inventory", "Estoque", CapabilityScope.STORE, "Saldos e razão de movimentações por site.", "catalog"),
        _contract("customer", "Clientes", CapabilityScope.TENANT, "Cadastro e contexto comercial de clientes."),
        _contract("cash_management", "Gestão de caixa", CapabilityScope.STORE, "Sessões, sangrias, suprimentos e conferência."),
        _contract("payments", "Pagamentos", CapabilityScope.STORE, "Orquestração de recebimentos e split."),
        _contract("barcode_scanning", "Leitura de código de barras", CapabilityScope.TERMINAL, "Entrada rápida por EAN, SKU ou leitor.", "catalog"),
        _contract("quotes", "Orçamentos", CapabilityScope.TENANT, "Propostas comerciais convertíveis em venda.", "catalog", "customer"),
        _contract("modifiers", "Modificadores", CapabilityScope.TENANT, "Adicionais e escolhas aplicáveis a itens.", "catalog"),
        _contract("combos", "Combos", CapabilityScope.TENANT, "Composição comercial de produtos e opções.", "catalog", "modifiers"),
        _contract("kitchen_routing", "Roteamento de cozinha", CapabilityScope.STORE, "Direcionamento de produção por estação.", "catalog"),
        _contract("delivery_orders", "Pedidos de delivery", CapabilityScope.STORE, "Entrada e acompanhamento de canais de entrega.", "catalog", "customer"),
        _contract("counter_order", "Pedido de balcão", CapabilityScope.STORE, "Fluxo ágil de pedido e retirada.", "catalog", "payments"),
        _contract("table_service", "Mesas e comandas", CapabilityScope.STORE, "Atendimento de mesa e comandas individuais com ciclo operacional rastreável.", "catalog"),
        _contract("weighted_products", "Produtos pesáveis", CapabilityScope.STORE, "Venda por peso e leitura de etiqueta de balança.", "catalog"),
        _contract("high_speed_checkout", "Checkout de alta velocidade", CapabilityScope.TERMINAL, "Fluxo otimizado para grande volume.", "barcode_scanning", "payments"),
        _contract("supervisor_override", "Autorização de supervisor", CapabilityScope.STORE, "Elevação auditada para operações sensíveis."),
        _contract("customer_display", "Display do cliente", CapabilityScope.TERMINAL, "Espelhamento seguro da venda para o consumidor."),
        _contract("self_checkout", "Autoatendimento", CapabilityScope.TERMINAL, "Fluxo de compra sem operador dedicado.", "barcode_scanning", "payments"),
        _contract("serial_tracking", "Rastreio por série", CapabilityScope.STORE, "Controle unitário por número serial.", "inventory"),
        _contract("batch_tracking", "Rastreio por lote", CapabilityScope.STORE, "Controle de lote, validade e origem.", "inventory"),
        _contract("multi_price", "Múltiplas tabelas de preço", CapabilityScope.TENANT, "Preços por canal, site ou segmento.", "catalog"),
        _contract("pix", "PIX", CapabilityScope.STORE, "Recebimento e conciliação PIX.", "payments"),
        _contract("tef", "TEF", CapabilityScope.TERMINAL, "Integração de transferência eletrônica de fundos.", "payments"),
        _contract("fiscal_nfce", "NFC-e", CapabilityScope.STORE, "Emissão fiscal de consumidor.", "payments"),
        _contract("fiscal_nfe", "NF-e", CapabilityScope.STORE, "Emissão fiscal de mercadorias.", "payments"),
        _contract("receivables", "Crediário e recebíveis", CapabilityScope.TENANT, "Política de crédito, títulos, cobrança e renegociação.", "customer", "payments"),
    )
}


# A contract may be designed before its executable module exists. Commercial
# activation is allowed only for this audited list; planned contracts remain
# visible to architecture tooling but cannot be sold as working software.
IMPLEMENTED_CAPABILITIES = frozenset({
    "catalog", "inventory", "customer", "cash_management", "payments",
    "barcode_scanning", "modifiers", "combos", "kitchen_routing",
    "delivery_orders", "counter_order", "table_service", "high_speed_checkout",
    "supervisor_override", "tef", "fiscal_nfce", "receivables",
})


def resolve_dependencies(keys: Iterable[str]) -> tuple[str, ...]:
    requested = set(keys)
    resolved: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key not in CAPABILITY_REGISTRY:
            raise KeyError(f"Unknown capability: {key}")
        if key in visiting:
            raise ValueError(f"Capability dependency cycle detected at {key}")
        if key in visited:
            return
        visiting.add(key)
        for dependency in CAPABILITY_REGISTRY[key].requires:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)
        resolved.append(key)

    for key in sorted(requested):
        visit(key)
    return tuple(resolved)
