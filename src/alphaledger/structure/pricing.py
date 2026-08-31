"""Derive bounded entry rung prices from materialized option quotes.

The calculation is pure and deterministic. It validates every quoted plan leg,
then linearly interpolates from the executable net midpoint to the conservative
natural net debit without reading a clock or performing I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise

from alphaledger.domain import MONEY_EXPONENT, StructurePlan, require_utc
from alphaledger.structure.chains import ChainContract

__all__ = ["UnpricableStructureError", "rung_prices"]


class UnpricableStructureError(ValueError):
    """The plan's current quotes cannot support a safe entry ladder."""


def rung_prices(
    plan: StructurePlan,
    quotes: Mapping[str, ChainContract],
    rungs: int,
    max_quote_age: timedelta,
    as_of: datetime,
) -> tuple[Decimal, ...]:
    """Return conservative net debit prices from midpoint through natural."""
    if isinstance(rungs, bool) or not isinstance(rungs, int) or rungs <= 0:
        raise ValueError(f"rungs must be a positive integer; got {rungs!r}")
    if not isinstance(max_quote_age, timedelta) or max_quote_age <= timedelta(0):
        raise ValueError(f"max_quote_age must be a positive timedelta; got {max_quote_age!r}")
    observed_at = require_utc(as_of, "as_of")

    midpoint = Fraction(0)
    natural = Fraction(0)
    for index, leg in enumerate(plan.legs):
        symbol = leg.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise UnpricableStructureError(
                f"plan leg {index} is missing a non-empty contract symbol"
            )
        quote = quotes.get(symbol)
        if quote is None:
            raise UnpricableStructureError(f"{symbol} quote is missing for plan leg {index}")
        if quote.symbol != symbol:
            raise UnpricableStructureError(
                f"{symbol} quote mapping contains contract {quote.symbol}; symbols do not match"
            )

        ratio = _leg_ratio(leg, symbol)
        side = _leg_side(leg, symbol)
        _validate_quote(quote, ratio * plan.quantity, max_quote_age, observed_at)

        bid = Fraction(quote.bid)
        ask = Fraction(quote.ask)
        signed_ratio = ratio if side == "buy" else -ratio
        midpoint += signed_ratio * (bid + ask) / 2
        natural += ratio * (ask if side == "buy" else -bid)

    if midpoint <= 0:
        raise UnpricableStructureError(
            f"structure midpoint must be a positive net debit; got {_exact_text(midpoint)}"
        )
    if natural <= 0:
        raise UnpricableStructureError(
            f"structure natural price must be a positive net debit; got {_exact_text(natural)}"
        )

    midpoint_price = _ceiling_money(midpoint)
    natural_price = _ceiling_money(natural)
    bound = plan.entry_limit_bound
    if midpoint_price > bound:
        raise UnpricableStructureError(
            f"midpoint price {midpoint_price} exceeds plan.entry_limit_bound {bound}"
        )
    if natural_price > bound:
        raise UnpricableStructureError(
            f"natural price {natural_price} exceeds plan.entry_limit_bound {bound}"
        )

    if rungs == 1:
        return (midpoint_price,)
    if natural <= midpoint:
        raise UnpricableStructureError(
            f"quotes cannot produce {rungs} strictly increasing prices: "
            f"midpoint {_exact_text(midpoint)}, natural {_exact_text(natural)}"
        )

    span = natural - midpoint
    prices = tuple(_ceiling_money(midpoint + span * index / (rungs - 1)) for index in range(rungs))
    if any(right <= left for left, right in pairwise(prices)):
        raise UnpricableStructureError(
            f"quotes cannot produce {rungs} strictly increasing prices at "
            f"money increment {MONEY_EXPONENT}: midpoint {midpoint_price}, "
            f"natural {natural_price}"
        )
    if prices[-1] > bound:
        raise UnpricableStructureError(
            f"natural price {prices[-1]} exceeds plan.entry_limit_bound {bound}"
        )
    return prices


def _leg_ratio(leg: Mapping[str, object], symbol: str) -> int:
    ratio = leg.get("ratio_qty")
    if isinstance(ratio, bool) or not isinstance(ratio, int) or ratio <= 0:
        raise UnpricableStructureError(
            f"{symbol} ratio_qty must be a positive integer; got {ratio!r}"
        )
    return ratio


def _leg_side(leg: Mapping[str, object], symbol: str) -> str:
    side = leg.get("side")
    if side not in {"buy", "sell"}:
        raise UnpricableStructureError(f"{symbol} side must be 'buy' or 'sell'; got {side!r}")
    assert isinstance(side, str)
    return side


def _validate_quote(
    quote: ChainContract,
    required_size: int,
    max_quote_age: timedelta,
    as_of: datetime,
) -> None:
    if quote.bid <= 0 or quote.ask <= 0:
        raise UnpricableStructureError(
            f"{quote.symbol} has a non-positive market: bid {quote.bid}, ask {quote.ask}"
        )
    if quote.bid > quote.ask:
        raise UnpricableStructureError(
            f"{quote.symbol} has a crossed market: bid {quote.bid} exceeds ask {quote.ask}"
        )
    for field in ("bid_size", "ask_size"):
        size = getattr(quote, field)
        if isinstance(size, bool) or not isinstance(size, int) or size < required_size:
            raise UnpricableStructureError(
                f"{quote.symbol} displayed {field} {size!r} is below required size {required_size}"
            )

    quote_age = as_of - quote.quote_time
    if quote_age < timedelta(0):
        raise UnpricableStructureError(
            f"{quote.symbol} quote_time {quote.quote_time.isoformat()} is after "
            f"as_of {as_of.isoformat()}"
        )
    if quote_age > max_quote_age:
        raise UnpricableStructureError(
            f"{quote.symbol} stale quote_time {quote.quote_time.isoformat()} exceeds "
            f"max_quote_age {max_quote_age} at as_of {as_of.isoformat()}"
        )


def _ceiling_money(value: Fraction) -> Decimal:
    tick = Fraction(MONEY_EXPONENT)
    scaled = value / tick
    units = -(-scaled.numerator // scaled.denominator)
    exponent = MONEY_EXPONENT.as_tuple().exponent
    assert isinstance(exponent, int)
    digits = tuple(int(digit) for digit in str(abs(units)))
    return Decimal((units < 0, digits, exponent))


def _exact_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"
