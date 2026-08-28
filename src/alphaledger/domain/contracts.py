"""Frozen domain contracts shared by the execution and research lanes.

The five records come from `options-alpha-agent-design.md` section 14. Two
deviations from that sketch are recorded in
`specs/units/001-domain-contracts.md` under "Resolved conflicts":

1. money is `Decimal`, not `float`, because `.claude/rules/01-safety.md`
   requires it and a float is the more permissive reading;
2. only the records whose fields are all hashable are hashable.

This module performs no I/O and imports nothing from `alphaledger` outside
`domain`. Both properties are asserted by the tests.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from types import MappingProxyType
from typing import Literal

__all__ = [
    "MONEY_EXPONENT",
    "MONEY_ROUNDING",
    "EvidenceCard",
    "Forecast",
    "NewsLabel",
    "ObservationTimestamps",
    "RiskApproval",
    "StructurePlan",
    "money",
    "require_utc",
]

# Declared rounding for every money quantity, per .claude/rules/01-safety.md.
# Four places covers option premia quoted in cents and sub-cent increments.
MONEY_EXPONENT = Decimal("0.0001")
MONEY_ROUNDING = ROUND_HALF_EVEN

Direction = Literal["positive", "negative", "mixed", "neutral"]
Novelty = Literal["new", "follow_up", "duplicate"]
Relevance = Literal["direct", "industry_linked", "incidental"]
Surprise = Literal["unexpected", "partly_expected", "expected", "unknown"]
Ambiguity = Literal["low", "medium", "high"]
DataMode = Literal["opra", "indicative_no_option_alpha"]


def money(value: object, field: str) -> Decimal:
    """Coerce a money quantity to `Decimal` with declared rounding.

    `float` is rejected rather than converted. A binary float cannot represent
    a decimal premium exactly, and silently accepting one is how a payoff
    calculation drifts from the broker's arithmetic.
    """
    if isinstance(value, bool):
        raise TypeError(f"{field} must be Decimal, str, or int; got bool {value!r}")
    if isinstance(value, float):
        raise TypeError(
            f"{field} must be Decimal, str, or int, never float; got {value!r}. "
            "Pass a string or Decimal so the value is exact."
        )
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, str | int):
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{field} is not a valid decimal: {value!r}") from exc
    else:
        raise TypeError(f"{field} must be Decimal, str, or int; got {type(value).__name__}")
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite; got {value!r}")
    try:
        return parsed.quantize(MONEY_EXPONENT, rounding=MONEY_ROUNDING)
    except InvalidOperation as exc:
        raise ValueError(
            f"{field} magnitude cannot be represented at the declared "
            f"exponent {MONEY_EXPONENT}; got {value!r}"
        ) from exc


def require_utc(value: object, field: str) -> datetime:
    """Return `value` as a UTC datetime, rejecting a naive one."""
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime; got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field} must be timezone-aware UTC; got a naive datetime. "
            "A naive timestamp cannot be placed on the point-in-time record."
        )
    return value.astimezone(UTC)


def _floats(value: Mapping[str, object] | None, field: str) -> Mapping[str, float] | None:
    """Copy a feature mapping into a read-only view of floats."""
    if value is None:
        return None
    out: dict[str, float] = {}
    for key, item in dict(value).items():
        if isinstance(item, bool) or not isinstance(item, int | float | Decimal):
            raise TypeError(f"{field}[{key}] must be a real number; got {type(item).__name__}")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{field}[{key}] must be finite; got {item!r}")
        out[str(key)] = number
    return MappingProxyType(out)


def _money_map(value: Mapping[str, object], field: str) -> Mapping[str, Decimal]:
    """Copy a money mapping into a read-only view of `Decimal`."""
    out = {str(key): money(item, f"{field}[{key}]") for key, item in dict(value).items()}
    return MappingProxyType(out)


def _strings(value: Iterable[object], field: str) -> tuple[str, ...]:
    if isinstance(value, str | bytes):
        raise TypeError(
            f"{field} must be a sequence of strings, not a bare string. "
            f"A string is iterable and would be split into characters; got {value!r}"
        )
    return tuple(str(item) for item in value)


LEG_VALUE_TYPES = (str, int, Decimal, datetime)


def _leg(value: Mapping[str, object], field: str) -> Mapping[str, object]:
    """Copy one leg into a read-only view, allowing scalars only.

    Design section 14 leaves the leg schema open. Values are still bounded
    here: a nested container would stay shared by reference, so a caller
    could mutate a plan after a RiskApproval was bound to its payload hash.
    """
    out: dict[str, object] = {}
    for key, item in dict(value).items():
        if isinstance(item, float):
            raise TypeError(
                f"{field}[{key}] must not be float; a strike or premium is money. "
                f"Pass a string or Decimal; got {item!r}"
            )
        if not isinstance(item, LEG_VALUE_TYPES):
            raise TypeError(
                f"{field}[{key}] must be a scalar, not {type(item).__name__}. "
                "A nested value would stay mutable through a shared reference"
            )
        out[str(key)] = item
    return MappingProxyType(out)


def _set(instance: object, field: str, value: object) -> None:
    object.__setattr__(instance, field, value)


@dataclass(frozen=True, slots=True)
class ObservationTimestamps:
    """The point-in-time contract from design section 4.

    Every observation carries all six. Features are reconstructed as of
    `first_seen_time`; a later revision is a different observation.
    """

    event_time: datetime
    first_seen_time: datetime
    source_time: datetime
    received_time: datetime
    feed: str
    as_of: datetime

    def __post_init__(self) -> None:
        for field in ("event_time", "first_seen_time", "source_time", "received_time", "as_of"):
            _set(self, field, require_utc(getattr(self, field), field))
        if not self.feed:
            raise ValueError("feed must identify the source; it is never defaulted")
        if self.first_seen_time < self.source_time:
            raise ValueError(
                "first_seen_time precedes source_time, which would mean observing a "
                f"record before its source emitted it: {self.first_seen_time.isoformat()} "
                f"< {self.source_time.isoformat()}"
            )


@dataclass(frozen=True, slots=True)
class NewsLabel:
    article_id: str
    source_time: datetime
    first_seen_time: datetime
    direction: Direction
    category: str
    novelty: Novelty
    relevance: Relevance
    surprise: Surprise
    ambiguity: Ambiguity
    evidence_spans: tuple[str, ...]
    labeler_version: str

    def __post_init__(self) -> None:
        _set(self, "source_time", require_utc(self.source_time, "source_time"))
        _set(self, "first_seen_time", require_utc(self.first_seen_time, "first_seen_time"))
        _set(self, "evidence_spans", _strings(self.evidence_spans, "evidence_spans"))


@dataclass(frozen=True, slots=True)
class EvidenceCard:
    candidate_id: str
    symbol: str
    as_of: datetime
    data_mode: DataMode
    price_volume_features: Mapping[str, float]
    news_features: Mapping[str, float]
    options_features: Mapping[str, float] | None
    quality_flags: tuple[str, ...]
    raw_data_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _set(self, "as_of", require_utc(self.as_of, "as_of"))
        _set(
            self,
            "price_volume_features",
            _floats(self.price_volume_features, "price_volume_features"),
        )
        _set(self, "news_features", _floats(self.news_features, "news_features"))
        _set(self, "options_features", _floats(self.options_features, "options_features"))
        _set(self, "quality_flags", _strings(self.quality_flags, "quality_flags"))
        _set(self, "raw_data_hashes", _strings(self.raw_data_hashes, "raw_data_hashes"))


@dataclass(frozen=True, slots=True)
class Forecast:
    candidate_id: str
    horizon_sessions: int
    p_up: float
    expected_residual_return: float
    quantiles: Mapping[str, float]
    contribution_by_family: Mapping[str, float]
    calibration_error: float
    effective_sample_size: float
    eligible: bool
    rejection_reasons: tuple[str, ...]
    model_version: str

    def __post_init__(self) -> None:
        for field in ("expected_residual_return", "calibration_error", "effective_sample_size"):
            number = getattr(self, field)
            if not math.isfinite(number):
                raise ValueError(f"{field} must be finite; got {number!r}")
        if not 0.0 <= self.p_up <= 1.0:
            raise ValueError(f"p_up must be a probability in [0, 1]; got {self.p_up!r}")
        if self.horizon_sessions <= 0:
            raise ValueError(f"horizon_sessions must be positive; got {self.horizon_sessions!r}")
        _set(self, "quantiles", _floats(self.quantiles, "quantiles"))
        _set(
            self,
            "contribution_by_family",
            _floats(self.contribution_by_family, "contribution_by_family"),
        )
        _set(self, "rejection_reasons", _strings(self.rejection_reasons, "rejection_reasons"))
        if not self.eligible and not self.rejection_reasons:
            raise ValueError("an ineligible forecast must record why; rejection_reasons is empty")


@dataclass(frozen=True, slots=True)
class StructurePlan:
    plan_id: str
    candidate_id: str
    legs: tuple[Mapping[str, object], ...]
    quantity: int
    entry_limit_bound: Decimal
    exact_max_loss: Decimal
    exact_max_profit: Decimal
    expiry_breakeven: Decimal
    quote_times: tuple[datetime, ...]
    stress_pnl: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        for field in (
            "entry_limit_bound",
            "exact_max_loss",
            "exact_max_profit",
            "expiry_breakeven",
        ):
            _set(self, field, money(getattr(self, field), field))
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive; got {self.quantity!r}")
        if not self.legs:
            raise ValueError("a structure plan must name at least one leg")
        _set(self, "legs", tuple(_leg(leg, "legs") for leg in self.legs))
        _set(
            self,
            "quote_times",
            tuple(require_utc(item, "quote_times") for item in self.quote_times),
        )
        _set(self, "stress_pnl", _money_map(self.stress_pnl, "stress_pnl"))


@dataclass(frozen=True, slots=True)
class RiskApproval:
    approval_id: str
    plan_id: str
    account_snapshot_hash: str
    order_payload_hash: str
    expires_at: datetime
    approved: bool
    failed_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        _set(self, "expires_at", require_utc(self.expires_at, "expires_at"))
        _set(self, "failed_gates", _strings(self.failed_gates, "failed_gates"))
        if self.approved and self.failed_gates:
            raise ValueError("an approval cannot be granted while gates are recorded as failed")
        if not self.approved and not self.failed_gates:
            raise ValueError(
                "a refused approval must record failed_gates; an unexplained refusal "
                "cannot be audited"
            )
