"""Pure sizing gates and approval tokens bound to exact entry intent.

This module performs no I/O. It rebuilds the expected order payload from the
plan, refuses a supplied payload that differs, and binds the decision to the
rebuilt payload, account snapshot, sizing mode, and expiry.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Final

from alphaledger.config import FrozenConfig, RiskConfig
from alphaledger.domain import RiskApproval, StructurePlan, money, require_utc
from alphaledger.execution.lifecycle import client_order_id
from alphaledger.execution.orders import build_mleg_order, canonical_bytes, order_payload_hash

__all__ = [
    "GATE_CONCURRENT_POSITION_LIMIT",
    "GATE_CONFIG_HASH_MISMATCH",
    "GATE_ENTRY_LIMIT_BOUND_EXCEEDED",
    "GATE_PAYLOAD_PLAN_MISMATCH",
    "GATE_QUANTITY_EXCEEDS_APPROVED_CAP",
    "GATE_SNAPSHOT_IN_FUTURE",
    "GATE_SNAPSHOT_STALE",
    "GATE_UNBALANCED_LEGS",
    "AccountSnapshot",
    "SizingMode",
    "account_snapshot_hash",
    "approve",
    "is_expired",
    "max_approved_quantity",
]

GATE_ENTRY_LIMIT_BOUND_EXCEEDED: Final = "entry_limit_bound_exceeded"
GATE_QUANTITY_EXCEEDS_APPROVED_CAP: Final = "quantity_exceeds_approved_cap"
GATE_UNBALANCED_LEGS: Final = "unbalanced_legs"
GATE_CONCURRENT_POSITION_LIMIT: Final = "concurrent_position_limit_reached"
GATE_CONFIG_HASH_MISMATCH: Final = "config_hash_mismatch"
GATE_PAYLOAD_PLAN_MISMATCH: Final = "payload_plan_mismatch"
GATE_SNAPSHOT_IN_FUTURE: Final = "snapshot_in_future"
GATE_SNAPSHOT_STALE: Final = "snapshot_stale"


class SizingMode(StrEnum):
    """Select the explicit frozen quantity cap for one approval check."""

    STANDARD = "standard"
    SMOKE_TEST = "smoke_test"


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Account state observed together under one frozen configuration."""

    equity: Decimal
    open_position_count: int
    frozen_config_hash: str
    snapshot_time: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "equity", money(self.equity, "equity"))
        if isinstance(self.open_position_count, bool) or not isinstance(
            self.open_position_count, int
        ):
            raise TypeError(
                "open_position_count must be a non-negative whole number; "
                f"got {self.open_position_count!r}"
            )
        if self.open_position_count < 0:
            raise ValueError(
                "open_position_count must be a non-negative whole number; "
                f"got {self.open_position_count!r}"
            )
        if not isinstance(self.frozen_config_hash, str) or not self.frozen_config_hash:
            raise ValueError("frozen_config_hash must be a non-empty string")
        object.__setattr__(
            self,
            "snapshot_time",
            require_utc(self.snapshot_time, "snapshot_time"),
        )


def account_snapshot_hash(snapshot: AccountSnapshot) -> str:
    """Hash every canonical account snapshot field."""
    content = canonical_bytes(
        {
            "equity": snapshot.equity,
            "frozen_config_hash": snapshot.frozen_config_hash,
            "open_position_count": snapshot.open_position_count,
            "snapshot_time": snapshot.snapshot_time.isoformat(),
        }
    )
    return hashlib.sha256(content).hexdigest()


def max_approved_quantity(
    plan: StructurePlan,
    equity: Decimal,
    risk_config: RiskConfig,
    mode: SizingMode,
) -> int:
    """Return the floor-sized quantity under the cap selected by ``mode``."""
    _require_sizing_mode(mode)
    _require_positive_exact_max_loss(plan)
    exact_equity = money(equity, "equity")
    risk_budget = exact_equity * risk_config.maximum_loss_fraction_per_new_trade
    risk_sized = int((risk_budget / plan.exact_max_loss).to_integral_value(rounding=ROUND_DOWN))
    if risk_sized <= 0:
        return 0
    cap = (
        risk_config.max_contracts_per_structure
        if mode is SizingMode.STANDARD
        else risk_config.smoke_test_max_contracts
    )
    return min(risk_sized, cap)


def approve(
    plan: StructurePlan,
    payload: Mapping[str, object],
    snapshot: AccountSnapshot,
    frozen_config: FrozenConfig,
    mode: SizingMode,
    expires_at: datetime,
    now: datetime,
    max_snapshot_age: timedelta,
) -> RiskApproval:
    """Rebuild one entry intent, evaluate every gate, and bind the result."""
    _require_sizing_mode(mode)
    current_time = require_utc(now, "now")
    expiry_time = require_utc(expires_at, "expires_at")
    if expiry_time <= current_time:
        raise ValueError("expires_at must be strictly after now")
    _require_positive_exact_max_loss(plan)
    _require_max_snapshot_age(max_snapshot_age)

    quantity = _payload_quantity(payload)
    limit_price = _payload_limit_price(payload)
    _payload_leg_ratios(payload)
    expected_payload = build_mleg_order(
        plan,
        quantity,
        limit_price,
        client_order_id(plan.plan_id, quantity, limit_price),
    )
    expected_payload_hash = order_payload_hash(expected_payload)
    supplied_payload_hash = order_payload_hash(payload)
    buy_ratio, sell_ratio = _payload_leg_ratios(expected_payload)

    failed_gates: list[str] = []
    if supplied_payload_hash != expected_payload_hash:
        failed_gates.append(GATE_PAYLOAD_PLAN_MISMATCH)
    if limit_price > plan.entry_limit_bound:
        failed_gates.append(GATE_ENTRY_LIMIT_BOUND_EXCEEDED)
    approved_quantity = max_approved_quantity(plan, snapshot.equity, frozen_config.risk, mode)
    if quantity > approved_quantity:
        failed_gates.append(GATE_QUANTITY_EXCEEDS_APPROVED_CAP)
    if buy_ratio != sell_ratio:
        failed_gates.append(GATE_UNBALANCED_LEGS)
    if snapshot.open_position_count >= frozen_config.risk.maximum_concurrent_positions:
        failed_gates.append(GATE_CONCURRENT_POSITION_LIMIT)
    if snapshot.frozen_config_hash != frozen_config.frozen_config_hash:
        failed_gates.append(GATE_CONFIG_HASH_MISMATCH)
    if snapshot.snapshot_time > current_time:
        failed_gates.append(GATE_SNAPSHOT_IN_FUTURE)
    if current_time - snapshot.snapshot_time > max_snapshot_age:
        failed_gates.append(GATE_SNAPSHOT_STALE)

    failures = tuple(failed_gates)
    approved = not failures
    snapshot_hash = account_snapshot_hash(snapshot)
    approval_id = _approval_id(
        plan_id=plan.plan_id,
        quantity=quantity,
        order_payload_hash=expected_payload_hash,
        account_snapshot_hash=snapshot_hash,
        mode=mode,
        expires_at=expiry_time,
        approved=approved,
        failed_gates=failures,
    )
    return RiskApproval(
        approval_id=approval_id,
        plan_id=plan.plan_id,
        account_snapshot_hash=snapshot_hash,
        order_payload_hash=expected_payload_hash,
        expires_at=expiry_time,
        approved=approved,
        failed_gates=failures,
    )


def is_expired(approval: RiskApproval, now: datetime) -> bool:
    """Return whether ``approval`` has reached its exact expiry boundary."""
    return require_utc(now, "now") >= approval.expires_at


def _approval_id(
    *,
    plan_id: str,
    quantity: int,
    order_payload_hash: str,
    account_snapshot_hash: str,
    mode: SizingMode | str,
    expires_at: datetime,
    approved: bool,
    failed_gates: tuple[str, ...],
) -> str:
    """Derive the restart-stable identity of an approval decision."""
    bound_fields = canonical_bytes(
        {
            "account_snapshot_hash": account_snapshot_hash,
            "approved": approved,
            "expires_at": require_utc(expires_at, "expires_at").isoformat(),
            "failed_gates": failed_gates,
            "mode": str(mode),
            "order_payload_hash": order_payload_hash,
            "plan_id": plan_id,
            "quantity": quantity,
        }
    )
    digest = hashlib.sha256(bound_fields).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _require_sizing_mode(mode: SizingMode) -> None:
    if not isinstance(mode, SizingMode):
        raise TypeError(f"mode must be SizingMode; got {type(mode).__name__}")


def _require_positive_exact_max_loss(plan: StructurePlan) -> None:
    if plan.exact_max_loss <= 0:
        raise ValueError(f"exact_max_loss must be strictly positive; got {plan.exact_max_loss}")


def _require_max_snapshot_age(max_snapshot_age: timedelta) -> None:
    if not isinstance(max_snapshot_age, timedelta):
        raise TypeError(
            "max_snapshot_age must be a non-negative timedelta; "
            f"got {type(max_snapshot_age).__name__}"
        )
    if max_snapshot_age < timedelta(0):
        raise ValueError(
            f"max_snapshot_age must be a non-negative timedelta; got {max_snapshot_age!r}"
        )


def _payload_field(payload: Mapping[str, object], field: str) -> object:
    if field not in payload:
        raise ValueError(f"payload is missing required field '{field}'")
    return payload[field]


def _payload_quantity(payload: Mapping[str, object]) -> int:
    value = _payload_field(payload, "qty")
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("payload field 'qty' must be a positive integer string")
    quantity = int(value)
    if quantity <= 0 or str(quantity) != value:
        raise ValueError("payload field 'qty' must be a positive integer string")
    return quantity


def _payload_limit_price(payload: Mapping[str, object]) -> Decimal:
    value = _payload_field(payload, "limit_price")
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("payload field 'limit_price' must be a finite Decimal")
    return value


def _payload_leg_ratios(payload: Mapping[str, object]) -> tuple[int, int]:
    value = _payload_field(payload, "legs")
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError("payload field 'legs' must be an array of two to four legs")
    if not 2 <= len(value) <= 4:
        raise ValueError("payload field 'legs' must contain two to four legs")

    buy_ratio = 0
    sell_ratio = 0
    for index, leg in enumerate(value):
        if not isinstance(leg, Mapping):
            raise ValueError(f"payload field 'legs[{index}]' must be a mapping")
        side = _leg_field(leg, index, "side")
        if side not in ("buy", "sell"):
            raise ValueError(f"payload field 'legs[{index}].side' must be buy or sell")
        ratio = _positive_integer_string(
            _leg_field(leg, index, "ratio_qty"),
            f"legs[{index}].ratio_qty",
        )
        if side == "buy":
            buy_ratio += ratio
        else:
            sell_ratio += ratio
    return buy_ratio, sell_ratio


def _leg_field(leg: Mapping[object, object], index: int, field: str) -> object:
    if field not in leg:
        raise ValueError(f"payload field 'legs[{index}].{field}' is required")
    return leg[field]


def _positive_integer_string(value: object, field: str) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError(f"payload field '{field}' must be a positive integer string")
    quantity = int(value)
    if quantity <= 0 or str(quantity) != value:
        raise ValueError(f"payload field '{field}' must be a positive integer string")
    return quantity
