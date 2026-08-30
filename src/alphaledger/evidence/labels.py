"""Forward residual return labels, the target UNIT-025 predicts.

This is the highest-leverage definition in the research lane. Everything else
produces evidence about the label; the label decides what the evidence is
evidence of. An error here does not add noise, it silently redefines the
question, and no care taken later recovers it.

The quantity is the sum of per-session residual returns over a holding window,
where a session's residual return is the symbol's close to close return minus
the median close to close return of its sector peers on that same session. That
is the cumulative abnormal return of the event-study literature, and it is
deliberately identical to `cumulative_abnormal_return` and `residual_return_5s`
in UNIT-022 with the window pointed forwards instead of backwards. Feature and
label are then the same quantity in two directions rather than two quantities
that happen to correlate. A geometric compounding would be defensible on its
own and inconsistent here, which is worse.

Three properties of this module exist because the corresponding mistake is
routine in cross-sectional equity research, not because the code looked
fragile.

The label starts at a tradeable price. A decision taken from session `t`'s
close cannot be filled at session `t`'s close, so `entry_offset_sessions`
defaults to one and the return runs from the next session's close. The skipped
overnight gap is exactly where news is repriced, so including it is the single
easiest way to manufacture an alpha that evaporates on contact with a broker.
An offset of zero is permitted, because a later intraday variant may want it,
and it carries `untradeable_entry` so no result built on it can be mistaken for
one an order could have earned.

Overlapping labels are not independent observations. Sampling daily at a
multi-session horizon makes consecutive labels share most of their outcome
window, so a fit that counts rows counts the same information many times and
every significance estimate built on that count is inflated.
`with_uniqueness` gives each label the average, over its own outcome sessions,
of one divided by the number of labels concurrently open on that session for
that symbol, which is the standard uniqueness weight. UNIT-025 is expected to
carry it into the fit; this unit only measures it.

An incomplete horizon is never a zero. A symbol that stops trading mid-window
yields no label at all. Scoring a delisting as a flat return is the most
flattering error available, because it converts the worst outcome in the
dataset into an average one.

Two things this module cannot do, stated rather than hidden. It cannot verify
that its bars are split and dividend adjusted: an adjustment is invisible in a
single price series, and the only detector available is a magnitude threshold,
which would be an unselected number sitting inside a label definition.
`implausible_return` therefore flags and never filters, so an artefact stays
visible instead of being quietly removed. And it does not read a clock, because
a label rebuilt a year later has to be the same label.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from alphaledger.domain.contracts import require_utc
from alphaledger.evidence.price_volume import (
    NO_PEER_DATA,
    SECTOR_FALLBACK_MARKET,
    AmbiguousBarError,
    Bar,
)
from alphaledger.forecast.splits import Labelled

__all__ = [
    "IMPLAUSIBLE_MAGNITUDE",
    "NO_PEER_DATA",
    "SECTOR_FALLBACK_MARKET",
    "UNTRADEABLE_ENTRY",
    "AmbiguousBarError",
    "DuplicateLabelError",
    "InsufficientHistoryError",
    "Label",
    "LabelConfig",
    "build",
    "with_uniqueness",
]

# `NO_PEER_DATA`, `SECTOR_FALLBACK_MARKET`, and `AmbiguousBarError` are
# re-exported from UNIT-022 rather than redefined. One condition deserves one
# name: a consumer reading a label flag and a feature flag should not have to
# discover that two spellings of `no_peer_data` mean the same thing, and two
# exception types for one ambiguity would make an `except` clause silently
# partial.

IMPLAUSIBLE_MAGNITUDE = "implausible_magnitude"
UNTRADEABLE_ENTRY = "untradeable_entry"


class InsufficientHistoryError(ValueError):
    """The panel cannot reach the session the entry would have filled on."""


class DuplicateLabelError(ValueError):
    """One label identity appeared twice in a set being weighted."""


@dataclass(frozen=True, slots=True)
class LabelConfig:
    """Frozen label configuration. Any change changes `label_version`.

    Every default here is declared, not selected. Design section 4 requires
    selection on development data, registration as a trial, and a freeze before
    an autonomous session, and none of that has happened.
    """

    horizon_sessions: int = 5
    entry_offset_sessions: int = 1
    min_sector_peers: int = 2
    implausible_return: float = 0.5
    sector_by_symbol: Mapping[str, str] = MappingProxyType({})
    label_version: str = field(init=False, default="")

    def __post_init__(self) -> None:
        for name in ("horizon_sessions", "entry_offset_sessions", "min_sector_peers"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be a whole number of sessions; got {value!r}")
        if self.horizon_sessions <= 0:
            raise ValueError(
                f"horizon_sessions must be positive; got {self.horizon_sessions!r}. A "
                "zero-session horizon would label an entry against its own price"
            )
        if self.entry_offset_sessions < 0:
            raise ValueError(
                f"entry_offset_sessions must not be negative; got "
                f"{self.entry_offset_sessions!r}. A negative offset would enter before "
                "the decision that justified the entry"
            )
        if self.min_sector_peers < 1:
            raise ValueError(
                f"min_sector_peers must be at least one; got {self.min_sector_peers!r}"
            )
        if isinstance(self.implausible_return, bool) or not isinstance(
            self.implausible_return, int | float
        ):
            raise TypeError(
                f"implausible_return must be a real number; got {self.implausible_return!r}"
            )
        if not float(self.implausible_return) > 0.0:
            raise ValueError(
                f"implausible_return must be positive; got {self.implausible_return!r}. A "
                "non-positive bound would flag every label and so flag nothing"
            )
        object.__setattr__(self, "implausible_return", float(self.implausible_return))
        object.__setattr__(
            self,
            "sector_by_symbol",
            MappingProxyType({str(k): str(v) for k, v in dict(self.sector_by_symbol).items()}),
        )
        object.__setattr__(self, "label_version", self._version())

    def _version(self) -> str:
        body = {
            "horizon_sessions": self.horizon_sessions,
            "entry_offset_sessions": self.entry_offset_sessions,
            "min_sector_peers": self.min_sector_peers,
            "implausible_return": repr(self.implausible_return),
            "sector_by_symbol": dict(sorted(self.sector_by_symbol.items())),
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return "lbl-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Label:
    """One realised forward residual return, with when it became knowable.

    `prediction_time` and `outcome_time` are the pair UNIT-024 purges against,
    and they are deliberately far apart: the decision is made at the first and
    the answer is not knowable until the second. `entry_session` sits between
    them and is what makes the return tradeable.
    """

    label_id: str
    symbol: str
    prediction_time: datetime
    outcome_time: datetime
    forward_residual_return: float
    entry_session: datetime
    exit_session: datetime
    sessions_used: int
    outcome_sessions: tuple[datetime, ...]
    uniqueness: float
    quality_flags: tuple[str, ...]
    label_version: str

    def as_labelled(self) -> Labelled:
        """Hand this label to UNIT-024's walk-forward without a shim.

        A shim would be one more place for the two timestamps to disagree, and
        a label placed in the wrong window by a disagreement is exactly the
        leak the purge exists to prevent.
        """
        return Labelled(
            label_id=self.label_id,
            prediction_time=self.prediction_time,
            outcome_time=self.outcome_time,
        )


def build(
    symbol: str,
    decision_session: datetime,
    bars: Iterable[Bar],
    config: LabelConfig,
) -> Label | None:
    """Return the forward residual label for `symbol` decided at `decision_session`.

    `bars` covers the symbol and its peers and deliberately includes sessions
    after the decision. A label is allowed to see the future; that is what
    distinguishes it from a feature, and `outcome_time` is how a consumer knows
    when it stopped being the future.

    `None` means the horizon does not complete, which is an ordinary outcome
    and never a zero return.
    """
    anchor = require_utc(decision_session, "decision_session")
    series = _series(bars)
    own = series.get(symbol)
    if not own:
        return None

    sessions = sorted(own)
    decided = [item for item in sessions if item <= anchor]
    if not decided:
        return None

    entry_index = len(decided) - 1 + config.entry_offset_sessions
    if entry_index >= len(sessions):
        # Two different facts wear the same shape here, and only one of them is
        # the caller's mistake. If the panel itself stops before the entry
        # session, it was built too short and no symbol in it could be
        # labelled. If this symbol stops while the rest of the panel keeps
        # trading, it delisted, which AC-4 makes an ordinary missing outcome.
        # The caller cannot precompute the second from the panel's own bounds,
        # so raising on it would demand knowledge only this function has.
        panel_last = max(max(known) for known in series.values())
        if sessions[-1] < panel_last:
            return None
        raise InsufficientHistoryError(
            f"{symbol}: the panel ends at {sessions[-1].isoformat()}, before the entry "
            f"session an offset of {config.entry_offset_sessions} from "
            f"{anchor.isoformat()} would have filled on. The panel was built wrong; "
            "this is not a missing outcome"
        )
    exit_index = entry_index + config.horizon_sessions
    if exit_index >= len(sessions):
        return None

    window = sessions[entry_index : exit_index + 1]
    flags: list[str] = []
    peers = _peers(symbol, series, config, flags)
    value, outcome_time = _residual_sum(own, peers, window, flags)

    if config.entry_offset_sessions == 0:
        flags.append(UNTRADEABLE_ENTRY)
    if abs(value) > config.implausible_return:
        flags.append(IMPLAUSIBLE_MAGNITUDE)

    return Label(
        label_id=_label_id(symbol, anchor, config),
        symbol=symbol,
        prediction_time=anchor,
        outcome_time=outcome_time,
        forward_residual_return=value,
        entry_session=window[0],
        exit_session=window[-1],
        sessions_used=len(window) - 1,
        outcome_sessions=tuple(window[1:]),
        uniqueness=1.0,
        quality_flags=tuple(sorted(set(flags))),
        label_version=config.label_version,
    )


def with_uniqueness(labels: Sequence[Label]) -> tuple[Label, ...]:
    """Give every label the average uniqueness of its own outcome sessions.

    Concurrency is counted per symbol and session. Two symbols resolving over
    the same calendar dates are two independent observations: sharing a date is
    not sharing an outcome, and treating it as one would shrink the effective
    sample of a diversified panel for no reason.

    A label overlapping nothing weighs one. Two labels sharing every outcome
    session weigh one half each, which is the whole point: they are close to
    one observation and a fit that counted them as two would overstate its
    effective sample size by a factor of two.
    """
    seen: set[str] = set()
    for label in labels:
        if label.label_id in seen:
            # Refused rather than tolerated, unlike `_series`, which accepts a
            # bar repeated identically. The asymmetry is the point: a repeated
            # bar is idempotent, while a repeated label changes the arithmetic
            # it is an input to. Counting one label twice makes it concurrent
            # with itself and halves the weight of the very observation being
            # duplicated, so the caller would get a quieter fit and no signal
            # that anything went wrong.
            raise DuplicateLabelError(
                f"label {label.label_id} appears more than once. Weighting it would "
                "make it concurrent with itself and halve its own uniqueness"
            )
        seen.add(label.label_id)

    concurrent: dict[tuple[str, datetime], int] = {}
    for label in labels:
        for session in label.outcome_sessions:
            key = (label.symbol, session)
            concurrent[key] = concurrent.get(key, 0) + 1

    weighted: list[Label] = []
    for label in labels:
        if not label.outcome_sessions:
            weighted.append(label)
            continue
        shares = [1.0 / concurrent[(label.symbol, session)] for session in label.outcome_sessions]
        carried = {
            name: getattr(label, name)
            for name in Label.__dataclass_fields__
            if name != "uniqueness"
        }
        weighted.append(Label(uniqueness=sum(shares) / len(shares), **carried))
    return tuple(weighted)


def _series(bars: Iterable[Bar]) -> dict[str, dict[datetime, Bar]]:
    """Bars by symbol and session, refusing a contradiction rather than resolving it."""
    held: dict[str, dict[datetime, Bar]] = {}
    for item in bars:
        sessions = held.setdefault(item.symbol, {})
        seen = sessions.get(item.session)
        if seen is None:
            sessions[item.session] = item
        elif seen != item:
            raise AmbiguousBarError(
                f"two bars describe {item.symbol} on {item.session.isoformat()} and "
                "disagree. Choosing between them would make the label depend on the "
                "order the panel was assembled in"
            )
    return held


def _peers(
    symbol: str,
    series: Mapping[str, Mapping[datetime, Bar]],
    config: LabelConfig,
    flags: list[str],
) -> list[Mapping[datetime, Bar]]:
    """Sector peers, falling back to the whole panel and saying so.

    This mirrors UNIT-022 rather than inventing a second policy. A label
    demeaned against a different cross-section from the features would make the
    model predict something its inputs are not about.
    """
    sector = config.sector_by_symbol.get(symbol)
    named = [
        other
        for other in sorted(series)
        if other != symbol and sector is not None and config.sector_by_symbol.get(other) == sector
    ]
    if len(named) >= config.min_sector_peers:
        return [series[other] for other in named]
    flags.append(SECTOR_FALLBACK_MARKET)
    return [series[other] for other in sorted(series) if other != symbol]


@dataclass(frozen=True, slots=True)
class _Move:
    """One close to close return and the two bars it was actually measured across.

    The two bars are carried rather than recomputed because `outcome_time` has
    to cover every bar the label consumed, and the bar a return reaches back to
    is not always the one a reader would predict. A series missing a session
    yields a multi-session return whose predecessor can sit outside the holding
    window entirely, and a window scan cannot see it.
    """

    value: float
    previous: Bar
    current: Bar


def _returns(sessions: Mapping[datetime, Bar]) -> dict[datetime, _Move]:
    """Close to close returns keyed by the session they belong to.

    Numerically identical to UNIT-022's `_return_by_session`. The duplication is
    recorded in the intake and pinned by a test that compares the two on one
    fixture, because two implementations of one definition drift and a drifting
    label is not detectable from its own output.

    Known limitation, shared with UNIT-022 and deliberately not fixed here: a
    missing session produces a multi-session return silently, so a peer absent
    for three sessions contributes a four-session move to a one-session
    cross-section. `own` has the same defect for the same reason. Correcting it
    would change the number and break the test pinning this against the price
    family, so it belongs to the refactor unit that owns both files. What is
    fixed here is the temporal half: whatever bars a return reaches, they count
    towards `outcome_time`.
    """
    out: dict[datetime, _Move] = {}
    ordered = [sessions[key] for key in sorted(sessions)]
    for previous, current in itertools.pairwise(ordered):
        out[current.session] = _Move(
            value=float(current.close / previous.close) - 1.0,
            previous=previous,
            current=current,
        )
    return out


def _residual_sum(
    own: Mapping[datetime, Bar],
    peers: Sequence[Mapping[datetime, Bar]],
    window: Sequence[datetime],
    flags: list[str],
) -> tuple[float, datetime]:
    """The summed residual return, and the instant its last input was observed.

    `window` runs from the entry session to the exit session inclusive, and the
    entry session contributes only its close: the first return measured is the
    one from the entry close to the next session's close, which is the first
    move an order placed at entry could actually have earned.

    The outcome instant is returned from here rather than recomputed by a second
    function walking the same window. That is the whole correction: the two
    walks disagreed whenever a peer return reached back through a gap to a bar
    the window did not contain, and a label reporting the earlier instant would
    be admitted by UNIT-024 into a window its outcome had not yet resolved in.
    Derived in one place, they cannot disagree.
    """
    own_returns = _returns(own)
    peer_returns = [_returns(peer) for peer in peers]
    total = 0.0
    undemeaned = 0
    consumed: list[datetime] = []
    for session in window[1:]:
        move = own_returns[session]
        consumed.append(move.previous.first_seen_time)
        consumed.append(move.current.first_seen_time)
        cross_section: list[float] = []
        for values in peer_returns:
            peer_move = values.get(session)
            if peer_move is None:
                continue
            cross_section.append(peer_move.value)
            consumed.append(peer_move.previous.first_seen_time)
            consumed.append(peer_move.current.first_seen_time)
        if not cross_section:
            undemeaned += 1
            total += move.value
            continue
        total += move.value - statistics.median(cross_section)
    if undemeaned:
        # The count, not a bare flag, matching UNIT-022: one raw return inside a
        # five-session label is a different fact from a label nothing was
        # demeaned against at all, and a consumer cannot weigh the first
        # without knowing how many.
        flags.append(f"{NO_PEER_DATA}:{undemeaned}")
    # `window` always holds at least an entry and one further session, because
    # `horizon_sessions` is validated positive, so `consumed` is never empty.
    return total, max(consumed)


def _label_id(symbol: str, decision_session: datetime, config: LabelConfig) -> str:
    """A stable address for one symbol, one decision instant, one definition.

    `hashlib` rather than the builtin `hash`, whose per-process salt would give
    the same label two identities in two runs and break every join a frozen run
    depends on. The label version is inside the address on purpose: relabelling
    under a changed horizon produces a different label, and silently reusing
    the identity would let two definitions collide in the ledger.
    """
    body = f"{symbol}|{decision_session.isoformat()}|{config.label_version}"
    return "lbl-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]
