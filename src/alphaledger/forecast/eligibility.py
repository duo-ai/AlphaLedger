"""The trade eligibility gate from design section 6.

Section 6 lists six conditions a candidate must meet before it reaches
structure construction. This module evaluates the four that are computable from
one forecast, and says plainly which two it does not.

Gate 5, that the signal is not concentrated in one symbol, one week, or one
sector in the held-out evaluation, is a property of the evaluation across every
candidate rather than of any single one. A forecast cannot see the distribution
it belongs to, so a function taking one forecast cannot decide it. It belongs
with the baselines and ablations.

Gate 6, that current data, chain, account, and portfolio checks pass, is
execution-lane state. This unit owns `forecast/` and nothing else, and D-006
keeps account facts out of the coding agent's reach entirely, so a claim here
that the account was checked would be an assertion with no input behind it.

`EVALUATED_GATES` and `UNEVALUATED_GATES` exist so that boundary is checkable
by a test rather than only described here. `eligible` means "cleared every gate
this function evaluates", never "cleared section 6", and a caller that needs
the other two has to run them itself.

The single-family case deserves its own reading. Section 6 says the MVP does
not silently downgrade to a price-only live trade, and that the price-only
output continues in a shadow book until a separately predeclared fallback model
is validated. So a candidate whose news family is missing is refused, and its
reason names the shadow book rather than a generic failure. The failure this
prevents is a gate that lowers itself exactly when the evidence thins out,
which is when it is least safe to lower.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from alphaledger.domain.contracts import Forecast

__all__ = [
    "EVALUATED_GATES",
    "GATE_1_FAMILIES_DISAGREE",
    "GATE_1_SINGLE_FAMILY_SHADOW",
    "GATE_2_BELOW_FLOOR",
    "GATE_2_BELOW_THRESHOLD",
    "GATE_3_BELOW_COST_HURDLE",
    "GATE_4_CALIBRATION",
    "GATE_4_SAMPLE_SIZE",
    "GATE_4_UNCERTAINTY",
    "UNEVALUATED_GATES",
    "EligibilityConfig",
    "decide",
]

EVALUATED_GATES = (1, 2, 3, 4)
UNEVALUATED_GATES = (5, 6)

# Every reason begins `gate_<n>_` so a reader, and a test, can check that no
# reason claims a gate this module never evaluated.
GATE_1_SINGLE_FAMILY_SHADOW = "gate_1_single_family_shadow_book"
GATE_1_FAMILIES_DISAGREE = "gate_1_families_disagree_on_direction"
GATE_2_BELOW_FLOOR = "gate_2_below_non_negotiable_floor"
GATE_2_BELOW_THRESHOLD = "gate_2_below_calibrated_threshold"
GATE_3_BELOW_COST_HURDLE = "gate_3_expected_move_below_cost_hurdle"
GATE_4_CALIBRATION = "gate_4_calibration_error_above_limit"
GATE_4_SAMPLE_SIZE = "gate_4_effective_sample_size_below_floor"
GATE_4_UNCERTAINTY = "gate_4_quantile_spread_above_limit"


@dataclass(frozen=True, slots=True)
class EligibilityConfig:
    """The frozen thresholds the gates compare against.

    These arrive as a parameter rather than from `config/` because this unit's
    path globs cover `forecast/` only and no `config/model.toml` exists. D-017
    wants a threshold that explains a decision committed and hashed, so that is
    a recorded gap, and it is the same one UNIT-013 and UNIT-017 already carry.

    Every default is declared, not selected on data. Design section 4 requires
    selection on development data, registration as a trial, and a freeze before
    an autonomous session, and none of that has happened.
    """

    p_up_floor: float = 0.55
    p_up_threshold: float = 0.58
    cost_hurdle: float = 0.01
    max_calibration_error: float = 0.05
    min_effective_sample_size: float = 100.0
    max_quantile_spread: float = 0.40
    required_family_count: int = 2

    def __post_init__(self) -> None:
        for name in (
            "p_up_floor",
            "p_up_threshold",
            "cost_hurdle",
            "max_calibration_error",
            "min_effective_sample_size",
            "max_quantile_spread",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"{name} must be a real number; got {value!r}")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite; got {value!r}")
            object.__setattr__(self, name, float(value))

        for name in ("p_up_floor", "p_up_threshold"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a probability in [0, 1]; got {value!r}")
        if self.p_up_threshold < self.p_up_floor:
            raise ValueError(
                f"p_up_threshold {self.p_up_threshold!r} is below p_up_floor "
                f"{self.p_up_floor!r}. Section 6 calls the floor non-negotiable, so a "
                "threshold under it would disable the floor while leaving it visible"
            )
        for name in ("cost_hurdle", "max_calibration_error", "max_quantile_spread"):
            value = getattr(self, name)
            if value < 0.0:
                raise ValueError(
                    f"{name} must not be negative; got {value!r}. A negative bound would "
                    "pass every candidate, which deletes the gate without removing it"
                )
        if self.min_effective_sample_size < 0.0:
            raise ValueError(
                f"min_effective_sample_size must not be negative; got "
                f"{self.min_effective_sample_size!r}"
            )
        if isinstance(self.required_family_count, bool) or not isinstance(
            self.required_family_count, int
        ):
            raise TypeError(
                f"required_family_count must be a whole number; got {self.required_family_count!r}"
            )
        if self.required_family_count < 2:
            raise ValueError(
                f"required_family_count must be at least two; got "
                f"{self.required_family_count!r}. Gate 1 exists to require agreement "
                "between families, and a count below two is a gate that cannot refuse"
            )


def decide(
    forecast: Forecast,
    families: Mapping[str, float],
    config: EligibilityConfig,
) -> Forecast:
    """Return `forecast` with `eligible` and `rejection_reasons` settled.

    `families` maps each evidence family to its signed directional view for
    this candidate: positive for up, negative for down. A family absent from
    the mapping did not contribute, and a family present with zero has no view,
    which is not the same as agreeing.

    Every failing gate is reported, not only the first. A candidate refused for
    one reason when four apply would be corrected once, refused again, and the
    ledger would not show why.
    """
    reasons: set[str] = set()

    direction = _direction(forecast)
    voters = [value for value in families.values() if _sign(value) != 0]
    if len(voters) < config.required_family_count:
        # Named for the shadow book rather than for the missing family, because
        # section 6 does not merely refuse this case, it says where the output
        # goes instead.
        reasons.add(GATE_1_SINGLE_FAMILY_SHADOW)
    elif len({_sign(value) for value in voters}) > 1:
        reasons.add(GATE_1_FAMILIES_DISAGREE)

    confidence = forecast.p_up if direction >= 0 else 1.0 - forecast.p_up
    if confidence < config.p_up_floor:
        reasons.add(GATE_2_BELOW_FLOOR)
    elif confidence < config.p_up_threshold:
        reasons.add(GATE_2_BELOW_THRESHOLD)

    if abs(forecast.expected_residual_return) < config.cost_hurdle:
        reasons.add(GATE_3_BELOW_COST_HURDLE)

    if forecast.calibration_error > config.max_calibration_error:
        reasons.add(GATE_4_CALIBRATION)
    if forecast.effective_sample_size < config.min_effective_sample_size:
        reasons.add(GATE_4_SAMPLE_SIZE)
    if _spread(forecast) > config.max_quantile_spread:
        reasons.add(GATE_4_UNCERTAINTY)

    return _replace(forecast, eligible=not reasons, rejection_reasons=tuple(sorted(reasons)))


def _direction(forecast: Forecast) -> int:
    """Which way this candidate points, from the magnitude model.

    Taken from `expected_residual_return` rather than from `p_up` so a short is
    judged on its own confidence. Reading `p_up` alone would refuse every
    bearish candidate and make the model look directionless.
    """
    return _sign(forecast.expected_residual_return)


def _sign(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def _spread(forecast: Forecast) -> float:
    """The q10 to q90 band, or infinity when the band was not emitted.

    Missing quantiles fail the gate rather than skipping it. A forecast that
    could not say how uncertain it was is not a forecast that was certain, and
    treating an absent band as a narrow one is the most flattering possible
    reading of missing data.
    """
    try:
        low = forecast.quantiles["q10"]
        high = forecast.quantiles["q90"]
    except KeyError:
        return math.inf
    return high - low


def _replace(forecast: Forecast, *, eligible: bool, rejection_reasons: tuple[str, ...]) -> Forecast:
    """Rebuild the frozen record with the decision applied.

    `dataclasses.replace` is avoided because `Forecast` normalises several
    fields in `__post_init__`, and rebuilding from the current values keeps the
    round trip explicit and checkable field by field.
    """
    return Forecast(
        candidate_id=forecast.candidate_id,
        horizon_sessions=forecast.horizon_sessions,
        p_up=forecast.p_up,
        expected_residual_return=forecast.expected_residual_return,
        quantiles=dict(forecast.quantiles),
        contribution_by_family=dict(forecast.contribution_by_family),
        calibration_error=forecast.calibration_error,
        effective_sample_size=forecast.effective_sample_size,
        eligible=eligible,
        rejection_reasons=rejection_reasons,
        model_version=forecast.model_version,
    )
