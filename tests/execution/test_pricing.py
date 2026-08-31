from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import pytest

from alphaledger.config import load
from alphaledger.domain import StructurePlan
from alphaledger.execution.ladder import LadderBudget, step_ladder
from alphaledger.risk.approval import AccountSnapshot, SizingMode
from alphaledger.structure.chains import ChainContract, OptionType

_CONFIG_DIRECTORY = Path(__file__).parents[2] / "config"
_AS_OF = datetime(2026, 8, 31, 15, 0, tzinfo=UTC)
_QUOTE_TIME = _AS_OF - timedelta(seconds=30)
_EXPIRY = date(2026, 9, 11)
_LONG_SYMBOL = "SPY260911C00100000"
_SHORT_SYMBOL = "SPY260911C00105000"
_MAX_QUOTE_AGE = timedelta(minutes=2)


def _pricing_api() -> ModuleType:
    try:
        return importlib.import_module("alphaledger.structure.pricing")
    except ModuleNotFoundError as exc:
        if exc.name != "alphaledger.structure.pricing":
            raise
        pytest.fail("alphaledger.structure.pricing must implement the rung price contract")


def _plan(*, entry_limit_bound: Decimal = Decimal("1.8000")) -> StructurePlan:
    return StructurePlan(
        plan_id="plan-pricing-019",
        candidate_id="candidate-spy-pricing-019",
        legs=(
            {
                "symbol": _LONG_SYMBOL,
                "ratio_qty": 1,
                "side": "buy",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": _SHORT_SYMBOL,
                "ratio_qty": 1,
                "side": "sell",
                "position_intent": "sell_to_open",
            },
        ),
        quantity=1,
        entry_limit_bound=entry_limit_bound,
        exact_max_loss=Decimal("180.0000"),
        exact_max_profit=Decimal("320.0000"),
        expiry_breakeven=Decimal("101.8000"),
        quote_times=(_QUOTE_TIME, _QUOTE_TIME),
        stress_pnl={
            "max_loss_scenario": Decimal("-180.0000"),
            "max_profit_scenario": Decimal("320.0000"),
        },
    )


def _contract(symbol: str, **overrides: object) -> ChainContract:
    values: dict[str, object] = {
        "symbol": symbol,
        "underlying_symbol": "SPY",
        "option_type": OptionType.CALL,
        "strike": Decimal("100") if symbol == _LONG_SYMBOL else Decimal("105"),
        "expiry": _EXPIRY,
        "bid": Decimal("2.9000") if symbol == _LONG_SYMBOL else Decimal("1.2000"),
        "ask": Decimal("3.0000") if symbol == _LONG_SYMBOL else Decimal("1.3000"),
        "bid_size": 10,
        "ask_size": 10,
        "multiplier": 100,
        "delta": Decimal("0.52") if symbol == _LONG_SYMBOL else Decimal("0.30"),
        "quote_time": _QUOTE_TIME,
        "feed": "opra",
    }
    values.update(overrides)
    return ChainContract(**values)  # type: ignore[arg-type]


def _quotes(**overrides: ChainContract) -> dict[str, ChainContract]:
    quotes = {
        _LONG_SYMBOL: _contract(_LONG_SYMBOL),
        _SHORT_SYMBOL: _contract(_SHORT_SYMBOL),
    }
    quotes.update(overrides)
    return quotes


def _price_projection() -> str:
    api = _pricing_api()
    prices = api.rung_prices(_plan(), _quotes(), 4, _MAX_QUOTE_AGE, _AS_OF)
    return json.dumps([str(price) for price in prices], separators=(",", ":"))


def test_debit_vertical_has_hand_computed_midpoint_natural_and_rounded_rungs() -> None:
    api = _pricing_api()

    prices = api.rung_prices(_plan(), _quotes(), 4, _MAX_QUOTE_AGE, _AS_OF)

    assert prices == (
        Decimal("1.7000"),
        Decimal("1.7334"),
        Decimal("1.7667"),
        Decimal("1.8000"),
    )
    assert all(left < right for left, right in pairwise(prices))


def test_single_rung_returns_executable_midpoint_alone() -> None:
    api = _pricing_api()

    prices = api.rung_prices(_plan(), _quotes(), 1, _MAX_QUOTE_AGE, _AS_OF)

    assert prices == (Decimal("1.7000"),)


def test_crossed_market_raises_and_names_the_leg() -> None:
    api = _pricing_api()
    quotes = _quotes(**{_LONG_SYMBOL: _contract(_LONG_SYMBOL, bid=Decimal("3.1000"))})

    with pytest.raises(api.UnpricableStructureError, match=rf"{_LONG_SYMBOL}.*crossed"):
        api.rung_prices(_plan(), quotes, 4, _MAX_QUOTE_AGE, _AS_OF)


def test_zero_displayed_size_raises_and_names_the_leg() -> None:
    api = _pricing_api()
    quotes = _quotes(**{_SHORT_SYMBOL: _contract(_SHORT_SYMBOL, ask_size=0)})

    with pytest.raises(api.UnpricableStructureError, match=rf"{_SHORT_SYMBOL}.*size"):
        api.rung_prices(_plan(), quotes, 4, _MAX_QUOTE_AGE, _AS_OF)


def test_stale_quote_raises_and_names_quote_and_evaluation_instants() -> None:
    api = _pricing_api()
    stale_time = _AS_OF - timedelta(minutes=3)
    quotes = _quotes(**{_LONG_SYMBOL: _contract(_LONG_SYMBOL, quote_time=stale_time)})

    with pytest.raises(api.UnpricableStructureError) as exc_info:
        api.rung_prices(_plan(), quotes, 4, _MAX_QUOTE_AGE, _AS_OF)

    message = str(exc_info.value)
    assert _LONG_SYMBOL in message
    assert stale_time.isoformat() in message
    assert _AS_OF.isoformat() in message


def test_missing_leg_raises_instead_of_pricing_the_remainder() -> None:
    api = _pricing_api()
    quotes = {_LONG_SYMBOL: _contract(_LONG_SYMBOL)}

    with pytest.raises(api.UnpricableStructureError, match=rf"{_SHORT_SYMBOL}.*missing"):
        api.rung_prices(_plan(), quotes, 4, _MAX_QUOTE_AGE, _AS_OF)


def test_midpoint_above_entry_limit_bound_raises_instead_of_clamping() -> None:
    api = _pricing_api()

    with pytest.raises(api.UnpricableStructureError, match=r"midpoint.*entry_limit_bound"):
        api.rung_prices(
            _plan(entry_limit_bound=Decimal("1.6999")),
            _quotes(),
            4,
            _MAX_QUOTE_AGE,
            _AS_OF,
        )


def test_separate_processes_reproduce_prices_under_two_hash_seeds() -> None:
    script = (
        "from tests.execution.test_pricing import _price_projection; print(_price_projection())"
    )

    projections = [
        subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("1", "8675309")
    ]

    assert projections == [_price_projection(), _price_projection()]


def test_unpricable_structure_raises_instead_of_returning_an_empty_ladder() -> None:
    api = _pricing_api()
    locked_quotes = _quotes(
        **{
            _LONG_SYMBOL: _contract(
                _LONG_SYMBOL,
                bid=Decimal("3.0000"),
                ask=Decimal("3.0000"),
            ),
            _SHORT_SYMBOL: _contract(
                _SHORT_SYMBOL,
                bid=Decimal("1.2000"),
                ask=Decimal("1.2000"),
            ),
        }
    )

    with pytest.raises(api.UnpricableStructureError, match="strictly increasing"):
        api.rung_prices(_plan(), locked_quotes, 2, _MAX_QUOTE_AGE, _AS_OF)


def test_emitted_sequence_is_accepted_by_entry_ladder() -> None:
    api = _pricing_api()
    config = load(_CONFIG_DIRECTORY)
    plan = _plan()
    prices = api.rung_prices(plan, _quotes(), 4, _MAX_QUOTE_AGE, _AS_OF)
    snapshot = AccountSnapshot(
        equity=Decimal("60000.0000"),
        open_position_count=0,
        frozen_config_hash=config.frozen_config_hash,
        snapshot_time=_AS_OF,
    )

    decision = step_ladder(
        plan,
        1,
        prices,
        2,
        _AS_OF - timedelta(seconds=30),
        _AS_OF,
        LadderBudget(max_steps=4, time_budget=timedelta(minutes=2)),
        snapshot,
        config,
        SizingMode.STANDARD,
        _AS_OF + timedelta(minutes=5),
        _MAX_QUOTE_AGE,
    )

    assert decision.step is not None
    assert decision.step.limit_price == prices[2]
    assert decision.reasons == ()
