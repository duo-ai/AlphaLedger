"""Trade eligibility gates, design section 6.

`decide` evaluates the four gates computable from one forecast. Gates 5 and 6
are not: gate 5 is a property of the held out evaluation across all candidates,
and gate 6 is execution lane state this unit's path globs cannot reach. The
module says so through `UNEVALUATED_GATES` rather than letting a caller read
`eligible` as "cleared section 6", and AC-4a records why that is the honest
shape rather than a narrowing of convenience.

The single family case is the one worth reading twice. Design section 6 is
explicit that a missing news family does not silently downgrade to a price only
live trade, and that the price only output continues in a shadow book. That is
the difference between a gate that refuses and a gate that quietly lowers
itself, and it is the failure this file exists to make impossible.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from alphaledger.domain.contracts import Forecast
from alphaledger.forecast.eligibility import (
    EVALUATED_GATES,
    GATE_1_FAMILIES_DISAGREE,
    GATE_1_SINGLE_FAMILY_SHADOW,
    GATE_2_BELOW_FLOOR,
    GATE_2_BELOW_THRESHOLD,
    GATE_3_BELOW_COST_HURDLE,
    GATE_4_CALIBRATION,
    GATE_4_SAMPLE_SIZE,
    GATE_4_UNCERTAINTY,
    UNEVALUATED_GATES,
    EligibilityConfig,
    decide,
)

CONFIG = EligibilityConfig(
    p_up_floor=0.52,
    p_up_threshold=0.55,
    cost_hurdle=0.01,
    max_calibration_error=0.05,
    min_effective_sample_size=100.0,
    max_quantile_spread=0.40,
)

BOTH_UP: Mapping[str, float] = {"price_volume": 0.6, "news": 0.4}


def forecast(**overrides: object) -> Forecast:
    """A candidate that clears every gate unless a test moves one field."""
    settings: dict[str, object] = {
        "candidate_id": "ACME-2026-06-01",
        "horizon_sessions": 5,
        "p_up": 0.61,
        "expected_residual_return": 0.03,
        "quantiles": {"q10": -0.05, "q50": 0.03, "q90": 0.11},
        "contribution_by_family": {"price_volume": 0.6, "news": 0.4},
        "calibration_error": 0.02,
        "effective_sample_size": 250.0,
        "eligible": False,
        "rejection_reasons": ("undecided",),
        "model_version": "mdl-000000000000",
    }
    settings.update(overrides)
    return Forecast(**settings)  # type: ignore[arg-type]


# --- the gates this function does and does not evaluate -------------------


def test_the_module_names_the_gates_it_does_not_evaluate() -> None:
    """AC-4a. Section 6 lists six conditions and this function can compute
    four. Saying which two are missing is what stops a caller reading
    `eligible` as `cleared section 6`, and a constant is checkable where a
    docstring is not."""
    assert EVALUATED_GATES == (1, 2, 3, 4)
    assert UNEVALUATED_GATES == (5, 6)
    assert set(EVALUATED_GATES) | set(UNEVALUATED_GATES) == {1, 2, 3, 4, 5, 6}
    assert not set(EVALUATED_GATES) & set(UNEVALUATED_GATES)


def test_every_rejection_reason_names_a_gate_this_function_evaluates() -> None:
    """AC-4. A reason that named gate 5 or 6 would be claiming an evaluation
    that never happened."""
    reasons = (
        GATE_1_FAMILIES_DISAGREE,
        GATE_1_SINGLE_FAMILY_SHADOW,
        GATE_2_BELOW_FLOOR,
        GATE_2_BELOW_THRESHOLD,
        GATE_3_BELOW_COST_HURDLE,
        GATE_4_CALIBRATION,
        GATE_4_SAMPLE_SIZE,
        GATE_4_UNCERTAINTY,
    )
    for reason in reasons:
        gate = int(reason.split("_")[1])
        assert gate in EVALUATED_GATES, reason


# --- success --------------------------------------------------------------


def test_a_candidate_clearing_every_evaluated_gate_is_eligible() -> None:
    """AC-4. The eligible case carries no reason at all, so a reader never has
    to decide whether a reason on an eligible forecast was advisory."""
    decided = decide(forecast(), BOTH_UP, CONFIG)

    assert decided.eligible is True
    assert decided.rejection_reasons == ()


def test_deciding_changes_nothing_but_eligibility_and_its_reasons() -> None:
    """The gate reads a forecast; it does not revise one. A `decide` that
    adjusted a probability would be a second model nobody registered."""
    original = forecast()
    decided = decide(original, BOTH_UP, CONFIG)

    assert decided.p_up == original.p_up
    assert decided.expected_residual_return == original.expected_residual_return
    assert decided.quantiles == original.quantiles
    assert decided.contribution_by_family == original.contribution_by_family
    assert decided.calibration_error == original.calibration_error
    assert decided.effective_sample_size == original.effective_sample_size
    assert decided.model_version == original.model_version
    assert decided.candidate_id == original.candidate_id


# --- gate 1, family agreement ---------------------------------------------


def test_a_single_family_candidate_is_ineligible_and_named_as_shadow() -> None:
    """AC-5 and the no-trade case. Section 6 says the MVP does not silently
    downgrade to a price only live trade and that the price only output
    continues in a shadow book. Ineligible is the whole point: the alternative
    is a gate that lowers itself whenever the news family is unavailable, which
    is exactly when a price only signal is least worth trusting."""
    decided = decide(forecast(), {"price_volume": 0.6}, CONFIG)

    assert decided.eligible is False
    assert GATE_1_SINGLE_FAMILY_SHADOW in decided.rejection_reasons


def test_families_disagreeing_on_direction_is_a_different_reason() -> None:
    """AC-6. Two families pointing opposite ways is not the same failure as one
    family speaking alone, and a shared reason would make the two
    indistinguishable in the ledger."""
    decided = decide(forecast(), {"price_volume": 0.6, "news": -0.4}, CONFIG)

    assert decided.eligible is False
    assert GATE_1_FAMILIES_DISAGREE in decided.rejection_reasons
    assert GATE_1_SINGLE_FAMILY_SHADOW not in decided.rejection_reasons


def test_the_single_family_and_disagreement_reasons_are_distinct() -> None:
    """AC-6 states this directly, so it is asserted directly rather than left
    to follow from the two tests above."""
    assert GATE_1_SINGLE_FAMILY_SHADOW != GATE_1_FAMILIES_DISAGREE


def test_a_family_contributing_nothing_does_not_count_as_agreement() -> None:
    """A zero contribution is a family with no view, not a family that agrees.
    Counting it would let one real family plus one silent one clear a gate that
    exists to require two."""
    decided = decide(forecast(), {"price_volume": 0.6, "news": 0.0}, CONFIG)

    assert decided.eligible is False
    assert GATE_1_SINGLE_FAMILY_SHADOW in decided.rejection_reasons


# --- gate 2, probability ---------------------------------------------------


def test_a_probability_below_the_floor_is_ineligible_however_good_the_rest() -> None:
    """Section 6 calls the floor non-negotiable, so it is checked on its own
    and not folded into the threshold."""
    decided = decide(forecast(p_up=0.51), BOTH_UP, CONFIG)

    assert decided.eligible is False
    assert GATE_2_BELOW_FLOOR in decided.rejection_reasons


def test_a_probability_between_the_floor_and_the_threshold_is_still_refused() -> None:
    """The threshold is chosen on the calibration set and the floor is set
    before arm time. Clearing the second is not clearing the first."""
    decided = decide(forecast(p_up=0.53), BOTH_UP, CONFIG)

    assert decided.eligible is False
    assert GATE_2_BELOW_THRESHOLD in decided.rejection_reasons
    assert GATE_2_BELOW_FLOOR not in decided.rejection_reasons


def test_a_short_candidate_is_judged_on_its_own_direction() -> None:
    """A bearish candidate is confident when `p_up` is low. Judging it on
    `p_up` alone would refuse every short and call the model directionless."""
    decided = decide(
        forecast(p_up=0.39, expected_residual_return=-0.03),
        {"price_volume": -0.6, "news": -0.4},
        CONFIG,
    )

    assert decided.eligible is True
    assert decided.rejection_reasons == ()


# --- gate 3, cost hurdle ---------------------------------------------------


def test_an_expected_move_under_the_cost_hurdle_is_ineligible() -> None:
    """A forecast edge smaller than the round trip cost is not an edge. This is
    the gate that stops a technically correct signal becoming a losing trade."""
    decided = decide(forecast(expected_residual_return=0.005), BOTH_UP, CONFIG)

    assert decided.eligible is False
    assert GATE_3_BELOW_COST_HURDLE in decided.rejection_reasons


def test_the_cost_hurdle_is_judged_on_magnitude_not_sign() -> None:
    """A short with a large negative expected move clears a hurdle a long with
    the same magnitude clears. Comparing the signed value would pass every
    short automatically."""
    decided = decide(
        forecast(p_up=0.39, expected_residual_return=-0.005),
        {"price_volume": -0.6, "news": -0.4},
        CONFIG,
    )

    assert decided.eligible is False
    assert GATE_3_BELOW_COST_HURDLE in decided.rejection_reasons


# --- gate 4, uncertainty, sample size, calibration -------------------------


def test_a_calibration_error_over_its_frozen_limit_is_ineligible() -> None:
    decided = decide(forecast(calibration_error=0.20), BOTH_UP, CONFIG)

    assert decided.eligible is False
    assert GATE_4_CALIBRATION in decided.rejection_reasons


def test_an_effective_sample_size_under_its_floor_is_ineligible() -> None:
    """Overlapping labels make the row count a lie, which is why UNIT-027
    computes uniqueness at all. This gate is where that number earns its
    keep."""
    decided = decide(forecast(effective_sample_size=40.0), BOTH_UP, CONFIG)

    assert decided.eligible is False
    assert GATE_4_SAMPLE_SIZE in decided.rejection_reasons


def test_a_forecast_too_uncertain_to_act_on_is_ineligible() -> None:
    """A wide quantile band around a small expected move is a coin flip with a
    point estimate attached."""
    decided = decide(
        forecast(quantiles={"q10": -0.60, "q50": 0.03, "q90": 0.60}),
        BOTH_UP,
        CONFIG,
    )

    assert decided.eligible is False
    assert GATE_4_UNCERTAINTY in decided.rejection_reasons


# --- several gates at once -------------------------------------------------


def test_every_failing_gate_is_reported_not_only_the_first() -> None:
    """A candidate refused for one reason that is really refused for four would
    be fixed once and refused again, and the ledger would not show why."""
    decided = decide(
        forecast(p_up=0.50, expected_residual_return=0.001, calibration_error=0.9),
        {"price_volume": 0.6},
        CONFIG,
    )

    assert decided.eligible is False
    for reason in (
        GATE_1_SINGLE_FAMILY_SHADOW,
        GATE_2_BELOW_FLOOR,
        GATE_3_BELOW_COST_HURDLE,
        GATE_4_CALIBRATION,
    ):
        assert reason in decided.rejection_reasons


def test_the_reasons_are_ordered_and_carry_no_duplicates() -> None:
    """Two runs of one decision must produce one string, or a ledger diff
    reports a change that did not happen."""
    decided = decide(forecast(p_up=0.10, expected_residual_return=0.0001), BOTH_UP, CONFIG)

    assert list(decided.rejection_reasons) == sorted(set(decided.rejection_reasons))


# --- configuration ---------------------------------------------------------


def test_a_threshold_below_the_floor_is_refused() -> None:
    """The floor is non-negotiable, so a threshold under it would be a
    configuration that quietly disables it."""
    with pytest.raises(ValueError, match="floor"):
        EligibilityConfig(p_up_floor=0.60, p_up_threshold=0.55)


@pytest.mark.parametrize("probability", [-0.1, 1.1])
def test_a_floor_outside_zero_to_one_is_refused(probability: float) -> None:
    with pytest.raises(ValueError, match="p_up_floor"):
        EligibilityConfig(p_up_floor=probability)


def test_a_negative_cost_hurdle_is_refused() -> None:
    """A negative hurdle would make every candidate clear gate 3, which is the
    same as deleting it while leaving it visible in the code."""
    with pytest.raises(ValueError, match="cost_hurdle"):
        EligibilityConfig(cost_hurdle=-0.01)
