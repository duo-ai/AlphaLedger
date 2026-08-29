import importlib
import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from types import ModuleType

import pytest

from alphaledger.execution.orders import build_mleg_order

_AS_OF = datetime(2026, 8, 29, 15, 0, tzinfo=UTC)
_QUOTE_TIME = datetime(2026, 8, 29, 14, 59, 30, tzinfo=UTC)
_EXPIRY = date(2026, 9, 11)
_LONG_CALL_SYMBOL = "SPY260911C00100000"
_SHORT_CALL_SYMBOL = "SPY260911C00105000"
_LONG_PUT_SYMBOL = "SPY260911P00105000"
_SHORT_PUT_SYMBOL = "SPY260911P00100000"


def _chains() -> ModuleType:
    try:
        return importlib.import_module("alphaledger.structure.chains")
    except ModuleNotFoundError as exc:
        if exc.name not in {"alphaledger.structure", "alphaledger.structure.chains"}:
            raise
        pytest.fail("alphaledger.structure.chains must implement UNIT-014")


class MemoryChains:
    def __init__(self, contracts: tuple[object, ...]) -> None:
        self.contracts = contracts
        self.queries: list[tuple[str, datetime]] = []

    def contracts_for(self, underlying_symbol: str, as_of: datetime) -> tuple[object, ...]:
        self.queries.append((underlying_symbol, as_of))
        return self.contracts


def _rules(chains: ModuleType, **overrides: object) -> object:
    values: dict[str, object] = {
        "dte_min": 7,
        "dte_max": 21,
        "long_abs_delta_min": Decimal("0.45"),
        "long_abs_delta_max": Decimal("0.60"),
        "short_abs_delta_min": Decimal("0.20"),
        "short_abs_delta_max": Decimal("0.35"),
        "max_quote_age": timedelta(minutes=2),
        "max_relative_spread": Decimal("0.10"),
        "max_absolute_spread": Decimal("0.25"),
        "expected_feed": "opra",
    }
    values.update(overrides)
    return chains.StructureRules(**values)


def _contract(chains: ModuleType, **overrides: object) -> object:
    values: dict[str, object] = {
        "symbol": _LONG_CALL_SYMBOL,
        "underlying_symbol": "SPY",
        "option_type": chains.OptionType.CALL,
        "strike": Decimal("100"),
        "expiry": _EXPIRY,
        "bid": Decimal("2.90"),
        "ask": Decimal("3.00"),
        "bid_size": 10,
        "ask_size": 10,
        "multiplier": 100,
        "delta": Decimal("0.52"),
        "quote_time": _QUOTE_TIME,
        "feed": "opra",
    }
    values.update(overrides)
    return chains.ChainContract(**values)


def _call_contracts(chains: ModuleType, **short_overrides: object) -> tuple[object, object]:
    long_leg = _contract(chains)
    short_values: dict[str, object] = {
        "symbol": _SHORT_CALL_SYMBOL,
        "strike": Decimal("105"),
        "bid": Decimal("1.20"),
        "ask": Decimal("1.30"),
        "delta": Decimal("0.30"),
    }
    short_values.update(short_overrides)
    short_leg = _contract(chains, **short_values)
    return long_leg, short_leg


def _put_contracts(chains: ModuleType) -> tuple[object, object]:
    long_leg = _contract(
        chains,
        symbol=_LONG_PUT_SYMBOL,
        option_type=chains.OptionType.PUT,
        strike=Decimal("105"),
        delta=Decimal("-0.52"),
    )
    short_leg = _contract(
        chains,
        symbol=_SHORT_PUT_SYMBOL,
        option_type=chains.OptionType.PUT,
        strike=Decimal("100"),
        bid=Decimal("1.20"),
        ask=Decimal("1.30"),
        delta=Decimal("-0.30"),
    )
    return long_leg, short_leg


def _enumerate(
    chains: ModuleType,
    contracts: tuple[object, ...],
    *,
    kind: str = "bull_call_debit_vertical",
    quantity: int = 2,
    rules: object | None = None,
) -> tuple[object, MemoryChains]:
    lookup = MemoryChains(contracts)
    result = chains.enumerate_candidates(
        kind,
        "candidate-spy-014",
        "SPY",
        _AS_OF,
        quantity,
        rules if rules is not None else _rules(chains),
        lookup,
    )
    return result, lookup


def _assert_rejection(result: object, gate: str, *symbols: str) -> None:
    assert result.candidates == ()
    assert result.rejection_reasons
    for symbol in symbols:
        assert any(gate in reason and symbol in reason for reason in result.rejection_reasons)


def _project_plans(plans: tuple[object, ...]) -> str:
    projection = []
    for plan in plans:
        projection.append(
            {
                "plan_id": plan.plan_id,
                "candidate_id": plan.candidate_id,
                "legs": [dict(leg) for leg in plan.legs],
                "quantity": plan.quantity,
                "entry_limit_bound": str(plan.entry_limit_bound),
                "exact_max_loss": str(plan.exact_max_loss),
                "exact_max_profit": str(plan.exact_max_profit),
                "expiry_breakeven": str(plan.expiry_breakeven),
                "quote_times": [item.isoformat() for item in plan.quote_times],
                "stress_pnl": {key: str(value) for key, value in plan.stress_pnl.items()},
            }
        )
    return json.dumps(projection, separators=(",", ":"), sort_keys=True)


def _ordered_contracts(chains: ModuleType) -> tuple[object, ...]:
    cheap_expiry = date(2026, 9, 10)
    tied_expiry = date(2026, 9, 12)
    return (
        _contract(
            chains,
            symbol="SPY260912C00105000",
            strike=Decimal("105"),
            expiry=tied_expiry,
            bid=Decimal("1.90"),
            ask=Decimal("2.00"),
            delta=Decimal("0.50"),
        ),
        _contract(
            chains,
            symbol="SPY260910C00106000",
            strike=Decimal("106"),
            expiry=cheap_expiry,
            bid=Decimal("1.90"),
            ask=Decimal("2.00"),
            delta=Decimal("0.30"),
        ),
        _contract(
            chains,
            symbol="SPY260912C00110000",
            strike=Decimal("110"),
            expiry=tied_expiry,
            bid=Decimal("1.00"),
            ask=Decimal("1.10"),
            delta=Decimal("0.30"),
        ),
        _contract(
            chains,
            symbol="SPY260910C00101000",
            strike=Decimal("101"),
            expiry=cheap_expiry,
            bid=Decimal("2.40"),
            ask=Decimal("2.50"),
            delta=Decimal("0.50"),
        ),
        _contract(
            chains,
            symbol="SPY260912C00100000",
            strike=Decimal("100"),
            expiry=tied_expiry,
            bid=Decimal("2.90"),
            ask=Decimal("3.00"),
            delta=Decimal("0.50"),
        ),
    )


def _ordered_projection() -> str:
    chains = _chains()
    result, _ = _enumerate(chains, _ordered_contracts(chains))
    return _project_plans(result.candidates)


def _context_sensitive_contracts(chains: ModuleType) -> tuple[object, ...]:
    nearer_expiry = date(2026, 9, 10)
    later_expiry = date(2026, 9, 12)
    return (
        _contract(
            chains,
            symbol="SPY260910C01099999",
            strike=Decimal("1099.9999"),
            expiry=nearer_expiry,
            bid=Decimal("0.10"),
            ask=Decimal("0.11"),
            multiplier=1,
            delta=Decimal("0.30"),
        ),
        _contract(
            chains,
            symbol="SPY260912C00100000",
            strike=Decimal("100"),
            expiry=later_expiry,
            bid=Decimal("1.00"),
            ask=Decimal("1.10"),
            multiplier=1,
            delta=Decimal("0.50"),
        ),
        _contract(
            chains,
            symbol="SPY260912C01100000",
            strike=Decimal("1100"),
            expiry=later_expiry,
            bid=Decimal("0.10"),
            ask=Decimal("0.11"),
            multiplier=1,
            delta=Decimal("0.30"),
        ),
        _contract(
            chains,
            symbol="SPY260910C00100000",
            strike=Decimal("100"),
            expiry=nearer_expiry,
            bid=Decimal("1.00"),
            ask=Decimal("1.10"),
            multiplier=1,
            delta=Decimal("0.50"),
        ),
    )


def _low_precision_projection() -> str:
    chains = _chains()
    contracts = _context_sensitive_contracts(chains)
    with localcontext() as context:
        context.prec = 7
        result, _ = _enumerate(chains, contracts)
    return _project_plans(result.candidates)


def _call_projection() -> str:
    chains = _chains()
    result, _ = _enumerate(chains, _call_contracts(chains))
    return _project_plans(result.candidates)


def _subprocess_helper(helper_name: str) -> str:
    script = f"from tests.structure.test_chains import {helper_name}; print({helper_name}())"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_call_debit_vertical_has_hand_computed_exact_payoff_and_closed_leg_vocabulary() -> None:
    chains = _chains()
    result, lookup = _enumerate(chains, _call_contracts(chains))

    assert lookup.queries == [("SPY", _AS_OF)]
    assert result.rejection_reasons == ()
    assert len(result.candidates) == 1
    plan = result.candidates[0]
    assert plan.plan_id == f"candidate-spy-014/{_LONG_CALL_SYMBOL}/{_SHORT_CALL_SYMBOL}"
    assert plan.candidate_id == "candidate-spy-014"
    assert tuple(dict(leg) for leg in plan.legs) == (
        {
            "symbol": _LONG_CALL_SYMBOL,
            "ratio_qty": 1,
            "side": "buy",
            "position_intent": "buy_to_open",
        },
        {
            "symbol": _SHORT_CALL_SYMBOL,
            "ratio_qty": 1,
            "side": "sell",
            "position_intent": "sell_to_open",
        },
    )
    assert all(set(leg) == {"symbol", "ratio_qty", "side", "position_intent"} for leg in plan.legs)
    assert plan.quantity == 2
    assert plan.entry_limit_bound == Decimal("1.8000")
    assert plan.exact_max_loss == Decimal("180.0000")
    assert plan.exact_max_profit == Decimal("320.0000")
    assert plan.expiry_breakeven == Decimal("101.8000")
    assert plan.quote_times == (_QUOTE_TIME, _QUOTE_TIME)
    assert plan.stress_pnl == {
        "max_loss_scenario": Decimal("-180.0000"),
        "max_profit_scenario": Decimal("320.0000"),
    }
    assert all(
        isinstance(getattr(plan, field), Decimal)
        for field in (
            "entry_limit_bound",
            "exact_max_loss",
            "exact_max_profit",
            "expiry_breakeven",
        )
    )
    assert all(isinstance(value, Decimal) for value in plan.stress_pnl.values())


def test_put_debit_vertical_mirrors_breakeven_and_has_hand_computed_exact_payoff() -> None:
    chains = _chains()
    result, _ = _enumerate(
        chains,
        _put_contracts(chains),
        kind="bear_put_debit_vertical",
    )

    assert result.rejection_reasons == ()
    assert len(result.candidates) == 1
    plan = result.candidates[0]
    assert plan.plan_id == f"candidate-spy-014/{_LONG_PUT_SYMBOL}/{_SHORT_PUT_SYMBOL}"
    assert plan.entry_limit_bound == Decimal("1.8000")
    assert plan.exact_max_loss == Decimal("180.0000")
    assert plan.exact_max_profit == Decimal("320.0000")
    assert plan.expiry_breakeven == Decimal("103.2000")
    assert plan.stress_pnl == {
        "max_loss_scenario": Decimal("-180.0000"),
        "max_profit_scenario": Decimal("320.0000"),
    }


def test_produced_plan_passes_unmodified_into_the_mleg_order_adapter() -> None:
    chains = _chains()
    result, _ = _enumerate(chains, _call_contracts(chains))
    plan = result.candidates[0]

    payload = build_mleg_order(
        plan,
        quantity=plan.quantity,
        limit_price=plan.entry_limit_bound,
        client_order_id="unit-014-adapter-contract",
    )

    assert payload["legs"] == [
        {
            "symbol": _LONG_CALL_SYMBOL,
            "ratio_qty": "1",
            "side": "buy",
            "position_intent": "buy_to_open",
        },
        {
            "symbol": _SHORT_CALL_SYMBOL,
            "ratio_qty": "1",
            "side": "sell",
            "position_intent": "sell_to_open",
        },
    ]


def test_three_candidates_follow_cost_expiry_and_long_strike_order_across_processes() -> None:
    chains = _chains()
    first, _ = _enumerate(chains, _ordered_contracts(chains))
    second, _ = _enumerate(chains, tuple(reversed(_ordered_contracts(chains))))

    expected_ids = [
        "candidate-spy-014/SPY260910C00101000/SPY260910C00106000",
        "candidate-spy-014/SPY260912C00100000/SPY260912C00110000",
        "candidate-spy-014/SPY260912C00105000/SPY260912C00110000",
    ]
    assert [plan.plan_id for plan in first.candidates] == expected_ids
    assert first.candidates == second.candidates
    assert _subprocess_helper("_ordered_projection") == _project_plans(first.candidates)
    assert len({plan.plan_id for plan in first.candidates}) == 3


def test_cost_drag_order_is_exact_across_decimal_contexts_and_processes() -> None:
    chains = _chains()
    contracts = _context_sensitive_contracts(chains)
    default_result, _ = _enumerate(chains, contracts)
    with localcontext() as context:
        context.prec = 7
        low_precision_result, _ = _enumerate(chains, contracts)

    expected_ids = [
        "candidate-spy-014/SPY260912C00100000/SPY260912C01100000",
        "candidate-spy-014/SPY260910C00100000/SPY260910C01099999",
    ]
    assert [plan.plan_id for plan in default_result.candidates] == expected_ids
    assert low_precision_result.candidates == default_result.candidates
    assert _subprocess_helper("_low_precision_projection") == _project_plans(
        default_result.candidates
    )


def test_identical_duplicate_symbols_collapse_to_one_plan_with_one_plan_id() -> None:
    chains = _chains()
    long_leg, short_leg = _call_contracts(chains)
    result, _ = _enumerate(chains, (long_leg, short_leg, long_leg, short_leg))

    assert len(result.candidates) == 1
    assert result.candidates[0].plan_id == (
        f"candidate-spy-014/{_LONG_CALL_SYMBOL}/{_SHORT_CALL_SYMBOL}"
    )


def test_conflicting_duplicate_symbol_fails_closed_independent_of_lookup_order() -> None:
    chains = _chains()
    long_leg, short_leg = _call_contracts(chains)
    conflicting_long = _contract(
        chains,
        bid=Decimal("2.95"),
        ask=Decimal("3.05"),
        quote_time=_AS_OF - timedelta(seconds=15),
    )
    contracts = (long_leg, short_leg, conflicting_long)

    first, _ = _enumerate(chains, contracts)
    second, _ = _enumerate(chains, tuple(reversed(contracts)))

    _assert_rejection(first, "contract_symbol_uniqueness", _LONG_CALL_SYMBOL)
    assert second == first


def test_matching_nonstandard_multiplier_scales_payoff_by_that_multiplier() -> None:
    chains = _chains()
    long_leg, short_leg = _call_contracts(chains, multiplier=10)
    long_leg = _contract(chains, multiplier=10)
    result, _ = _enumerate(chains, (long_leg, short_leg))

    plan = result.candidates[0]
    assert plan.exact_max_loss == Decimal("18.0000")
    assert plan.exact_max_profit == Decimal("32.0000")


@pytest.mark.parametrize("field", ["strike", "bid", "ask", "delta"])
def test_float_chain_decimal_is_rejected_at_construction_and_names_field(field: str) -> None:
    chains = _chains()

    with pytest.raises(TypeError, match=field):
        _contract(chains, **{field: 1.25})


def test_unknown_structure_kind_is_rejected_before_the_chain_is_touched() -> None:
    chains = _chains()

    class ExplodingLookup:
        def contracts_for(self, underlying_symbol: str, as_of: datetime) -> tuple[object, ...]:
            raise AssertionError((underlying_symbol, as_of))

    with pytest.raises(chains.StructureError, match="kind"):
        chains.enumerate_candidates(
            "iron_condor",
            "candidate-spy-014",
            "SPY",
            _AS_OF,
            1,
            _rules(chains),
            ExplodingLookup(),
        )


def test_dte_min_below_one_is_rejected_and_same_day_contracts_never_trade() -> None:
    chains = _chains()

    with pytest.raises(ValueError, match="dte_min"):
        _rules(chains, dte_min=0)

    same_day = _AS_OF.date()
    contracts = (
        _contract(chains, expiry=same_day),
        _contract(
            chains,
            symbol=_SHORT_CALL_SYMBOL,
            strike=Decimal("105"),
            bid=Decimal("1.20"),
            ask=Decimal("1.30"),
            delta=Decimal("0.30"),
            expiry=same_day,
        ),
    )
    result, _ = _enumerate(chains, contracts)
    _assert_rejection(result, "dte_window", _LONG_CALL_SYMBOL, _SHORT_CALL_SYMBOL)


def test_zero_bid_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    result, _ = _enumerate(chains, _call_contracts(chains, bid=Decimal("0")))

    _assert_rejection(result, "quote_integrity", _SHORT_CALL_SYMBOL)


def test_crossed_quote_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    contracts = (
        _contract(chains, bid=Decimal("3.10"), ask=Decimal("3.00")),
        _call_contracts(chains)[1],
    )
    result, _ = _enumerate(chains, contracts)

    _assert_rejection(result, "quote_integrity", _LONG_CALL_SYMBOL)


def test_stale_quote_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    contracts = (
        _contract(chains, quote_time=_AS_OF - timedelta(minutes=3)),
        _call_contracts(chains)[1],
    )
    result, _ = _enumerate(chains, contracts)

    _assert_rejection(result, "quote_freshness", _LONG_CALL_SYMBOL)


def test_missing_multiplier_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    contracts = (
        _contract(chains, multiplier=None),
        _call_contracts(chains)[1],
    )
    result, _ = _enumerate(chains, contracts)

    _assert_rejection(result, "contract_metadata", _LONG_CALL_SYMBOL)


def test_multiplier_mismatch_gate_excludes_pair_and_names_gate_and_symbols() -> None:
    chains = _chains()
    long_leg, short_leg = _call_contracts(chains, multiplier=10)
    result, _ = _enumerate(chains, (long_leg, short_leg))

    _assert_rejection(
        result,
        "contract_metadata",
        _LONG_CALL_SYMBOL,
        _SHORT_CALL_SYMBOL,
    )


def test_missing_delta_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    contracts = (_contract(chains, delta=None), _call_contracts(chains)[1])
    result, _ = _enumerate(chains, contracts)

    _assert_rejection(result, "delta_required", _LONG_CALL_SYMBOL)


def test_relative_spread_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    contracts = (
        _contract(chains, bid=Decimal("2.50"), ask=Decimal("3.00")),
        _call_contracts(chains)[1],
    )
    rules = _rules(
        chains,
        max_relative_spread=Decimal("0.10"),
        max_absolute_spread=Decimal("1.00"),
    )
    result, _ = _enumerate(chains, contracts, rules=rules)

    _assert_rejection(result, "relative_spread", _LONG_CALL_SYMBOL)


def test_absolute_spread_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    contracts = (
        _contract(chains, bid=Decimal("2.50"), ask=Decimal("3.00")),
        _call_contracts(chains)[1],
    )
    rules = _rules(
        chains,
        max_relative_spread=Decimal("1.00"),
        max_absolute_spread=Decimal("0.25"),
    )
    result, _ = _enumerate(chains, contracts, rules=rules)

    _assert_rejection(result, "absolute_spread", _LONG_CALL_SYMBOL)


def test_displayed_size_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    contracts = (_contract(chains, ask_size=1), _call_contracts(chains)[1])
    result, _ = _enumerate(chains, contracts, quantity=2)

    _assert_rejection(result, "displayed_size", _LONG_CALL_SYMBOL)


def test_feed_identity_gate_excludes_contract_and_names_gate_and_symbol() -> None:
    chains = _chains()
    contracts = (_contract(chains, feed="indicative"), _call_contracts(chains)[1])
    result, _ = _enumerate(chains, contracts)

    _assert_rejection(result, "feed_identity", _LONG_CALL_SYMBOL)


@pytest.mark.parametrize(
    ("flaw", "reason"),
    [
        ("non_positive_debit", "payoff_invariant"),
        ("debit_at_width", "payoff_invariant"),
        ("different_expiry", "expiry_match"),
        ("different_underlying", "underlying_match"),
    ],
)
def test_invalid_spread_combination_is_absent_without_raising(flaw: str, reason: str) -> None:
    chains = _chains()
    long_leg, short_leg = _call_contracts(chains)
    if flaw == "non_positive_debit":
        long_leg = _contract(chains, bid=Decimal("0.95"), ask=Decimal("1.00"))
        short_leg = _call_contracts(
            chains,
            bid=Decimal("1.10"),
            ask=Decimal("1.15"),
        )[1]
    elif flaw == "debit_at_width":
        long_leg = _contract(chains, bid=Decimal("6.40"), ask=Decimal("6.50"))
        short_leg = _call_contracts(
            chains,
            bid=Decimal("1.00"),
            ask=Decimal("1.10"),
        )[1]
    elif flaw == "different_expiry":
        short_leg = _call_contracts(chains, expiry=date(2026, 9, 12))[1]
    elif flaw == "different_underlying":
        short_leg = _call_contracts(chains, underlying_symbol="QQQ")[1]

    result, _ = _enumerate(chains, (long_leg, short_leg))

    assert result.candidates == ()
    assert any(reason in item for item in result.rejection_reasons)


def test_restart_reconstructs_equal_structure_plan_fields_in_a_new_process() -> None:
    assert _subprocess_helper("_call_projection") == _call_projection()


def test_restart_reconstructs_same_plan_id_after_crash_before_risk_approval() -> None:
    chains = _chains()
    result, _ = _enumerate(chains, _call_contracts(chains))
    before_crash = result.candidates[0].plan_id
    after_restart = json.loads(_subprocess_helper("_call_projection"))[0]["plan_id"]

    assert after_restart == before_crash


def test_empty_chain_returns_auditable_no_trade_instead_of_raising() -> None:
    chains = _chains()
    result, _ = _enumerate(chains, ())

    assert result.candidates == ()
    assert any("no_contracts" in reason and "SPY" in reason for reason in result.rejection_reasons)


def test_wrong_option_type_returns_no_trade_reason_naming_absent_call_contracts() -> None:
    chains = _chains()
    result, _ = _enumerate(chains, _put_contracts(chains))

    assert result.candidates == ()
    assert any("no_call_contracts" in reason for reason in result.rejection_reasons)


def test_all_delta_band_failures_are_distinct_from_contract_gate_failures() -> None:
    chains = _chains()
    contracts = (
        _contract(chains, delta=Decimal("0.80")),
        _call_contracts(chains, delta=Decimal("0.10"))[1],
    )
    result, _ = _enumerate(chains, contracts)

    _assert_rejection(result, "delta_band", _LONG_CALL_SYMBOL, _SHORT_CALL_SYMBOL)
    assert all("delta_required" not in reason for reason in result.rejection_reasons)
