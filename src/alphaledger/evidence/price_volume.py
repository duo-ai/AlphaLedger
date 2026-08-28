"""Residual price and volume features, from design section 5.1.

This family is the control in the comparison that decides whether the news
family adds anything, so its entire value lies in being a strict function of
past observations. Every number here is computed from bars the caller has
already restricted to `as_of`, and a bar that was not knowable then stops the
build rather than being dropped, because a silent drop leaves a caller
believing a cutoff was honoured that was never checked.

The model is a rolling, robust market and sector demeaning. For each session
the residual return is the symbol's return minus the median return of its
sector peers, and the median is used rather than a mean because one peer with a
corporate action should not move the whole cross-section. A sector too thin to
be informative falls back to the whole panel and says so with a flag. No betas
are fitted: a regression would add configuration that has not been selected on
development data, and the median demeaning is already a strict function of
past observations.

Three rules hold everywhere in this module:

A feature that cannot be computed is absent from the output and named in a
quality flag. It is never an imputed zero, because a zero is a value and a
missing feature is not. `EvidenceCard` rejects NaN outright, so a zero
denominator, which is routine here, has to be handled rather than produced.

Winsorization limits, lookbacks, and the sector map are configuration, not
judgment. They are versioned, and `feature_version` changes whenever any of
them changes.

Nothing reads a clock. Rebuilding a past `as_of` from cached bars has to give
the same numbers a year later, which it cannot do if anything inside depends
on when it ran.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from alphaledger.domain.contracts import money, require_utc

__all__ = [
    "ABNORMAL_VOLUME_DAILY_BASELINE",
    "INSUFFICIENT_HISTORY",
    "NO_EVENT_TIME",
    "NO_QUALIFYING_DATA",
    "SECTOR_FALLBACK_MARKET",
    "WINSORIZED",
    "ZERO_DENOMINATOR",
    "AmbiguousBarError",
    "Bar",
    "FeatureBlock",
    "FeatureConfig",
    "LeakedBarError",
    "build",
]

INSUFFICIENT_HISTORY = "insufficient_history"
ZERO_DENOMINATOR = "zero_denominator"
WINSORIZED = "winsorized"
SECTOR_FALLBACK_MARKET = "sector_fallback_market"
ABNORMAL_VOLUME_DAILY_BASELINE = "abnormal_volume_daily_baseline"
NO_EVENT_TIME = "no_event_time"
NO_QUALIFYING_DATA = "no_qualifying_data"

# Proximity is a position inside its own window, already bounded to [0, 1], so
# clipping it to a return-shaped limit would distort rather than protect.
UNWINSORIZED_FEATURES = frozenset({"proximity_to_extreme"})


class LeakedBarError(ValueError):
    """A bar in the input was not knowable at `as_of`."""


class AmbiguousBarError(ValueError):
    """Two bars describe one symbol's session and disagree.

    Raised rather than resolved, for the same reason the universe builder
    refuses a tied timestamp: choosing between them would make the features
    depend on the order the panel was assembled in.
    """


@dataclass(frozen=True, slots=True)
class Bar:
    """One session's prices and volume for one symbol."""

    symbol: str
    feed: str
    session: datetime
    first_seen_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        for name in ("symbol", "feed"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must be recorded; it is never defaulted")
        for name in ("session", "first_seen_time"):
            object.__setattr__(self, name, require_utc(getattr(self, name), name))
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, money(getattr(self, name), name))
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise TypeError(f"volume must be a whole number of shares; got {self.volume!r}")
        if self.volume < 0:
            raise ValueError(f"volume must not be negative; got {self.volume!r}")
        if self.high < self.low:
            raise ValueError(
                f"high {self.high} is below low {self.low} for {self.symbol}; the bar is malformed"
            )


@dataclass(frozen=True, slots=True)
class FeatureConfig:
    """Frozen feature configuration. Any change changes `feature_version`."""

    lookback_sessions: int = 60
    residual_volatility_sessions: int = 20
    abnormal_volume_sessions: int = 20
    atr_sessions: int = 14
    extreme_sessions: int = 20
    min_sector_peers: int = 2
    winsor_lower: float = -5.0
    winsor_upper: float = 5.0
    sector_by_symbol: Mapping[str, str] = MappingProxyType({})
    feature_version: str = field(init=False, default="")

    def __post_init__(self) -> None:
        for name in (
            "lookback_sessions",
            "residual_volatility_sessions",
            "abnormal_volume_sessions",
            "atr_sessions",
            "extreme_sessions",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive number of sessions; got {value!r}")
        if self.min_sector_peers < 1:
            raise ValueError(
                f"min_sector_peers must be at least one; got {self.min_sector_peers!r}"
            )
        for name in ("winsor_lower", "winsor_upper"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{name} must be a real number; got {value!r}")
        if not self.winsor_lower < self.winsor_upper:
            raise ValueError(
                f"winsor_lower {self.winsor_lower} must be below winsor_upper "
                f"{self.winsor_upper}; inverted bounds would clip every feature to a "
                "single point while looking like configuration"
            )
        sectors = MappingProxyType({str(k): str(v) for k, v in dict(self.sector_by_symbol).items()})
        object.__setattr__(self, "sector_by_symbol", sectors)
        object.__setattr__(self, "feature_version", self._version())

    def _version(self) -> str:
        body = {
            "lookback_sessions": self.lookback_sessions,
            "residual_volatility_sessions": self.residual_volatility_sessions,
            "abnormal_volume_sessions": self.abnormal_volume_sessions,
            "atr_sessions": self.atr_sessions,
            "extreme_sessions": self.extreme_sessions,
            "min_sector_peers": self.min_sector_peers,
            "winsor_lower": repr(self.winsor_lower),
            "winsor_upper": repr(self.winsor_upper),
            "sector_by_symbol": dict(sorted(self.sector_by_symbol.items())),
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return "pv-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class FeatureBlock:
    """The features for one symbol at one instant, with why any are missing."""

    symbol: str
    as_of: datetime
    features: Mapping[str, float]
    quality_flags: tuple[str, ...]
    feature_version: str
    winsorization: tuple[float, float]


def build(
    symbol: str,
    as_of: datetime,
    bars: Iterable[Bar],
    config: FeatureConfig,
    *,
    event_time: datetime | None = None,
) -> FeatureBlock:
    """Return the residual price and volume block for `symbol` at `as_of`.

    `bars` is the panel the caller has already restricted to `as_of`, covering
    the symbol and its peers. A bar first seen later than `as_of` is a defect
    in whatever assembled the panel and stops the build.
    """
    cutoff = require_utc(as_of, "as_of")
    series = _series(bars, cutoff)
    flags: list[str] = []

    own = series.get(symbol, ())
    if not own:
        return _empty(symbol, cutoff, config, (NO_QUALIFYING_DATA,))

    peers = _peers(symbol, series, config, flags)
    residuals = _residuals(own, peers, config)
    features: dict[str, float] = {}

    _returns_features(features, residuals, flags)
    _gap_feature(features, symbol, own, peers, flags)
    _volatility_feature(features, residuals, config, flags)
    _volume_feature(features, own, config, flags)
    _range_feature(features, own, config, flags)
    _extreme_feature(features, own, config, flags)
    _event_feature(features, own, residuals, event_time, flags)

    return FeatureBlock(
        symbol=symbol,
        as_of=cutoff,
        features=MappingProxyType(_winsorized(features, config, flags)),
        quality_flags=tuple(sorted(set(flags))),
        feature_version=config.feature_version,
        winsorization=(config.winsor_lower, config.winsor_upper),
    )


def _empty(
    symbol: str, as_of: datetime, config: FeatureConfig, flags: tuple[str, ...]
) -> FeatureBlock:
    """An empty block is an answer. The forecast layer reads it as ineligible."""
    return FeatureBlock(
        symbol=symbol,
        as_of=as_of,
        features=MappingProxyType({}),
        quality_flags=flags,
        feature_version=config.feature_version,
        winsorization=(config.winsor_lower, config.winsor_upper),
    )


def _series(bars: Iterable[Bar], cutoff: datetime) -> dict[str, tuple[Bar, ...]]:
    """Bars per symbol, session ordered, rejecting anything unknowable."""
    held: dict[tuple[str, datetime], Bar] = {}
    for item in bars:
        if item.first_seen_time > cutoff:
            raise LeakedBarError(
                f"{item.symbol}: first_seen_time {item.first_seen_time.isoformat()} is "
                f"later than as_of {cutoff.isoformat()}, so this bar was not knowable "
                "when the features are claimed to have been built"
            )
        key = (item.symbol, item.session)
        seen = held.get(key)
        if seen is None:
            held[key] = item
        elif seen != item:
            raise AmbiguousBarError(
                f"{item.symbol}: two bars describe the session "
                f"{item.session.isoformat()} and disagree, so which one the features "
                "use would be decided by the order the panel was assembled"
            )
    grouped: dict[str, list[Bar]] = {}
    for (name, _), item in sorted(held.items(), key=lambda entry: (entry[0][0], entry[0][1])):
        grouped.setdefault(name, []).append(item)
    return {name: tuple(items) for name, items in grouped.items()}


def _peers(
    symbol: str,
    series: Mapping[str, Sequence[Bar]],
    config: FeatureConfig,
    flags: list[str],
) -> tuple[tuple[Bar, ...], ...]:
    """The sector peer series, falling back to the whole panel when too thin."""
    sector = config.sector_by_symbol.get(symbol)
    others = sorted(name for name in series if name != symbol)
    in_sector = [
        name
        for name in others
        if sector is not None and config.sector_by_symbol.get(name) == sector
    ]
    if len(in_sector) >= config.min_sector_peers:
        return tuple(tuple(series[name]) for name in in_sector)
    flags.append(SECTOR_FALLBACK_MARKET)
    return tuple(tuple(series[name]) for name in others)


def _return_by_session(bars: Sequence[Bar]) -> dict[datetime, float]:
    """Close to close returns, keyed by the session they belong to."""
    out: dict[datetime, float] = {}
    for previous, current in itertools.pairwise(bars):
        if previous.close == 0:
            continue
        out[current.session] = float(current.close / previous.close) - 1.0
    return out


def _gap_by_session(bars: Sequence[Bar]) -> dict[datetime, float]:
    """Opening gaps against the prior close, keyed by session."""
    out: dict[datetime, float] = {}
    for previous, current in itertools.pairwise(bars):
        if previous.close == 0:
            continue
        out[current.session] = float(current.open / previous.close) - 1.0
    return out


def _demeaned(
    own: Mapping[datetime, float], peers: Iterable[Mapping[datetime, float]]
) -> list[tuple[datetime, float]]:
    """Own value minus the peer median, session by session, in time order."""
    peer_values = list(peers)
    out: list[tuple[datetime, float]] = []
    for session in sorted(own):
        cross_section = [values[session] for values in peer_values if session in values]
        centre = statistics.median(cross_section) if cross_section else 0.0
        out.append((session, own[session] - centre))
    return out


def _residuals(
    own: Sequence[Bar], peers: Sequence[Sequence[Bar]], config: FeatureConfig
) -> list[float]:
    """Residual returns in time order, capped at the model lookback."""
    demeaned = _demeaned(_return_by_session(own), [_return_by_session(peer) for peer in peers])
    return [value for _, value in demeaned][-config.lookback_sessions :]


def _returns_features(
    features: dict[str, float], residuals: Sequence[float], flags: list[str]
) -> None:
    if residuals:
        features["residual_return_1s"] = residuals[-1]
    else:
        flags.append(f"{INSUFFICIENT_HISTORY}:residual_return_1s")
    if len(residuals) >= 5:
        features["residual_return_5s"] = sum(residuals[-5:])
    else:
        flags.append(f"{INSUFFICIENT_HISTORY}:residual_return_5s")


def _gap_feature(
    features: dict[str, float],
    symbol: str,
    own: Sequence[Bar],
    peers: Sequence[Sequence[Bar]],
    flags: list[str],
) -> None:
    demeaned = _demeaned(_gap_by_session(own), [_gap_by_session(peer) for peer in peers])
    if demeaned:
        features["opening_gap_residual"] = demeaned[-1][1]
    else:
        flags.append(f"{INSUFFICIENT_HISTORY}:opening_gap_residual")


def _volatility_feature(
    features: dict[str, float], residuals: Sequence[float], config: FeatureConfig, flags: list[str]
) -> None:
    window = residuals[-config.residual_volatility_sessions :]
    if len(window) < config.residual_volatility_sessions or len(window) < 2:
        flags.append(f"{INSUFFICIENT_HISTORY}:residual_return_zscore")
        return
    spread = statistics.stdev(window)
    if spread == 0.0:
        flags.append(f"{ZERO_DENOMINATOR}:residual_return_zscore")
        return
    features["residual_return_zscore"] = residuals[-1] / spread


def _volume_feature(
    features: dict[str, float], own: Sequence[Bar], config: FeatureConfig, flags: list[str]
) -> None:
    # Design section 5.1 prefers a time-of-day baseline where intraday data
    # exists. It does not here, so the daily baseline is used and disclosed
    # rather than presented as the intended comparison.
    flags.append(ABNORMAL_VOLUME_DAILY_BASELINE)
    baseline = [item.volume for item in own[:-1]][-config.abnormal_volume_sessions :]
    if len(baseline) < config.abnormal_volume_sessions:
        flags.append(f"{INSUFFICIENT_HISTORY}:abnormal_volume")
        return
    centre = statistics.median(baseline)
    if centre == 0:
        flags.append(f"{ZERO_DENOMINATOR}:abnormal_volume")
        return
    features["abnormal_volume"] = own[-1].volume / centre - 1.0


def _true_range(previous: Bar, current: Bar) -> float:
    return float(
        max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
    )


def _range_feature(
    features: dict[str, float], own: Sequence[Bar], config: FeatureConfig, flags: list[str]
) -> None:
    ranges = [_true_range(previous, current) for previous, current in itertools.pairwise(own[:-1])][
        -config.atr_sessions :
    ]
    if len(ranges) < config.atr_sessions:
        flags.append(f"{INSUFFICIENT_HISTORY}:range_over_atr")
        return
    average_true_range = statistics.fmean(ranges)
    if average_true_range == 0.0:
        flags.append(f"{ZERO_DENOMINATOR}:range_over_atr")
        return
    features["range_over_atr"] = float(own[-1].high - own[-1].low) / average_true_range


def _extreme_feature(
    features: dict[str, float], own: Sequence[Bar], config: FeatureConfig, flags: list[str]
) -> None:
    window = own[-config.extreme_sessions :]
    if len(window) < config.extreme_sessions:
        flags.append(f"{INSUFFICIENT_HISTORY}:proximity_to_extreme")
        return
    lowest = min(item.low for item in window)
    highest = max(item.high for item in window)
    if highest == lowest:
        flags.append(f"{ZERO_DENOMINATOR}:proximity_to_extreme")
        return
    features["proximity_to_extreme"] = float((own[-1].close - lowest) / (highest - lowest))


def _event_feature(
    features: dict[str, float],
    own: Sequence[Bar],
    residuals: Sequence[float],
    event_time: datetime | None,
    flags: list[str],
) -> None:
    if event_time is None:
        flags.append(NO_EVENT_TIME)
        return
    event = require_utc(event_time, "event_time")
    sessions = [item.session for item in own][-len(residuals) :] if residuals else []
    window = [value for session, value in zip(sessions, residuals, strict=True) if session > event]
    if not window:
        flags.append(f"{INSUFFICIENT_HISTORY}:cumulative_abnormal_return")
        return
    features["cumulative_abnormal_return"] = sum(window)


def _winsorized(
    features: Mapping[str, float], config: FeatureConfig, flags: list[str]
) -> dict[str, float]:
    """Clip to the configured limits, recording every feature that was clipped."""
    out: dict[str, float] = {}
    for name in sorted(features):
        value = features[name]
        if name in UNWINSORIZED_FEATURES:
            out[name] = value
            continue
        clipped = min(max(value, config.winsor_lower), config.winsor_upper)
        if clipped != value:
            flags.append(f"{WINSORIZED}:{name}")
        out[name] = clipped
    return out
