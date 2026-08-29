"""Enumerate quoted debit verticals and compute their exact bounded payoffs.

The module accepts already-typed chain records behind a small lookup protocol.
It performs no network access, position sizing, candidate ranking across
underlyings, or broker payload mapping.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from fractions import Fraction
from typing import Literal, Protocol

from alphaledger.domain import StructurePlan, money, require_utc

__all__ = [
    "ChainContract",
    "ChainLookup",
    "OptionType",
    "StructureEnumerationResult",
    "StructureError",
    "StructureKind",
    "StructureRules",
    "enumerate_candidates",
]


class OptionType(StrEnum):
    """The two option types used by the debit-vertical allowlist."""

    CALL = "call"
    PUT = "put"


type StructureKind = Literal[
    "bull_call_debit_vertical",
    "bear_put_debit_vertical",
]
_STRUCTURE_KINDS: tuple[StructureKind, ...] = (
    "bull_call_debit_vertical",
    "bear_put_debit_vertical",
)


class StructureError(ValueError):
    """A malformed request cannot be enumerated safely."""


def _set(instance: object, field: str, value: object) -> None:
    object.__setattr__(instance, field, value)


def _exact_decimal(value: object, field: str) -> Decimal:
    """Parse a finite non-money decimal without quantizing it."""
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
    return parsed


@dataclass(frozen=True, slots=True)
class ChainContract:
    """One real option contract with the quote metadata needed for screening."""

    symbol: str
    underlying_symbol: str
    option_type: OptionType
    strike: Decimal
    expiry: date
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    multiplier: int
    delta: Decimal | None
    quote_time: datetime
    feed: str

    def __post_init__(self) -> None:
        for field in ("strike", "bid", "ask"):
            _set(self, field, money(getattr(self, field), field))
        if self.delta is not None:
            _set(self, "delta", _exact_decimal(self.delta, "delta"))
        _set(self, "quote_time", require_utc(self.quote_time, "quote_time"))
        if not isinstance(self.option_type, OptionType):
            raise TypeError(
                f"option_type must be OptionType; got {type(self.option_type).__name__}"
            )
        if isinstance(self.expiry, datetime) or not isinstance(self.expiry, date):
            raise TypeError(f"expiry must be a date; got {type(self.expiry).__name__}")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty contract symbol")
        if not isinstance(self.underlying_symbol, str) or not self.underlying_symbol.strip():
            raise ValueError("underlying_symbol must be a non-empty symbol")


class ChainLookup(Protocol):
    """Minimal boundary for a point-in-time option-chain observation."""

    def contracts_for(
        self,
        underlying_symbol: str,
        as_of: datetime,
    ) -> Sequence[ChainContract]:
        """Return already-typed contracts observed for one underlying."""
        ...


@dataclass(frozen=True, slots=True)
class StructureRules:
    """Frozen caller-supplied thresholds for one enumeration."""

    dte_min: int
    dte_max: int
    long_abs_delta_min: Decimal
    long_abs_delta_max: Decimal
    short_abs_delta_min: Decimal
    short_abs_delta_max: Decimal
    max_quote_age: timedelta
    max_relative_spread: Decimal
    max_absolute_spread: Decimal
    expected_feed: str

    def __post_init__(self) -> None:
        for field in ("dte_min", "dte_max"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field} must be an integer; got {value!r}")
        if self.dte_min < 1:
            raise StructureError(f"dte_min must be at least 1; got {self.dte_min!r}")
        if self.dte_max < self.dte_min:
            raise StructureError(
                f"dte_max must be at least dte_min {self.dte_min}; got {self.dte_max!r}"
            )

        for prefix in ("long", "short"):
            minimum_field = f"{prefix}_abs_delta_min"
            maximum_field = f"{prefix}_abs_delta_max"
            minimum = _exact_decimal(getattr(self, minimum_field), minimum_field)
            maximum = _exact_decimal(getattr(self, maximum_field), maximum_field)
            if not Decimal(0) <= minimum <= maximum <= Decimal(1):
                raise StructureError(
                    f"{minimum_field} and {maximum_field} must satisfy "
                    f"0 <= minimum <= maximum <= 1; got {minimum} and {maximum}"
                )
            _set(self, minimum_field, minimum)
            _set(self, maximum_field, maximum)

        if not isinstance(self.max_quote_age, timedelta) or self.max_quote_age <= timedelta(0):
            raise StructureError(
                f"max_quote_age must be a positive timedelta; got {self.max_quote_age!r}"
            )
        for field in ("max_relative_spread", "max_absolute_spread"):
            value = _exact_decimal(getattr(self, field), field)
            if value < 0:
                raise StructureError(f"{field} must not be negative; got {value}")
            _set(self, field, value)
        if not isinstance(self.expected_feed, str) or not self.expected_feed.strip():
            raise StructureError("expected_feed must be a non-empty feed identity")


@dataclass(frozen=True, slots=True)
class StructureEnumerationResult:
    """Candidates or auditable no-trade reasons, but never both or neither."""

    candidates: tuple[StructurePlan, ...]
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _set(self, "candidates", tuple(self.candidates))
        _set(self, "rejection_reasons", tuple(self.rejection_reasons))
        if bool(self.candidates) == bool(self.rejection_reasons):
            raise StructureError(
                "enumeration must return candidates or rejection_reasons, exclusively"
            )


@dataclass(frozen=True, slots=True)
class _RankedPlan:
    cost_drag_ratio: Fraction
    expiry: date
    long_strike: Decimal
    long_symbol: str
    short_strike: Decimal
    short_symbol: str
    plan: StructurePlan


def enumerate_candidates(
    kind: StructureKind,
    candidate_id: str,
    underlying_symbol: str,
    as_of: datetime,
    quantity: int,
    rules: StructureRules,
    chains: ChainLookup,
) -> StructureEnumerationResult:
    """Enumerate admissible debit verticals in a deterministic total order.

    Candidates are ordered by ascending cost-drag ratio, defined as net debit
    divided by spread width. Ties use the nearest expiry and then the lowest
    long-leg strike. Contract symbols finish otherwise-identical ties so input
    chain order can never change the result.
    """
    if kind not in _STRUCTURE_KINDS:
        raise StructureError(f"kind must be one of {', '.join(_STRUCTURE_KINDS)}; got {kind!r}")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise StructureError("candidate_id must be a non-empty decision identifier")
    if not isinstance(underlying_symbol, str) or not underlying_symbol.strip():
        raise StructureError("underlying_symbol must be a non-empty symbol")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise StructureError(f"quantity must be a positive integer; got {quantity!r}")
    observed_at = require_utc(as_of, "as_of")
    observed = tuple(chains.contracts_for(underlying_symbol, observed_at))
    if not observed:
        return _no_trade(f"no_contracts: {underlying_symbol} chain returned no contracts")
    observed, symbol_conflicts = _deduplicate_contracts(observed)
    if symbol_conflicts:
        return _no_trade(
            *(
                "contract_symbol_uniqueness: "
                f"{symbol} has conflicting observations at the same as_of; "
                "enumeration failed closed"
                for symbol in symbol_conflicts
            )
        )

    reasons: list[str] = []
    matching_underlying: list[ChainContract] = []
    for contract in observed:
        if contract.underlying_symbol != underlying_symbol:
            reasons.append(
                "underlying_match: "
                f"{contract.symbol} belongs to {contract.underlying_symbol}, "
                f"not {underlying_symbol}"
            )
        else:
            matching_underlying.append(contract)

    desired_type = OptionType.CALL if kind == "bull_call_debit_vertical" else OptionType.PUT
    desired_contracts = [
        contract for contract in matching_underlying if contract.option_type is desired_type
    ]
    if not desired_contracts:
        if reasons and not matching_underlying:
            return _no_trade(*reasons)
        return _no_trade(
            f"no_{desired_type.value}_contracts: {underlying_symbol} chain has no "
            f"{desired_type.value} contracts"
        )

    screened: list[ChainContract] = []
    for contract in desired_contracts:
        rejection = _contract_rejection(contract, observed_at, quantity, rules)
        if rejection is None:
            screened.append(contract)
        else:
            reasons.append(rejection)

    if not screened:
        return _no_trade(*reasons)

    screened.sort(key=lambda contract: (contract.expiry, contract.strike, contract.symbol))
    long_contracts: list[ChainContract] = []
    short_contracts: list[ChainContract] = []
    for contract in screened:
        assert contract.delta is not None
        absolute_delta = abs(contract.delta)
        fits_long = rules.long_abs_delta_min <= absolute_delta <= rules.long_abs_delta_max
        fits_short = rules.short_abs_delta_min <= absolute_delta <= rules.short_abs_delta_max
        if fits_long:
            long_contracts.append(contract)
        if fits_short:
            short_contracts.append(contract)
        if not fits_long and not fits_short:
            reasons.append(
                "delta_band: "
                f"{contract.symbol} absolute delta {absolute_delta} matches neither "
                "the long-leg nor short-leg band"
            )

    ranked: list[_RankedPlan] = []
    for long_leg in long_contracts:
        for short_leg in short_contracts:
            candidate = _build_ranked_plan(
                kind,
                candidate_id,
                quantity,
                long_leg,
                short_leg,
                reasons,
            )
            if candidate is not None:
                ranked.append(candidate)

    if not ranked:
        if not reasons:
            reasons.append(
                "delta_band: no contract combination satisfied both long-leg and short-leg bands"
            )
        return _no_trade(*reasons)

    ranked.sort(
        key=lambda item: (
            item.cost_drag_ratio,
            item.expiry,
            item.long_strike,
            item.long_symbol,
            item.short_strike,
            item.short_symbol,
        )
    )
    return StructureEnumerationResult(
        candidates=tuple(item.plan for item in ranked),
        rejection_reasons=(),
    )


def _contract_rejection(
    contract: ChainContract,
    as_of: datetime,
    quantity: int,
    rules: StructureRules,
) -> str | None:
    dte = (contract.expiry - as_of.date()).days
    if not rules.dte_min <= dte <= rules.dte_max:
        return (
            f"dte_window: {contract.symbol} has DTE {dte}, outside "
            f"[{rules.dte_min}, {rules.dte_max}]"
        )
    if contract.bid <= 0 or contract.ask <= 0 or contract.bid > contract.ask:
        return (
            f"quote_integrity: {contract.symbol} requires positive, uncrossed bid/ask; "
            f"got bid {contract.bid} and ask {contract.ask}"
        )
    quote_age = as_of - contract.quote_time
    if quote_age < timedelta(0) or quote_age > rules.max_quote_age:
        return (
            f"quote_freshness: {contract.symbol} quote age {quote_age} is outside "
            f"[0, {rules.max_quote_age}]"
        )
    if (
        isinstance(contract.multiplier, bool)
        or not isinstance(contract.multiplier, int)
        or contract.multiplier <= 0
    ):
        return (
            f"contract_metadata: {contract.symbol} multiplier is missing or invalid; "
            f"got {contract.multiplier!r}"
        )
    if contract.delta is None:
        return f"delta_required: {contract.symbol} has no delta for delta-band selection"

    spread = contract.ask - contract.bid
    relative_spread = (Decimal(2) * spread) / (contract.ask + contract.bid)
    if relative_spread > rules.max_relative_spread:
        return (
            f"relative_spread: {contract.symbol} relative width {relative_spread} exceeds "
            f"{rules.max_relative_spread}"
        )
    if spread > rules.max_absolute_spread:
        return (
            f"absolute_spread: {contract.symbol} absolute width {spread} exceeds "
            f"{rules.max_absolute_spread}"
        )
    if (
        isinstance(contract.bid_size, bool)
        or not isinstance(contract.bid_size, int)
        or isinstance(contract.ask_size, bool)
        or not isinstance(contract.ask_size, int)
        or contract.bid_size < quantity
        or contract.ask_size < quantity
    ):
        return (
            f"displayed_size: {contract.symbol} bid/ask size "
            f"{contract.bid_size}/{contract.ask_size} is below quantity {quantity}"
        )
    if contract.feed != rules.expected_feed:
        return (
            f"feed_identity: {contract.symbol} feed {contract.feed!r} does not match "
            f"expected feed {rules.expected_feed!r}"
        )
    return None


def _build_ranked_plan(
    kind: StructureKind,
    candidate_id: str,
    quantity: int,
    long_leg: ChainContract,
    short_leg: ChainContract,
    reasons: list[str],
) -> _RankedPlan | None:
    if long_leg.symbol == short_leg.symbol:
        return None
    pair = f"{long_leg.symbol}/{short_leg.symbol}"
    if long_leg.underlying_symbol != short_leg.underlying_symbol:
        reasons.append(f"underlying_match: {pair} spans two underlyings")
        return None
    if long_leg.expiry != short_leg.expiry:
        reasons.append(f"expiry_match: {pair} spans two expiries")
        return None
    if long_leg.multiplier != short_leg.multiplier:
        reasons.append(
            "contract_metadata: "
            f"{pair} has inconsistent multipliers "
            f"{long_leg.multiplier} and {short_leg.multiplier}"
        )
        return None

    if kind == "bull_call_debit_vertical":
        if long_leg.strike >= short_leg.strike:
            return None
        width = short_leg.strike - long_leg.strike
    else:
        if long_leg.strike <= short_leg.strike:
            return None
        width = long_leg.strike - short_leg.strike

    net_debit = long_leg.ask - short_leg.bid
    if net_debit <= 0 or net_debit >= width:
        reasons.append(
            f"payoff_invariant: {pair} requires 0 < net debit < width; "
            f"got debit {net_debit} and width {width}"
        )
        return None

    multiplier = Decimal(long_leg.multiplier)
    exact_max_loss = multiplier * net_debit
    exact_max_profit = multiplier * (width - net_debit)
    if kind == "bull_call_debit_vertical":
        expiry_breakeven = long_leg.strike + net_debit
    else:
        expiry_breakeven = long_leg.strike - net_debit
    plan = StructurePlan(
        plan_id=f"{candidate_id}/{long_leg.symbol}/{short_leg.symbol}",
        candidate_id=candidate_id,
        legs=(
            {
                "symbol": long_leg.symbol,
                "ratio_qty": 1,
                "side": "buy",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": short_leg.symbol,
                "ratio_qty": 1,
                "side": "sell",
                "position_intent": "sell_to_open",
            },
        ),
        quantity=quantity,
        entry_limit_bound=net_debit,
        exact_max_loss=exact_max_loss,
        exact_max_profit=exact_max_profit,
        expiry_breakeven=expiry_breakeven,
        quote_times=(long_leg.quote_time, short_leg.quote_time),
        stress_pnl={
            "max_loss_scenario": -exact_max_loss,
            "max_profit_scenario": exact_max_profit,
        },
    )
    return _RankedPlan(
        cost_drag_ratio=Fraction(net_debit) / Fraction(width),
        expiry=long_leg.expiry,
        long_strike=long_leg.strike,
        long_symbol=long_leg.symbol,
        short_strike=short_leg.strike,
        short_symbol=short_leg.symbol,
        plan=plan,
    )


def _deduplicate_contracts(
    contracts: tuple[ChainContract, ...],
) -> tuple[tuple[ChainContract, ...], tuple[str, ...]]:
    by_symbol: dict[str, ChainContract] = {}
    conflicts: set[str] = set()
    for contract in contracts:
        prior = by_symbol.get(contract.symbol)
        if prior is None:
            by_symbol[contract.symbol] = contract
        elif prior != contract:
            conflicts.add(contract.symbol)
    return tuple(by_symbol.values()), tuple(sorted(conflicts))


def _no_trade(*reasons: str) -> StructureEnumerationResult:
    unique_reasons = tuple(sorted(set(reasons)))
    if not unique_reasons:
        unique_reasons = ("no_admissible_structure: enumeration produced no candidates",)
    return StructureEnumerationResult(candidates=(), rejection_reasons=unique_reasons)
