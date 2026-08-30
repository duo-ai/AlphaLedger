"""Forward residual return label tests.

The label is the prediction target, so an error here redefines what every
downstream result means rather than adding noise to it. The fixture is built so
every expected number can be computed by hand: each session moves the symbol by
a distinct round percentage, and the peers are flat unless a test is about the
demeaning, which makes the residual equal to the raw return everywhere else.

Three of these tests exist because the corresponding mistake is routine in
cross-sectional equity research rather than because the code looked risky. The
entry offset guards a return the strategy could not have captured, the
uniqueness weights guard treating overlapping labels as independent
observations, and the incomplete-horizon case guards a delisting silently
becoming a zero return.
"""

from __future__ import annotations

import math
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from alphaledger.evidence.labels import (
    IMPLAUSIBLE_MAGNITUDE,
    NO_PEER_DATA,
    UNTRADEABLE_ENTRY,
    AmbiguousBarError,
    DuplicateLabelError,
    InsufficientHistoryError,
    Label,
    LabelConfig,
    build,
    with_uniqueness,
)
from alphaledger.evidence.price_volume import Bar
from alphaledger.forecast.splits import (
    OUTCOME_CROSSES_BOUNDARY,
    Labelled,
    SplitConfig,
    walk_forward,
)

SYMBOL = "TARGET"
PEERS = ("PEER1", "PEER2")
FIRST = datetime(2026, 5, 1, 20, 0, tzinfo=UTC)
SECTORS = {"TARGET": "tech", "PEER1": "tech", "PEER2": "tech"}


def session_at(index: int) -> datetime:
    return FIRST + timedelta(days=index)


def bar(symbol: str, index: int, close: str, *, seen_offset_minutes: int = 15) -> Bar:
    session = session_at(index)
    price = Decimal(close)
    return Bar(
        symbol=symbol,
        feed="sip_daily",
        session=session,
        first_seen_time=session + timedelta(minutes=seen_offset_minutes),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1_000_000,
    )


def config(**overrides: object) -> LabelConfig:
    settings: dict[str, object] = {"sector_by_symbol": SECTORS}
    settings.update(overrides)
    return LabelConfig(**settings)  # type: ignore[arg-type]


def panel(
    closes: dict[int, str],
    *,
    sessions: int = 12,
    peer_closes: dict[int, str] | None = None,
) -> tuple[Bar, ...]:
    """The symbol closes at 100 and the peers at 50 unless a test says otherwise."""
    bars: list[Bar] = []
    for index in range(sessions):
        bars.append(bar(SYMBOL, index, closes.get(index, "100.00")))
        for peer in PEERS:
            bars.append(bar(peer, index, (peer_closes or {}).get(index, "50.00")))
    return tuple(bars)


def vars_of(label: Label) -> dict[str, object]:
    """Field values of a frozen slots dataclass, for building a variant."""
    return {
        name: getattr(label, name)
        for name in (
            "label_id",
            "symbol",
            "prediction_time",
            "outcome_time",
            "forward_residual_return",
            "entry_session",
            "exit_session",
            "sessions_used",
            "outcome_sessions",
            "uniqueness",
            "quality_flags",
            "label_version",
        )
    }


# --- success: the hand-computed fixture ---------------------------------


def test_the_label_sums_the_sessions_the_entry_offset_names() -> None:
    """AC-1. Session 1's return is deliberately large and must not appear: a
    decision taken from session 0's close cannot be filled at that close, so a
    label including session 1's move collects a gap no order could earn."""
    closes = {1: "150.00", 2: "165.00", 3: "181.50"}
    block = build(SYMBOL, session_at(0), panel(closes), config(horizon_sessions=2))
    assert block is not None
    # Entry at session 1's close of 150. Sessions 2 and 3 each return 0.10.
    assert block.forward_residual_return == pytest.approx(0.20)
    assert block.entry_session == session_at(1)
    assert block.exit_session == session_at(3)
    assert block.sessions_used == 2


def test_the_untradeable_first_session_is_what_the_offset_excludes() -> None:
    """AC-1, stated as a difference. The same panel at offset zero picks up
    session 1's fifty percent move, which is precisely the overstatement the
    default offset exists to prevent."""
    closes = {1: "150.00", 2: "165.00", 3: "181.50"}
    tradeable = build(SYMBOL, session_at(0), panel(closes), config(horizon_sessions=2))
    immediate = build(
        SYMBOL, session_at(0), panel(closes), config(horizon_sessions=2, entry_offset_sessions=0)
    )
    assert tradeable is not None
    assert immediate is not None
    assert immediate.forward_residual_return > tradeable.forward_residual_return
    assert immediate.forward_residual_return == pytest.approx(0.60)


def test_an_offset_of_two_skips_two_sessions() -> None:
    """The offset has to mean what it says, not merely be non-zero."""
    closes = {1: "110.00", 2: "121.00", 3: "133.10"}
    block = build(
        SYMBOL, session_at(0), panel(closes), config(horizon_sessions=1, entry_offset_sessions=2)
    )
    assert block is not None
    assert block.entry_session == session_at(2)
    assert block.forward_residual_return == pytest.approx(0.10)


def test_a_flat_symbol_against_rising_peers_earns_a_negative_label() -> None:
    """AC-2. The label is residual, so standing still while the sector rises is
    a loss. A raw-return label would score this zero and the whole
    cross-sectional premise would be lost."""
    peers = {1: "50.00", 2: "55.00", 3: "60.50"}
    block = build(SYMBOL, session_at(0), panel({}, peer_closes=peers), config(horizon_sessions=2))
    assert block is not None
    assert block.forward_residual_return == pytest.approx(-0.20)


def test_the_residual_is_the_return_minus_the_peer_median_session_by_session() -> None:
    """AC-2. Both sides move, so neither a raw return nor a negated peer sum
    would produce this number."""
    closes = {1: "100.00", 2: "108.00", 3: "116.64"}
    peers = {1: "50.00", 2: "51.50", 3: "53.045"}
    block = build(
        SYMBOL, session_at(0), panel(closes, peer_closes=peers), config(horizon_sessions=2)
    )
    assert block is not None
    assert block.forward_residual_return == pytest.approx(0.16 - 0.06, abs=1e-9)


# --- outcome knowability -------------------------------------------------


def test_outcome_time_is_the_latest_first_seen_not_the_exit_session() -> None:
    """AC-3. UNIT-024 purges on the outcome instant, so a label that reported
    its exit session instead would claim to have resolved before the bar that
    resolved it was ever observed."""
    late = bar(SYMBOL, 3, "133.10", seen_offset_minutes=600)
    bars = [
        item
        for item in panel({1: "110.00", 2: "121.00", 3: "133.10"})
        if not (item.symbol == SYMBOL and item.session == session_at(3))
    ]
    bars.append(late)
    block = build(SYMBOL, session_at(0), tuple(bars), config(horizon_sessions=2))
    assert block is not None
    assert block.outcome_time == late.first_seen_time
    assert block.outcome_time > block.exit_session


def test_prediction_time_is_the_decision_session_not_the_entry() -> None:
    """The pair is what UNIT-024 purges against; collapsing them would hide the
    entry offset from every downstream fold."""
    block = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert block is not None
    assert block.prediction_time == session_at(0)
    assert block.entry_session == session_at(1)


def test_as_labelled_round_trips_into_the_split_contract() -> None:
    """AC-10. UNIT-024 consumes `Labelled`, so a shim between the two would be
    a place for the two timestamps to disagree."""
    block = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert block is not None
    handed = block.as_labelled()
    assert isinstance(handed, Labelled)
    assert handed.label_id == block.label_id
    assert handed.prediction_time == block.prediction_time
    assert handed.outcome_time == block.outcome_time


# --- uniqueness: overlapping labels are not independent -------------------


def test_an_isolated_label_has_uniqueness_one() -> None:
    """AC-5. Nothing shares its outcome sessions, so it is a whole observation."""
    only = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert only is not None
    (weighted,) = with_uniqueness((only,))
    assert weighted.uniqueness == pytest.approx(1.0)


def test_two_completely_overlapping_labels_each_count_one_half() -> None:
    """AC-5. Two labels resolving over the same sessions are close to one
    observation, not two, and a fit that counted them as two would overstate
    its effective sample size by a factor of two."""
    first = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert first is not None
    second = Label(**{**vars_of(first), "label_id": "second"})  # type: ignore[arg-type]
    weighted = with_uniqueness((first, second))
    assert [item.uniqueness for item in weighted] == [pytest.approx(0.5), pytest.approx(0.5)]


def test_a_partial_overlap_lands_strictly_between_one_half_and_one() -> None:
    """AC-5. The measure has to be graded, or it would only distinguish
    identical labels from disjoint ones and every real panel sits between."""
    settings = config(horizon_sessions=3)
    first = build(SYMBOL, session_at(0), panel({}), settings)
    second = build(SYMBOL, session_at(2), panel({}), settings)
    assert first is not None
    assert second is not None
    weighted = with_uniqueness((first, second))
    for item in weighted:
        assert 0.5 < item.uniqueness < 1.0


def test_uniqueness_is_counted_per_symbol_not_across_the_panel() -> None:
    """Two symbols moving over the same calendar sessions are two independent
    observations. Sharing a date is not sharing an outcome."""
    ours = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert ours is not None
    theirs = Label(**{**vars_of(ours), "label_id": "other", "symbol": "PEER1"})  # type: ignore[arg-type]
    weighted = with_uniqueness((ours, theirs))
    assert all(item.uniqueness == pytest.approx(1.0) for item in weighted)


def test_uniqueness_survives_being_applied_to_an_empty_panel() -> None:
    assert with_uniqueness(()) == ()


# --- failure paths --------------------------------------------------------


def test_a_panel_that_ends_before_the_entry_session_is_refused() -> None:
    """Entry is a precondition, not an outcome: if the panel cannot even reach
    the session the order would have filled on, the caller built it wrong."""
    with pytest.raises(InsufficientHistoryError, match=SYMBOL):
        build(SYMBOL, session_at(10), panel({}, sessions=11), config(horizon_sessions=2))


def test_two_bars_describing_one_session_and_disagreeing_stop_the_build() -> None:
    """Matching UNIT-022 rather than resolving it: choosing between them would
    make the label depend on the order the panel was assembled in."""
    bars = (*panel({}), bar(SYMBOL, 3, "999.00"))
    with pytest.raises(AmbiguousBarError, match=SYMBOL):
        build(SYMBOL, session_at(0), bars, config(horizon_sessions=2))


def test_a_bar_repeated_identically_is_not_ambiguous() -> None:
    bars = (*panel({}), bar(SYMBOL, 3, "100.00"))
    assert build(SYMBOL, session_at(0), bars, config(horizon_sessions=2)) is not None


def test_a_session_with_no_peer_leaves_the_return_undemeaned_and_says_so() -> None:
    """Matching UNIT-022's `no_peer_data` count. A raw return silently treated
    as a residual is the failure this flag exists to make visible."""
    bars = [
        item for item in panel({}) if not (item.symbol in PEERS and item.session == session_at(2))
    ]
    block = build(SYMBOL, session_at(0), tuple(bars), config(horizon_sessions=2))
    assert block is not None
    assert any(flag.startswith(NO_PEER_DATA) for flag in block.quality_flags)


def test_an_implausible_magnitude_is_flagged_and_still_emitted() -> None:
    """AC-7. An unadjusted split is the likely cause, and suppressing the label
    would hide the data defect while leaving the panel looking clean."""
    closes = {1: "100.00", 2: "50.00", 3: "50.00"}
    block = build(
        SYMBOL, session_at(0), panel(closes), config(horizon_sessions=2, implausible_return=0.4)
    )
    assert block is not None
    assert IMPLAUSIBLE_MAGNITUDE in block.quality_flags
    assert block.forward_residual_return == pytest.approx(-0.5)


def test_a_plausible_magnitude_carries_no_such_flag() -> None:
    block = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert block is not None
    assert IMPLAUSIBLE_MAGNITUDE not in block.quality_flags


def test_an_entry_offset_of_zero_is_flagged_as_untradeable() -> None:
    """AC-6. Permitted for a later intraday variant, but no result built on it
    may be mistaken for one an order could have earned."""
    immediate = build(
        SYMBOL, session_at(0), panel({}), config(horizon_sessions=2, entry_offset_sessions=0)
    )
    tradeable = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert immediate is not None
    assert tradeable is not None
    assert UNTRADEABLE_ENTRY in immediate.quality_flags
    assert UNTRADEABLE_ENTRY not in tradeable.quality_flags


# --- no-trade: an incomplete horizon is not a zero return -----------------


def test_an_incomplete_horizon_yields_no_label_rather_than_a_zero() -> None:
    """AC-4. A delisting scored as zero is the most flattering possible lie: it
    turns the worst outcome in the dataset into an average one."""
    assert build(SYMBOL, session_at(8), panel({}, sessions=12), config(horizon_sessions=5)) is None


def test_a_symbol_with_no_bars_at_all_yields_no_label() -> None:
    """An empty universe member is an ordinary outcome, not an error."""
    only_peers = tuple(item for item in panel({}) if item.symbol != SYMBOL)
    assert build(SYMBOL, session_at(0), only_peers, config(horizon_sessions=2)) is None


def test_the_horizon_boundary_is_exact_rather_than_off_by_one() -> None:
    """A horizon that fits exactly must produce a label, and one session more
    must not. An off-by-one here silently shortens every label in the panel."""
    settings = config(horizon_sessions=2)
    exact = build(SYMBOL, session_at(8), panel({}, sessions=12), settings)
    assert exact is not None
    assert exact.exit_session == session_at(11)
    assert build(SYMBOL, session_at(9), panel({}, sessions=12), settings) is None


# --- configuration is versioned ------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"horizon_sessions": 10},
        {"entry_offset_sessions": 2},
        {"implausible_return": 0.9},
        {"min_sector_peers": 5},
        {"sector_by_symbol": {"TARGET": "energy"}},
    ],
)
def test_any_configuration_change_changes_the_label_version(override: dict[str, object]) -> None:
    """AC-8. Two different label definitions sharing one identity in the ledger
    would make every recorded result ambiguous."""
    assert config(**override).label_version != config().label_version


def test_the_label_version_ignores_the_order_the_sector_map_was_given() -> None:
    first = config(sector_by_symbol={"A": "tech", "B": "energy"})
    second = config(sector_by_symbol={"B": "energy", "A": "tech"})
    assert first.label_version == second.label_version


def test_a_non_positive_horizon_is_refused() -> None:
    with pytest.raises(ValueError, match="horizon_sessions"):
        config(horizon_sessions=0)


def test_a_negative_entry_offset_is_refused() -> None:
    """A negative offset would enter before the decision that justified it."""
    with pytest.raises(ValueError, match="entry_offset_sessions"):
        config(entry_offset_sessions=-1)


def test_a_non_positive_implausible_return_is_refused() -> None:
    with pytest.raises(ValueError, match="implausible_return"):
        config(implausible_return=0.0)


def test_a_label_is_frozen_against_mutation() -> None:
    block = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert block is not None
    with pytest.raises(AttributeError):
        block.forward_residual_return = 1.0  # type: ignore[misc]


def test_no_label_value_is_ever_nan_or_infinite() -> None:
    """`Forecast` and `EvidenceCard` both reject non-finite floats, so emitting
    one here would only move the failure somewhere with less context."""
    block = build(
        SYMBOL, session_at(0), panel({1: "110.00", 2: "121.00"}), config(horizon_sessions=2)
    )
    assert block is not None
    assert math.isfinite(block.forward_residual_return)
    assert math.isfinite(block.uniqueness)


# --- restart and determinism ---------------------------------------------


DETERMINISM_SCRIPT = """
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphaledger.evidence.labels import LabelConfig, build, with_uniqueness
from alphaledger.evidence.price_volume import Bar

FIRST = datetime(2026, 5, 1, 20, 0, tzinfo=UTC)
SECTORS = {"TARGET": "tech", "PEER1": "tech", "PEER2": "tech"}


def bar(symbol, index, close):
    session = FIRST + timedelta(days=index)
    price = Decimal(close)
    return Bar(symbol=symbol, feed="sip_daily", session=session,
               first_seen_time=session + timedelta(minutes=15), open=price, high=price,
               low=price, close=price, volume=1_000_000)


closes = {1: "101.00", 2: "103.00", 3: "99.50", 4: "104.25", 5: "97.75"}
peers = {1: "50.50", 2: "50.25", 3: "51.00", 4: "49.75", 5: "50.10"}
bars = []
for index in range(12):
    bars.append(bar("TARGET", index, closes.get(index, "100.00")))
    for peer in ("PEER1", "PEER2"):
        bars.append(bar(peer, index, peers.get(index, "50.00")))

config = LabelConfig(horizon_sessions=3, sector_by_symbol=SECTORS)
made = []
for start in range(6):
    label = build("TARGET", FIRST + timedelta(days=start), tuple(bars), config)
    if label is not None:
        made.append(label)
print(config.label_version)
for item in with_uniqueness(tuple(made)):
    print(item.label_id, repr(item.forward_residual_return), repr(item.uniqueness),
          item.entry_session.isoformat(), item.exit_session.isoformat(),
          ",".join(item.quality_flags))
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


def test_two_processes_produce_byte_identical_output() -> None:
    """AC-9, checked to the repr and under two hash seeds so any dependence on
    dict or set ordering would show."""
    assert in_a_new_process("0") == in_a_new_process("54321")


def test_the_determinism_fixture_actually_produces_labels() -> None:
    """Comparing two empty outputs would pass while proving nothing."""
    output = in_a_new_process("0")
    assert output.count("lbl-") >= 6
    # A uniqueness strictly below one proves the overlap weighting actually
    # ran, which a fixture of disjoint labels would not have exercised.
    assert " 0.6111" in output


def test_the_demeaning_agrees_with_the_price_feature_family() -> None:
    """The label and the features must be the same quantity pointed in
    opposite directions in time. Two implementations of one definition drift,
    so this pins them against a shared fixture until a refactor unit owning
    both files can unify them.
    """
    from alphaledger.evidence.price_volume import FeatureConfig
    from alphaledger.evidence.price_volume import build as price_build

    bars = panel({8: "110.00", 9: "121.00"}, peer_closes={8: "50.00", 9: "50.00"})

    forward = build(SYMBOL, session_at(7), bars, config(horizon_sessions=1))
    assert forward is not None
    assert forward.entry_session == session_at(8)
    assert forward.exit_session == session_at(9)

    # The price family refuses a bar it could not have seen, so it is handed
    # only the sessions up to its own `as_of`. The label is handed the whole
    # panel, because a label is allowed to see the future and a feature is not.
    # That asymmetry is the point of the two modules and is why this comparison
    # is worth making at all.
    knowable = tuple(item for item in bars if item.session <= session_at(9))
    trailing = price_build(
        SYMBOL,
        session_at(9) + timedelta(hours=1),
        knowable,
        FeatureConfig(sector_by_symbol=SECTORS),
    )
    # Session 9 is the only session the label sums, and the price family
    # reports that same session's residual as its most recent one-day return.
    assert trailing.features["residual_return_1s"] == pytest.approx(forward.forward_residual_return)


def test_outcome_time_waits_for_the_peers_the_residual_was_measured_against() -> None:
    """AC-3, the half the symbol's own bars cannot prove. A residual is not
    knowable until the cross-section it is demeaned against has been observed,
    so a peer bar arriving late moves the outcome instant. Ignoring peers would
    let UNIT-024 admit the label into a window the purge should have excluded
    it from, which is a leak no test on the symbol's own timestamps can see."""
    late_peer = bar("PEER1", 3, "50.00", seen_offset_minutes=900)
    bars = [
        item for item in panel({}) if not (item.symbol == "PEER1" and item.session == session_at(3))
    ]
    bars.append(late_peer)
    block = build(SYMBOL, session_at(0), tuple(bars), config(horizon_sessions=2))
    assert block is not None
    assert block.outcome_time == late_peer.first_seen_time


def test_the_label_id_changes_when_the_definition_changes() -> None:
    """Two definitions must not share one address. Relabelling the same symbol
    and instant under a changed configuration produces a different label, and
    a reused identity would silently collide with the old one in the ledger
    while every join still looked healthy."""
    settings = config(horizon_sessions=2)
    other = config(horizon_sessions=2, implausible_return=0.9)
    assert settings.label_version != other.label_version
    first = build(SYMBOL, session_at(0), panel({}), settings)
    second = build(SYMBOL, session_at(0), panel({}), other)
    assert first is not None
    assert second is not None
    assert first.forward_residual_return == second.forward_residual_return
    assert first.label_id != second.label_id


def test_the_same_symbol_and_instant_under_one_definition_keep_one_id() -> None:
    """The other half: an id that varied run to run would break every join a
    frozen run depends on."""
    settings = config(horizon_sessions=2)
    first = build(SYMBOL, session_at(0), panel({}), settings)
    second = build(SYMBOL, session_at(0), panel({}), settings)
    assert first is not None
    assert second is not None
    assert first.label_id == second.label_id


# --- round two: the review findings ---------------------------------------
#
# Every test below transcribes a defect the round one `backtest-auditor` review
# demonstrated on constructed input, so each one fails on the code as it was
# reviewed. They are kept together because the two blocking findings share a
# cause worth naming: an acceptance criterion whose stated falsification could
# not distinguish the right behaviour from the wrong one, so the test written
# from it passed either way.


def gapped_peer_panel(
    *,
    missing: tuple[int, ...],
    predecessor_seen_offset_minutes: int,
) -> tuple[Bar, ...]:
    """A panel where PEER1 is missing sessions and its predecessor arrived late.

    The predecessor is the bar `_returns` silently reaches back to across the
    gap. It sits outside the holding window, which is exactly why a scan of the
    window cannot see it.
    """
    kept = [
        item
        for item in panel({})
        if not (item.symbol == "PEER1" and item.session in {session_at(i) for i in missing})
    ]
    revised = bar("PEER1", 4, "50.00", seen_offset_minutes=predecessor_seen_offset_minutes)
    without_predecessor = [
        item for item in kept if not (item.symbol == "PEER1" and item.session == session_at(4))
    ]
    return (*without_predecessor, revised)


def test_a_peer_bar_reached_through_a_gap_still_moves_the_outcome_time() -> None:
    """Finding 1, the temporal half. AC-3 says `outcome_time` is the latest
    `first_seen_time` among the bars the label consumed. A peer missing two
    in-window sessions makes `_returns` produce a multi-session return for the
    next session it does have, measured against a predecessor bar that sits
    outside the window entirely. That bar was consumed, so a revision to it
    must move the outcome instant, or UNIT-024 admits the label into a window
    the purge exists to keep it out of.
    """
    two_years = 60 * 24 * 730
    late = bar("PEER1", 4, "50.00", seen_offset_minutes=two_years)
    bars = gapped_peer_panel(missing=(5, 6), predecessor_seen_offset_minutes=two_years)

    block = build(SYMBOL, session_at(4), bars, config(horizon_sessions=2))

    assert block is not None
    assert block.entry_session == session_at(5)
    assert block.exit_session == session_at(7)
    # PEER1 has no bar on sessions 5 or 6, so its session 7 return is measured
    # against session 4, and nothing inside the window carries that instant.
    assert block.outcome_time == late.first_seen_time


def test_a_late_peer_predecessor_purges_the_label_from_the_fold_it_would_have_leaked_into() -> None:
    """AC-10's own stated falsification, which round one never implemented.

    This is the end-to-end shape of the finding above: the fold geometry is
    chosen so that the outcome instant a window scan produces still lands
    inside the training window, while the instant the consumed bars produce
    does not. A label carrying the first is trained on before its outcome was
    knowable.
    """
    two_years = 60 * 24 * 730
    bars = gapped_peer_panel(missing=(5, 6), predecessor_seen_offset_minutes=two_years)
    label = build(SYMBOL, session_at(4), bars, config(horizon_sessions=2))
    assert label is not None

    split = SplitConfig(
        horizon=timedelta(days=3),
        purge=timedelta(days=3),
        train=timedelta(days=9),
        calibration=timedelta(days=5),
        test=timedelta(days=5),
        folds=1,
    )
    result = walk_forward(
        FIRST,
        [label.as_labelled()],
        split,
        available_until=FIRST + timedelta(days=30),
    )

    fold = result.folds[0]
    assert fold.train.holds(label.prediction_time)
    assert label.label_id not in fold.train_labels
    assert [item.reason for item in fold.purged] == [OUTCOME_CROSSES_BOUNDARY]


def test_a_symbol_that_stops_trading_while_the_panel_continues_yields_no_label() -> None:
    """Finding 2. AC-4 makes an incomplete horizon a `None`, and names a symbol
    that stops trading as one of its two causes. A delisting on the decision
    session itself is still a delisting: the caller cannot precompute it from
    the panel's own bounds the way it could a uniform panel end, because every
    other symbol keeps trading for weeks.
    """
    bars = [bar(SYMBOL, index, "100.00") for index in range(6)]
    for peer in PEERS:
        bars.extend(bar(peer, index, "50.00") for index in range(20))

    assert build(SYMBOL, session_at(5), tuple(bars), config(horizon_sessions=2)) is None


def test_the_cross_section_is_a_median_and_not_a_mean() -> None:
    """AC-2 says median, and the two-peer fixture every other test uses cannot
    tell the difference: the median of two numbers is their mean. A third peer
    making one outsized move separates them, which is the whole reason the
    median was specified. Without this, swapping `statistics.median` for
    `statistics.mean` passes the entire suite.
    """
    third = "PEER3"
    sectors = {**SECTORS, third: "tech"}
    bars: list[Bar] = []
    for index in range(4):
        bars.append(bar(SYMBOL, index, "100.00"))
        bars.append(bar("PEER1", index, "50.00"))
        bars.append(bar("PEER2", index, "50.00"))
        # The outlier moves only on the single session the label sums.
        bars.append(bar(third, index, "65.00" if index == 2 else "50.00"))

    block = build(
        SYMBOL,
        session_at(0),
        tuple(bars),
        config(horizon_sessions=1, sector_by_symbol=sectors),
    )

    assert block is not None
    assert block.exit_session == session_at(2)
    # Peer returns on session 2 are 0.0, 0.0 and 0.3. The median is 0.0, so a
    # flat symbol has a flat residual. Their mean is 0.1, which would make it
    # -0.1 and quietly attribute a third peer's move to this symbol.
    assert block.forward_residual_return == pytest.approx(0.0)


def test_the_implausible_bound_is_exclusive_at_its_own_boundary() -> None:
    """A return landing exactly on `implausible_return` is not implausible. The
    bound is `>` and this pins it, because a silent drift to `>=` would flag a
    boundary label and nothing else in the suite distinguishes the two.
    """
    exact = panel({2: "150.00"})

    block = build(SYMBOL, session_at(0), exact, config(horizon_sessions=1, implausible_return=0.5))

    assert block is not None
    assert block.forward_residual_return == pytest.approx(0.5)
    assert IMPLAUSIBLE_MAGNITUDE not in block.quality_flags


def test_one_label_passed_twice_is_refused_rather_than_halving_its_own_weight() -> None:
    """A duplicate identity makes a label concurrent with itself, so it would
    silently weigh one half. That is the opposite of what uniqueness is for: it
    exists to stop a fit overcounting information, and here it would undercount
    a real observation while reporting a healthy-looking number.
    """
    only = build(SYMBOL, session_at(0), panel({}), config(horizon_sessions=2))
    assert only is not None

    with pytest.raises(DuplicateLabelError, match=only.label_id):
        with_uniqueness([only, only])
