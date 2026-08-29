"""Pure order identity, lifecycle, and duplicate-submission decisions.

This module performs no broker I/O and has no submit operation. Broker truth is
observed only through the lookup protocol, so an ambiguous result can be
resolved without creating a second intent.
"""

import base64
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol

from alphaledger.execution.orders import BrokerOrder, BrokerOrderStatus, canonical_bytes

__all__ = [
    "BROKER_TRUTH_UNAVAILABLE_REASON",
    "UNKNOWN_ORDER_STATE_REASON",
    "BrokerOrderLookup",
    "OrderEvent",
    "OrderState",
    "SubmissionAction",
    "SubmissionDecision",
    "blocks_new_entries",
    "client_order_id",
    "decide_submission",
    "is_broker_terminal",
    "is_lifecycle_terminal",
    "resolve_ambiguous_submit",
    "transition",
]

BROKER_TRUTH_UNAVAILABLE_REASON: Final = "broker_truth_unavailable"
UNKNOWN_ORDER_STATE_REASON: Final = "unknown_order_state"


class OrderState(StrEnum):
    """The complete per-order lifecycle vocabulary."""

    PROPOSED = "proposed"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    WORKING = "working"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    EXPIRED = "expired"
    CLOSING = "closing"
    RECONCILED = "reconciled"


class OrderEvent(StrEnum):
    """Observed events, named for the state each event attempts to enter."""

    REJECTED = "rejected"
    SUBMITTED = "submitted"
    WORKING = "working"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    EXPIRED = "expired"
    CLOSING = "closing"
    RECONCILED = "reconciled"


class SubmissionAction(StrEnum):
    """The only three safe decisions before a caller submits an intent."""

    SUBMIT = "submit"
    ADOPT_EXISTING = "adopt_existing"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class SubmissionDecision:
    """A duplicate guard result with any adopted state or no-trade reason."""

    action: SubmissionAction
    state: OrderState | None
    reason: str | None


class BrokerOrderLookup(Protocol):
    """Minimal broker boundary needed to recover one stable intent."""

    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        """Return broker truth for an id, or ``None`` when it does not exist."""
        ...


_TRANSITIONS: Final = MappingProxyType(
    {
        (OrderState.PROPOSED, OrderEvent.SUBMITTED): OrderState.SUBMITTED,
        (OrderState.PROPOSED, OrderEvent.REJECTED): OrderState.REJECTED,
        (OrderState.SUBMITTED, OrderEvent.WORKING): OrderState.WORKING,
        (OrderState.SUBMITTED, OrderEvent.PARTIAL): OrderState.PARTIAL,
        (OrderState.SUBMITTED, OrderEvent.FILLED): OrderState.FILLED,
        (OrderState.SUBMITTED, OrderEvent.REJECTED): OrderState.REJECTED,
        (OrderState.SUBMITTED, OrderEvent.CANCELED): OrderState.CANCELED,
        (OrderState.SUBMITTED, OrderEvent.EXPIRED): OrderState.EXPIRED,
        (OrderState.WORKING, OrderEvent.PARTIAL): OrderState.PARTIAL,
        (OrderState.WORKING, OrderEvent.FILLED): OrderState.FILLED,
        (OrderState.WORKING, OrderEvent.CANCEL_PENDING): OrderState.CANCEL_PENDING,
        (OrderState.WORKING, OrderEvent.CANCELED): OrderState.CANCELED,
        (OrderState.WORKING, OrderEvent.EXPIRED): OrderState.EXPIRED,
        (OrderState.PARTIAL, OrderEvent.FILLED): OrderState.FILLED,
        (OrderState.PARTIAL, OrderEvent.CANCEL_PENDING): OrderState.CANCEL_PENDING,
        (OrderState.PARTIAL, OrderEvent.CANCELED): OrderState.CANCELED,
        (OrderState.PARTIAL, OrderEvent.EXPIRED): OrderState.EXPIRED,
        (OrderState.CANCEL_PENDING, OrderEvent.CANCELED): OrderState.CANCELED,
        (OrderState.CANCEL_PENDING, OrderEvent.PARTIAL): OrderState.PARTIAL,
        (OrderState.CANCEL_PENDING, OrderEvent.FILLED): OrderState.FILLED,
        (OrderState.FILLED, OrderEvent.CLOSING): OrderState.CLOSING,
        (OrderState.FILLED, OrderEvent.RECONCILED): OrderState.RECONCILED,
        (OrderState.REJECTED, OrderEvent.RECONCILED): OrderState.RECONCILED,
        (OrderState.CANCELED, OrderEvent.RECONCILED): OrderState.RECONCILED,
        (OrderState.EXPIRED, OrderEvent.RECONCILED): OrderState.RECONCILED,
        (OrderState.CLOSING, OrderEvent.RECONCILED): OrderState.RECONCILED,
    }
)

_BROKER_TERMINAL: Final = frozenset(
    {
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.CANCELED,
        OrderState.EXPIRED,
    }
)

_BROKER_STATE: Final = MappingProxyType(
    {
        BrokerOrderStatus.ACCEPTED: OrderState.SUBMITTED,
        BrokerOrderStatus.PENDING_NEW: OrderState.SUBMITTED,
        BrokerOrderStatus.ACCEPTED_FOR_BIDDING: OrderState.SUBMITTED,
        BrokerOrderStatus.PENDING_REVIEW: OrderState.SUBMITTED,
        BrokerOrderStatus.NEW: OrderState.WORKING,
        BrokerOrderStatus.PARTIALLY_FILLED: OrderState.PARTIAL,
        BrokerOrderStatus.FILLED: OrderState.FILLED,
        BrokerOrderStatus.PENDING_CANCEL: OrderState.CANCEL_PENDING,
        BrokerOrderStatus.CANCELED: OrderState.CANCELED,
        BrokerOrderStatus.EXPIRED: OrderState.EXPIRED,
        BrokerOrderStatus.REJECTED: OrderState.REJECTED,
    }
)


def client_order_id(plan_id: str, quantity: int, limit_price: Decimal) -> str:
    """Derive one stable id; ``plan_id`` must be unique per plan instance."""
    if not isinstance(plan_id, str) or not plan_id:
        raise ValueError("plan_id must be a non-empty string")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    if not isinstance(limit_price, Decimal) or not limit_price.is_finite():
        raise ValueError("limit_price must be a finite Decimal")

    intent = canonical_bytes(
        {
            "limit_price": limit_price,
            "plan_id": plan_id,
            "quantity": quantity,
        }
    )
    digest = hashlib.sha256(intent).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"al-{encoded}"


def transition(current: OrderState, event: OrderEvent) -> OrderState:
    """Apply one declared transition or raise without changing state."""
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError:
        target = OrderState(event.value)
        raise ValueError(
            f"illegal order transition from '{current.value}' to '{target.value}' "
            f"on event '{event.value}'"
        ) from None


def is_broker_terminal(state: OrderState) -> bool:
    """Return whether the broker will send no further order update."""
    return state in _BROKER_TERMINAL


def is_lifecycle_terminal(state: OrderState) -> bool:
    """Return whether all post-broker reconciliation is complete."""
    return state is OrderState.RECONCILED


def blocks_new_entries(state: OrderState | None) -> bool:
    """Fail closed until the prior lifecycle is known to be reconciled."""
    return state is not OrderState.RECONCILED


def resolve_ambiguous_submit(
    lookup: BrokerOrderLookup,
    client_order_id: str,
) -> OrderState | None:
    """Query once by stable id; any absent or unusable truth remains unknown."""
    try:
        order = lookup.order_by_client_id(client_order_id)
    except Exception:
        return None
    return _known_state(order, client_order_id)


def decide_submission(
    lookup: BrokerOrderLookup,
    client_order_id: str,
) -> SubmissionDecision:
    """Permit, adopt, or block an intent after exactly one identity lookup."""
    try:
        order = lookup.order_by_client_id(client_order_id)
    except Exception:
        return SubmissionDecision(
            action=SubmissionAction.BLOCK,
            state=None,
            reason=BROKER_TRUTH_UNAVAILABLE_REASON,
        )

    if order is None:
        return SubmissionDecision(
            action=SubmissionAction.SUBMIT,
            state=None,
            reason=None,
        )

    state = _known_state(order, client_order_id)
    if state is None:
        return SubmissionDecision(
            action=SubmissionAction.BLOCK,
            state=None,
            reason=UNKNOWN_ORDER_STATE_REASON,
        )
    return SubmissionDecision(
        action=SubmissionAction.ADOPT_EXISTING,
        state=state,
        reason=None,
    )


def _known_state(order: BrokerOrder | None, expected_client_order_id: str) -> OrderState | None:
    if order is None or order.client_order_id != expected_client_order_id:
        return None
    return _BROKER_STATE.get(order.status)
