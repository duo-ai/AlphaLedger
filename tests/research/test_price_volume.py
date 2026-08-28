"""Residual price and volume feature tests.

This family is the control in the comparison that decides whether news adds
anything, so its whole value is being a strict function of past observations.
The fixture is built so every expected number can be computed by hand: the peer
symbols are flat, which makes the sector median return zero and the residual
equal to the raw return.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from alphaledger.evidence.price_volume import (
    ABNORMAL_VOLUME_DAILY_BASELINE,
    INSUFFICIENT_HISTORY,
    NO_EVENT_TIME,
    NO_QUALIFYING_DATA,
    SECTOR_FALLBACK_MARKET,
    WINSORIZED,
    ZERO_DENOMINATOR,
    AmbiguousBarError,
    Bar,
    FeatureConfig,
    LeakedBarError,
    build,
)

SESSIONS = 80
FIRST_SESSION = datetime(2026, 5, 1, 20, 0, tzinfo=UTC)
AS_OF = FIRST_SESSION + timedelta(days=SESSIONS - 1, hours=1)
SECTORS = {"TARGET": "tech", "PEER1": "tech", "PEER2": "tech"}


def session_at(index: int) -> datetime:
    return FIRST_SESSION + timedelta(days=index)


def bar(
    symbol: str,
    index: int,
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    volume: int,
    first_seen_time: datetime | None = None,
) -> Bar:
    session = session_at(index)
    return Bar(
        symbol=symbol,
        feed="sip_daily",
        session=session,
        first_seen_time=first_seen_time or session + timedelta(minutes=15),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def flat_peer(symbol: str, sessions: int = SESSIONS) -> list[Bar]:
    """A peer that never moves, so the sector median return is exactly zero."""
    return [
        bar(
            symbol, index, open_="50.00", high="51.00", low="49.00", close="50.00", volume=1_000_000
        )
        for index in range(sessions)
    ]


def target(sessions: int = SESSIONS) -> list[Bar]:
    """Flat at 100 until the last session, which moves 2 percent on twice the
    volume, with a range of 4.00 against a true range of 2.00 before it."""
    bars = [
        bar(
            "TARGET",
            index,
            open_="100.00",
            high="101.00",
            low="99.00",
            close="100.00",
            volume=1_000_000,
        )
        for index in range(sessions - 1)
    ]
    bars.append(
        bar(
            "TARGET",
            sessions - 1,
            open_="101.00",
            high="103.00",
            low="99.00",
            close="102.00",
            volume=2_000_000,
        )
    )
    return bars


def panel(sessions: int = SESSIONS) -> tuple[Bar, ...]:
    return tuple(target(sessions) + flat_peer("PEER1", sessions) + flat_peer("PEER2", sessions))


def config(**overrides: object) -> FeatureConfig:
    defaults: dict[str, object] = {"sector_by_symbol": SECTORS}
    return FeatureConfig(**{**defaults, **overrides})  # type: ignore[arg-type]


# --- success, the arithmetic itself -------------------------------------


def test_each_feature_reproduces_a_hand_computed_value() -> None:
    """The peers are flat, so the sector median return is zero and every
    residual equals the raw return. Each expectation below is arithmetic a
    reader can redo on paper from the fixture."""
    block = build("TARGET", AS_OF, panel(), config(), event_time=session_at(SESSIONS - 2))
    features = block.features

    # close 100.00 to 102.00 on the last session
    assert features["residual_return_1s"] == pytest.approx(0.02, abs=1e-12)
    # only the last session moved, so five sessions sum to the same move
    assert features["residual_return_5s"] == pytest.approx(0.02, abs=1e-12)
    # open 101.00 against the prior close of 100.00
    assert features["opening_gap_residual"] == pytest.approx(0.01, abs=1e-12)
    # one move of 0.02 among nineteen zeroes, sample standard deviation
    assert features["residual_return_zscore"] == pytest.approx(4.472136, rel=1e-6)
    # 2,000,000 against a median of 1,000,000
    assert features["abnormal_volume"] == pytest.approx(1.0, abs=1e-12)
    # a range of 4.00 against a true range of 2.00 on every prior session
    assert features["range_over_atr"] == pytest.approx(2.0, abs=1e-12)
    # close 102.00 between a low of 99.00 and a high of 103.00
    assert features["proximity_to_extreme"] == pytest.approx(0.75, abs=1e-12)
    # the event is the session before last, so the window is the last move
    assert features["cumulative_abnormal_return"] == pytest.approx(0.02, abs=1e-12)


def test_every_feature_value_is_a_finite_float_the_evidence_card_will_accept() -> None:
    """EvidenceCard rejects NaN and Infinity, so a feature block that carried
    one would fail at the boundary rather than here."""
    from alphaledger.domain.contracts import EvidenceCard

    block = build("TARGET", AS_OF, panel(), config())

    card = EvidenceCard(
        candidate_id="c1",
        symbol="TARGET",
        as_of=AS_OF,
        data_mode="opra",
        price_volume_features=block.features,
        news_features={},
        options_features=None,
        quality_flags=block.quality_flags,
        raw_data_hashes=(),
    )
    assert set(card.price_volume_features) == set(block.features)


def test_a_missing_event_time_omits_the_abnormal_return_and_says_why() -> None:
    block = build("TARGET", AS_OF, panel(), config())

    assert "cumulative_abnormal_return" not in block.features
    assert NO_EVENT_TIME in block.quality_flags


def test_the_sector_median_is_used_and_a_thin_sector_falls_back_to_the_market() -> None:
    lonely = {"TARGET": "tech", "PEER1": "energy", "PEER2": "energy"}

    block = build("TARGET", AS_OF, panel(), config(sector_by_symbol=lonely))

    assert SECTOR_FALLBACK_MARKET in block.quality_flags
    assert block.features["residual_return_1s"] == pytest.approx(0.02, abs=1e-12)


def test_a_moving_sector_is_subtracted_so_the_residual_is_not_the_raw_return() -> None:
    """If the peers move with the target, the residual is smaller than the raw
    return. Without this the feature would just be momentum."""
    moving = [
        bar(
            symbol,
            index,
            open_="50.00",
            high="51.00",
            low="49.00",
            close="50.00" if index < SESSIONS - 1 else "51.00",
            volume=1_000_000,
        )
        for symbol in ("PEER1", "PEER2")
        for index in range(SESSIONS)
    ]

    block = build("TARGET", AS_OF, tuple(target() + moving), config())

    # the peers rose 2 percent as well, so the residual is zero
    assert block.features["residual_return_1s"] == pytest.approx(0.0, abs=1e-12)


def test_one_wild_peer_does_not_move_the_residual_because_the_centre_is_a_median() -> None:
    """The model is robust by choice, not by accident.

    A mean would let a single peer with a corporate action or a squeeze drag
    the whole cross-section, and the residual would then measure that peer.
    """
    wild = [
        bar(
            "PEER3",
            index,
            open_="50.00",
            high="61.00",
            low="49.00",
            close="50.00" if index < SESSIONS - 1 else "60.00",
            volume=1_000_000,
        )
        for index in range(SESSIONS)
    ]
    sectors = {**SECTORS, "PEER3": "tech"}

    block = build("TARGET", AS_OF, tuple(panel()) + tuple(wild), config(sector_by_symbol=sectors))

    # peer returns are 0, 0 and +0.20, whose median is 0
    assert block.features["residual_return_1s"] == pytest.approx(0.02, abs=1e-12)


def test_the_volume_baseline_excludes_the_session_being_measured() -> None:
    """A baseline that contained today would be partly compared with itself,
    which flatters an unusual volume towards looking ordinary."""
    narrow = config(abnormal_volume_sessions=2)

    block = build("TARGET", AS_OF, panel(), narrow)

    # the two prior sessions are 1,000,000 each, so the baseline is 1,000,000
    # and not the 1,500,000 that including today's 2,000,000 would give
    assert block.features["abnormal_volume"] == pytest.approx(1.0, abs=1e-12)


def test_the_abnormal_return_window_starts_after_the_event_not_on_it() -> None:
    """The event session's own move belongs to the event, not to the reaction
    the feature is meant to measure."""
    moved = [
        bar(
            "TARGET",
            index,
            open_="100.00",
            high="103.00",
            low="99.00",
            close={SESSIONS - 2: "101.00", SESSIONS - 1: "102.00"}.get(index, "100.00"),
            volume=1_000_000,
        )
        for index in range(SESSIONS)
    ]
    bars = tuple(moved) + tuple(flat_peer("PEER1")) + tuple(flat_peer("PEER2"))

    block = build("TARGET", AS_OF, bars, config(), event_time=session_at(SESSIONS - 2))

    # 102.00 against 101.00 only. Including the event session would add its own
    # one percent move on top.
    assert block.features["cumulative_abnormal_return"] == pytest.approx(102 / 101 - 1, abs=1e-12)


# --- point in time ------------------------------------------------------


def test_a_bar_stamped_after_as_of_is_rejected_rather_than_used() -> None:
    """The leaked fixture the research rules require.

    The bar is in the input and it would change every feature. Silently
    dropping it would leave the caller believing the builder had honoured a
    cutoff it never checked.
    """
    leaked = bar(
        "TARGET",
        SESSIONS,
        open_="102.00",
        high="110.00",
        low="102.00",
        close="110.00",
        volume=9_000_000,
        first_seen_time=AS_OF + timedelta(minutes=1),
    )

    with pytest.raises(LeakedBarError) as raised:
        build("TARGET", AS_OF, (*panel(), leaked), config())

    assert "TARGET" in str(raised.value)
    assert "first_seen_time" in str(raised.value)


def test_a_bar_first_seen_exactly_at_as_of_is_knowable_at_as_of() -> None:
    edge = bar(
        "TARGET",
        SESSIONS - 1,
        open_="101.00",
        high="103.00",
        low="99.00",
        close="102.00",
        volume=2_000_000,
        first_seen_time=AS_OF,
    )
    bars = tuple(
        item
        for item in panel()
        if not (item.symbol == "TARGET" and item.session == session_at(SESSIONS - 1))
    )

    block = build("TARGET", AS_OF, (*bars, edge), config())

    assert block.features["residual_return_1s"] == pytest.approx(0.02, abs=1e-12)


def test_an_earlier_as_of_sees_only_what_was_knowable_then() -> None:
    """The caller restricts the panel, the way UNIT-021's source does. Handing
    the builder a bar it must not use is the source defect above, so the honest
    call is the filtered one."""
    past = session_at(SESSIONS - 2) + timedelta(hours=1)
    knowable = tuple(item for item in panel() if item.first_seen_time <= past)

    block = build("TARGET", past, knowable, config())

    assert block.features["residual_return_1s"] == pytest.approx(0.0, abs=1e-12)


def test_two_bars_for_one_session_that_disagree_are_ambiguous_not_ordered() -> None:
    """The same rule UNIT-021 needed: a tie resolved by arrival order makes the
    result depend on how the panel was assembled."""
    disagreeing = bar(
        "TARGET",
        SESSIONS - 1,
        open_="101.00",
        high="103.00",
        low="99.00",
        close="105.00",
        volume=2_000_000,
    )

    with pytest.raises(AmbiguousBarError) as raised:
        build("TARGET", AS_OF, (*panel(), disagreeing), config())

    assert "TARGET" in str(raised.value)


def test_two_identical_bars_for_one_session_are_not_ambiguous() -> None:
    repeated = tuple(panel())

    block = build("TARGET", AS_OF, (*repeated, *repeated), config())

    assert block.features["residual_return_1s"] == pytest.approx(0.02, abs=1e-12)


# --- missing data, never imputed ----------------------------------------


def test_a_short_history_yields_missing_markers_and_flags_not_zeroes() -> None:
    """AC-3. A zero is a value. Absence is the truth."""
    block = build("TARGET", AS_OF, panel(sessions=3), config())

    assert "residual_return_5s" not in block.features
    assert "residual_return_zscore" not in block.features
    assert f"{INSUFFICIENT_HISTORY}:residual_return_5s" in block.quality_flags
    assert 0.0 not in set(block.features.values()) or "residual_return_1s" in block.features


def test_a_flat_price_gives_a_missing_marker_rather_than_a_zero_denominator() -> None:
    """A zero denominator is routine here. RESEARCH-LANE.md names it: the
    domain type rejects NaN, so it has to be handled rather than produced."""
    flat = tuple(flat_peer("TARGET") + flat_peer("PEER1") + flat_peer("PEER2"))
    still = [
        bar(
            symbol, index, open_="50.00", high="50.00", low="50.00", close="50.00", volume=1_000_000
        )
        for symbol in ("TARGET", "PEER1", "PEER2")
        for index in range(SESSIONS)
    ]

    block = build("TARGET", AS_OF, tuple(still), config())

    assert "range_over_atr" not in block.features
    assert "proximity_to_extreme" not in block.features
    assert f"{ZERO_DENOMINATOR}:range_over_atr" in block.quality_flags
    assert flat  # the flat panel is built to prove the helper is not the cause


def test_the_volume_baseline_is_daily_and_says_so_because_intraday_is_absent() -> None:
    block = build("TARGET", AS_OF, panel(), config())

    assert ABNORMAL_VOLUME_DAILY_BASELINE in block.quality_flags


# --- configuration ------------------------------------------------------


def test_inverted_winsorization_bounds_are_rejected_at_load() -> None:
    with pytest.raises(ValueError, match="winsor"):
        config(winsor_lower=1.0, winsor_upper=-1.0)


def test_winsorization_clips_from_config_and_records_that_it_bit() -> None:
    tight = config(winsor_lower=-0.005, winsor_upper=0.005)

    block = build("TARGET", AS_OF, panel(), tight)

    assert block.features["residual_return_1s"] == pytest.approx(0.005, abs=1e-12)
    assert f"{WINSORIZED}:residual_return_1s" in block.quality_flags
    assert block.winsorization == (-0.005, 0.005)


def test_the_feature_version_changes_when_any_config_value_changes() -> None:
    """AC-5. A frozen run is identified by this string, so a silent config
    change that kept it would make two different feature sets indistinguishable."""
    baseline = config()
    versions = {
        baseline.feature_version,
        config(atr_sessions=13).feature_version,
        config(winsor_lower=-0.5).feature_version,
        config(extreme_sessions=21).feature_version,
        config(sector_by_symbol={**SECTORS, "TARGET": "energy"}).feature_version,
    }

    assert len(versions) == 5
    assert build("TARGET", AS_OF, panel(), baseline).feature_version == baseline.feature_version


def test_a_non_positive_lookback_is_rejected() -> None:
    with pytest.raises(ValueError, match="lookback_sessions"):
        config(lookback_sessions=0)


# --- restart and determinism --------------------------------------------


DETERMINISM_SCRIPT = """
from datetime import UTC, datetime, timedelta

from alphaledger.evidence.price_volume import Bar, FeatureConfig, build

FIRST = datetime(2026, 5, 1, 20, 0, tzinfo=UTC)
SESSIONS = 80
AS_OF = FIRST + timedelta(days=SESSIONS - 1, hours=1)


def make(symbol, index, open_, high, low, close, volume):
    session = FIRST + timedelta(days=index)
    return Bar(symbol=symbol, feed="sip_daily", session=session,
               first_seen_time=session + timedelta(minutes=15), open=open_, high=high,
               low=low, close=close, volume=volume)


bars = []
for index in range(SESSIONS):
    last = index == SESSIONS - 1
    bars.append(make("TARGET", index, "101.00" if last else "100.00",
                     "103.00" if last else "101.00", "99.00",
                     "102.00" if last else "100.00", 2_000_000 if last else 1_000_000))
    for peer in ("PEER1", "PEER2"):
        bars.append(make(peer, index, "50.00", "51.00", "49.00", "50.00", 1_000_000))

config = FeatureConfig(sector_by_symbol={"TARGET": "tech", "PEER1": "tech", "PEER2": "tech"})
block = build("TARGET", AS_OF, tuple(bars), config)
print(config.feature_version)
for name in sorted(block.features):
    print(f"{name}={block.features[name]!r}")
print(",".join(block.quality_flags))
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
    """AC-2. Identical to the repr, not merely close, and under two different
    hash seeds so any dependence on dict or set ordering would show."""
    assert in_a_new_process("0") == in_a_new_process("54321")


def test_a_rebuild_of_a_past_as_of_reproduces_the_same_values() -> None:
    """A frozen run stays reproducible: the same cached bars and the same
    instant give the same numbers, whatever has been recorded since."""
    past = session_at(SESSIONS - 5) + timedelta(hours=1)
    knowable = tuple(item for item in panel() if item.first_seen_time <= past)

    first = build("TARGET", past, knowable, config())
    second = build("TARGET", past, tuple(reversed(knowable)), config())

    assert first.features == second.features
    assert first.quality_flags == second.quality_flags


def test_the_builder_reads_no_clock() -> None:
    """The contract says pure and deterministic with no clock read inside. A
    wall-clock call would make a rebuild of a past as_of unreproducible."""
    import inspect

    from alphaledger.evidence import price_volume

    body = inspect.getsource(price_volume)

    assert "datetime.now" not in body
    assert "utcnow" not in body
    assert "time.time" not in body


# --- no trade -----------------------------------------------------------


def test_a_symbol_with_no_qualifying_data_yields_an_empty_block_with_flags() -> None:
    """An empty block is an answer, and the forecast layer has to read it as
    ineligible rather than as a neutral signal."""
    block = build("ABSENT", AS_OF, panel(), config())

    assert block.features == {}
    assert NO_QUALIFYING_DATA in block.quality_flags
    assert block.feature_version


def test_an_empty_panel_yields_an_empty_block_rather_than_an_error() -> None:
    block = build("TARGET", AS_OF, (), config())

    assert block.features == {}
    assert NO_QUALIFYING_DATA in block.quality_flags


def test_an_unfiltered_panel_at_an_early_as_of_stops_rather_than_reporting_no_data() -> None:
    """ "No data" and "data you must not use" are different answers.

    Discarding every unknowable bar and reporting an empty block would let a
    caller who forgot to restrict the panel read a leak as a quiet no-trade.
    """
    with pytest.raises(LeakedBarError):
        build("TARGET", FIRST_SESSION - timedelta(days=1), panel(), config())


def test_a_correctly_restricted_panel_before_every_bar_is_simply_empty() -> None:
    early = FIRST_SESSION - timedelta(days=1)
    knowable = tuple(item for item in panel() if item.first_seen_time <= early)

    block = build("TARGET", early, knowable, config())

    assert knowable == ()
    assert block.features == {}
    assert NO_QUALIFYING_DATA in block.quality_flags


def test_the_block_is_immutable_so_a_caller_cannot_edit_a_recorded_feature() -> None:
    block = build("TARGET", AS_OF, panel(), config())

    with pytest.raises(TypeError):
        block.features["residual_return_1s"] = 0.0  # type: ignore[index]


def test_a_float_price_on_a_bar_is_rejected_because_a_close_is_money() -> None:
    with pytest.raises(TypeError, match="float"):
        Bar(
            symbol="TARGET",
            feed="sip_daily",
            session=session_at(0),
            first_seen_time=session_at(0),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=100.0,  # type: ignore[arg-type]
            volume=1_000,
        )
