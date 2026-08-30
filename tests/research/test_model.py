"""The pooled forecast, design section 6.

The fixture is a known linear relationship so every directional assertion has a
right answer rather than a plausible one: the outcome is a fixed positive
weight on one price feature and a fixed negative weight on one news feature,
with no noise, so a fit that recovers nothing is visibly wrong rather than
merely disappointing.

Three properties here exist because the corresponding mistake is routine.
Nothing from the test window may reach the fit, which is checked both by
refusing a fold whose own label lists overlap and by refusing supplied features
for a test label. The model's identity must not depend on the test window's
contents, which is why `model_version` excludes `fold_hash`. And a trial is
registered before any result exists, so an abandoned fit is still counted
against the multiple-testing budget.
"""

from __future__ import annotations

import pickle
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sklearn.linear_model import Ridge

from alphaledger.data.storage import AppendOnlyStore
from alphaledger.forecast.model import (
    UNDECIDED,
    LeakedFitError,
    ModelConfig,
    UncalibratedModelError,
    fit,
)
from alphaledger.forecast.registry import TrialRegistry, UnregisteredTrialError
from alphaledger.forecast.splits import Fold, Window

ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)
PRICE = ("residual_return_5s", "volume_z")
NEWS = ("direction_weighted", "novelty_weighted")

CONFIG = ModelConfig(
    feature_families={"price_volume": PRICE, "news": NEWS},
    feature_versions={"price_volume": "fv-price-0001", "news": "fv-news-0001"},
    horizon_sessions=5,
)


def at(days: int) -> datetime:
    return ORIGIN + timedelta(days=days)


def features_for(index: int) -> dict[str, float]:
    """A point whose outcome is exactly recoverable from two of its four features."""
    return {
        "residual_return_5s": (index % 7) / 7.0 - 0.5,
        "volume_z": (index % 5) / 5.0 - 0.5,
        "direction_weighted": (index % 3) / 3.0 - 0.5,
        "novelty_weighted": (index % 11) / 11.0 - 0.5,
    }


def outcome_for(index: int) -> float:
    """The relationship the fit has to recover: positive on price, negative on news."""
    point = features_for(index)
    return 0.20 * point["residual_return_5s"] - 0.10 * point["direction_weighted"]


def panel(
    count: int = 90,
) -> tuple[dict[str, dict[str, float]], dict[str, float], dict[str, float]]:
    features = {f"lbl-{index:03d}": features_for(index) for index in range(count)}
    outcomes = {f"lbl-{index:03d}": outcome_for(index) for index in range(count)}
    uniqueness = {f"lbl-{index:03d}": 1.0 for index in range(count)}
    return features, outcomes, uniqueness


def fold_over(
    *,
    train: tuple[str, ...],
    calibration: tuple[str, ...],
    test: tuple[str, ...] = (),
    index: int = 0,
) -> Fold:
    horizon = timedelta(days=5)
    return Fold(
        index=index,
        train=Window(start=at(0), end=at(60)),
        calibration=Window(start=at(70), end=at(90)),
        test=Window(start=at(100), end=at(120)),
        horizon=horizon,
        purge=timedelta(days=10),
        train_labels=train,
        calibration_labels=calibration,
        test_labels=test,
        purged=(),
    )


def ids(start: int, stop: int) -> tuple[str, ...]:
    return tuple(f"lbl-{index:03d}" for index in range(start, stop))


def registry() -> TrialRegistry:
    return TrialRegistry(AppendOnlyStore(Path(tempfile.mkdtemp()) / "trials.jsonl"))


class CapturingRegistry(TrialRegistry):
    """Records what `fit` actually passed, which `trials()` cannot show.

    `Trial` carries a `configuration_hash` and not the configuration itself, so
    the only way to observe AC-3's requirement is at the call boundary.
    """

    def __init__(self, store: AppendOnlyStore) -> None:
        super().__init__(store)
        self.configurations: list[Mapping[str, object]] = []
        self.purposes: list[str] = []

    def register(
        self, configuration: Mapping[str, object], purpose: str, registered_at: datetime
    ) -> object:
        self.configurations.append(dict(configuration))
        self.purposes.append(purpose)
        return super().register(configuration, purpose, registered_at)


def fitted(**overrides: object):  # type: ignore[no-untyped-def]
    """Fit the default fold, handing it only the labels that fold fits on.

    The restriction is the point rather than tidiness: `fit` refuses features
    for any label the fold places in neither its training nor its calibration
    window, so a caller has to say which labels belong to which fold instead of
    handing every fold the whole panel and letting each one select.
    """
    fold = overrides.pop("fold", fold_over(train=ids(0, 60), calibration=ids(60, 85)))
    features, outcomes, uniqueness = panel()
    usable = set(fold.train_labels) | set(fold.calibration_labels)  # type: ignore[union-attr]
    settings: dict[str, object] = {
        "fold": fold,
        "features": {key: value for key, value in features.items() if key in usable},
        "outcomes": outcomes,
        "uniqueness": uniqueness,
        "config": CONFIG,
        "registry": registry(),
        "registered_at": at(95),
    }
    settings.update(overrides)
    return fit(**settings)  # type: ignore[arg-type]


# --- success: the relationship is recovered -------------------------------


def test_the_fit_recovers_the_direction_of_a_known_linear_relationship() -> None:
    """The outcome is a positive weight on one price feature and a negative one
    on one news feature. A model that recovered neither would still emit a
    well-formed `Forecast`, which is why the sign is asserted and not merely
    the shape."""
    model = fitted()

    up = model.predict("ACME-up", {**features_for(0), "residual_return_5s": 0.5}, at(110))
    down = model.predict("ACME-down", {**features_for(0), "residual_return_5s": -0.5}, at(110))

    assert up.p_up > 0.5
    assert down.p_up < 0.5
    assert up.expected_residual_return > 0.0
    assert down.expected_residual_return < 0.0


def test_a_forecast_populates_every_field_rather_than_defaulting_one() -> None:
    """The contract says none is defaulted. A zero `effective_sample_size` or a
    missing quantile would sail through the frozen record and be read as a
    measurement."""
    emitted = fitted().predict("ACME", features_for(3), at(110))

    assert emitted.candidate_id == "ACME"
    assert emitted.horizon_sessions == CONFIG.horizon_sessions
    assert set(emitted.quantiles) == {"q10", "q50", "q90"}
    assert emitted.quantiles["q10"] <= emitted.quantiles["q50"] <= emitted.quantiles["q90"]
    assert emitted.effective_sample_size > 0.0
    assert emitted.calibration_error >= 0.0
    assert emitted.model_version


def test_an_emitted_forecast_is_undecided_rather_than_quietly_eligible() -> None:
    """`predict` does not run the section 6 gates, so it must not emit a record
    that reads as having passed them. The frozen record refuses an ineligible
    forecast with no reason, so the reason says exactly what has not happened
    yet."""
    emitted = fitted().predict("ACME", features_for(3), at(110))

    assert emitted.eligible is False
    assert emitted.rejection_reasons == (UNDECIDED,)


def test_contribution_names_both_families_and_neither_is_zero() -> None:
    """AC-8. A single blended number would make it impossible to say whether a
    trade was a news trade, which is the comparison the whole research lane
    exists to make."""
    emitted = fitted().predict("ACME", features_for(4), at(110))

    assert set(emitted.contribution_by_family) == {"price_volume", "news"}
    assert emitted.contribution_by_family["price_volume"] != 0.0
    assert emitted.contribution_by_family["news"] != 0.0


def test_a_family_contributing_nothing_attributes_nothing() -> None:
    """A contribution is a coefficient against a value, not a coefficient. With
    every price feature at zero the price family has contributed nothing, and a
    non-zero attribution would be reporting the model's shape rather than this
    candidate's evidence."""
    silent = {**features_for(4), "residual_return_5s": 0.0, "volume_z": 0.0}

    emitted = fitted().predict("ACME", silent, at(110))

    assert emitted.contribution_by_family["price_volume"] == pytest.approx(0.0)
    assert emitted.contribution_by_family["news"] != 0.0


def test_a_family_attribution_scales_with_the_evidence() -> None:
    """The other half: the attribution is linear in the feature values, so
    doubling the family's evidence doubles its contribution. Together with the
    test above this pins the attribution to the candidate rather than to the
    fitted coefficients alone."""
    base = {**features_for(4), "residual_return_5s": 0.2, "volume_z": 0.1}
    doubled = {**base, "residual_return_5s": 0.4, "volume_z": 0.2}
    model = fitted()

    single = model.predict("ACME", base, at(110)).contribution_by_family["price_volume"]
    double = model.predict("ACME", doubled, at(110)).contribution_by_family["price_volume"]

    assert single != pytest.approx(0.0)
    assert double == pytest.approx(2.0 * single)


def test_a_family_attribution_ignores_features_belonging_to_the_other() -> None:
    """AC-8's falsification: an attribution that changed when an unrelated
    family's feature moved would not be an attribution."""
    model = fitted()
    base = features_for(4)
    moved = {**base, "direction_weighted": base["direction_weighted"] + 0.4}

    first = model.predict("ACME", base, at(110)).contribution_by_family["price_volume"]
    second = model.predict("ACME", moved, at(110)).contribution_by_family["price_volume"]

    assert first == pytest.approx(second)


# --- the test window reaches nothing --------------------------------------


def test_a_fold_whose_training_labels_overlap_its_test_window_is_refused() -> None:
    """AC-1. The deliberately leaked fixture the research rules require."""
    leaked = fold_over(train=(*ids(0, 60), "lbl-090"), calibration=ids(60, 85), test=("lbl-090",))

    with pytest.raises(LeakedFitError, match="lbl-090"):
        fitted(fold=leaked)


def test_a_fold_whose_calibration_labels_overlap_its_test_window_is_refused() -> None:
    """The two leaks are named separately, because a training leak and a
    calibration leak call for different corrections and a shared message would
    make them indistinguishable in the ledger."""
    leaked = fold_over(train=ids(0, 60), calibration=(*ids(60, 85), "lbl-091"), test=("lbl-091",))

    with pytest.raises(LeakedFitError, match="calibration"):
        fitted(fold=leaked)


def test_the_training_leak_and_the_calibration_leak_say_different_things() -> None:
    training = fold_over(train=(*ids(0, 60), "lbl-090"), calibration=ids(60, 85), test=("lbl-090",))
    calibrating = fold_over(
        train=ids(0, 60), calibration=(*ids(60, 85), "lbl-091"), test=("lbl-091",)
    )

    with pytest.raises(LeakedFitError) as first:
        fitted(fold=training)
    with pytest.raises(LeakedFitError) as second:
        fitted(fold=calibrating)

    assert str(first.value) != str(second.value)


def test_supplying_features_for_a_test_label_is_refused() -> None:
    """AC-2c. Reading `test_labels` in order to refuse is not reading them in
    order to fit."""
    features, outcomes, uniqueness = panel()
    held = fold_over(train=ids(0, 60), calibration=ids(60, 85), test=ids(85, 90))

    with pytest.raises(LeakedFitError, match="test window"):
        fitted(fold=held, features=features, outcomes=outcomes, uniqueness=uniqueness)


def test_two_folds_differing_only_in_their_test_window_fit_the_same_model() -> None:
    """AC-2, and the reason AC-2b exists. `Fold.fold_hash` hashes `test_labels`,
    so these two folds already have different fold hashes. A `model_version`
    built from the fold hash could never pass this, however carefully the fit
    ignored the test window."""
    features, outcomes, uniqueness = panel()
    train, calibration = ids(0, 60), ids(60, 85)
    first = fold_over(train=train, calibration=calibration, test=("lbl-086",))
    second = fold_over(train=train, calibration=calibration, test=("lbl-087",))

    assert first.fold_hash != second.fold_hash

    kept = {key: value for key, value in features.items() if key in set(train) | set(calibration)}
    outs = {key: value for key, value in outcomes.items() if key in kept}
    weights = {key: value for key, value in uniqueness.items() if key in kept}

    one = fitted(fold=first, features=kept, outcomes=outs, uniqueness=weights)
    two = fitted(fold=second, features=kept, outcomes=outs, uniqueness=weights)

    assert one.model_version == two.model_version
    assert one.predict("ACME", features_for(3), at(110)) == two.predict(
        "ACME", features_for(3), at(110)
    )


def test_the_model_still_carries_the_fold_hash_as_provenance() -> None:
    """Excluded from identity, kept as provenance. The two are different
    questions and this is the one place they visibly diverge."""
    held = fold_over(train=ids(0, 60), calibration=ids(60, 85))
    model = fitted(fold=held)

    assert model.fold_hash == held.fold_hash


# --- trial registration ----------------------------------------------------


def test_a_trial_is_registered_and_names_both_feature_versions_and_the_fold() -> None:
    """AC-3. A trial recorded without the feature versions could not be told
    apart from the same model fitted on a different feature definition."""
    store = CapturingRegistry(AppendOnlyStore(Path(tempfile.mkdtemp()) / "trials.jsonl"))
    model = fitted(registry=store)

    assert len(store.configurations) == 1
    recorded = store.configurations[0]
    assert recorded["price_volume_feature_version"] == "fv-price-0001"
    assert recorded["news_feature_version"] == "fv-news-0001"
    assert recorded["fold_hash"] == fold_over(train=ids(0, 60), calibration=ids(60, 85)).fold_hash
    assert store.purposes[0].strip()
    assert len(store.trials()) == 1
    assert model.trial_id == store.trials()[0].trial_id


def test_a_registry_that_refuses_the_registration_stops_the_fit() -> None:
    """The registry is not advisory. A fit that proceeded past a refused
    registration would be an unregistered trial, which is the one thing the
    registry exists to make impossible."""

    class Refuses(TrialRegistry):
        def register(
            self, configuration: Mapping[str, object], purpose: str, registered_at: datetime
        ) -> object:
            raise UnregisteredTrialError("refused")

    with pytest.raises(UnregisteredTrialError):
        fitted(registry=Refuses(AppendOnlyStore(Path(tempfile.mkdtemp()) / "trials.jsonl")))


def test_the_trial_is_registered_before_the_result_is_computed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3's ordering. A trial registered afterwards would let a fit abandoned
    because its result disappointed escape the multiple-testing count, which is
    the failure the registry exists to prevent.

    The estimator is instrumented rather than the return of `fit`, because
    appending a marker after `fit` returns would record the same order whenever
    registration happened, which is an observation that cannot fail.
    """
    seen: list[str] = []

    class WatchedRidge(Ridge):  # type: ignore[misc]
        def fit(self, *args: object, **kwargs: object) -> object:
            seen.append("fitted")
            return super().fit(*args, **kwargs)

    class Watches(TrialRegistry):
        def register(
            self, configuration: Mapping[str, object], purpose: str, registered_at: datetime
        ) -> object:
            seen.append("registered")
            return super().register(configuration, purpose, registered_at)

    monkeypatch.setattr("alphaledger.forecast.model.Ridge", WatchedRidge)
    model = fitted(registry=Watches(AppendOnlyStore(Path(tempfile.mkdtemp()) / "trials.jsonl")))

    assert seen == ["registered", "fitted"]
    assert model.model_version


def test_the_ordering_probe_can_actually_fail() -> None:
    """The test above is only worth having if its instrumentation observes the
    real order. This pins that `Ridge.fit` is reached through the module
    attribute the probe patches, so the patch is not silently inert."""
    from alphaledger.forecast import model as module

    assert module.Ridge is Ridge


# --- calibration -----------------------------------------------------------


def test_a_fold_with_no_usable_calibration_label_refuses_to_produce_a_model() -> None:
    """AC-9 and the no-trade case. `predict` returns a `Forecast` and has no way
    to return nothing, so a model carrying an invented `calibration_error` is
    worse than no model at all."""
    empty = fold_over(train=ids(0, 60), calibration=())

    with pytest.raises(UncalibratedModelError, match="calibration"):
        fitted(fold=empty)


def test_a_calibration_window_whose_labels_have_no_features_is_the_same_refusal() -> None:
    """A fold naming calibration labels nothing supplied features for is
    empty in the only sense that matters."""
    features, outcomes, uniqueness = panel()
    kept = {key: value for key, value in features.items() if key in set(ids(0, 60))}

    with pytest.raises(UncalibratedModelError):
        fitted(
            fold=fold_over(train=ids(0, 60), calibration=ids(60, 85)),
            features=kept,
            outcomes={key: outcomes[key] for key in kept},
            uniqueness={key: uniqueness[key] for key in kept},
        )


# --- point in time ---------------------------------------------------------


def test_predicting_inside_the_window_the_model_was_fitted_on_is_refused() -> None:
    """A forecast made for an instant the model trained on is not a forecast.
    `as_of` is what makes that checkable, and refusing is the only honest
    answer: the model has already seen the answer."""
    model = fitted()

    with pytest.raises(LeakedFitError, match="as_of"):
        model.predict("ACME", features_for(3), at(30))


def test_predicting_after_the_calibration_window_is_allowed() -> None:
    model = fitted()

    assert model.predict("ACME", features_for(3), at(110)) is not None


# --- effective sample size -------------------------------------------------


def test_overlapping_labels_shrink_the_effective_sample_below_the_row_count() -> None:
    """The reason `uniqueness` is a required argument. Counting rows would
    report a sample many times larger than the information it holds, and gate 4
    in `eligibility.py` would then refuse almost nothing."""
    features, _outcomes, _ = panel()
    # Deliberately NOT a uniform weight. Kish's effective sample size of any
    # uniform weighting is exactly the row count, whatever the weight, so a
    # fixture halving every label would have agreed with the row count it is
    # supposed to detect. An earlier version of this test did exactly that and
    # a mutation replacing the whole computation with `len(weights)` survived
    # it.
    uneven = {
        label_id: (1.0 if int(label_id.split("-")[1]) % 2 == 0 else 0.2) for label_id in features
    }

    model = fitted(uniqueness=uneven)
    emitted = model.predict("ACME", features_for(3), at(110))

    # Thirty labels weigh one and thirty weigh a fifth across the training
    # window. Sum is 36, sum of squares is 31.2, so Kish gives 36^2 / 31.2.
    assert emitted.effective_sample_size == pytest.approx(1296.0 / 31.2)
    assert emitted.effective_sample_size < 60.0


def test_unique_labels_give_an_effective_sample_equal_to_the_row_count() -> None:
    emitted = fitted().predict("ACME", features_for(3), at(110))

    assert emitted.effective_sample_size == pytest.approx(60.0)


def test_a_missing_uniqueness_weight_is_refused_rather_than_assumed_to_be_one() -> None:
    """Assuming one is the most flattering reading of absent data, and it is
    exactly the row-count lie this argument exists to prevent."""
    _features, _outcomes, uniqueness = panel()
    del uniqueness["lbl-005"]

    with pytest.raises(ValueError, match="lbl-005"):
        fitted(uniqueness=uniqueness)


# --- failure paths ---------------------------------------------------------


def test_a_missing_feature_at_prediction_is_refused_rather_than_zero_filled() -> None:
    """A zero-filled feature is a claim that the evidence said nothing, which
    is different from not having looked."""
    model = fitted()
    incomplete = {key: value for key, value in features_for(3).items() if key != "volume_z"}

    with pytest.raises(ValueError, match="volume_z"):
        model.predict("ACME", incomplete, at(110))


def test_a_label_with_features_but_no_outcome_is_refused() -> None:
    _features, outcomes, _uniqueness = panel()
    del outcomes["lbl-004"]

    with pytest.raises(ValueError, match="lbl-004"):
        fitted(outcomes=outcomes)


def test_a_config_naming_a_family_with_no_feature_version_is_refused() -> None:
    """A family fitted but unversioned would make the trial registry unable to
    say what definition produced the result."""
    with pytest.raises(ValueError, match="news"):
        ModelConfig(
            feature_families={"price_volume": PRICE, "news": NEWS},
            feature_versions={"price_volume": "fv-price-0001"},
        )


def test_a_config_with_fewer_than_two_families_is_refused() -> None:
    """Section 6 gate 1 requires two families to agree. A model fitted on one
    could never satisfy it, so the configuration is refused where the mistake
    is cheap rather than at the gate where it is not."""
    with pytest.raises(ValueError, match="famil"):
        ModelConfig(
            feature_families={"price_volume": PRICE},
            feature_versions={"price_volume": "fv-price-0001"},
        )


# --- restart and determinism ----------------------------------------------

DETERMINISM_SCRIPT = """
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alphaledger.data.storage import AppendOnlyStore
from alphaledger.forecast.model import ModelConfig, fit
from alphaledger.forecast.registry import TrialRegistry
from alphaledger.forecast.splits import Fold, Window
from sklearn.linear_model import Ridge

ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


def at(days):
    return ORIGIN + timedelta(days=days)


def features_for(index):
    return {
        "residual_return_5s": (index % 7) / 7.0 - 0.5,
        "volume_z": (index % 5) / 5.0 - 0.5,
        "direction_weighted": (index % 3) / 3.0 - 0.5,
        "novelty_weighted": (index % 11) / 11.0 - 0.5,
    }


def outcome_for(index):
    point = features_for(index)
    return 0.20 * point["residual_return_5s"] - 0.10 * point["direction_weighted"]


ids = lambda a, b: tuple("lbl-%03d" % i for i in range(a, b))
# Only the labels the fold fits on: fit refuses features for anything outside
# its training and calibration windows.
features = {"lbl-%03d" % i: features_for(i) for i in range(85)}
outcomes = {"lbl-%03d" % i: outcome_for(i) for i in range(85)}
uniqueness = {"lbl-%03d" % i: 1.0 for i in range(85)}

fold = Fold(
    index=0,
    train=Window(start=at(0), end=at(60)),
    calibration=Window(start=at(70), end=at(90)),
    test=Window(start=at(100), end=at(120)),
    horizon=timedelta(days=5),
    purge=timedelta(days=10),
    train_labels=ids(0, 60),
    calibration_labels=ids(60, 85),
    test_labels=(),
    purged=(),
)
config = ModelConfig(
    feature_families={"price_volume": ("residual_return_5s", "volume_z"),
                      "news": ("direction_weighted", "novelty_weighted")},
    feature_versions={"price_volume": "fv-price-0001", "news": "fv-news-0001"},
)
store = TrialRegistry(AppendOnlyStore(Path(tempfile.mkdtemp()) / "trials.jsonl"))
model = fit(fold, features, outcomes, uniqueness, config, store, at(95))
emitted = model.predict("ACME", features_for(3), at(110))

print(model.model_version)
print(model.trial_id)
print(repr(emitted.p_up))
print(repr(emitted.expected_residual_return))
print(repr(emitted.calibration_error))
print(repr(emitted.effective_sample_size))
for name in sorted(emitted.quantiles):
    print(name, repr(emitted.quantiles[name]))
for name in sorted(emitted.contribution_by_family):
    print(name, repr(emitted.contribution_by_family[name]))
"""


def in_a_new_process(hash_seed: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", DETERMINISM_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": hash_seed, "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_two_processes_produce_byte_identical_forecasts() -> None:
    """AC-7. A frozen run has to be replayable, and a model whose coefficients
    moved between processes would make every recorded decision unauditable.
    Two hash seeds, because a dictionary iteration order leaking into the
    feature order is the way this silently breaks."""
    assert in_a_new_process("0") == in_a_new_process("12345")


def test_the_determinism_fixture_actually_emits_a_forecast() -> None:
    """Two empty outputs are also identical. This pins that the comparison
    above is comparing something."""
    output = in_a_new_process("0")

    assert output.startswith("mdl-")
    assert "price_volume" in output
    assert len(output.splitlines()) == 11


def test_a_persisted_model_reloads_and_emits_identical_forecasts() -> None:
    """Restart. A frozen run is replayed from a stored model, so a reload that
    perturbed a coefficient would change a decision the ledger already
    recorded."""
    model = fitted()
    reloaded = pickle.loads(pickle.dumps(model))

    original = model.predict("ACME", features_for(7), at(110))
    replayed = reloaded.predict("ACME", features_for(7), at(110))

    assert reloaded.model_version == model.model_version
    assert reloaded.trial_id == model.trial_id
    assert replayed == original


def test_no_path_produces_a_model_that_has_not_been_calibrated() -> None:
    """The contract names `UncalibratedModelError` for `predict` called before
    calibration. That state is unreachable by construction rather than guarded
    at the point of use: `fit` is the only way to obtain a `FittedModel`, and
    it refuses to return one it could not calibrate, so there is no window in
    which an uncalibrated model exists to be asked. Making the invalid state
    unrepresentable is stronger than checking for it, and this test pins the
    property so a later constructor cannot quietly reintroduce it.
    """
    model = fitted()

    assert model.calibration_error >= 0.0
    with pytest.raises(UncalibratedModelError):
        fitted(fold=fold_over(train=ids(0, 60), calibration=()))


# --- round two: the review findings ---------------------------------------


def test_a_label_the_fold_places_in_no_window_is_refused_not_ignored() -> None:
    """Finding 1. AC-2c promises refusal of any supplied label the fold does
    not place in its training or calibration window, and round one enforced
    only the test-window subset. The extra label was inert, because `_rows`
    reads the fold's own lists and never the supplied keys, but "inert" was an
    implementation detail rather than a guarantee, and the criterion read as
    satisfied while only part of it was."""
    features, outcomes, uniqueness = panel()
    fold = fold_over(train=ids(0, 60), calibration=ids(60, 85))
    usable = set(fold.train_labels) | set(fold.calibration_labels)
    stranger = {key: value for key, value in features.items() if key in usable}
    stranger["lbl-089"] = features["lbl-089"]

    with pytest.raises(LeakedFitError, match="lbl-089"):
        fitted(fold=fold, features=stranger, outcomes=outcomes, uniqueness=uniqueness)


def test_the_stranger_and_the_test_label_are_refused_in_different_words() -> None:
    """A leak and an unprovenanced label are different facts. One means the
    caller handed over data the fold exists to hold back; the other means the
    caller cannot say where the data came from."""
    features, outcomes, uniqueness = panel()
    fold = fold_over(train=ids(0, 60), calibration=ids(60, 85), test=("lbl-086",))
    usable = set(fold.train_labels) | set(fold.calibration_labels)

    leaked = {key: features[key] for key in usable | {"lbl-086"}}
    stranger = {key: features[key] for key in usable | {"lbl-089"}}

    with pytest.raises(LeakedFitError) as first:
        fitted(fold=fold, features=leaked, outcomes=outcomes, uniqueness=uniqueness)
    with pytest.raises(LeakedFitError) as second:
        fitted(fold=fold, features=stranger, outcomes=outcomes, uniqueness=uniqueness)

    assert "test window" in str(first.value)
    assert "test window" not in str(second.value)


def test_a_fold_training_and_calibrating_on_one_label_is_refused() -> None:
    """Finding 2. Calibrating against a label the model trained on measures the
    fit rather than the generalisation, so every gate reading
    `calibration_error` would be reading an optimistic number. `walk_forward`
    cannot build this, but a hand-built `Fold` can, and a hand-built `Fold` is
    already the threat model the test-window checks take seriously."""
    overlapping = fold_over(train=ids(0, 60), calibration=ids(55, 85))

    with pytest.raises(LeakedFitError, match="training and the calibration"):
        fitted(fold=overlapping)


def test_the_uniqueness_weights_reach_the_fit_and_not_only_the_reported_sample() -> None:
    """Finding 3. `uniqueness` is passed as `sample_weight` to both estimators,
    and round one had no fixture that could tell: every success case weighted
    every label at one, and weighted and unweighted regression are identical
    under uniform weights.

    Here a numerous minority follows the opposite relationship to a small
    majority and is weighted almost to nothing. An unweighted fit follows the
    forty-label minority; a weighted one follows the twenty-label majority. The
    sign of the recovered coefficient is therefore decisive, which is what a
    test of a weighting has to be.
    """
    fold = fold_over(train=ids(0, 60), calibration=ids(60, 85))
    features: dict[str, dict[str, float]] = {}
    outcomes: dict[str, float] = {}
    uniqueness: dict[str, float] = {}
    for index in range(85):
        label_id = f"lbl-{index:03d}"
        signal = (index % 7) / 7.0 - 0.5
        features[label_id] = {
            "residual_return_5s": signal,
            "volume_z": 0.0,
            "direction_weighted": 0.0,
            "novelty_weighted": 0.0,
        }
        minority = 20 <= index < 60
        outcomes[label_id] = (-0.5 if minority else 0.5) * signal
        uniqueness[label_id] = 1e-6 if minority else 1.0

    model = fitted(fold=fold, features=features, outcomes=outcomes, uniqueness=uniqueness)
    rising = model.predict(
        "ACME",
        {
            "residual_return_5s": 0.5,
            "volume_z": 0.0,
            "direction_weighted": 0.0,
            "novelty_weighted": 0.0,
        },
        at(110),
    )

    # The heavily weighted twenty say a positive signal means a positive
    # outcome. The near-weightless forty say the opposite and outnumber them.
    # Both estimators are asserted, because `sample_weight` is passed to each
    # of them separately and a test reading only the magnitude model would let
    # the direction model quietly go unweighted.
    assert rising.expected_residual_return > 0.0
    assert rising.p_up > 0.5


def test_the_contributions_and_the_intercept_account_for_the_whole_prediction() -> None:
    """Finding 4. The contributions deliberately exclude the ridge intercept,
    which belongs to no family. That is a defensible convention and it was
    undocumented and unpinned, so the exact relationship is asserted here
    rather than left for a reader to assume one way or the other."""
    model = fitted()
    emitted = model.predict("ACME", features_for(6), at(110))

    attributed = sum(emitted.contribution_by_family.values())
    intercept = float(model._magnitude.intercept_)

    assert attributed + intercept == pytest.approx(emitted.expected_residual_return)
    assert attributed != pytest.approx(emitted.expected_residual_return)


def test_predicting_exactly_at_the_calibration_boundary_is_allowed() -> None:
    """Finding 5. `Window` is half-open, so the calibration window does not
    contain its own end instant and a prediction there has seen nothing. The
    guard is therefore strictly less-than, and this pins the boundary so a
    drift to less-than-or-equal cannot pass unnoticed."""
    model = fitted()
    boundary = fold_over(train=ids(0, 60), calibration=ids(60, 85)).calibration.end

    assert model.predict("ACME", features_for(3), boundary) is not None
    with pytest.raises(LeakedFitError):
        model.predict("ACME", features_for(3), boundary - timedelta(microseconds=1))
