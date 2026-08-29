from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from alphaledger.config import FrozenConfig, load
from alphaledger.domain import StructurePlan
from alphaledger.risk.approval import (
    GATE_CONCURRENT_POSITION_LIMIT,
    AccountSnapshot,
    SizingMode,
    approve,
)

_CONFIG_DIRECTORY = Path(__file__).parents[2] / "config"
_NOW = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
_EXPIRES_AT = _NOW + timedelta(minutes=5)
_MAX_SNAPSHOT_AGE = timedelta(minutes=2)
_PRICE_LADDER = (Decimal("0.7500"), Decimal("1.0000"), Decimal("1.2500"))


def _ladder_api() -> ModuleType:
    try:
        return importlib.import_module("alphaledger.execution.ladder")
    except ModuleNotFoundError:
        pytest.fail("alphaledger.execution.ladder must implement the entry ladder contract")


def _frozen_config() -> FrozenConfig:
    return load(_CONFIG_DIRECTORY)


def _plan(
    *,
    plan_id: str = "plan-ladder-001",
    entry_limit_bound: Decimal = Decimal("1.2500"),
) -> StructurePlan:
    quote_time = datetime(2026, 8, 29, 13, 59, tzinfo=UTC)
    return StructurePlan(
        plan_id=plan_id,
        candidate_id="candidate-spy-ladder-001",
        legs=(
            {
                "symbol": "SPY260918C00500000",
                "ratio_qty": 1,
                "side": "buy",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": "SPY260918C00505000",
                "ratio_qty": 1,
                "side": "sell",
                "position_intent": "sell_to_open",
            },
        ),
        quantity=1,
        entry_limit_bound=entry_limit_bound,
        exact_max_loss=Decimal("100.0000"),
        exact_max_profit=Decimal("400.0000"),
        expiry_breakeven=Decimal("501.2500"),
        quote_times=(quote_time, quote_time),
        stress_pnl={"down": Decimal("-100.0000"), "up": Decimal("400.0000")},
    )


def _snapshot(
    config: FrozenConfig,
    *,
    open_position_count: int = 0,
) -> AccountSnapshot:
    return AccountSnapshot(
        equity=Decimal("60000.0000"),
        open_position_count=open_position_count,
        frozen_config_hash=config.frozen_config_hash,
        snapshot_time=_NOW,
    )


def _valid_inputs(api: ModuleType, **overrides: object) -> dict[str, Any]:
    config = _frozen_config()
    inputs: dict[str, Any] = {
        "plan": _plan(),
        "quantity": 1,
        "price_ladder": _PRICE_LADDER,
        "step_index": 0,
        "ladder_started_at": _NOW - timedelta(seconds=30),
        "now": _NOW,
        "budget": api.LadderBudget(max_steps=3, time_budget=timedelta(minutes=2)),
        "snapshot": _snapshot(config),
        "frozen_config": config,
        "mode": SizingMode.STANDARD,
        "expires_at": _EXPIRES_AT,
        "max_snapshot_age": _MAX_SNAPSHOT_AGE,
    }
    inputs.update(overrides)
    return inputs


def _assert_step_reason_invariant(decision: Any) -> None:
    assert (decision.step is None) == bool(decision.reasons)


def test_identical_rung_inputs_return_equal_decisions_in_every_field() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(api)

    first = api.step_ladder(**inputs)
    second = api.step_ladder(**inputs)

    assert first == second
    assert first.step is not None
    assert second.step is not None
    assert first.step.client_order_id == second.step.client_order_id
    assert first.step.approval.approval_id == second.step.approval.approval_id


def test_different_rung_prices_produce_distinct_order_and_approval_ids() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(api)

    first = api.step_ladder(**inputs)
    second = api.step_ladder(**(inputs | {"step_index": 1}))

    assert first.step is not None
    assert second.step is not None
    assert first.step.limit_price != second.step.limit_price
    assert first.step.client_order_id != second.step.client_order_id
    assert first.step.approval.approval_id != second.step.approval.approval_id


def test_rung_at_entry_limit_bound_is_accepted_without_crossing_it() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(api, step_index=2)

    decision = api.step_ladder(**inputs)

    assert decision.step is not None
    assert decision.step.limit_price == inputs["plan"].entry_limit_bound
    assert decision.reasons == ()


def test_last_valid_rung_returns_a_step_before_exhaustion() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(api, step_index=len(_PRICE_LADDER) - 1)

    decision = api.step_ladder(**inputs)

    assert decision.step is not None
    assert decision.step.step_index == len(_PRICE_LADDER) - 1
    assert decision.reasons == ()


def test_returned_approval_matches_independent_approval_over_rebuilt_inputs() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(api, step_index=1)

    decision = api.step_ladder(**inputs)

    assert decision.step is not None
    expected = approve(
        inputs["plan"],
        decision.step.payload,
        inputs["snapshot"],
        inputs["frozen_config"],
        inputs["mode"],
        inputs["expires_at"],
        inputs["now"],
        inputs["max_snapshot_age"],
    )
    assert decision.step.approval == expected


def test_rung_above_entry_limit_bound_raises_before_any_approval() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(
        api,
        price_ladder=(Decimal("0.7500"), Decimal("1.2501")),
    )

    with pytest.raises(ValueError, match=r"price_ladder.*entry_limit_bound"):
        api.step_ladder(**inputs)


def test_equal_adjacent_rungs_raise_instead_of_reusing_one_intent() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(
        api,
        price_ladder=(Decimal("0.7500"), Decimal("0.7500")),
    )

    with pytest.raises(ValueError, match=r"price_ladder.*strictly increasing"):
        api.step_ladder(**inputs)


def test_price_ladder_longer_than_max_steps_raises() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(
        api,
        budget=api.LadderBudget(max_steps=2, time_budget=timedelta(minutes=2)),
    )

    with pytest.raises(ValueError, match=r"price_ladder.*max_steps"):
        api.step_ladder(**inputs)


@pytest.mark.parametrize(
    ("max_steps", "time_budget", "field"),
    [
        (0, timedelta(seconds=1), "max_steps"),
        (-1, timedelta(seconds=1), "max_steps"),
        (1, timedelta(0), "time_budget"),
        (1, timedelta(microseconds=-1), "time_budget"),
    ],
)
def test_non_positive_ladder_budget_raises_and_names_invalid_field(
    max_steps: int,
    time_budget: timedelta,
    field: str,
) -> None:
    api = _ladder_api()

    with pytest.raises(ValueError, match=field):
        api.LadderBudget(max_steps=max_steps, time_budget=time_budget)


@pytest.mark.parametrize("step_index", [-1, True])
def test_invalid_step_index_raises_and_names_the_field(step_index: object) -> None:
    api = _ladder_api()
    inputs = _valid_inputs(api, step_index=step_index)

    with pytest.raises(ValueError, match="step_index"):
        api.step_ladder(**inputs)


def test_ladder_start_after_current_time_raises() -> None:
    api = _ladder_api()
    inputs = _valid_inputs(api, ladder_started_at=_NOW + timedelta(microseconds=1))

    with pytest.raises(ValueError, match=r"ladder_started_at.*after now"):
        api.step_ladder(**inputs)


@pytest.mark.parametrize(
    "price_ladder",
    [
        (Decimal("0.7500"), Decimal("1.2501")),
        (Decimal("0.7500"), Decimal("0.7500")),
    ],
)
def test_invalid_price_ladder_raises_even_when_step_index_is_exhausted(
    price_ladder: tuple[Decimal, ...],
) -> None:
    api = _ladder_api()
    inputs = _valid_inputs(
        api,
        price_ladder=price_ladder,
        step_index=len(price_ladder),
    )

    with pytest.raises(ValueError, match="price_ladder"):
        api.step_ladder(**inputs)


@pytest.mark.parametrize(
    "price_ladder",
    [
        (),
        (Decimal("0.7500"), Decimal("0.5000")),
    ],
)
def test_empty_or_descending_price_ladder_raises_as_a_construction_error(
    price_ladder: tuple[Decimal, ...],
) -> None:
    api = _ladder_api()
    inputs = _valid_inputs(api, price_ladder=price_ladder)

    with pytest.raises(ValueError, match="price_ladder"):
        api.step_ladder(**inputs)


def test_subprocess_reproduces_order_and_approval_ids_for_the_same_rung() -> None:
    api = _ladder_api()
    decision = api.step_ladder(**_valid_inputs(api, step_index=1))
    assert decision.step is not None
    script = """
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alphaledger.config import load
from alphaledger.domain import StructurePlan
from alphaledger.execution.ladder import LadderBudget, step_ladder
from alphaledger.risk.approval import AccountSnapshot, SizingMode

now = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
quote_time = datetime(2026, 8, 29, 13, 59, tzinfo=UTC)
config = load(Path(sys.argv[1]))
plan = StructurePlan(
    plan_id="plan-ladder-001",
    candidate_id="candidate-spy-ladder-001",
    legs=(
        {
            "symbol": "SPY260918C00500000",
            "ratio_qty": 1,
            "side": "buy",
            "position_intent": "buy_to_open",
        },
        {
            "symbol": "SPY260918C00505000",
            "ratio_qty": 1,
            "side": "sell",
            "position_intent": "sell_to_open",
        },
    ),
    quantity=1,
    entry_limit_bound=Decimal("1.2500"),
    exact_max_loss=Decimal("100.0000"),
    exact_max_profit=Decimal("400.0000"),
    expiry_breakeven=Decimal("501.2500"),
    quote_times=(quote_time, quote_time),
    stress_pnl={"down": Decimal("-100.0000"), "up": Decimal("400.0000")},
)
snapshot = AccountSnapshot(
    equity=Decimal("60000.0000"),
    open_position_count=0,
    frozen_config_hash=config.frozen_config_hash,
    snapshot_time=now,
)
decision = step_ladder(
    plan,
    1,
    (Decimal("0.7500"), Decimal("1.0000"), Decimal("1.2500")),
    1,
    now - timedelta(seconds=30),
    now,
    LadderBudget(max_steps=3, time_budget=timedelta(minutes=2)),
    snapshot,
    config,
    SizingMode.STANDARD,
    now + timedelta(minutes=5),
    timedelta(minutes=2),
)
assert decision.step is not None
print(json.dumps([decision.step.client_order_id, decision.step.approval.approval_id]))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script, str(_CONFIG_DIRECTORY)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [
        decision.step.client_order_id,
        decision.step.approval.approval_id,
    ]


def test_recomputing_after_simulated_crash_reuses_same_rung_id() -> None:
    api = _ladder_api()
    before_crash = api.step_ladder(**_valid_inputs(api, step_index=1))
    assert before_crash.step is not None
    recorded_id = before_crash.step.client_order_id
    del before_crash

    after_restart = api.step_ladder(**_valid_inputs(api, step_index=1))

    assert after_restart.step is not None
    assert after_restart.step.step_index == 1
    assert after_restart.step.client_order_id == recorded_id


@pytest.mark.parametrize("step_index", [len(_PRICE_LADDER), len(_PRICE_LADDER) + 3])
def test_step_index_at_or_beyond_ladder_length_returns_step_exhaustion(
    step_index: int,
) -> None:
    api = _ladder_api()

    decision = api.step_ladder(**_valid_inputs(api, step_index=step_index))

    assert decision.step is None
    assert decision.reasons == (api.LADDER_STEPS_EXHAUSTED_REASON,)
    _assert_step_reason_invariant(decision)


@pytest.mark.parametrize(
    "elapsed",
    [timedelta(minutes=2), timedelta(minutes=2, microseconds=1)],
)
def test_elapsed_time_at_or_beyond_budget_returns_time_exhaustion(
    elapsed: timedelta,
) -> None:
    api = _ladder_api()

    decision = api.step_ladder(**_valid_inputs(api, step_index=0, ladder_started_at=_NOW - elapsed))
    before_boundary = api.step_ladder(
        **_valid_inputs(
            api,
            step_index=0,
            ladder_started_at=_NOW - timedelta(minutes=2) + timedelta(microseconds=1),
        )
    )

    assert decision.step is None
    assert decision.reasons == (api.LADDER_TIME_BUDGET_EXCEEDED_REASON,)
    _assert_step_reason_invariant(decision)
    assert before_boundary.step is not None
    assert before_boundary.reasons == ()
    _assert_step_reason_invariant(before_boundary)


def test_time_and_step_exhaustion_return_both_reasons_once() -> None:
    api = _ladder_api()

    decision = api.step_ladder(
        **_valid_inputs(
            api,
            step_index=len(_PRICE_LADDER),
            ladder_started_at=_NOW - timedelta(minutes=2),
        )
    )

    assert decision.step is None
    assert decision.reasons == (
        api.LADDER_TIME_BUDGET_EXCEEDED_REASON,
        api.LADDER_STEPS_EXHAUSTED_REASON,
    )
    assert decision.reasons.count(api.LADDER_TIME_BUDGET_EXCEEDED_REASON) == 1
    assert decision.reasons.count(api.LADDER_STEPS_EXHAUSTED_REASON) == 1
    _assert_step_reason_invariant(decision)


def test_non_price_risk_refusal_returns_a_step_without_ladder_exhaustion() -> None:
    api = _ladder_api()
    config = _frozen_config()
    refused_snapshot = _snapshot(
        config,
        open_position_count=config.risk.maximum_concurrent_positions,
    )

    decision = api.step_ladder(
        **_valid_inputs(
            api,
            snapshot=refused_snapshot,
            frozen_config=config,
        )
    )

    assert decision.step is not None
    assert decision.reasons == ()
    assert decision.step.approval.approved is False
    assert decision.step.approval.failed_gates == (GATE_CONCURRENT_POSITION_LIMIT,)
    _assert_step_reason_invariant(decision)
