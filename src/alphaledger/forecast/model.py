"""The pooled forecast from design section 6.

One deliberately simple model across the whole universe: a logistic model for
the probability that the forward residual is positive, and a ridge model for
its magnitude, calibrated on a later chronological slice and never on the test
slice. Symbol identity is not a feature, because a pooled model handed one
would memorise the symbol instead of learning the relationship.

Four properties here exist because the corresponding mistake is routine in
cross-sectional research, not because the code looked fragile.

Nothing from the test window reaches the fit. That is enforced twice, once by
refusing a fold whose own label lists overlap, and once by refusing supplied
features for a label the fold places in its test window. Reading `test_labels`
in order to refuse is not reading them in order to fit.

The model's identity does not depend on the test window. `Fold.fold_hash`
hashes `test_labels`, so two folds identical but for their test contents
already carry different fold hashes. `model_version` is therefore derived from
the training-relevant view alone, and the fold hash rides along as provenance.
Provenance and identity are different questions, and this is the one place they
visibly diverge.

A trial is registered before any result exists. A trial registered afterwards
would let an abandoned fit escape the multiple-testing count, which is the one
thing the registry exists to make impossible.

The effective sample size comes from label uniqueness and never from the row
count. Sampling daily at a multi-session horizon makes consecutive labels share
most of their outcome window, so a fit that counted rows would count the same
information many times, and the eligibility gate reading that number would
refuse almost nothing. `uniqueness` is therefore a required argument, and a
missing weight is refused rather than assumed to be one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge

from alphaledger.domain.contracts import Forecast, require_utc
from alphaledger.forecast.registry import TrialRegistry
from alphaledger.forecast.splits import Fold

__all__ = [
    "UNDECIDED",
    "FittedModel",
    "LeakedFitError",
    "ModelConfig",
    "UncalibratedModelError",
    "fit",
]

# `predict` does not run the section 6 gates, and the frozen `Forecast` refuses
# an ineligible record carrying no reason. So the reason states precisely what
# has not happened, rather than borrowing a gate's name and implying a gate
# refused it.
UNDECIDED = "eligibility_not_yet_evaluated"

_PURPOSE = "pooled forward residual forecast, design section 6"


class LeakedFitError(ValueError):
    """An instant the fold does not admit reached the fit, or the prediction."""


class UncalibratedModelError(ValueError):
    """There is no calibration slice, so no honest calibration error exists."""


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """The frozen shape of the model. Any change changes `config_version`.

    Every default is declared, not selected on data. Design section 4 requires
    selection on development data, registration as a trial, and a freeze before
    an autonomous session, and none of that has happened.
    """

    feature_families: Mapping[str, tuple[str, ...]]
    feature_versions: Mapping[str, str]
    horizon_sessions: int = 5
    ridge_alpha: float = 1.0
    logistic_c: float = 1.0
    calibration_bins: int = 10
    feature_names: tuple[str, ...] = field(init=False, default=())
    config_version: str = field(init=False, default="")

    def __post_init__(self) -> None:
        families = {
            str(name): tuple(str(item) for item in cols)
            for name, cols in dict(self.feature_families).items()
        }
        if len(families) < 2:
            raise ValueError(
                f"feature_families names {len(families)} family; section 6 gate 1 requires "
                "two families to agree on direction, so a model fitted on one could never "
                "satisfy it. Refused here, where the mistake is cheap"
            )
        versions = {str(name): str(value) for name, value in dict(self.feature_versions).items()}
        for name in families:
            if not versions.get(name, "").strip():
                raise ValueError(
                    f"family {name!r} has no feature_version. A family fitted but unversioned "
                    "would leave the trial registry unable to say what definition produced "
                    "the result"
                )
        ordered: list[str] = []
        for name in sorted(families):
            for column in families[name]:
                if column in ordered:
                    raise ValueError(
                        f"feature {column!r} appears in more than one family, so its "
                        "contribution could not be attributed to either"
                    )
                ordered.append(column)
        if not ordered:
            raise ValueError("feature_families names no features at all")
        if self.horizon_sessions <= 0:
            raise ValueError(f"horizon_sessions must be positive; got {self.horizon_sessions!r}")
        for name in ("ridge_alpha", "logistic_c"):
            value = getattr(self, name)
            if not float(value) > 0.0:
                raise ValueError(f"{name} must be positive; got {value!r}")
        if self.calibration_bins < 1:
            raise ValueError(
                f"calibration_bins must be at least one; got {self.calibration_bins!r}"
            )

        object.__setattr__(self, "feature_families", MappingProxyType(families))
        object.__setattr__(self, "feature_versions", MappingProxyType(versions))
        object.__setattr__(self, "feature_names", tuple(ordered))
        object.__setattr__(self, "config_version", self._version())

    def __reduce__(self) -> tuple[object, ...]:
        """Rebuild through `__init__` so a reload is a revalidation.

        The mapping fields are `MappingProxyType`, which pickle cannot handle,
        and a frozen run has to be replayable from a stored model. Rebuilding
        from the constructor arguments rather than restoring `__dict__` means
        the reloaded configuration passes the same checks the original did and
        recomputes `config_version` rather than trusting a stored string.
        """
        return (
            _rebuild_config,
            (
                {name: list(cols) for name, cols in self.feature_families.items()},
                dict(self.feature_versions),
                self.horizon_sessions,
                self.ridge_alpha,
                self.logistic_c,
                self.calibration_bins,
            ),
        )

    def family_of(self, feature: str) -> str:
        for name, columns in self.feature_families.items():
            if feature in columns:
                return name
        raise KeyError(feature)

    def _version(self) -> str:
        body = {
            "feature_families": {k: list(v) for k, v in sorted(self.feature_families.items())},
            "feature_versions": dict(sorted(self.feature_versions.items())),
            "horizon_sessions": self.horizon_sessions,
            "ridge_alpha": repr(float(self.ridge_alpha)),
            "logistic_c": repr(float(self.logistic_c)),
            "calibration_bins": self.calibration_bins,
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return "cfg-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _rebuild_config(
    families: Mapping[str, Sequence[str]],
    versions: Mapping[str, str],
    horizon_sessions: int,
    ridge_alpha: float,
    logistic_c: float,
    calibration_bins: int,
) -> ModelConfig:
    """Module-level so pickle can find it; see `ModelConfig.__reduce__`."""
    return ModelConfig(
        feature_families={name: tuple(cols) for name, cols in families.items()},
        feature_versions=dict(versions),
        horizon_sessions=horizon_sessions,
        ridge_alpha=ridge_alpha,
        logistic_c=logistic_c,
        calibration_bins=calibration_bins,
    )


@dataclass(frozen=True, slots=True)
class FittedModel:
    """One fitted pooled model, with what it may and may not be asked."""

    model_version: str
    fold_hash: str
    trial_id: str
    calibration_error: float
    effective_sample_size: float
    config: ModelConfig
    _magnitude: Ridge
    _direction: LogisticRegression
    _residual_quantiles: tuple[float, float, float]
    _fitted_through: datetime

    def predict(
        self, candidate_id: str, features: Mapping[str, float], as_of: datetime
    ) -> Forecast:
        """Emit the frozen `Forecast` for one candidate.

        `as_of` is not decoration. A prediction for an instant inside the
        windows this model was fitted and calibrated on is not a forecast, it
        is a lookup of an answer the model has already seen, so it is refused
        rather than emitted with a caveat.
        """
        moment = require_utc(as_of, "as_of")
        if moment < self._fitted_through:
            raise LeakedFitError(
                f"as_of {moment.isoformat()} falls before "
                f"{self._fitted_through.isoformat()}, the end of the calibration window this "
                "model was fitted through. A forecast for an instant the model already saw "
                "is not a forecast"
            )
        row = _row(features, self.config.feature_names)
        matrix = np.asarray([row], dtype=float)

        probability = float(self._direction.predict_proba(matrix)[0][1])
        magnitude = float(self._magnitude.predict(matrix)[0])
        low, mid, high = self._residual_quantiles

        return Forecast(
            candidate_id=candidate_id,
            horizon_sessions=self.config.horizon_sessions,
            p_up=probability,
            expected_residual_return=magnitude,
            quantiles={
                "q10": magnitude + low,
                "q50": magnitude + mid,
                "q90": magnitude + high,
            },
            contribution_by_family=self._contributions(row),
            calibration_error=self.calibration_error,
            effective_sample_size=self.effective_sample_size,
            eligible=False,
            rejection_reasons=(UNDECIDED,),
            model_version=self.model_version,
        )

    def _contributions(self, row: Sequence[float]) -> dict[str, float]:
        """Each family's own coefficients against its own values, computed alone.

        Deliberately not a full decomposition of `expected_residual_return`.
        The ridge model fits an intercept, and the intercept belongs to no
        family, so the contributions sum to the prediction minus that
        intercept. Attributing a constant baseline to whichever family happened
        to be listed first would be arbitrary, and splitting it between them
        would invent evidence neither family supplied. The unattributed
        remainder is named here rather than hidden, and
        `test_the_contributions_and_the_intercept_account_for_the_whole_prediction`
        pins the exact relationship.

        A family's attribution sums only its own coefficients against its own
        values, so it cannot move when a feature belonging to another family
        moves. AC-8's falsification is exactly that independence, and a single
        blended number would make it impossible to say whether a trade was a
        news trade.
        """
        coefficients = np.asarray(self._magnitude.coef_, dtype=float).ravel()
        totals = dict.fromkeys(self.config.feature_families, 0.0)
        for index, name in enumerate(self.config.feature_names):
            totals[self.config.family_of(name)] += float(coefficients[index]) * float(row[index])
        return totals


def fit(
    fold: Fold,
    features: Mapping[str, Mapping[str, float]],
    outcomes: Mapping[str, float],
    uniqueness: Mapping[str, float],
    config: ModelConfig,
    registry: TrialRegistry,
    registered_at: datetime,
) -> FittedModel:
    """Fit the pooled model for one fold and return it.

    The order is deliberate and is what AC-3 pins: every input is validated,
    then the trial is registered, and only then is anything fitted. A trial
    registered after a result exists would let a fit that was abandoned because
    its result disappointed escape the multiple-testing count entirely.
    """
    moment = require_utc(registered_at, "registered_at")
    _refuse_overlapping_labels(fold)
    _refuse_foreign_features(fold, features)

    training = _rows(fold.train_labels, features, outcomes, uniqueness, config)
    calibrating = _rows(fold.calibration_labels, features, outcomes, uniqueness, config)
    if not training.label_ids:
        raise UncalibratedModelError(
            f"fold {fold.index} has no usable training label; nothing supplied features and "
            "an outcome for any label in its training window"
        )
    if not calibrating.label_ids:
        raise UncalibratedModelError(
            f"fold {fold.index} has no usable calibration label in the window "
            f"{fold.calibration.start.isoformat()} to {fold.calibration.end.isoformat()}. "
            "A model carrying an invented calibration_error is worse than no model, because "
            "predict returns a Forecast and has no way to return nothing"
        )

    model_version = _model_version(fold, config, training.label_ids, calibrating.label_ids)
    trial_id = registry.register(
        {
            "model_version": model_version,
            "config_version": config.config_version,
            "fold_hash": fold.fold_hash,
            "fold_index": fold.index,
            **{
                f"{family}_feature_version": version
                for family, version in config.feature_versions.items()
            },
            "train_label_count": len(training.label_ids),
            "calibration_label_count": len(calibrating.label_ids),
            "horizon_sessions": config.horizon_sessions,
        },
        _PURPOSE,
        moment,
    )

    magnitude = Ridge(alpha=config.ridge_alpha, solver="cholesky")
    magnitude.fit(training.matrix, training.outcomes, sample_weight=training.weights)

    direction = LogisticRegression(C=config.logistic_c, solver="lbfgs", max_iter=1000)
    labels = (training.outcomes > 0.0).astype(int)
    if len(set(labels.tolist())) < 2:
        raise UncalibratedModelError(
            f"fold {fold.index}: every training outcome has the same sign, so a direction "
            "model cannot be fitted and a probability from it would be a constant dressed "
            "as a forecast"
        )
    direction.fit(training.matrix, labels, sample_weight=training.weights)

    predicted = direction.predict_proba(calibrating.matrix)[:, 1]
    observed = (calibrating.outcomes > 0.0).astype(int)
    residuals = calibrating.outcomes - magnitude.predict(calibrating.matrix)

    return FittedModel(
        model_version=model_version,
        fold_hash=fold.fold_hash,
        trial_id=str(trial_id),
        calibration_error=_expected_calibration_error(predicted, observed, config.calibration_bins),
        effective_sample_size=_effective_sample_size(training.weights),
        config=config,
        _magnitude=magnitude,
        _direction=direction,
        _residual_quantiles=(
            float(np.quantile(residuals, 0.10)),
            float(np.quantile(residuals, 0.50)),
            float(np.quantile(residuals, 0.90)),
        ),
        _fitted_through=fold.calibration.end,
    )


@dataclass(frozen=True, slots=True)
class _Rows:
    label_ids: tuple[str, ...]
    matrix: np.ndarray
    outcomes: np.ndarray
    weights: np.ndarray


def _rows(
    label_ids: Sequence[str],
    features: Mapping[str, Mapping[str, float]],
    outcomes: Mapping[str, float],
    uniqueness: Mapping[str, float],
    config: ModelConfig,
) -> _Rows:
    """Assemble one window's design matrix in the frozen feature order.

    A label the fold names but nothing supplied features for is skipped, which
    is an ordinary data gap. A label that has features but no outcome, or no
    uniqueness weight, is refused: those are inconsistent inputs rather than
    missing ones, and silently dropping them would change the sample without
    saying so.
    """
    kept: list[str] = []
    rows: list[list[float]] = []
    values: list[float] = []
    weights: list[float] = []
    for label_id in label_ids:
        point = features.get(label_id)
        if point is None:
            continue
        if label_id not in outcomes:
            raise ValueError(
                f"{label_id} has features but no outcome. Dropping it would change the "
                "sample without recording that the sample changed"
            )
        if label_id not in uniqueness:
            raise ValueError(
                f"{label_id} has no uniqueness weight. Assuming one is the row-count lie "
                "this argument exists to prevent, so it is refused instead"
            )
        weight = float(uniqueness[label_id])
        if not weight > 0.0:
            raise ValueError(f"{label_id} has a non-positive uniqueness weight {weight!r}")
        kept.append(label_id)
        rows.append(_row(point, config.feature_names))
        values.append(float(outcomes[label_id]))
        weights.append(weight)
    return _Rows(
        label_ids=tuple(kept),
        matrix=np.asarray(rows, dtype=float).reshape(len(rows), len(config.feature_names)),
        outcomes=np.asarray(values, dtype=float),
        weights=np.asarray(weights, dtype=float),
    )


def _row(point: Mapping[str, float], names: Sequence[str]) -> list[float]:
    """One feature vector in the frozen order, refusing to invent a missing value.

    A zero-filled feature is a claim that the evidence said nothing, which is a
    different statement from not having looked, and the model cannot tell them
    apart once the zero is in the matrix.
    """
    row: list[float] = []
    for name in names:
        if name not in point:
            raise ValueError(
                f"feature {name!r} is absent. Filling it with zero would assert that the "
                "evidence said nothing, which is not the same as not having looked"
            )
        row.append(float(point[name]))
    return row


def _refuse_overlapping_labels(fold: Fold) -> None:
    """A label in two windows at once, named by the window that should not hold it."""
    held = set(fold.test_labels)
    windows = (("training", fold.train_labels), ("calibration", fold.calibration_labels))
    for window, members in windows:
        shared = sorted(held.intersection(members))
        if shared:
            raise LeakedFitError(
                f"fold {fold.index}: {', '.join(shared)} appears in both the {window} window "
                "and the test window, so fitting would train on what the fold exists to hold "
                "back"
            )
    # The test window is not the only overlap that matters. A label in both the
    # training and the calibration window would be calibrated against by a
    # model that had already trained on it, so the calibration error would
    # measure fit rather than generalisation and every gate reading it would be
    # reading an optimistic number. `walk_forward` cannot produce this, since
    # `_assign` places each label in exactly one window, but a hand-built
    # `Fold` can, and a hand-built `Fold` is already the threat model the
    # test-window checks above take seriously.
    both = sorted(set(fold.train_labels).intersection(fold.calibration_labels))
    if both:
        raise LeakedFitError(
            f"fold {fold.index}: {', '.join(both)} appears in both the training and the "
            "calibration window. Calibrating against a label the model trained on measures "
            "the fit, not the generalisation the calibration error is supposed to report"
        )


def _refuse_foreign_features(fold: Fold, features: Mapping[str, Mapping[str, float]]) -> None:
    """Refuse evidence for any label this fold does not fit on.

    Two refusals, deliberately worded apart. A supplied test-window label is a
    leak and says so. A supplied label the fold places in no window at all is
    not a leak today, because `_rows` reads only the fold's own lists and would
    ignore it, but it is refused anyway: its provenance cannot be established
    from here, so nothing rules out its being a future or held-back
    observation, and the only reason it is currently harmless is an
    implementation detail of `_rows` that a later change could reverse without
    anyone noticing.

    The cost is that a caller cannot hand the whole panel to every fold and let
    each one select. That is the intended cost. Being explicit about which
    labels belong to which fold is exactly the discipline the windows exist to
    enforce, and a caller that cannot say is a caller that does not know.
    """
    leaked = sorted(set(fold.test_labels).intersection(features))
    if leaked:
        raise LeakedFitError(
            f"fold {fold.index}: features were supplied for {', '.join(leaked)}, which the "
            "fold places in its test window. The fit does not need them and their presence "
            "means the caller assembled the panel wrong"
        )
    usable = set(fold.train_labels) | set(fold.calibration_labels)
    foreign = sorted(set(features) - usable)
    if foreign:
        shown = ", ".join(foreign[:5]) + ("..." if len(foreign) > 5 else "")
        raise LeakedFitError(
            f"fold {fold.index}: features were supplied for {len(foreign)} label(s) the fold "
            f"places in neither its training nor its calibration window ({shown}). Their "
            "provenance cannot be established here, so they are refused rather than ignored"
        )


def _model_version(
    fold: Fold,
    config: ModelConfig,
    train_labels: Sequence[str],
    calibration_labels: Sequence[str],
) -> str:
    """The identity of the fitted function, excluding everything held back.

    `fold.fold_hash` is deliberately not an input. It hashes `test_labels`, so
    using it would make two folds that differ only in what they hold back
    produce two different models, which is exactly the observation AC-2 uses to
    prove the test window did not reach the fit.
    """
    body = {
        "config_version": config.config_version,
        "fold_index": fold.index,
        "train": [fold.train.start.isoformat(), fold.train.end.isoformat()],
        "calibration": [
            fold.calibration.start.isoformat(),
            fold.calibration.end.isoformat(),
        ],
        "horizon_seconds": int(fold.horizon.total_seconds()),
        "purge_seconds": int(fold.purge.total_seconds()),
        "train_labels": list(train_labels),
        "calibration_labels": list(calibration_labels),
        "feature_names": list(config.feature_names),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "mdl-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _effective_sample_size(weights: np.ndarray) -> float:
    """Kish's effective sample size from the uniqueness weights.

    Equal weights give back the row count, which is the only case where the row
    count was ever the right answer. Overlapping labels weigh less than one
    each and the sum falls below the count, which is the whole reason UNIT-027
    computes uniqueness at all.
    """
    total = float(weights.sum())
    squared = float((weights**2).sum())
    if squared <= 0.0:
        return 0.0
    return total * total / squared


def _expected_calibration_error(predicted: np.ndarray, observed: np.ndarray, bins: int) -> float:
    """Bin the predicted probabilities and average the gap to observed frequency.

    Weighted by bin occupancy, so a bin holding two points cannot dominate one
    holding two hundred. An empty bin contributes nothing rather than a zero
    error, because no evidence is not perfect agreement.
    """
    edges = np.linspace(0.0, 1.0, bins + 1)
    placed = np.clip(np.digitize(predicted, edges[1:-1], right=False), 0, bins - 1)
    total = 0.0
    for index in range(bins):
        members = placed == index
        count = int(members.sum())
        if not count:
            continue
        gap = abs(float(predicted[members].mean()) - float(observed[members].mean()))
        total += gap * count
    return total / float(len(predicted)) if len(predicted) else 0.0
