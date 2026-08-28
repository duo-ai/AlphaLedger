"""Load and hash the committed, non-secret operational configuration.

The four section records live here rather than importing research or execution
records. Consumers adapt them at their own boundary, which keeps this shared
layer dependent only on :mod:`alphaledger.domain`. Universe and feature have
merged-code defaults checked by tests. Risk and session have no merged-code
counterpart yet, so there is nothing for those two sections to drift from.

Parsing uses Python's standard-library :mod:`tomllib`. It is available before
any third-party dependency and preserves TOML floats as floats, allowing money
fields to reject them through the domain's exact-money validator.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import cast

from alphaledger.domain import money

__all__ = [
    "FeatureConfig",
    "FrozenConfig",
    "RiskConfig",
    "SessionConfig",
    "UniverseConfig",
    "config_hash",
    "load",
]


def _set(instance: object, field: str, value: object) -> None:
    object.__setattr__(instance, field, value)


def _whole_number(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be a whole number; got {value!r}")
    if value < minimum:
        raise ValueError(f"{field} must be at least {minimum}; got {value!r}")
    return value


def _real_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be a real number; got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite; got {value!r}")
    return number


def _exact_decimal(value: object, field: str) -> Decimal:
    """Parse a non-money decimal without imposing the money exponent."""
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


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be true or false; got {value!r}")
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string; got {value!r}")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{field} must be an array of strings; got {type(value).__name__}")
    items = tuple(_nonempty_string(item, f"{field}[{index}]") for index, item in enumerate(value))
    if len(items) != len(set(items)):
        raise ValueError(f"{field} must not contain duplicate values; got {items!r}")
    return items


def _string_mapping(value: object, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a table of strings; got {type(value).__name__}")
    copied: dict[str, str] = {}
    for key, item in value.items():
        name = _nonempty_string(key, f"{field} key")
        copied[name] = _nonempty_string(item, f"{field}[{name}]")
    return MappingProxyType(copied)


def _scan_time(value: str, field: str) -> None:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use HH:MM; got {value!r}") from exc
    if parsed.second or parsed.microsecond or value != f"{parsed.hour:02}:{parsed.minute:02}":
        raise ValueError(f"{field} must use HH:MM; got {value!r}")


@dataclass(frozen=True, slots=True)
class UniverseConfig:
    """Frozen universe thresholds loaded from ``universe.toml``."""

    min_prior_close: Decimal
    min_median_dollar_volume: Decimal
    max_symbols: int

    def __post_init__(self) -> None:
        for field in ("min_prior_close", "min_median_dollar_volume"):
            value = money(getattr(self, field), field)
            if value < 0:
                raise ValueError(f"{field} must not be negative; got {value}")
            _set(self, field, value)
        _set(self, "max_symbols", _whole_number(self.max_symbols, "max_symbols", minimum=1))
        if self.max_symbols > 30:
            raise ValueError(
                f"max_symbols must not exceed the design cap of 30; got {self.max_symbols!r}"
            )


@dataclass(frozen=True, slots=True)
class FeatureConfig:
    """Frozen price and volume feature parameters from ``feature.toml``."""

    lookback_sessions: int
    residual_volatility_sessions: int
    abnormal_volume_sessions: int
    atr_sessions: int
    extreme_sessions: int
    min_sector_peers: int
    winsor_lower: float
    winsor_upper: float
    sector_by_symbol: Mapping[str, str]

    def __post_init__(self) -> None:
        for field in (
            "lookback_sessions",
            "residual_volatility_sessions",
            "abnormal_volume_sessions",
            "atr_sessions",
            "extreme_sessions",
            "min_sector_peers",
        ):
            _set(self, field, _whole_number(getattr(self, field), field, minimum=1))
        for field in ("winsor_lower", "winsor_upper"):
            _set(self, field, _real_number(getattr(self, field), field))
        if self.lookback_sessions < max(self.residual_volatility_sessions, 5):
            raise ValueError(
                f"lookback_sessions {self.lookback_sessions} is shorter than the "
                f"{max(self.residual_volatility_sessions, 5)} residual sessions the "
                "features derived from it need"
            )
        if not self.winsor_lower < self.winsor_upper:
            raise ValueError(
                f"winsor_lower {self.winsor_lower} must be below winsor_upper {self.winsor_upper}"
            )
        _set(self, "sector_by_symbol", _string_mapping(self.sector_by_symbol, "sector_by_symbol"))


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """Frozen entry-risk policy loaded from ``risk.toml``."""

    maximum_loss_fraction_per_new_trade: Decimal
    maximum_concurrent_positions: int
    max_contracts_per_structure: int
    smoke_test_max_contracts: int
    require_defined_risk: bool
    require_risk_token: bool
    require_human_paper_arm: bool
    start_at_half_risk: bool

    def __post_init__(self) -> None:
        fraction = _exact_decimal(
            self.maximum_loss_fraction_per_new_trade,
            "maximum_loss_fraction_per_new_trade",
        )
        if not Decimal(0) < fraction <= Decimal(1):
            raise ValueError(
                "maximum_loss_fraction_per_new_trade must be above zero and no greater "
                f"than one; got {fraction}"
            )
        _set(self, "maximum_loss_fraction_per_new_trade", fraction)
        for field in (
            "maximum_concurrent_positions",
            "max_contracts_per_structure",
            "smoke_test_max_contracts",
        ):
            _set(self, field, _whole_number(getattr(self, field), field, minimum=1))
        if self.smoke_test_max_contracts != 1:
            raise ValueError(
                "smoke_test_max_contracts must remain at the one-contract safety cap; "
                f"got {self.smoke_test_max_contracts!r}"
            )
        if self.smoke_test_max_contracts > self.max_contracts_per_structure:
            raise ValueError("smoke_test_max_contracts must not exceed max_contracts_per_structure")
        for field in (
            "require_defined_risk",
            "require_risk_token",
            "require_human_paper_arm",
            "start_at_half_risk",
        ):
            _set(self, field, _boolean(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """Frozen session cadence and allowlist loaded from ``session.toml``."""

    timezone: str
    scheduled_scans: tuple[str, ...]
    no_new_entry_first_minutes: int
    no_new_entry_final_minutes: int
    strategy_allowlist: tuple[str, ...]
    dte_min: int
    dte_max: int

    def __post_init__(self) -> None:
        _set(self, "timezone", _nonempty_string(self.timezone, "timezone"))
        scans = _string_tuple(self.scheduled_scans, "scheduled_scans")
        if not scans:
            raise ValueError("scheduled_scans must contain at least one scan time")
        for index, value in enumerate(scans):
            _scan_time(value, f"scheduled_scans[{index}]")
        _set(self, "scheduled_scans", scans)
        for field in ("no_new_entry_first_minutes", "no_new_entry_final_minutes"):
            _set(self, field, _whole_number(getattr(self, field), field))
        allowlist = _string_tuple(self.strategy_allowlist, "strategy_allowlist")
        if not allowlist:
            raise ValueError("strategy_allowlist must contain at least one defined-risk structure")
        _set(self, "strategy_allowlist", allowlist)
        _set(self, "dte_min", _whole_number(self.dte_min, "dte_min", minimum=1))
        _set(self, "dte_max", _whole_number(self.dte_max, "dte_max", minimum=1))
        if self.dte_min > self.dte_max:
            raise ValueError(f"dte_min {self.dte_min} must not exceed dte_max {self.dte_max}")


@dataclass(frozen=True, slots=True)
class FrozenConfig:
    """All committed sections and their canonical SHA-256 content hash."""

    universe: UniverseConfig
    feature: FeatureConfig
    risk: RiskConfig
    session: SessionConfig
    frozen_config_hash: str

    def __post_init__(self) -> None:
        expected = _content_hash(self.universe, self.feature, self.risk, self.session)
        if self.frozen_config_hash != expected:
            raise ValueError(
                f"frozen_config_hash does not match the loaded configuration; expected {expected}"
            )


_UNIVERSE_KEYS = frozenset({"min_prior_close", "min_median_dollar_volume", "max_symbols"})
_FEATURE_KEYS = frozenset(
    {
        "lookback_sessions",
        "residual_volatility_sessions",
        "abnormal_volume_sessions",
        "atr_sessions",
        "extreme_sessions",
        "min_sector_peers",
        "winsor_lower",
        "winsor_upper",
        "sector_by_symbol",
    }
)
_RISK_KEYS = frozenset(
    {
        "maximum_loss_fraction_per_new_trade",
        "maximum_concurrent_positions",
        "max_contracts_per_structure",
        "smoke_test_max_contracts",
        "require_defined_risk",
        "require_risk_token",
        "require_human_paper_arm",
        "start_at_half_risk",
    }
)
_SESSION_KEYS = frozenset(
    {
        "timezone",
        "scheduled_scans",
        "no_new_entry_first_minutes",
        "no_new_entry_final_minutes",
        "strategy_allowlist",
        "dte_min",
        "dte_max",
    }
)


def _read(directory: Path, filename: str, expected_keys: frozenset[str]) -> dict[str, object]:
    path = directory / filename
    with path.open("rb") as stream:
        values: dict[str, object] = tomllib.load(stream)
    actual_keys = frozenset(values)
    unknown = sorted(actual_keys - expected_keys)
    if unknown:
        raise ValueError(f"{filename} contains unknown key {unknown[0]!r}")
    missing = sorted(expected_keys - actual_keys)
    if missing:
        raise ValueError(f"{filename} is missing required key {missing[0]!r}")
    return values


def _load_universe(directory: Path) -> UniverseConfig:
    values = _read(directory, "universe.toml", _UNIVERSE_KEYS)
    return UniverseConfig(
        min_prior_close=cast(Decimal, values["min_prior_close"]),
        min_median_dollar_volume=cast(Decimal, values["min_median_dollar_volume"]),
        max_symbols=cast(int, values["max_symbols"]),
    )


def _load_feature(directory: Path) -> FeatureConfig:
    values = _read(directory, "feature.toml", _FEATURE_KEYS)
    return FeatureConfig(
        lookback_sessions=cast(int, values["lookback_sessions"]),
        residual_volatility_sessions=cast(int, values["residual_volatility_sessions"]),
        abnormal_volume_sessions=cast(int, values["abnormal_volume_sessions"]),
        atr_sessions=cast(int, values["atr_sessions"]),
        extreme_sessions=cast(int, values["extreme_sessions"]),
        min_sector_peers=cast(int, values["min_sector_peers"]),
        winsor_lower=cast(float, values["winsor_lower"]),
        winsor_upper=cast(float, values["winsor_upper"]),
        sector_by_symbol=cast(Mapping[str, str], values["sector_by_symbol"]),
    )


def _load_risk(directory: Path) -> RiskConfig:
    values = _read(directory, "risk.toml", _RISK_KEYS)
    return RiskConfig(
        maximum_loss_fraction_per_new_trade=cast(
            Decimal, values["maximum_loss_fraction_per_new_trade"]
        ),
        maximum_concurrent_positions=cast(int, values["maximum_concurrent_positions"]),
        max_contracts_per_structure=cast(int, values["max_contracts_per_structure"]),
        smoke_test_max_contracts=cast(int, values["smoke_test_max_contracts"]),
        require_defined_risk=cast(bool, values["require_defined_risk"]),
        require_risk_token=cast(bool, values["require_risk_token"]),
        require_human_paper_arm=cast(bool, values["require_human_paper_arm"]),
        start_at_half_risk=cast(bool, values["start_at_half_risk"]),
    )


def _load_session(directory: Path) -> SessionConfig:
    values = _read(directory, "session.toml", _SESSION_KEYS)
    return SessionConfig(
        timezone=cast(str, values["timezone"]),
        scheduled_scans=cast(tuple[str, ...], values["scheduled_scans"]),
        no_new_entry_first_minutes=cast(int, values["no_new_entry_first_minutes"]),
        no_new_entry_final_minutes=cast(int, values["no_new_entry_final_minutes"]),
        strategy_allowlist=cast(tuple[str, ...], values["strategy_allowlist"]),
        dte_min=cast(int, values["dte_min"]),
        dte_max=cast(int, values["dte_max"]),
    )


def _decimal_string(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _content_hash(
    universe: UniverseConfig,
    feature: FeatureConfig,
    risk: RiskConfig,
    session: SessionConfig,
) -> str:
    content = {
        "feature": {
            "abnormal_volume_sessions": feature.abnormal_volume_sessions,
            "atr_sessions": feature.atr_sessions,
            "extreme_sessions": feature.extreme_sessions,
            "lookback_sessions": feature.lookback_sessions,
            "min_sector_peers": feature.min_sector_peers,
            "residual_volatility_sessions": feature.residual_volatility_sessions,
            "sector_by_symbol": dict(sorted(feature.sector_by_symbol.items())),
            "winsor_lower": feature.winsor_lower,
            "winsor_upper": feature.winsor_upper,
        },
        "risk": {
            "max_contracts_per_structure": risk.max_contracts_per_structure,
            "maximum_concurrent_positions": risk.maximum_concurrent_positions,
            "maximum_loss_fraction_per_new_trade": _decimal_string(
                risk.maximum_loss_fraction_per_new_trade
            ),
            "require_defined_risk": risk.require_defined_risk,
            "require_human_paper_arm": risk.require_human_paper_arm,
            "require_risk_token": risk.require_risk_token,
            "smoke_test_max_contracts": risk.smoke_test_max_contracts,
            "start_at_half_risk": risk.start_at_half_risk,
        },
        "session": {
            "dte_max": session.dte_max,
            "dte_min": session.dte_min,
            "no_new_entry_final_minutes": session.no_new_entry_final_minutes,
            "no_new_entry_first_minutes": session.no_new_entry_first_minutes,
            "scheduled_scans": session.scheduled_scans,
            "strategy_allowlist": session.strategy_allowlist,
            "timezone": session.timezone,
        },
        "universe": {
            "max_symbols": universe.max_symbols,
            "min_median_dollar_volume": _decimal_string(universe.min_median_dollar_volume),
            "min_prior_close": _decimal_string(universe.min_prior_close),
        },
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load(directory: Path = Path("config")) -> FrozenConfig:
    """Load all four files, failing closed if any file or value is invalid."""
    universe = _load_universe(directory)
    feature = _load_feature(directory)
    risk = _load_risk(directory)
    session = _load_session(directory)
    digest = _content_hash(universe, feature, risk, session)
    return FrozenConfig(
        universe=universe,
        feature=feature,
        risk=risk,
        session=session,
        frozen_config_hash=digest,
    )


def config_hash(config: FrozenConfig) -> str:
    """Recompute the stable content hash without including the stored hash."""
    return _content_hash(config.universe, config.feature, config.risk, config.session)
