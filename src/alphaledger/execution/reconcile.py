"""Aggregate broker truth into one fail-closed reconciliation report.

The function in this module performs no broker I/O directly and retains no
state between calls. Injected boundaries provide fresh snapshots, which makes
the same operation suitable for startup recovery and later scheduled cycles.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from alphaledger.execution import lifecycle
from alphaledger.execution.lifecycle import (
    BrokerOrderLookup,
    OrderState,
    RecordedSubmissionAttempt,
    RecoveryDecision,
)
from alphaledger.execution.orders import BrokerActivity, BrokerOrder, BrokerPosition

__all__ = [
    "ORDER_NOT_RECONCILED_REASON",
    "UNEXPLAINED_ORDER_REASON",
    "UNEXPLAINED_POSITION_REASON",
    "BrokerTruthSource",
    "KnownOrder",
    "OrderReconciliation",
    "ReconciliationReport",
    "UnexplainedOrder",
    "UnexplainedPosition",
    "reconcile",
]

ORDER_NOT_RECONCILED_REASON: Final[str] = "order_not_reconciled"
UNEXPLAINED_ORDER_REASON: Final[str] = "unexplained_order"
UNEXPLAINED_POSITION_REASON: Final[str] = "unexplained_position"


class BrokerTruthSource(Protocol):
    """Broker snapshots needed to account for currently exposed state."""

    def open_orders(self) -> Sequence[BrokerOrder]:
        """Return every order the broker currently reports as open."""
        ...

    def positions(self) -> Sequence[BrokerPosition]:
        """Return every position the broker currently reports as held."""
        ...

    def activities(self) -> Sequence[BrokerActivity]:
        """Return enough activity history to attribute every held position."""
        ...


@dataclass(frozen=True, slots=True)
class KnownOrder:
    """Materialized local evidence needed to recover one stable intent."""

    client_order_id: str
    recorded_attempt: RecordedSubmissionAttempt | None
    local_state: OrderState | None
    covered_symbols: frozenset[str]


@dataclass(frozen=True, slots=True)
class OrderReconciliation:
    """Broker-backed recovery decision for one known order."""

    client_order_id: str
    decision: RecoveryDecision


@dataclass(frozen=True, slots=True)
class UnexplainedOrder:
    """Open broker order with no matching local intent."""

    order: BrokerOrder
    reason: str


@dataclass(frozen=True, slots=True)
class UnexplainedPosition:
    """Broker position without symbol and activity attribution."""

    position: BrokerPosition
    reason: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Complete immutable result of one broker-truth snapshot."""

    orders: tuple[OrderReconciliation, ...]
    unexplained_orders: tuple[UnexplainedOrder, ...]
    unexplained_positions: tuple[UnexplainedPosition, ...]
    blocks_new_entries: bool
    reasons: tuple[str, ...]


def reconcile(
    order_lookup: BrokerOrderLookup,
    truth: BrokerTruthSource,
    known_orders: Sequence[KnownOrder],
) -> ReconciliationReport:
    """Reconcile all known and broker-reported state without retaining state."""
    reasons: list[str] = []
    observed_reasons: set[str] = set()

    def add_reason(reason: str | None) -> None:
        if reason is not None and reason not in observed_reasons:
            observed_reasons.add(reason)
            reasons.append(reason)

    order_reconciliations: list[OrderReconciliation] = []
    for known_order in known_orders:
        decision = lifecycle.recover_submission(
            order_lookup,
            known_order.client_order_id,
            recorded_attempt=known_order.recorded_attempt,
            local_state=known_order.local_state,
        )
        order_reconciliations.append(
            OrderReconciliation(
                client_order_id=known_order.client_order_id,
                decision=decision,
            )
        )
        if decision.action is lifecycle.RecoveryAction.BLOCK:
            add_reason(decision.reason)
        elif lifecycle.blocks_new_entries(decision.state):
            add_reason(ORDER_NOT_RECONCILED_REASON)

    known_client_order_ids = frozenset(order.client_order_id for order in known_orders)
    open_orders, open_orders_available = _read_snapshot(truth.open_orders)
    unexplained_orders: tuple[UnexplainedOrder, ...] = ()
    if not open_orders_available:
        add_reason(lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON)
    else:
        unexplained_orders = tuple(
            UnexplainedOrder(order=order, reason=UNEXPLAINED_ORDER_REASON)
            for order in open_orders
            if order.client_order_id not in known_client_order_ids
        )
        if unexplained_orders:
            add_reason(UNEXPLAINED_ORDER_REASON)

    positions, positions_available = _read_snapshot(truth.positions)
    if not positions_available:
        add_reason(lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON)

    activities, activities_available = _read_snapshot(truth.activities)
    if not activities_available:
        add_reason(lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON)

    known_broker_ids, broker_identities_available = _known_broker_ids(
        order_lookup,
        known_orders,
    )
    if not broker_identities_available:
        add_reason(lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON)

    covered_symbols = frozenset(
        symbol for known_order in known_orders for symbol in known_order.covered_symbols
    )
    unexplained_positions: tuple[UnexplainedPosition, ...] = ()
    if positions_available:
        unexplained_positions = tuple(
            UnexplainedPosition(position=position, reason=UNEXPLAINED_POSITION_REASON)
            for position in positions
            if _position_is_unexplained(
                position,
                covered_symbols=covered_symbols,
                known_broker_ids=known_broker_ids,
                activities=activities,
                attribution_available=activities_available and broker_identities_available,
            )
        )
        if unexplained_positions:
            add_reason(UNEXPLAINED_POSITION_REASON)

    return ReconciliationReport(
        orders=tuple(order_reconciliations),
        unexplained_orders=unexplained_orders,
        unexplained_positions=unexplained_positions,
        blocks_new_entries=bool(reasons),
        reasons=tuple(reasons),
    )


def _read_snapshot[SnapshotItem](
    loader: Callable[[], Sequence[SnapshotItem]],
) -> tuple[tuple[SnapshotItem, ...], bool]:
    try:
        return tuple(loader()), True
    except Exception:
        return (), False


def _known_broker_ids(
    order_lookup: BrokerOrderLookup,
    known_orders: Sequence[KnownOrder],
) -> tuple[frozenset[str], bool]:
    broker_ids: set[str] = set()
    all_available = True
    for known_order in known_orders:
        try:
            order = order_lookup.order_by_client_id(known_order.client_order_id)
        except Exception:
            all_available = False
            continue
        if order is not None and order.client_order_id == known_order.client_order_id:
            broker_ids.add(order.broker_id)
    return frozenset(broker_ids), all_available


def _position_is_unexplained(
    position: BrokerPosition,
    *,
    covered_symbols: frozenset[str],
    known_broker_ids: frozenset[str],
    activities: Sequence[BrokerActivity],
    attribution_available: bool,
) -> bool:
    if position.symbol not in covered_symbols:
        return True
    if not attribution_available:
        return False
    return not any(
        activity.symbol == position.symbol and activity.order_id in known_broker_ids
        for activity in activities
    )
