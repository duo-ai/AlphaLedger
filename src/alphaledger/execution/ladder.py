"""Pure bounded entry-ladder decisions over caller-supplied prices.

The module performs no I/O and retains no state between calls. Each valid rung
is rebuilt as a new deterministic order intent and receives a fresh risk
approval; exhausted ladders return reasons without deriving an intent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from alphaledger.config import FrozenConfig
from alphaledger.domain import RiskApproval, StructurePlan, money, require_utc
from alphaledger.execution.lifecycle import client_order_id
from alphaledger.execution.orders import build_mleg_order
from alphaledger.risk.approval import AccountSnapshot, SizingMode, approve

__all__ = [
    "LADDER_STEPS_EXHAUSTED_REASON",
    "LADDER_TIME_BUDGET_EXCEEDED_REASON",
    "LadderBudget",
    "LadderDecision",
    "LadderStep",
    "step_ladder",
]

LADDER_STEPS_EXHAUSTED_REASON: Final = "ladder_steps_exhausted"
LADDER_TIME_BUDGET_EXCEEDED_REASON: Final = "ladder_time_budget_exceeded"


@dataclass(frozen=True, slots=True)
class LadderBudget:
    """Explicit rung and elapsed-time limits for one entry ladder."""

    max_steps: int
    time_budget: timedelta

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_steps, bool)
            or not isinstance(self.max_steps, int)
            or self.max_steps <= 0
        ):
            raise ValueError("max_steps must be a positive integer")
        if not isinstance(self.time_budget, timedelta) or self.time_budget <= timedelta(0):
            raise ValueError("time_budget must be a positive timedelta")


@dataclass(frozen=True, slots=True)
class LadderStep:
    """One rebuilt entry intent and the approval bound to its payload."""

    step_index: int
    limit_price: Decimal
    client_order_id: str
    payload: Mapping[str, object]
    approval: RiskApproval


@dataclass(frozen=True, slots=True)
class LadderDecision:
    """Either one actionable rung or the reasons the ladder is exhausted."""

    step: LadderStep | None
    reasons: tuple[str, ...]


def step_ladder(
    plan: StructurePlan,
    quantity: int,
    price_ladder: Sequence[Decimal],
    step_index: int,
    ladder_started_at: datetime,
    now: datetime,
    budget: LadderBudget,
    snapshot: AccountSnapshot,
    frozen_config: FrozenConfig,
    mode: SizingMode,
    expires_at: datetime,
    max_snapshot_age: timedelta,
) -> LadderDecision:
    """Derive one bounded entry rung or report mechanical exhaustion."""
    current_time = require_utc(now, "now")
    started_at = require_utc(ladder_started_at, "ladder_started_at")
    if started_at > current_time:
        raise ValueError("ladder_started_at must not be after now")
    if isinstance(step_index, bool) or not isinstance(step_index, int) or step_index < 0:
        raise ValueError("step_index must be a non-negative integer")

    prices = _validated_prices(price_ladder, plan.entry_limit_bound, budget.max_steps)

    reasons: list[str] = []
    if current_time - started_at >= budget.time_budget:
        reasons.append(LADDER_TIME_BUDGET_EXCEEDED_REASON)
    if step_index >= len(prices):
        reasons.append(LADDER_STEPS_EXHAUSTED_REASON)
    if reasons:
        return LadderDecision(step=None, reasons=tuple(reasons))

    limit_price = prices[step_index]
    order_id = client_order_id(plan.plan_id, quantity, limit_price)
    payload = build_mleg_order(plan, quantity, limit_price, order_id)
    approval = approve(
        plan,
        payload,
        snapshot,
        frozen_config,
        mode,
        expires_at,
        current_time,
        max_snapshot_age,
    )
    return LadderDecision(
        step=LadderStep(
            step_index=step_index,
            limit_price=limit_price,
            client_order_id=order_id,
            payload=payload,
            approval=approval,
        ),
        reasons=(),
    )


def _validated_prices(
    price_ladder: Sequence[Decimal],
    entry_limit_bound: Decimal,
    max_steps: int,
) -> tuple[Decimal, ...]:
    prices = tuple(price_ladder)
    if not prices:
        raise ValueError("price_ladder must contain at least one rung")
    if len(prices) > max_steps:
        raise ValueError(f"price_ladder length {len(prices)} exceeds budget.max_steps {max_steps}")

    validated: list[Decimal] = []
    for index, value in enumerate(prices):
        if not isinstance(value, Decimal):
            raise ValueError(f"price_ladder[{index}] must be a Decimal")
        normalized = money(value, f"price_ladder[{index}]")
        if normalized != value:
            raise ValueError(
                f"price_ladder[{index}] must use the declared money precision without rounding"
            )
        if validated and value <= validated[-1]:
            raise ValueError("price_ladder must be strictly increasing")
        if value > entry_limit_bound:
            raise ValueError(f"price_ladder[{index}] exceeds plan.entry_limit_bound")
        validated.append(value)
    return tuple(validated)
