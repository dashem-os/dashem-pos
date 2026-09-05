"""What the money side promises the operation side about one item.

ADR-029 draws the direction of dependency: `finance` may read `operation`, and
`operation` never reaches up into `finance`. But cancelling an item or reducing
its quantity has to know whether somebody already paid for it, and that answer
only exists in finance.

So operation does not read `payment_allocations`. It asks. Finance registers the
answer here when it is imported, and this module holds no persistence, no
FastAPI and no knowledge of either side — it only names the question.

This is the shape the baseline of `test_module_boundaries.py` already asked for
in prose, next to `transfer -> negotiation`: "regra legítima que deveria ser
perguntada ao módulo de finanças, não lida direto da tabela dele".
"""

from decimal import Decimal
from typing import Iterable, Mapping, Optional, Protocol
from uuid import UUID


class SettlementHold(Protocol):
    """How much money is settled or reserved on each of these rows."""

    def __call__(self, session, ids: Iterable[UUID]) -> Mapping[UUID, Decimal]:
        ...


_on_items: Optional[SettlementHold] = None
_on_orders: Optional[SettlementHold] = None


def register(on_items: SettlementHold, on_orders: SettlementHold) -> None:
    """Called by the finance module at import time."""
    global _on_items, _on_orders
    _on_items, _on_orders = on_items, on_orders


def hold_on_items(session, order_item_ids: Iterable[UUID]) -> Mapping[UUID, Decimal]:
    """Money already resting on each item; absent keys carry nothing.

    An unwired registry raises instead of answering zero. Zero would be a
    permission — it would let a paid item be cancelled — and a missing wire is a
    programming error, not a licence.
    """
    wanted = [item_id for item_id in order_item_ids if item_id]
    if not wanted:
        return {}
    if _on_items is None:
        raise RuntimeError(_UNWIRED)
    return _on_items(session, wanted)


def hold_on_orders(session, order_ids: Iterable[UUID]) -> Mapping[UUID, Decimal]:
    """Money resting on each comanda, its own items included.

    A comanda changing hands is the same question one step up: what was paid
    against it, whether the allocation named the comanda or one of its lines.
    """
    wanted = [order_id for order_id in order_ids if order_id]
    if not wanted:
        return {}
    if _on_orders is None:
        raise RuntimeError(_UNWIRED)
    return _on_orders(session, wanted)


_UNWIRED = (
    "Nenhum módulo de liquidação registrado: a cobertura financeira não pode ser "
    "presumida como zero."
)
