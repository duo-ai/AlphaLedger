"""Expanding chronological walk-forward with purged boundaries.

Design section 7 asks for four periods in time order: a training window, a
calibration window where one threshold is chosen, a locked test window, and
then prospective competition observation. This module builds the first three
and decides which labels may be used in each.

The rule that does the work is the purge. A label predicted near the end of a
window has an outcome that resolves after the window ends, so using it fits on
information the boundary claims not to have. Such a label is excluded and
named, never trimmed or reassigned. The gap between adjacent windows is at
least the forecast horizon, and a configuration whose purge is shorter is
refused at construction rather than at use, because by the time a fold exists
the caller is already reasoning about results.

Nothing here reads a clock. A split of a past period has to be reproducible
later, which it cannot be if it depends on when it ran.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from alphaledger.domain.contracts import require_utc

__all__ = [
    "EMPTY_TEST_WINDOW",
    "IN_PURGE_GAP",
    "OUTCOME_CROSSES_BOUNDARY",
    "Fold",
    "FoldOrderError",
    "Labelled",
    "Purged",
    "SplitConfig",
    "SplitConfigurationError",
    "WalkForward",
    "Window",
    "walk_forward",
]

OUTCOME_CROSSES_BOUNDARY = "outcome_crosses_boundary"
IN_PURGE_GAP = "in_purge_gap"
EMPTY_TEST_WINDOW = "empty_test_window"


class SplitConfigurationError(ValueError):
    """A split was asked for that cannot be honest."""


class FoldOrderError(ValueError):
    """A fold's windows are not in time order, or are not purged apart."""


@dataclass(frozen=True, slots=True)
class Window:
    """A half-open interval, start inclusive and end exclusive."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", require_utc(self.start, "start"))
        object.__setattr__(self, "end", require_utc(self.end, "end"))
        if self.end <= self.start:
            raise ValueError(
                f"end {self.end.isoformat()} must follow start {self.start.isoformat()}"
            )

    def holds(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


@dataclass(frozen=True, slots=True)
class Labelled:
    """One prediction instant and the instant its outcome is known."""

    label_id: str
    prediction_time: datetime
    outcome_time: datetime

    def __post_init__(self) -> None:
        if not self.label_id.strip():
            raise ValueError("label_id must identify the observation; it is never defaulted")
        for field in ("prediction_time", "outcome_time"):
            object.__setattr__(self, field, require_utc(getattr(self, field), field))
        if self.outcome_time < self.prediction_time:
            raise ValueError(
                f"outcome_time {self.outcome_time.isoformat()} precedes prediction_time "
                f"{self.prediction_time.isoformat()}, which would resolve a label before "
                "it was made"
            )


@dataclass(frozen=True, slots=True)
class SplitConfig:
    """The frozen shape of the walk-forward."""

    horizon: timedelta
    purge: timedelta
    train: timedelta
    calibration: timedelta
    test: timedelta
    folds: int

    def __post_init__(self) -> None:
        for field in ("horizon", "train", "calibration", "test"):
            value = getattr(self, field)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise SplitConfigurationError(f"{field} must be a positive duration; got {value!r}")
        if not isinstance(self.folds, int) or isinstance(self.folds, bool) or self.folds <= 0:
            raise SplitConfigurationError(f"folds must be a positive count; got {self.folds!r}")
        if self.purge < self.horizon:
            raise SplitConfigurationError(
                f"purge {self.purge} is shorter than horizon {self.horizon}. The purge exists "
                "to cover the horizon; a shorter one leaves a label still resolving on both "
                "sides of a boundary"
            )


@dataclass(frozen=True, slots=True)
class Purged:
    """One label kept out of every window, and why."""

    label_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Fold:
    """One training, calibration, and locked test window, with its labels."""

    index: int
    train: Window
    calibration: Window
    test: Window
    horizon: timedelta
    purge: timedelta
    train_labels: tuple[str, ...]
    calibration_labels: tuple[str, ...]
    test_labels: tuple[str, ...]
    purged: tuple[Purged, ...]
    fold_hash: str = ""

    def __post_init__(self) -> None:
        pairs = ((self.train, self.calibration), (self.calibration, self.test))
        for earlier, later in pairs:
            if later.start < earlier.end:
                raise FoldOrderError(
                    f"fold {self.index}: a window starting {later.start.isoformat()} overlaps "
                    f"one ending {earlier.end.isoformat()}, so a fit could see what it is "
                    "meant to be tested against"
                )
            if later.start - earlier.end < self.purge:
                raise FoldOrderError(
                    f"fold {self.index}: the gap between {earlier.end.isoformat()} and "
                    f"{later.start.isoformat()} is narrower than the purge {self.purge}"
                )
        object.__setattr__(self, "fold_hash", self.fold_hash or self._address())

    def _address(self) -> str:
        body = {
            "index": self.index,
            "train": [self.train.start.isoformat(), self.train.end.isoformat()],
            "calibration": [
                self.calibration.start.isoformat(),
                self.calibration.end.isoformat(),
            ],
            "test": [self.test.start.isoformat(), self.test.end.isoformat()],
            "horizon_seconds": int(self.horizon.total_seconds()),
            "purge_seconds": int(self.purge.total_seconds()),
            "train_labels": list(self.train_labels),
            "calibration_labels": list(self.calibration_labels),
            "test_labels": list(self.test_labels),
            "purged": [[item.label_id, item.reason] for item in self.purged],
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WalkForward:
    """The folds that fit, and what stopped the ones that did not."""

    folds: tuple[Fold, ...]
    reasons: tuple[str, ...]


def walk_forward(
    origin: datetime,
    labels: Iterable[Labelled],
    config: SplitConfig,
    *,
    available_until: datetime,
) -> WalkForward:
    """Build the folds the available span supports, in time order.

    The training window expands fold over fold while the calibration and test
    windows move forward, and successive test windows never overlap, so no
    period is counted twice in a final result.

    A span too short for a fold returns no folds and the reason. It never
    returns a fold with a shortened purge, because that would answer the
    question by changing it.

    `available_until` is required rather than defaulted. Without it a caller
    gets as many folds as it asked for, whatever the data covers, and a later
    stage averaging over "three folds" would be averaging over one real fold and
    two built out of nothing with no artifact saying so.
    """
    start = require_utc(origin, "origin")
    limit = require_utc(available_until, "available_until")
    ordered = sorted(labels, key=lambda item: (item.prediction_time, item.label_id))

    folds: list[Fold] = []
    reasons: list[str] = []
    for index in range(config.folds):
        train = Window(start=start, end=start + config.train + index * config.test)
        calibration = Window(
            start=train.end + config.purge,
            end=train.end + config.purge + config.calibration,
        )
        test = Window(
            start=calibration.end + config.purge,
            end=calibration.end + config.purge + config.test,
        )
        if test.end > limit:
            reasons.append(
                f"insufficient span for fold {index}: it would end "
                f"{test.end.isoformat()}, past the available {limit.isoformat()}"
            )
            break
        assigned = _assign(ordered, train, calibration, test)
        folds.append(
            Fold(
                index=index,
                train=train,
                calibration=calibration,
                test=test,
                horizon=config.horizon,
                purge=config.purge,
                train_labels=assigned[0],
                calibration_labels=assigned[1],
                test_labels=assigned[2],
                purged=assigned[3],
            )
        )
    if len(folds) < config.folds:
        reasons.append(f"requested {config.folds} folds, built {len(folds)}")
    # A fold whose test window holds nothing, while the label series holds
    # something, is a fold that cannot produce a result. It stays, because the
    # geometry is still true, but it does not get to look like the others.
    if ordered:
        for fold in folds:
            if not fold.test_labels:
                reasons.append(
                    f"{EMPTY_TEST_WINDOW}: fold {fold.index} tests "
                    f"{fold.test.start.isoformat()} to {fold.test.end.isoformat()}, "
                    "where no label resolves"
                )
    return WalkForward(folds=tuple(folds), reasons=tuple(reasons))


def _assign(
    labels: Sequence[Labelled], train: Window, calibration: Window, test: Window
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[Purged, ...]]:
    """Place each label in the window that holds its whole outcome, or purge it.

    A label is usable only when both its prediction and its outcome fall inside
    one window. A prediction inside a window whose outcome resolves after it is
    the leak the purge exists for, and a prediction inside a gap belongs to no
    window at all.
    """
    train_labels: list[str] = []
    calibration_labels: list[str] = []
    test_labels: list[str] = []
    purged: list[Purged] = []
    windows = ((train, train_labels), (calibration, calibration_labels), (test, test_labels))
    for label in labels:
        for window, bucket in windows:
            if not window.holds(label.prediction_time):
                continue
            if label.outcome_time <= window.end:
                bucket.append(label.label_id)
            else:
                purged.append(Purged(label_id=label.label_id, reason=OUTCOME_CROSSES_BOUNDARY))
            break
        else:
            if train.start <= label.prediction_time < test.end:
                purged.append(Purged(label_id=label.label_id, reason=IN_PURGE_GAP))
    return tuple(train_labels), tuple(calibration_labels), tuple(test_labels), tuple(purged)
