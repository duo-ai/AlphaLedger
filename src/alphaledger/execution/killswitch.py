"""Evaluate equity stops and report observable emergency-flatten progress.

This module performs no broker submission and retains no state. It recovers
each caller-materialized closing intent through the existing lifecycle and
checks positions independently so a clean order result is never presented as
guaranteed liquidation.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Protocol

from alphaledger.domain import money, require_utc
from alphaledger.execution import lifecycle
from alphaledger.execution.lifecycle import BrokerOrderLookup, RecoveryAction
from alphaledger.execution.orders import BrokerPosition
from alphaledger.execution.reconcile import KnownOrder, OrderReconciliation

__all__ = [
    "DAILY_LOSS_STOP_REASON",
    "PEAK_TO_VALLEY_KILL_SWITCH_REASON",
    "POSITION_STILL_OPEN_REASON",
    "EquityState",
    "FlattenReport",
    "KillSwitchDecision",
    "KnownOrder",
    "OrderReconciliation",
    "PositionSource",
    "evaluate_kill_switch",
    "flatten",
]

DAILY_LOSS_STOP_REASON: Final[str] = "daily_loss_stop_breached"
PEAK_TO_VALLEY_KILL_SWITCH_REASON: Final[str] = "peak_to_valley_kill_switch_triggered"
POSITION_STILL_OPEN_REASON: Final[str] = "position_still_open"


@dataclass(frozen=True, slots=True)
class EquityState:
    """Materialized account equity facts at one UTC instant."""

    session_start_equity: Decimal
    peak_equity: Decimal
    current_equity: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        session_start_equity = money(
            self.session_start_equity,
            "session_start_equity",
        )
        peak_equity = money(self.peak_equity, "peak_equity")
        current_equity = money(self.current_equity, "current_equity")
        if session_start_equity <= 0:
            raise ValueError(
                f"session_start_equity must be strictly positive; got {session_start_equity}"
            )
        if peak_equity <= 0:
            raise ValueError(f"peak_equity must be strictly positive; got {peak_equity}")
        object.__setattr__(self, "session_start_equity", session_start_equity)
        object.__setattr__(self, "peak_equity", peak_equity)
        object.__setattr__(self, "current_equity", current_equity)
        object.__setattr__(self, "as_of", require_utc(self.as_of, "as_of"))


@dataclass(frozen=True, slots=True)
class KillSwitchDecision:
    """Deterministic stop result for one equity reading."""

    triggered: bool
    reasons: tuple[str, ...]


def evaluate_kill_switch(
    equity: EquityState,
    *,
    daily_loss_stop_fraction: Decimal,
    peak_to_valley_fraction: Decimal,
) -> KillSwitchDecision:
    """Trip either configured equity stop at or beyond its exact boundary."""
    daily_threshold = _threshold_fraction(
        daily_loss_stop_fraction,
        "daily_loss_stop_fraction",
    )
    peak_threshold = _threshold_fraction(
        peak_to_valley_fraction,
        "peak_to_valley_fraction",
    )
    daily_loss_fraction = (
        equity.session_start_equity - equity.current_equity
    ) / equity.session_start_equity
    peak_to_valley_observed = (equity.peak_equity - equity.current_equity) / equity.peak_equity

    reasons: list[str] = []
    if daily_loss_fraction >= daily_threshold:
        reasons.append(DAILY_LOSS_STOP_REASON)
    if peak_to_valley_observed >= peak_threshold:
        reasons.append(PEAK_TO_VALLEY_KILL_SWITCH_REASON)
    return KillSwitchDecision(triggered=bool(reasons), reasons=tuple(reasons))


class PositionSource(Protocol):
    """Minimal broker boundary needed to confirm covered symbols are flat."""

    def positions(self) -> Sequence[BrokerPosition]:
        """Return every position the broker currently reports as held."""
        ...


@dataclass(frozen=True, slots=True)
class FlattenReport:
    """Observable per-target recovery and independent position evidence."""

    targets: tuple[OrderReconciliation, ...]
    still_open_symbols: frozenset[str]
    blocks_new_entries: bool
    reasons: tuple[str, ...]


def flatten(
    order_lookup: BrokerOrderLookup,
    positions: PositionSource,
    targets: Sequence[KnownOrder],
) -> FlattenReport:
    """Recover closing intents and conservatively report remaining exposure."""
    reasons: list[str] = []
    observed_reasons: set[str] = set()

    def add_reason(reason: str | None) -> None:
        if reason is not None and reason not in observed_reasons:
            observed_reasons.add(reason)
            reasons.append(reason)

    reconciliations: list[OrderReconciliation] = []
    for target in targets:
        decision = lifecycle.recover_submission(
            order_lookup,
            target.client_order_id,
            recorded_attempt=target.recorded_attempt,
            local_state=target.local_state,
        )
        reconciliations.append(
            OrderReconciliation(
                client_order_id=target.client_order_id,
                decision=decision,
            )
        )
        if decision.action is RecoveryAction.BLOCK:
            add_reason(decision.reason)

    covered_symbols = frozenset(symbol for target in targets for symbol in target.covered_symbols)
    try:
        position_snapshot = tuple(positions.positions())
    except Exception:
        still_open_symbols = covered_symbols
        add_reason(lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON)
    else:
        held_symbols = frozenset(
            position.symbol for position in position_snapshot if position.signed_quantity != 0
        )
        still_open_symbols = covered_symbols & held_symbols
        if still_open_symbols:
            add_reason(POSITION_STILL_OPEN_REASON)

    return FlattenReport(
        targets=tuple(reconciliations),
        still_open_symbols=still_open_symbols,
        blocks_new_entries=bool(reasons),
        reasons=tuple(reasons),
    )


def _threshold_fraction(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal; got {type(value).__name__}")
    if not value.is_finite() or not Decimal(0) < value <= Decimal(1):
        raise ValueError(f"{field} must be above zero and no greater than one; got {value}")
    return value
