"""Chronological split tests.

A split is the machinery that makes a later number honest, so every test here
asks whether information could travel backwards: from a calibration window into
a fit, or from an outcome that had not resolved yet into the window that claims
to predict it.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from alphaledger.forecast.splits import (
    EMPTY_TEST_WINDOW,
    IN_PURGE_GAP,
    OUTCOME_CROSSES_BOUNDARY,
    Fold,
    FoldOrderError,
    Labelled,
    SplitConfig,
    SplitConfigurationError,
    Window,
    walk_forward,
)

ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)
# A span long enough that the limit is never what stops a fold.
FAR = ORIGIN + timedelta(days=10_000)


def moment(days: float) -> datetime:
    return ORIGIN + timedelta(days=days)


def config(**overrides: object) -> SplitConfig:
    fields: dict[str, object] = {
        "horizon": 5 * DAY,
        "purge": 5 * DAY,
        "train": 100 * DAY,
        "calibration": 20 * DAY,
        "test": 20 * DAY,
        "folds": 3,
    }
    fields.update(overrides)
    return SplitConfig(**fields)  # type: ignore[arg-type]


def labelled(label_id: str, predicted: float, resolves_in: float = 5) -> Labelled:
    return Labelled(
        label_id=label_id,
        prediction_time=moment(predicted),
        outcome_time=moment(predicted + resolves_in),
    )


# --- success ------------------------------------------------------------


def test_a_fold_places_its_windows_in_time_order_with_the_purge_between_them() -> None:
    [fold, *_] = walk_forward(ORIGIN, (), config(), available_until=FAR).folds

    assert fold.train.start == ORIGIN
    assert fold.train.end == moment(100)
    assert fold.calibration.start == moment(105)
    assert fold.calibration.end == moment(125)
    assert fold.test.start == moment(130)
    assert fold.test.end == moment(150)


def test_the_training_window_expands_while_the_test_window_moves_forward() -> None:
    folds = walk_forward(ORIGIN, (), config(), available_until=FAR).folds

    assert [fold.train.end for fold in folds] == [moment(100), moment(120), moment(140)]
    assert [fold.train.start for fold in folds] == [ORIGIN, ORIGIN, ORIGIN]
    assert [fold.test.start for fold in folds] == [moment(130), moment(150), moment(170)]


def test_no_two_test_windows_overlap_so_a_result_is_never_counted_twice() -> None:
    folds = walk_forward(ORIGIN, (), config(), available_until=FAR).folds

    for earlier, later in itertools.pairwise(folds):
        assert earlier.test.end <= later.test.start


def test_a_label_is_assigned_to_the_window_its_whole_outcome_falls_inside() -> None:
    labels = (labelled("in-train", 10), labelled("in-cal", 110), labelled("in-test", 135))

    [fold, *_] = walk_forward(ORIGIN, labels, config(), available_until=FAR).folds

    assert fold.train_labels == ("in-train",)
    assert fold.calibration_labels == ("in-cal",)
    assert fold.test_labels == ("in-test",)


def test_the_same_inputs_produce_the_same_fold_hashes() -> None:
    labels = (labelled("a", 10), labelled("b", 110))

    first = walk_forward(ORIGIN, labels, config(), available_until=FAR).folds
    second = walk_forward(ORIGIN, labels, config(), available_until=FAR).folds

    assert [fold.fold_hash for fold in first] == [fold.fold_hash for fold in second]


def test_a_different_purge_changes_the_hash_so_two_splits_are_never_confused() -> None:
    wide = walk_forward(ORIGIN, (), config(purge=10 * DAY), available_until=FAR).folds
    narrow = walk_forward(ORIGIN, (), config(), available_until=FAR).folds

    assert wide[0].fold_hash != narrow[0].fold_hash


def test_the_declared_purge_is_part_of_the_fold_address() -> None:
    """Two folds over identical windows but built under different purges are
    different folds. Only a direct construction can hold the windows still
    while the purge moves, which is why this is not a walk forward."""

    def fold(purge: timedelta) -> Fold:
        return Fold(
            index=0,
            train=Window(start=ORIGIN, end=moment(100)),
            calibration=Window(start=moment(120), end=moment(140)),
            test=Window(start=moment(160), end=moment(180)),
            horizon=5 * DAY,
            purge=purge,
            train_labels=(),
            calibration_labels=(),
            test_labels=(),
            purged=(),
        )

    assert fold(5 * DAY).fold_hash != fold(10 * DAY).fold_hash


# --- failure ------------------------------------------------------------


def test_a_purge_shorter_than_the_horizon_is_refused_naming_both() -> None:
    """The purge exists to cover the horizon. A shorter one lets a label whose
    outcome is still resolving sit on both sides of a boundary."""
    with pytest.raises(SplitConfigurationError) as raised:
        config(purge=4 * DAY, horizon=5 * DAY)

    assert "purge" in str(raised.value)
    assert "horizon" in str(raised.value)


def test_a_label_whose_outcome_crosses_a_boundary_is_excluded_and_named() -> None:
    """The leaked fixture the research rules require.

    The prediction sits inside the training window but the outcome resolves
    after it ends, so keeping it would fit on information that had not happened
    yet at the boundary the fold claims to respect.
    """
    labels = (labelled("straddles", 98, resolves_in=5), labelled("clean", 10))

    [fold, *_] = walk_forward(ORIGIN, labels, config(), available_until=FAR).folds

    assert fold.train_labels == ("clean",)
    excluded = {item.label_id: item.reason for item in fold.purged}
    assert excluded["straddles"] == OUTCOME_CROSSES_BOUNDARY


def test_a_label_predicted_inside_the_purge_gap_is_excluded_and_named() -> None:
    labels = (labelled("in-gap", 102),)

    [fold, *_] = walk_forward(ORIGIN, labels, config(), available_until=FAR).folds

    assert fold.train_labels == ()
    assert fold.calibration_labels == ()
    assert [(item.label_id, item.reason) for item in fold.purged] == [("in-gap", IN_PURGE_GAP)]


def test_a_fold_whose_windows_overlap_is_refused_rather_than_trimmed() -> None:
    """Constructed directly, because a caller assembling a fold by hand must
    not be able to produce one that a walk forward never would."""
    with pytest.raises(FoldOrderError, match="overlaps"):
        Fold(
            index=0,
            train=Window(start=ORIGIN, end=moment(100)),
            calibration=Window(start=moment(99), end=moment(120)),
            test=Window(start=moment(125), end=moment(145)),
            horizon=5 * DAY,
            purge=5 * DAY,
            train_labels=(),
            calibration_labels=(),
            test_labels=(),
            purged=(),
        )


def test_a_fold_whose_gap_is_narrower_than_its_purge_is_refused() -> None:
    with pytest.raises(FoldOrderError):
        Fold(
            index=0,
            train=Window(start=ORIGIN, end=moment(100)),
            calibration=Window(start=moment(102), end=moment(120)),
            test=Window(start=moment(125), end=moment(145)),
            horizon=5 * DAY,
            purge=5 * DAY,
            train_labels=(),
            calibration_labels=(),
            test_labels=(),
            purged=(),
        )


def test_a_window_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="end"):
        Window(start=moment(10), end=moment(5))


def test_a_label_whose_outcome_precedes_its_prediction_is_refused() -> None:
    with pytest.raises(ValueError, match="outcome_time"):
        Labelled(
            label_id="backwards",
            prediction_time=moment(10),
            outcome_time=moment(9),
        )


def test_a_naive_origin_is_refused() -> None:
    with pytest.raises(ValueError, match="origin"):
        walk_forward(datetime(2026, 1, 1), (), config(), available_until=FAR)


def test_a_non_positive_fold_count_is_refused() -> None:
    with pytest.raises(SplitConfigurationError, match="folds"):
        config(folds=0)


def test_a_label_predicted_in_the_calibration_gap_is_excluded_too() -> None:
    """Both gaps run through one branch today. A fixture for each keeps a
    change that special cased one boundary from passing."""
    labels = (labelled("after-calibration", 127),)

    [fold, *_] = walk_forward(ORIGIN, labels, config(), available_until=FAR).folds

    assert fold.calibration_labels == ()
    assert fold.test_labels == ()
    assert [(item.label_id, item.reason) for item in fold.purged] == [
        ("after-calibration", IN_PURGE_GAP)
    ]


# --- no trade -----------------------------------------------------------


def test_a_fold_whose_test_window_holds_no_label_is_reported_as_such() -> None:
    """Three structurally valid folds over data that only reaches the first one
    is not three results. Without this a later stage averages one real fold and
    two built out of nothing, and no artifact says so."""
    labels = (labelled("early", 10), labelled("only-fold-zero", 135))

    result = walk_forward(ORIGIN, labels, config(), available_until=FAR)

    assert len(result.folds) == 3
    empty = [reason for reason in result.reasons if reason.startswith(EMPTY_TEST_WINDOW)]
    assert len(empty) == 2
    assert "fold 1" in " ".join(empty)
    assert "fold 2" in " ".join(empty)


def test_a_fold_with_labels_in_its_test_window_is_not_reported_as_empty() -> None:
    labels = tuple(labelled(f"l{day}", day) for day in (135, 155, 175))

    result = walk_forward(ORIGIN, labels, config(), available_until=FAR)

    assert not [r for r in result.reasons if r.startswith(EMPTY_TEST_WINDOW)]


def test_an_absent_span_is_refused_rather_than_assumed() -> None:
    """The argument is required. A caller that omits it would otherwise get
    every fold it asked for, whatever the data covers."""
    with pytest.raises(TypeError):
        walk_forward(ORIGIN, (), config())  # type: ignore[call-arg]


def test_a_span_too_short_for_one_fold_yields_no_folds_and_says_why() -> None:
    """An empty split is an answer. The one thing it must never become is a
    fold with the purge relaxed to make the data fit."""
    result = walk_forward(ORIGIN, (), config(), available_until=moment(60))

    assert result.folds == ()
    assert any("insufficient" in reason for reason in result.reasons)


def test_a_span_that_fits_fewer_folds_than_asked_yields_those_it_fits() -> None:
    result = walk_forward(ORIGIN, (), config(), available_until=moment(155))

    assert len(result.folds) == 1
    assert any("requested 3" in reason for reason in result.reasons)


def test_a_fold_with_no_labels_at_all_is_still_a_fold() -> None:
    result = walk_forward(ORIGIN, (), config(), available_until=FAR)
    [fold, *_] = result.folds

    assert fold.train_labels == ()
    assert fold.purged == ()
    assert fold.fold_hash
    # An empty label series is the caller's input, not a property of the split.
    # Flagging every fold here would bury the case the flag is for, where data
    # exists and some folds cannot reach it.
    assert not [r for r in result.reasons if r.startswith(EMPTY_TEST_WINDOW)]
