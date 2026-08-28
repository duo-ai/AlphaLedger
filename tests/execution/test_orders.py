import copy
import hashlib
import subprocess
import sys
import traceback
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from alphaledger.domain import StructurePlan
from alphaledger.execution.orders import (
    DEBIT_CREDIT_SIGN_CONVENTION,
    BrokerOrderStatus,
    OrderAdapterError,
    build_mleg_order,
    canonical_bytes,
    order_payload_hash,
    parse_order,
)


def _debit_vertical() -> StructurePlan:
    quote_time = datetime(2026, 8, 28, 15, 30, tzinfo=UTC)
    return StructurePlan(
        plan_id="plan-debit-001",
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
        entry_limit_bound=Decimal("1.5000"),
        exact_max_loss=Decimal("150.0000"),
        exact_max_profit=Decimal("350.0000"),
        expiry_breakeven=Decimal("501.5000"),
        quote_times=(quote_time, quote_time),
        stress_pnl={"down": Decimal("-150.0000"), "up": Decimal("350.0000")},
    )


def _expected_payload() -> dict[str, object]:
    return {
        "order_class": "mleg",
        "qty": "2",
        "type": "limit",
        "limit_price": Decimal("1.2500"),
        "time_in_force": "day",
        "client_order_id": "client-debit-001",
        "legs": [
            {
                "symbol": "SPY260918C00500000",
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": "SPY260918C00505000",
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
        ],
    }


def _subprocess_output(script: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def test_two_leg_debit_vertical_maps_field_by_field_to_documented_mleg_payload() -> None:
    payload = build_mleg_order(
        _debit_vertical(),
        quantity=2,
        limit_price=Decimal("1.2500"),
        client_order_id="client-debit-001",
    )

    assert payload == _expected_payload()
    assert DEBIT_CREDIT_SIGN_CONVENTION == {
        "debit": Decimal("1"),
        "credit": Decimal("-1"),
    }


def test_canonical_payload_is_byte_identical_and_hash_identical_across_processes() -> None:
    script = """
from decimal import Decimal
from alphaledger.execution.orders import canonical_bytes, order_payload_hash

payload = {
    "type": "limit",
    "legs": [
        {
            "side": "buy",
            "symbol": "SPY260918C00500000",
            "position_intent": "buy_to_open",
            "ratio_qty": "1",
        },
        {
            "ratio_qty": "1",
            "position_intent": "sell_to_open",
            "symbol": "SPY260918C00505000",
            "side": "sell",
        },
    ],
    "qty": "2",
    "client_order_id": "client-debit-001",
    "time_in_force": "day",
    "order_class": "mleg",
    "limit_price": Decimal("1.2500"),
}
print(canonical_bytes(payload).hex())
print(order_payload_hash(payload))
"""
    first = _subprocess_output(script)
    second = _subprocess_output(script)
    expected_bytes = canonical_bytes(_expected_payload())

    assert first == second
    assert bytes.fromhex(first[0]) == expected_bytes
    assert first[1] == hashlib.sha256(expected_bytes).hexdigest()
    assert b'"limit_price":"1.2500"' in expected_bytes
    assert b'"limit_price":1.25' not in expected_bytes


def test_realistic_filled_order_parses_status_quantity_and_utc_timestamps() -> None:
    raw = {
        "id": "4c51a4ba-53f9-4bf2-88a5-6d1c17b8e108",
        "client_order_id": "client-debit-001",
        "status": "filled",
        "filled_qty": "2",
        "created_at": "2026-08-28T15:31:02.123456789Z",
        "updated_at": "2026-08-28T15:31:05.987654321Z",
        "submitted_at": "2026-08-28T15:31:02.223456789Z",
        "filled_at": "2026-08-28T15:31:05.887654321Z",
        "order_class": "mleg",
        "type": "limit",
        "time_in_force": "day",
        "qty": "2",
        "limit_price": "1.25",
        "legs": [],
    }

    order = parse_order(raw)

    assert order.broker_id == raw["id"]
    assert order.client_order_id == "client-debit-001"
    assert order.status is BrokerOrderStatus.FILLED
    assert order.filled_quantity == Decimal("2")
    assert order.created_at == datetime(2026, 8, 28, 15, 31, 2, 123456, tzinfo=UTC)
    assert order.updated_at == datetime(2026, 8, 28, 15, 31, 5, 987654, tzinfo=UTC)
    assert order.submitted_at == datetime(2026, 8, 28, 15, 31, 2, 223456, tzinfo=UTC)
    assert order.filled_at == datetime(2026, 8, 28, 15, 31, 5, 887654, tzinfo=UTC)
    with pytest.raises(FrozenInstanceError):
        order.status = BrokerOrderStatus.CANCELED  # type: ignore[misc]


def test_float_price_or_nested_leg_value_is_rejected_and_names_the_field() -> None:
    with pytest.raises(OrderAdapterError, match=r"limit_price.*float"):
        build_mleg_order(
            _debit_vertical(),
            quantity=1,
            limit_price=cast(Decimal, 1.25),
            client_order_id="client-debit-001",
        )

    with pytest.raises(OrderAdapterError, match=r"legs\[0\]\.ratio_qty.*float"):
        canonical_bytes({"legs": [{"ratio_qty": 1.0}]})


def test_leg_key_outside_declared_vocabulary_is_rejected_and_names_the_key() -> None:
    plan = _debit_vertical()
    bad_leg = dict(plan.legs[0])
    bad_leg["strike"] = Decimal("500")
    object.__setattr__(plan, "legs", (bad_leg, plan.legs[1]))

    with pytest.raises(OrderAdapterError, match="strike"):
        build_mleg_order(
            plan,
            quantity=1,
            limit_price=Decimal("1.2500"),
            client_order_id="client-debit-001",
        )


def test_truncated_broker_payload_raises_redacted_typed_adapter_error() -> None:
    credential_shaped_value = "credential-shaped-value"
    payloads = (
        {
            "id": "4c51a4ba-53f9-4bf2-88a5-6d1c17b8e108",
            "authorization": credential_shaped_value,
        },
        {
            "id": "4c51a4ba-53f9-4bf2-88a5-6d1c17b8e108",
            "client_order_id": "client-debit-001",
            "status": "new",
            "filled_qty": "0",
            "created_at": credential_shaped_value,
        },
    )

    for raw in payloads:
        with pytest.raises(OrderAdapterError) as error:
            parse_order(raw)

        formatted_error = "".join(traceback.format_exception(error.value))
        assert not isinstance(error.value, (KeyError, TypeError))
        assert credential_shaped_value not in formatted_error
        assert "authorization" not in formatted_error


def test_mutating_one_leg_after_hashing_changes_the_risk_binding() -> None:
    payload = _expected_payload()
    before = order_payload_hash(payload)
    mutated = copy.deepcopy(payload)
    legs = cast(list[dict[str, object]], mutated["legs"])
    legs[0]["symbol"] = "SPY260918C00501000"
    reordered = copy.deepcopy(payload)
    reordered_legs = cast(list[dict[str, object]], reordered["legs"])
    reordered_legs.reverse()

    assert order_payload_hash(mutated) != before
    assert order_payload_hash(reordered) != before


def test_order_hash_survives_restart_when_plan_and_approval_inputs_are_unchanged() -> None:
    payload = build_mleg_order(
        _debit_vertical(),
        quantity=2,
        limit_price=Decimal("1.2500"),
        client_order_id="client-debit-001",
    )
    local_hash = order_payload_hash(payload)
    script = """
from datetime import UTC, datetime
from decimal import Decimal
from alphaledger.domain import StructurePlan
from alphaledger.execution.orders import build_mleg_order, order_payload_hash

quote_time = datetime(2026, 8, 28, 15, 30, tzinfo=UTC)
plan = StructurePlan(
    plan_id="plan-debit-001",
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
    entry_limit_bound=Decimal("1.5000"),
    exact_max_loss=Decimal("150.0000"),
    exact_max_profit=Decimal("350.0000"),
    expiry_breakeven=Decimal("501.5000"),
    quote_times=(quote_time, quote_time),
    stress_pnl={"down": Decimal("-150.0000"), "up": Decimal("350.0000")},
)
payload = build_mleg_order(plan, 2, Decimal("1.2500"), "client-debit-001")
print(order_payload_hash(payload))
"""

    assert len(local_hash) == 64
    assert _subprocess_output(script) == [local_hash]


def test_unrecognised_status_is_explicit_unknown_and_not_any_terminal_result() -> None:
    raw = {
        "id": "4c51a4ba-53f9-4bf2-88a5-6d1c17b8e108",
        "client_order_id": "client-debit-001",
        "status": "future_status_not_known_to_this_adapter",
        "filled_qty": "0",
        "created_at": "2026-08-28T15:31:02Z",
        "updated_at": None,
        "submitted_at": "2026-08-28T15:31:02Z",
        "filled_at": None,
    }

    order = parse_order(raw)
    terminal_statuses = {
        BrokerOrderStatus.FILLED,
        BrokerOrderStatus.CANCELED,
        BrokerOrderStatus.EXPIRED,
        BrokerOrderStatus.REJECTED,
    }

    assert order.status is BrokerOrderStatus.UNKNOWN
    assert order.status not in terminal_statuses
