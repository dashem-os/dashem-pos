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

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Optional, Protocol
from uuid import UUID


@dataclass(frozen=True)
class ChannelOrderTerms:
    """Financial terms declared by the external channel for a `SALES_CHANNEL` order."""

    order_id: UUID
    payment_origin: Optional[str] = None
    delivery_fee: Optional[Decimal] = None
    channel_discount: Optional[Decimal] = None
    channel_subsidy: Optional[Decimal] = None
    declared_total: Optional[Decimal] = None


@dataclass(frozen=True)
class OrderCoverage:
    """Separate coverage attributed to one order from joint negotiation coverage."""

    order_id: UUID
    order_covered: Decimal = Decimal("0.0000")
    unassigned_covered: Decimal = Decimal("0.0000")
    joint_covered: Decimal = Decimal("0.0000")
    other_orders_amount: Decimal = Decimal("0.0000")
    negotiation_adjustments: Decimal = Decimal("0.0000")

    @property
    def has_any_coverage(self) -> bool:
        return self.order_covered > Decimal("0.0000") or self.joint_covered > Decimal("0.0000")

    def joint_total_with(self, order_total: Decimal) -> Decimal:
        return max(
            Decimal("0.0000"),
            order_total + self.other_orders_amount + self.negotiation_adjustments,
        )


class SettlementHold(Protocol):
    """How much money is settled or reserved on each of these rows."""

    def __call__(self, session, ids: Iterable[UUID]) -> Mapping[UUID, Decimal]:
        ...


class OrderCoverageReader(Protocol):
    """Order-attributed coverage and joint negotiation coverage for each order."""

    def __call__(self, session, order_ids: Iterable[UUID]) -> Mapping[UUID, OrderCoverage]:
        ...


class ChannelOrderReader(Protocol):
    """Channel-level commercial terms mapped to internal `Order` ids."""

    def __call__(self, session, order_ids: Iterable[UUID]) -> Mapping[UUID, ChannelOrderTerms]:
        ...


_on_items: Optional[SettlementHold] = None
_on_orders: Optional[SettlementHold] = None
_on_order_coverage: Optional[OrderCoverageReader] = None
_on_channel_orders: Optional[ChannelOrderReader] = None


def register(
    on_items: SettlementHold,
    on_orders: SettlementHold,
    on_order_coverage: Optional[OrderCoverageReader] = None,
) -> None:
    """Called by the finance module at import time."""
    global _on_items, _on_orders, _on_order_coverage
    _on_items, _on_orders, _on_order_coverage = on_items, on_orders, on_order_coverage


def register_channel_orders(on_channel_orders: ChannelOrderReader) -> None:
    """Called by the channels module at import time."""
    global _on_channel_orders
    _on_channel_orders = on_channel_orders


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
    """Money explicitly attributed to each comanda, its own items included.

    A comanda changing hands is the same question one step up: what was paid
    against it, whether the allocation named the comanda or one of its lines.
    """
    wanted = [order_id for order_id in order_ids if order_id]
    if not wanted:
        return {}
    if _on_orders is None:
        raise RuntimeError(_UNWIRED)
    return _on_orders(session, wanted)


def coverage_on_orders(session, order_ids: Iterable[UUID]) -> Mapping[UUID, OrderCoverage]:
    """Order-attributed coverage and joint negotiation coverage for each order."""
    wanted = [order_id for order_id in order_ids if order_id]
    has_transfer_scope = bool(
        getattr(session, "info", None) and session.info.get("_transfer_scope")
    )
    if not wanted and not has_transfer_scope:
        return {}
    if _on_order_coverage is None:
        if _on_orders is None:
            raise RuntimeError(_UNWIRED)
        held = _on_orders(session, wanted)
        return {
            order_id: OrderCoverage(order_id=order_id, order_covered=amount, joint_covered=amount)
            for order_id, amount in held.items()
        }
    return _on_order_coverage(session, wanted)


def channel_order_terms(session, order_ids: Iterable[UUID]) -> Mapping[UUID, ChannelOrderTerms]:
    """Channel commercial terms for `SALES_CHANNEL` orders."""
    wanted = [order_id for order_id in order_ids if order_id]
    if not wanted:
        return {}
    if _on_channel_orders is None:
        raise RuntimeError(_UNWIRED_CHANNELS)
    return _on_channel_orders(session, wanted)


_UNWIRED = (
    "Nenhum módulo de liquidação registrado: a cobertura financeira não pode ser "
    "presumida como zero."
)
_UNWIRED_CHANNELS = (
    "Nenhum leitor de pedidos de canal registrado: a origem de pagamento e os "
    "termos comerciais do canal não podem ser presumidos."
)
