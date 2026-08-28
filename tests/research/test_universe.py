"""Frozen universe tests.

Membership has to be decided before the session it applies to. Every test here
is a way of asking whether a symbol could have been chosen with the information
available at `as_of`, or whether it was chosen because of what happened next.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from alphaledger.data.universe import (
    BELOW_DOLLAR_VOLUME_FLOOR,
    BELOW_PRICE_FLOOR,
    NO_QUOTED_EXPIRATION,
    OPTIONS_NOT_ENABLED,
    OUTSIDE_CAP,
    STATIC_FALLBACK_SYMBOLS,
    UNRESOLVED_CORPORATE_ACTION,
    LeakedObservationError,
    ObservationSource,
    SymbolObservation,
    UniverseFloors,
    build,
    static_fallback_hash,
)

PRIOR_CLOSE = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)


def moment(**offset: float) -> datetime:
    return PRIOR_CLOSE + timedelta(**offset)


def observed(
    symbol: str,
    *,
    first_seen_time: datetime | None = None,
    active: bool = True,
    tradable: bool = True,
    options_enabled: bool = True,
    prior_close: str = "100.00",
    median_dollar_volume: str = "50000000",
    near_money_quotes_7_to_21_dte: bool = True,
    unresolved_corporate_action: bool = False,
) -> SymbolObservation:
    return SymbolObservation(
        symbol=symbol,
        first_seen_time=first_seen_time or moment(hours=-1),
        active=active,
        tradable=tradable,
        options_enabled=options_enabled,
        prior_close=prior_close,
        median_dollar_volume=median_dollar_volume,
        near_money_quotes_7_to_21_dte=near_money_quotes_7_to_21_dte,
        unresolved_corporate_action=unresolved_corporate_action,
    )


def source(*observations: SymbolObservation, optionability: bool = True) -> ObservationSource:
    return ObservationSource(
        observations=observations, optionability_is_reconstructable=optionability
    )


def reason_for(universe: object, symbol: str) -> str:
    exclusions = {item.symbol: item.reason for item in universe.exclusions}  # type: ignore[attr-defined]
    return exclusions[symbol]


# --- success ------------------------------------------------------------


def test_a_fixture_produces_the_expected_set_and_the_same_hash_when_rebuilt() -> None:
    feed = source(
        observed("AAPL", median_dollar_volume="90000000"),
        observed("MSFT", median_dollar_volume="80000000"),
        observed("PENNY", prior_close="4.00"),
    )

    first = build(PRIOR_CLOSE, feed)
    second = build(PRIOR_CLOSE, feed)

    assert first.symbols == ("AAPL", "MSFT")
    assert first.universe_hash == second.universe_hash
    assert reason_for(first, "PENNY") == BELOW_PRICE_FLOOR


def test_the_cap_keeps_the_highest_median_dollar_volume_and_drops_the_rest() -> None:
    feed = source(
        *(
            observed(f"SYM{index:03d}", median_dollar_volume=str(1_000_000 * index))
            for index in range(1, 41)
        )
    )

    # A zero volume floor so the cap is the only thing that can cut a symbol.
    universe = build(PRIOR_CLOSE, feed, floors=UniverseFloors(min_median_dollar_volume=Decimal(0)))

    assert len(universe.symbols) == 30
    assert universe.symbols[0] == "SYM040"
    assert universe.symbols[-1] == "SYM011"
    assert "SYM010" not in universe.symbols
    assert reason_for(universe, "SYM010") == OUTSIDE_CAP


def test_a_tie_on_dollar_volume_is_broken_by_symbol_so_the_set_is_reproducible() -> None:
    feed = source(
        *(observed(symbol, median_dollar_volume="50000000") for symbol in ("ZZZZ", "AAAA", "MMMM"))
    )

    universe = build(PRIOR_CLOSE, feed, floors=UniverseFloors(max_symbols=2))

    assert universe.symbols == ("AAAA", "MMMM")


def test_the_set_order_does_not_depend_on_the_order_the_source_returned_rows() -> None:
    """Two determinism mechanisms guard this, and each masks the other alone.

    Symbols are collected in sorted order, and ranking breaks a volume tie by
    symbol. Removing either one leaves this passing, which is why the assertion
    is written against the pair: a frozen run has to be reproducible whatever
    order the rows arrived in.
    """
    reversed_arrival = source(
        *(observed(symbol, median_dollar_volume="50000000") for symbol in ("ZZZZ", "MMMM", "AAAA"))
    )
    alphabetical_arrival = source(
        *(observed(symbol, median_dollar_volume="50000000") for symbol in ("AAAA", "MMMM", "ZZZZ"))
    )

    first = build(PRIOR_CLOSE, reversed_arrival)
    second = build(PRIOR_CLOSE, alphabetical_arrival)

    assert first.symbols == ("AAAA", "MMMM", "ZZZZ")
    assert first.universe_hash == second.universe_hash


def test_a_symbol_delisted_after_as_of_is_still_a_member_at_as_of() -> None:
    """AC-3. Survivorship is not applied backwards: the set is what was
    investable then, not what still exists now."""
    feed = source(
        observed("GONE", first_seen_time=moment(hours=-2)),
        observed("GONE", first_seen_time=moment(days=3), active=False, tradable=False),
        observed("STAY"),
    )

    universe = build(PRIOR_CLOSE, feed)

    assert universe.symbols == ("GONE", "STAY")


def test_the_latest_observation_at_or_before_as_of_is_the_one_that_counts() -> None:
    feed = source(
        observed("FLIP", first_seen_time=moment(days=-5), prior_close="4.00"),
        observed("FLIP", first_seen_time=moment(hours=-2), prior_close="40.00"),
    )

    assert build(PRIOR_CLOSE, feed).symbols == ("FLIP",)


def test_the_floors_applied_are_recorded_next_to_the_set() -> None:
    floors = UniverseFloors(
        min_prior_close=Decimal("25"), min_median_dollar_volume=Decimal("1000000"), max_symbols=5
    )

    universe = build(PRIOR_CLOSE, source(observed("AAPL")), floors=floors)

    assert universe.floors == floors
    assert universe.as_of == PRIOR_CLOSE


# --- point in time failures ---------------------------------------------


def test_a_symbol_whose_liquidity_only_appears_after_as_of_is_excluded() -> None:
    """The leaked fixture the research rules require.

    The history contains the row that would have qualified this symbol. It is
    stamped after `as_of`, so a build at `as_of` must not be able to see it,
    and the symbol must fall out on the evidence that existed at the time.
    """
    feed = source(
        observed("LATE", first_seen_time=moment(hours=-1), median_dollar_volume="1000"),
        observed("LATE", first_seen_time=moment(days=2), median_dollar_volume="99000000"),
        observed("REAL"),
    )

    universe = build(PRIOR_CLOSE, feed)

    assert universe.symbols == ("REAL",)
    assert reason_for(universe, "LATE") == BELOW_DOLLAR_VOLUME_FLOOR


def test_a_symbol_first_optionable_after_as_of_is_absent_from_the_set_at_as_of() -> None:
    feed = source(
        observed("SOON", first_seen_time=moment(hours=-1), options_enabled=False),
        observed("SOON", first_seen_time=moment(days=1), options_enabled=True),
    )

    universe = build(PRIOR_CLOSE, feed)

    assert universe.symbols == ()
    assert reason_for(universe, "SOON") == OPTIONS_NOT_ENABLED


def test_a_source_that_returns_an_observation_stamped_after_as_of_is_rejected() -> None:
    """Rejected, not filtered. A source that hands over a future row is broken,
    and silently dropping it would hide the break from every later audit."""

    class LeakingSource:
        optionability_is_reconstructable = True

        def observations_as_of(self, as_of: datetime) -> Iterable[SymbolObservation]:
            return (
                observed("HONEST"),
                observed("LEAK", first_seen_time=as_of + timedelta(seconds=1)),
            )

    with pytest.raises(LeakedObservationError) as raised:
        build(PRIOR_CLOSE, LeakingSource())

    assert "LEAK" in str(raised.value)
    assert "first_seen_time" in str(raised.value)


def test_an_unresolved_corporate_action_excludes_the_symbol_and_records_the_reason() -> None:
    universe = build(
        PRIOR_CLOSE, source(observed("SPLIT", unresolved_corporate_action=True), observed("CLEAN"))
    )

    assert universe.symbols == ("CLEAN",)
    assert reason_for(universe, "SPLIT") == UNRESOLVED_CORPORATE_ACTION


def test_a_symbol_without_a_quoted_near_money_expiration_is_excluded() -> None:
    universe = build(
        PRIOR_CLOSE, source(observed("THIN", near_money_quotes_7_to_21_dte=False), observed("DEEP"))
    )

    assert universe.symbols == ("DEEP",)
    assert reason_for(universe, "THIN") == NO_QUOTED_EXPIRATION


def test_a_naive_as_of_is_rejected() -> None:
    with pytest.raises(ValueError, match="as_of"):
        build(datetime(2026, 8, 27, 20, 0), source(observed("AAPL")))


def test_a_float_price_is_rejected_because_a_close_is_money() -> None:
    with pytest.raises(TypeError, match="float"):
        SymbolObservation(
            symbol="AAPL",
            first_seen_time=moment(hours=-1),
            active=True,
            tradable=True,
            options_enabled=True,
            prior_close=100.0,  # type: ignore[arg-type]
            median_dollar_volume="50000000",
            near_money_quotes_7_to_21_dte=True,
            unresolved_corporate_action=False,
        )


# --- static fallback ----------------------------------------------------


def test_the_static_fallback_stands_in_for_optionability_and_says_so() -> None:
    """AC-6. Using the list is allowed. Using it silently is not."""
    inside = STATIC_FALLBACK_SYMBOLS[0]
    feed = source(
        observed(inside, options_enabled=False, near_money_quotes_7_to_21_dte=False),
        observed("NOTLISTED", options_enabled=False, near_money_quotes_7_to_21_dte=False),
        optionability=False,
    )

    universe = build(PRIOR_CLOSE, feed)

    assert universe.symbols == (inside,)
    assert universe.used_static_fallback is True
    assert universe.fallback_list_hash == static_fallback_hash()
    assert reason_for(universe, "NOTLISTED") == OPTIONS_NOT_ENABLED


def test_the_fallback_does_not_rescue_a_symbol_that_fails_a_price_or_volume_floor() -> None:
    inside = STATIC_FALLBACK_SYMBOLS[0]
    feed = source(observed(inside, prior_close="2.00", options_enabled=False), optionability=False)

    universe = build(PRIOR_CLOSE, feed)

    assert universe.symbols == ()
    assert reason_for(universe, inside) == BELOW_PRICE_FLOOR


def test_a_build_with_reconstructable_optionability_never_sets_the_fallback_flag() -> None:
    universe = build(PRIOR_CLOSE, source(observed("AAPL")))

    assert universe.used_static_fallback is False
    assert universe.fallback_list_hash is None


def test_the_fallback_flag_changes_the_hash_so_the_two_runs_are_never_confused() -> None:
    inside = STATIC_FALLBACK_SYMBOLS[0]
    reconstructable = build(PRIOR_CLOSE, source(observed(inside)))
    fallback = build(PRIOR_CLOSE, source(observed(inside), optionability=False))

    assert reconstructable.symbols == fallback.symbols
    assert reconstructable.universe_hash != fallback.universe_hash


# --- restart ------------------------------------------------------------


REBUILD_SCRIPT = """
from datetime import UTC, datetime

from alphaledger.data.universe import ObservationSource, SymbolObservation, build

as_of = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)
seen = datetime(2026, 8, 27, 19, 0, tzinfo=UTC)
rows = tuple(
    SymbolObservation(
        symbol=symbol,
        first_seen_time=seen,
        active=True,
        tradable=True,
        options_enabled=True,
        prior_close="100.00",
        median_dollar_volume=volume,
        near_money_quotes_7_to_21_dte=True,
        unresolved_corporate_action=False,
    )
    for symbol, volume in (
        ("AAPL", "90000000"), ("MSFT", "90000000"), ("NVDA", "80000000"), ("TSLA", "70000000")
    )
)
universe = build(as_of, ObservationSource(observations=rows, optionability_is_reconstructable=True))
print(universe.universe_hash)
print(",".join(universe.symbols))
"""


def rebuild_in_a_new_process(hash_seed: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", REBUILD_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": hash_seed, "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_rebuild_in_another_process_reproduces_the_set_and_the_hash_exactly() -> None:
    """A frozen run has to be verifiable afterwards, in a process that shares
    nothing with the one that built it. Two different PYTHONHASHSEED values
    would expose any dependence on set or dict iteration order."""
    first = rebuild_in_a_new_process("0")
    second = rebuild_in_a_new_process("12345")

    assert first == second
    assert "AAPL,MSFT,NVDA,TSLA" in first


# --- no trade -----------------------------------------------------------


def test_a_date_on_which_nothing_clears_the_floors_returns_an_empty_universe() -> None:
    """An empty universe is an answer. It is not an error, and it is never a
    retry with the floors relaxed."""
    floors = UniverseFloors(min_prior_close=Decimal("500"))

    universe = build(PRIOR_CLOSE, source(observed("AAPL"), observed("MSFT")), floors=floors)

    assert universe.symbols == ()
    assert universe.floors == floors
    assert universe.universe_hash
    assert {item.reason for item in universe.exclusions} == {BELOW_PRICE_FLOOR}


def test_an_empty_source_returns_an_empty_universe_rather_than_an_error() -> None:
    universe = build(PRIOR_CLOSE, source())

    assert universe.symbols == ()
    assert universe.exclusions == ()


def test_an_empty_universe_still_differs_by_as_of_so_two_dates_are_not_one_run() -> None:
    floors = UniverseFloors(min_prior_close=Decimal("500"))
    feed = source(observed("AAPL"))

    first = build(PRIOR_CLOSE, feed, floors=floors)
    second = build(PRIOR_CLOSE + timedelta(days=1), feed, floors=floors)

    assert first.symbols == second.symbols == ()
    assert first.universe_hash != second.universe_hash


# --- no injection -------------------------------------------------------


def test_the_module_exposes_no_way_to_add_a_symbol_to_a_built_universe() -> None:
    """Design section 4: a user cannot inject a symbol into the candidate set."""
    universe = build(PRIOR_CLOSE, source(observed("AAPL")))

    with pytest.raises((AttributeError, TypeError)):
        universe.symbols = ("AAPL", "INJECT")  # type: ignore[misc]
    assert not [name for name in dir(universe) if name.startswith(("add", "insert", "append"))]
