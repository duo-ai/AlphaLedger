"""Build the next session's symbol set from information available at a close.

Design section 4 fixes the universe at the prior close from five conditions:
active, tradable, and options enabled; at least ten dollars at the prior close;
top cohort by trailing twenty-session median dollar volume; at least one 7 to
21 DTE expiration quoted two-sided near the money; and free of unresolved
symbol changes or corporate actions. The set is capped at thirty names.

Two properties matter more than the conditions themselves.

Membership is decided from observations first seen at or before `as_of`. A
symbol that becomes liquid or optionable the next day is absent from the set
built today, and a symbol delisted next month is still present in the set built
today. Survivorship is never applied backwards, because a scan that quietly
drops the names that later failed is describing the past.

The result is reproducible. `build` is pure with respect to its source and
performs no I/O, ranking is totally ordered, and the hash covers the inputs
that decide membership, so a frozen run can be verified afterwards in a process
that shares nothing with the one that built it.

One interpretation is recorded here because the design leaves it open. Section
4 allows a checked-in static list when point-in-time optionability history
cannot be assembled, and requires the limitation to be disclosed. This module
reads that narrowly: the list substitutes for the optionability evidence alone,
membership in it standing in for `options_enabled` and for the near-money
expiration check. Price, dollar volume, tradability, and corporate-action
screens still come from point-in-time data, because those are reconstructable
whether or not optionability is. The flag and the list hash are recorded on
every universe built that way, and they change the universe hash, so a fallback
run can never be mistaken for a reconstructed one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from alphaledger.domain.contracts import money, require_utc

__all__ = [
    "BELOW_DOLLAR_VOLUME_FLOOR",
    "BELOW_PRICE_FLOOR",
    "DEFAULT_FLOORS",
    "INACTIVE",
    "NOT_TRADABLE",
    "NO_QUOTED_EXPIRATION",
    "OPTIONS_NOT_ENABLED",
    "OUTSIDE_CAP",
    "STATIC_FALLBACK_SYMBOLS",
    "UNRESOLVED_CORPORATE_ACTION",
    "AmbiguousObservationError",
    "Exclusion",
    "FrozenUniverse",
    "LeakedObservationError",
    "ObservationSource",
    "SymbolObservation",
    "UniverseFloors",
    "UniverseSource",
    "build",
    "static_fallback_hash",
]

INACTIVE = "inactive"
NOT_TRADABLE = "not_tradable"
OPTIONS_NOT_ENABLED = "options_not_enabled"
NO_QUOTED_EXPIRATION = "no_quoted_near_money_expiration"
BELOW_PRICE_FLOOR = "below_price_floor"
BELOW_DOLLAR_VOLUME_FLOOR = "below_dollar_volume_floor"
UNRESOLVED_CORPORATE_ACTION = "unresolved_corporate_action"
OUTSIDE_CAP = "outside_cap"

# Frozen configuration, not a judgment made per run. Used only when
# point-in-time optionability history cannot be assembled, and always
# disclosed by the fallback flag and the list hash.
# fmt: off
STATIC_FALLBACK_SYMBOLS: tuple[str, ...] = (
    "AAPL", "ABBV", "AMD", "AMZN", "AVGO", "BAC", "COST", "CRM", "CVX", "DIS",
    "GOOGL", "HD", "INTC", "JNJ", "JPM", "KO", "LLY", "MA", "META", "MRK",
    "MSFT", "NFLX", "NVDA", "PEP", "PFE", "PG", "QCOM", "TSLA", "UNH", "XOM",
)
# fmt: on


class AmbiguousObservationError(ValueError):
    """Two observations of one symbol share a timestamp and disagree.

    Raised rather than resolved. Availability derived as a published time plus
    a fixed lag gives every observation sharing a source time an identical
    `first_seen_time`, so ties are ordinary rather than exceptional, and
    picking a winner would make membership depend on the order a source
    happened to return its rows.
    """


class LeakedObservationError(ValueError):
    """A source returned an observation that was not knowable at `as_of`.

    Raised rather than filtered. A source handing over a future row is broken,
    and dropping the row quietly would leave the break invisible to every later
    audit while the resulting universe still looked ordinary.
    """


def static_fallback_hash() -> str:
    """The content address of the checked-in fallback list."""
    canonical = json.dumps(list(STATIC_FALLBACK_SYMBOLS), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SymbolObservation:
    """One symbol's screening facts, as they were known at `first_seen_time`."""

    symbol: str
    feed: str
    first_seen_time: datetime
    active: bool
    tradable: bool
    options_enabled: bool
    prior_close: Decimal
    median_dollar_volume: Decimal
    near_money_quotes_7_to_21_dte: bool
    unresolved_corporate_action: bool

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must name the instrument; it is never defaulted")
        if not self.feed.strip():
            raise ValueError(
                "feed must identify the source; design section 4 requires it on every "
                "record so a change of feed cannot pass unnoticed"
            )
        object.__setattr__(
            self, "first_seen_time", require_utc(self.first_seen_time, "first_seen_time")
        )
        for field in ("prior_close", "median_dollar_volume"):
            value = money(getattr(self, field), field)
            if value < 0:
                raise ValueError(f"{field} must not be negative; got {value}")
            object.__setattr__(self, field, value)


@dataclass(frozen=True, slots=True)
class UniverseFloors:
    """The frozen screening thresholds, recorded next to every universe."""

    min_prior_close: Decimal = Decimal("10")
    min_median_dollar_volume: Decimal = Decimal("10000000")
    max_symbols: int = 30

    def __post_init__(self) -> None:
        for field in ("min_prior_close", "min_median_dollar_volume"):
            value = money(getattr(self, field), field)
            if value < 0:
                raise ValueError(f"{field} must not be negative; got {value}")
            object.__setattr__(self, field, value)
        if self.max_symbols <= 0:
            raise ValueError(f"max_symbols must be positive; got {self.max_symbols!r}")
        if self.max_symbols > 30:
            raise ValueError(
                f"max_symbols must not exceed the design cap of 30; got {self.max_symbols!r}"
            )


DEFAULT_FLOORS = UniverseFloors()


@dataclass(frozen=True, slots=True)
class Exclusion:
    """Why one symbol is not in the set. Kept so a no-trade day is auditable.

    Every failed condition is recorded, not only the first. An unresolved
    corporate action is the one screen that can invalidate the numeric screens'
    own inputs, because an unadjusted close is what a pending split leaves
    behind, so a record showing only `below_price_floor` would read as routine
    exactly when the number is the untrustworthy part.
    """

    symbol: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FrozenUniverse:
    """The set that applies to the session after `as_of`."""

    as_of: datetime
    symbols: tuple[str, ...]
    #: Every feed behind the evidence considered, including excluded symbols.
    feeds: tuple[str, ...]
    floors: UniverseFloors
    used_static_fallback: bool
    fallback_list_hash: str | None
    universe_hash: str
    exclusions: tuple[Exclusion, ...]


class UniverseSource(Protocol):
    """Point-in-time screening facts, already restricted to an instant.

    `optionability_is_reconstructable` is an attribute rather than an argument
    to `build`, because whether optionability history exists is a property of
    the data behind the source, not a choice a caller should make per run.
    """

    optionability_is_reconstructable: bool

    def observations_as_of(self, as_of: datetime) -> Iterable[SymbolObservation]: ...


@dataclass(frozen=True, slots=True)
class ObservationSource:
    """A deterministic source over a fixed set of observations.

    Holds the whole history and answers an `as_of` question honestly, which is
    what a research fixture and a frozen-run replay both need.
    """

    observations: Sequence[SymbolObservation]
    optionability_is_reconstructable: bool = True

    def observations_as_of(self, as_of: datetime) -> tuple[SymbolObservation, ...]:
        cutoff = require_utc(as_of, "as_of")
        return tuple(item for item in self.observations if item.first_seen_time <= cutoff)


def build(
    as_of: datetime, source: UniverseSource, *, floors: UniverseFloors = DEFAULT_FLOORS
) -> FrozenUniverse:
    """Return the symbol set decided by the evidence available at `as_of`."""
    cutoff = require_utc(as_of, "as_of")
    fallback = not source.optionability_is_reconstructable
    latest = _latest_per_symbol(source.observations_as_of(cutoff), cutoff)

    qualified: list[SymbolObservation] = []
    exclusions: list[Exclusion] = []
    for observation in latest:
        reasons = _rejections(observation, floors, fallback)
        if reasons:
            exclusions.append(Exclusion(symbol=observation.symbol, reasons=reasons))
        else:
            qualified.append(observation)

    ranked = sorted(qualified, key=lambda item: (-item.median_dollar_volume, item.symbol))
    kept, cut = ranked[: floors.max_symbols], ranked[floors.max_symbols :]
    exclusions.extend(Exclusion(symbol=item.symbol, reasons=(OUTSIDE_CAP,)) for item in cut)

    symbols = tuple(item.symbol for item in kept)
    # Every feed that contributed evidence, not only the feeds behind the
    # survivors. A mixed-feed build whose odd feed sits among the screened out
    # names is still a mixed-feed build, and design section 4 wants a change of
    # feed to be impossible to miss rather than impossible to miss only when it
    # lands in the top cohort.
    feeds = tuple(sorted({item.feed for item in latest}))
    fallback_hash = static_fallback_hash() if fallback else None
    return FrozenUniverse(
        as_of=cutoff,
        symbols=symbols,
        feeds=feeds,
        floors=floors,
        used_static_fallback=fallback,
        fallback_list_hash=fallback_hash,
        universe_hash=_universe_hash(cutoff, symbols, feeds, floors, fallback, fallback_hash),
        exclusions=tuple(sorted(exclusions, key=lambda item: item.symbol)),
    )


def _latest_per_symbol(
    observations: Iterable[SymbolObservation], cutoff: datetime
) -> tuple[SymbolObservation, ...]:
    """The newest observation per symbol at or before `cutoff`.

    A later revision replaces an earlier one, which is how a symbol that was
    illiquid this morning can qualify this afternoon. Anything stamped after
    the cutoff is a source defect and stops the build.
    """
    newest: dict[str, SymbolObservation] = {}
    for observation in observations:
        if observation.first_seen_time > cutoff:
            raise LeakedObservationError(
                f"{observation.symbol}: first_seen_time "
                f"{observation.first_seen_time.isoformat()} is later than as_of "
                f"{cutoff.isoformat()}, so this row was not knowable when the "
                "universe was decided"
            )
        held = newest.get(observation.symbol)
        if held is None or observation.first_seen_time > held.first_seen_time:
            newest[observation.symbol] = observation
        elif observation.first_seen_time == held.first_seen_time and observation != held:
            raise AmbiguousObservationError(
                f"{observation.symbol}: two observations share first_seen_time "
                f"{observation.first_seen_time.isoformat()} and disagree, so which "
                "one describes the symbol at as_of is decided by the order the "
                "source returned them. The source must distinguish them"
            )
    return tuple(newest[symbol] for symbol in sorted(newest))


def _rejections(
    observation: SymbolObservation, floors: UniverseFloors, fallback: bool
) -> tuple[str, ...]:
    """Every condition this symbol fails, empty if it clears them all.

    Identity conditions come first, then optionability, then the numeric
    floors, because that is the order in which a reader should read them: a
    symbol whose identity is unresolved has numbers that may not mean what they
    say.
    """
    reasons: list[str] = []
    if not observation.active:
        reasons.append(INACTIVE)
    if not observation.tradable:
        reasons.append(NOT_TRADABLE)
    if observation.unresolved_corporate_action:
        reasons.append(UNRESOLVED_CORPORATE_ACTION)
    if fallback:
        # The list stands in for optionability evidence only.
        if observation.symbol not in STATIC_FALLBACK_SYMBOLS:
            reasons.append(OPTIONS_NOT_ENABLED)
    else:
        if not observation.options_enabled:
            reasons.append(OPTIONS_NOT_ENABLED)
        if not observation.near_money_quotes_7_to_21_dte:
            reasons.append(NO_QUOTED_EXPIRATION)
    if observation.prior_close < floors.min_prior_close:
        reasons.append(BELOW_PRICE_FLOOR)
    if observation.median_dollar_volume < floors.min_median_dollar_volume:
        reasons.append(BELOW_DOLLAR_VOLUME_FLOOR)
    return tuple(reasons)


def _universe_hash(
    as_of: datetime,
    symbols: tuple[str, ...],
    feeds: tuple[str, ...],
    floors: UniverseFloors,
    fallback: bool,
    fallback_hash: str | None,
) -> str:
    """Content address the decided set, not the evidence behind it.

    The address covers the instant, the ranked members, the feeds they came
    from, the floors, and the fallback disclosure. It deliberately does not
    cover the underlying observations, so two different bodies of evidence that
    rank to the same members under the same floors share an address. That is
    what AC-5 asks for, set identity, and it is a narrower guarantee than
    provenance; a run that needs provenance should address its inputs
    separately. Exclusions are audit detail and are not addressed either.
    """
    body = {
        "as_of": as_of.isoformat(),
        "symbols": list(symbols),
        "feeds": list(feeds),
        "min_prior_close": str(floors.min_prior_close),
        "min_median_dollar_volume": str(floors.min_median_dollar_volume),
        "max_symbols": floors.max_symbols,
        "used_static_fallback": fallback,
        "fallback_list_hash": fallback_hash,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
