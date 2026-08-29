from __future__ import annotations

import importlib
import json
import subprocess
import sys
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from alphaledger.config import FrozenConfig, load
from alphaledger.domain import RiskApproval, StructurePlan
from alphaledger.execution.lifecycle import client_order_id
from alphaledger.execution.orders import build_mleg_order, order_payload_hash

_CONFIG_DIRECTORY = Path(__file__).parents[2] / "config"
_NOW = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
_EXPIRES_AT = _NOW + timedelta(minutes=5)
_MAX_SNAPSHOT_AGE = timedelta(minutes=2)


def _risk_api() -> ModuleType:
    try:
        return importlib.import_module("alphaledger.risk.approval")
    except ModuleNotFoundError:
        pytest.fail("alphaledger.risk.approval must implement the risk approval contract")


def _frozen_config() -> FrozenConfig:
    return load(_CONFIG_DIRECTORY)


def _plan(
    *,
    plan_id: str = "plan-approval-001",
    entry_limit_bound: Decimal = Decimal("1.2500"),
    exact_max_loss: Decimal = Decimal("100.0000"),
) -> StructurePlan:
    quote_time = datetime(2026, 8, 29, 13, 59, tzinfo=UTC)
    return StructurePlan(
        plan_id=plan_id,
        candidate_id="candidate-spy-001",
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
        exact_max_loss=exact_max_loss,
        exact_max_profit=Decimal("400.0000"),
        expiry_breakeven=Decimal("501.2500"),
        quote_times=(quote_time, quote_time),
        stress_pnl={"down": Decimal("-100.0000"), "up": Decimal("400.0000")},
    )


def _payload(
    plan: StructurePlan,
    *,
    quantity: int = 2,
    limit_price: Decimal = Decimal("1.2500"),
    order_id: str | None = None,
) -> dict[str, object]:
    resolved_order_id = (
        order_id if order_id is not None else client_order_id(plan.plan_id, quantity, limit_price)
    )
    return dict(build_mleg_order(plan, quantity, limit_price, resolved_order_id))


class _PayloadMutatingAfterLegRead(Mapping[str, object]):
    """Expose a payload that changes after the final gate input is read."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.mutated = False

    def __getitem__(self, key: str) -> object:
        value = self._payload[key]
        if key == "legs" and not self.mutated:
            self._payload["client_order_id"] = "changed-after-gate-input-read"
            self.mutated = True
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)


def _snapshot(
    api: ModuleType,
    config: FrozenConfig,
    *,
    equity: Decimal = Decimal("60000.0000"),
    open_position_count: int = 0,
    frozen_config_hash: str | None = None,
    snapshot_time: datetime = _NOW,
) -> Any:
    return api.AccountSnapshot(
        equity=equity,
        open_position_count=open_position_count,
        frozen_config_hash=frozen_config_hash or config.frozen_config_hash,
        snapshot_time=snapshot_time,
    )


def _approved_token(api: ModuleType) -> RiskApproval:
    config = _frozen_config()
    plan = _plan()
    return api.approve(
        plan,
        _payload(plan),
        _snapshot(api, config),
        config,
        api.SizingMode.STANDARD,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )


def test_every_gate_passes_and_token_binds_independently_recomputed_hashes() -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()
    payload = _payload(plan)
    snapshot = _snapshot(api, config)

    approval = api.approve(
        plan,
        payload,
        snapshot,
        config,
        api.SizingMode.STANDARD,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )

    assert approval.approved is True
    assert approval.failed_gates == ()
    assert approval.account_snapshot_hash == api.account_snapshot_hash(snapshot)
    assert approval.order_payload_hash == order_payload_hash(payload)
    assert approval.plan_id == plan.plan_id
    assert approval.expires_at == _EXPIRES_AT


def test_standard_sizing_floors_risk_budget_below_the_frozen_cap() -> None:
    api = _risk_api()
    config = _frozen_config()

    quantity = api.max_approved_quantity(
        _plan(),
        Decimal("60000.0000"),
        config.risk,
        api.SizingMode.STANDARD,
    )

    assert quantity == 2
    assert quantity < config.risk.max_contracts_per_structure


def test_smoke_test_sizing_caps_quantity_that_standard_mode_allows() -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()
    equity = Decimal("100000.0000")

    standard = api.max_approved_quantity(plan, equity, config.risk, api.SizingMode.STANDARD)
    smoke_test = api.max_approved_quantity(plan, equity, config.risk, api.SizingMode.SMOKE_TEST)

    assert standard == 3
    assert smoke_test == config.risk.smoke_test_max_contracts == 1


def test_expiry_is_false_before_and_true_at_and_after_the_boundary() -> None:
    api = _risk_api()
    approval = _approved_token(api)

    assert api.is_expired(approval, _EXPIRES_AT - timedelta(microseconds=1)) is False
    assert api.is_expired(approval, _EXPIRES_AT) is True
    assert api.is_expired(approval, _EXPIRES_AT + timedelta(microseconds=1)) is True


@pytest.mark.parametrize("expires_at", [_NOW, _NOW - timedelta(microseconds=1)])
def test_expiry_at_or_before_now_raises_instead_of_returning_a_token(
    expires_at: datetime,
) -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()

    with pytest.raises(ValueError, match="expires_at"):
        api.approve(
            plan,
            _payload(plan),
            _snapshot(api, config),
            config,
            api.SizingMode.STANDARD,
            expires_at,
            _NOW,
            _MAX_SNAPSHOT_AGE,
        )


@pytest.mark.parametrize("exact_max_loss", [Decimal("0"), Decimal("-1")])
def test_nonpositive_exact_max_loss_raises_and_names_the_field(
    exact_max_loss: Decimal,
) -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan(exact_max_loss=exact_max_loss)

    with pytest.raises(ValueError, match="exact_max_loss"):
        api.approve(
            plan,
            _payload(plan),
            _snapshot(api, config),
            config,
            api.SizingMode.STANDARD,
            _EXPIRES_AT,
            _NOW,
            _MAX_SNAPSHOT_AGE,
        )


@pytest.mark.parametrize("missing_field", ["qty", "limit_price", "legs"])
def test_missing_payload_field_raises_value_error_and_names_the_field(
    missing_field: str,
) -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()
    payload = _payload(plan)
    payload.pop(missing_field)

    with pytest.raises(ValueError, match=missing_field):
        api.approve(
            plan,
            payload,
            _snapshot(api, config),
            config,
            api.SizingMode.STANDARD,
            _EXPIRES_AT,
            _NOW,
            _MAX_SNAPSHOT_AGE,
        )


@pytest.mark.parametrize(
    "mismatch",
    ["foreign_plan_legs", "handmade_client_order_id", "post_build_mutation"],
)
def test_readable_payload_mismatch_is_refused_with_a_named_gate(mismatch: str) -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()
    quantity = 2
    limit_price = Decimal("1.2500")

    if mismatch == "foreign_plan_legs":
        foreign_legs = [dict(leg) for leg in plan.legs]
        foreign_legs[1]["symbol"] = "SPY260918C00510000"
        foreign_plan = replace(
            plan,
            plan_id="foreign-plan-approval-001",
            legs=tuple(foreign_legs),
        )
        payload = _payload(
            foreign_plan,
            quantity=quantity,
            limit_price=limit_price,
            order_id=client_order_id(plan.plan_id, quantity, limit_price),
        )
    elif mismatch == "handmade_client_order_id":
        payload = _payload(plan, order_id="handmade-client-order-id")
    else:
        payload = _payload(plan)
        payload["time_in_force"] = "gtc"

    approval = api.approve(
        plan,
        payload,
        _snapshot(api, config),
        config,
        api.SizingMode.STANDARD,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )

    assert approval.approved is False
    assert approval.failed_gates == (api.GATE_PAYLOAD_PLAN_MISMATCH,)


def test_payload_mutating_after_gate_reads_cannot_change_decision_binding() -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()
    canonical_payload = _payload(plan)
    expected_payload_hash = order_payload_hash(canonical_payload)
    mutating_payload = _PayloadMutatingAfterLegRead(canonical_payload)

    approval = api.approve(
        plan,
        mutating_payload,
        _snapshot(api, config),
        config,
        api.SizingMode.STANDARD,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )

    assert mutating_payload.mutated is True
    assert approval.approved is False
    assert approval.failed_gates == (api.GATE_PAYLOAD_PLAN_MISMATCH,)
    assert approval.order_payload_hash == expected_payload_hash


@pytest.mark.parametrize(
    ("snapshot_time", "is_refused"),
    [
        (_NOW - timedelta(microseconds=1), False),
        (_NOW, False),
        (_NOW + timedelta(microseconds=1), True),
    ],
)
def test_future_snapshot_gate_is_strictly_after_now(
    snapshot_time: datetime,
    is_refused: bool,
) -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()

    approval = api.approve(
        plan,
        _payload(plan),
        _snapshot(api, config, snapshot_time=snapshot_time),
        config,
        api.SizingMode.STANDARD,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )

    assert (api.GATE_SNAPSHOT_IN_FUTURE in approval.failed_gates) is is_refused


@pytest.mark.parametrize(
    ("snapshot_time", "is_refused"),
    [
        (_NOW - _MAX_SNAPSHOT_AGE + timedelta(microseconds=1), False),
        (_NOW - _MAX_SNAPSHOT_AGE, False),
        (_NOW - _MAX_SNAPSHOT_AGE - timedelta(microseconds=1), True),
    ],
)
def test_stale_snapshot_gate_is_strictly_outside_the_age_boundary(
    snapshot_time: datetime,
    is_refused: bool,
) -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()

    approval = api.approve(
        plan,
        _payload(plan),
        _snapshot(api, config, snapshot_time=snapshot_time),
        config,
        api.SizingMode.STANDARD,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )

    assert (api.GATE_SNAPSHOT_STALE in approval.failed_gates) is is_refused


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("equity", Decimal("60001.0000")),
        ("open_position_count", 1),
        ("frozen_config_hash", "different-config-hash"),
        ("snapshot_time", _NOW + timedelta(microseconds=1)),
    ],
)
def test_snapshot_hash_changes_under_every_single_field_mutation(
    field: str,
    replacement: object,
) -> None:
    api = _risk_api()
    config = _frozen_config()
    snapshot = _snapshot(api, config)
    changed = replace(snapshot, **{field: replacement})

    assert api.account_snapshot_hash(changed) != api.account_snapshot_hash(snapshot)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("plan_id", "plan-approval-002"),
        ("quantity", 2),
        ("order_payload_hash", "payload-hash-002"),
        ("account_snapshot_hash", "snapshot-hash-002"),
        ("mode", "smoke_test"),
        ("expires_at", _EXPIRES_AT + timedelta(microseconds=1)),
        ("approved", False),
        ("failed_gates", ("one_failed_gate",)),
    ],
)
def test_approval_id_changes_under_every_single_bound_field_mutation(
    field: str,
    replacement: object,
) -> None:
    api = _risk_api()
    values = {
        "plan_id": "plan-approval-001",
        "quantity": 1,
        "order_payload_hash": "payload-hash-001",
        "account_snapshot_hash": "snapshot-hash-001",
        "mode": "standard",
        "expires_at": _EXPIRES_AT,
        "approved": True,
        "failed_gates": (),
    }
    changed = values | {field: replacement}

    assert api._approval_id(**changed) != api._approval_id(**values)


def test_identical_approval_inputs_reproduce_all_bound_ids_after_restart() -> None:
    api = _risk_api()
    approval = _approved_token(api)
    script = """
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alphaledger.config import load
from alphaledger.domain import StructurePlan
from alphaledger.execution.lifecycle import client_order_id
from alphaledger.execution.orders import build_mleg_order
from alphaledger.risk.approval import AccountSnapshot, SizingMode, approve

now = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
expires_at = datetime(2026, 8, 29, 14, 5, tzinfo=UTC)
quote_time = datetime(2026, 8, 29, 13, 59, tzinfo=UTC)
config = load(Path(sys.argv[1]))
plan = StructurePlan(
    plan_id="plan-approval-001",
    candidate_id="candidate-spy-001",
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
payload = build_mleg_order(
    plan,
    2,
    Decimal("1.2500"),
    client_order_id(plan.plan_id, 2, Decimal("1.2500")),
)
snapshot = AccountSnapshot(
    equity=Decimal("60000.0000"),
    open_position_count=0,
    frozen_config_hash=config.frozen_config_hash,
    snapshot_time=now,
)
token = approve(
    plan,
    payload,
    snapshot,
    config,
    SizingMode.STANDARD,
    expires_at,
    now,
    timedelta(minutes=2),
)
print(json.dumps([
    token.approval_id,
    token.account_snapshot_hash,
    token.order_payload_hash,
]))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script, str(_CONFIG_DIRECTORY)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [
        approval.approval_id,
        approval.account_snapshot_hash,
        approval.order_payload_hash,
    ]


def test_serialized_approval_expiry_agrees_after_restart_at_the_same_boundaries() -> None:
    api = _risk_api()
    approval = _approved_token(api)
    serialized = json.dumps(
        {
            "approval_id": approval.approval_id,
            "plan_id": approval.plan_id,
            "account_snapshot_hash": approval.account_snapshot_hash,
            "order_payload_hash": approval.order_payload_hash,
            "expires_at": approval.expires_at.isoformat(),
            "approved": approval.approved,
            "failed_gates": approval.failed_gates,
        }
    )
    boundaries = (
        _EXPIRES_AT - timedelta(microseconds=1),
        _EXPIRES_AT,
        _EXPIRES_AT + timedelta(microseconds=1),
    )
    expected = [api.is_expired(approval, boundary) for boundary in boundaries]
    script = """
import json
import sys
from datetime import datetime, timedelta

from alphaledger.domain import RiskApproval
from alphaledger.risk.approval import is_expired

raw = json.loads(sys.argv[1])
approval = RiskApproval(
    approval_id=raw["approval_id"],
    plan_id=raw["plan_id"],
    account_snapshot_hash=raw["account_snapshot_hash"],
    order_payload_hash=raw["order_payload_hash"],
    expires_at=datetime.fromisoformat(raw["expires_at"]),
    approved=raw["approved"],
    failed_gates=tuple(raw["failed_gates"]),
)
boundaries = (
    approval.expires_at - timedelta(microseconds=1),
    approval.expires_at,
    approval.expires_at + timedelta(microseconds=1),
)
print(json.dumps([is_expired(approval, boundary) for boundary in boundaries]))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script, serialized],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == expected


def test_too_little_equity_returns_zero_before_any_payload_exists() -> None:
    api = _risk_api()
    config = _frozen_config()

    quantity = api.max_approved_quantity(
        _plan(),
        Decimal("1000.0000"),
        config.risk,
        api.SizingMode.STANDARD,
    )

    assert quantity == 0


def test_every_failed_gate_is_recorded_together_in_one_refused_token() -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()
    unbalanced_legs = [dict(leg) for leg in plan.legs]
    unbalanced_legs[1]["ratio_qty"] = 2
    plan = replace(plan, legs=tuple(unbalanced_legs))
    payload = _payload(plan, quantity=4, limit_price=Decimal("1.2600"))
    snapshot = _snapshot(
        api,
        config,
        open_position_count=config.risk.maximum_concurrent_positions,
        frozen_config_hash="different-config-hash",
    )

    approval = api.approve(
        plan,
        payload,
        snapshot,
        config,
        api.SizingMode.STANDARD,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )

    assert approval.approved is False
    assert set(approval.failed_gates) == {
        api.GATE_ENTRY_LIMIT_BOUND_EXCEEDED,
        api.GATE_QUANTITY_EXCEEDS_APPROVED_CAP,
        api.GATE_UNBALANCED_LEGS,
        api.GATE_CONCURRENT_POSITION_LIMIT,
        api.GATE_CONFIG_HASH_MISMATCH,
    }
    assert len(approval.failed_gates) == 5


def test_smoke_mode_refuses_quantity_that_standard_mode_approves() -> None:
    api = _risk_api()
    config = _frozen_config()
    plan = _plan()
    payload = _payload(plan, quantity=2)
    snapshot = _snapshot(api, config)

    standard = api.approve(
        plan,
        payload,
        snapshot,
        config,
        api.SizingMode.STANDARD,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )
    smoke_test = api.approve(
        plan,
        payload,
        snapshot,
        config,
        api.SizingMode.SMOKE_TEST,
        _EXPIRES_AT,
        _NOW,
        _MAX_SNAPSHOT_AGE,
    )

    assert standard.approved is True
    assert smoke_test.approved is False
    assert smoke_test.failed_gates == (api.GATE_QUANTITY_EXCEEDS_APPROVED_CAP,)
