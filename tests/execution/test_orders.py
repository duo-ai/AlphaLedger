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
from alphaledger.execution import orders as order_adapter
from alphaledger.execution.orders import (
    DEBIT_CREDIT_SIGN_CONVENTION,
    BrokerOrderStatus,
    OrderAdapterError,
    build_mleg_order,
    canonical_bytes,
    order_payload_hash,
    parse_order,
)


_HASH_MUTATIONS: tuple[tuple[str, object], ...] = (
    ("order_class", "simple"),
    ("qty", "3"),
    ("type", "market"),
    ("limit_price", Decimal("1.2600")),
    ("time_in_force", "gtc"),
    ("client_order_id", "client-debit-002"),
    ("legs", "reverse"),
    ("legs[0].symbol", "SPY260918C00501000"),
    ("legs[0].ratio_qty", "2"),
    ("legs[0].side", "sell"),
    ("legs[0].position_intent", "sell_to_open"),
    ("legs[1].symbol", "SPY260918C00506000"),
    ("legs[1].ratio_qty", "2"),
    ("legs[1].side", "buy"),
    ("legs[1].position_intent", "buy_to_open"),
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


def _documented_trade_activity() -> dict[str, object]:
    return {
        "activity_type": "FILL",
        "cum_qty": "1",
        "id": "20190524113406977::8efc7b9a-8b2b-4000-9955-d36e7db0df74",
        "leaves_qty": "0",
        "price": "1.63",
        "qty": "1",
        "side": "buy",
        "symbol": "LPCN",
        "transaction_time": "2019-05-24T15:34:06.977Z",
        "order_id": "904837e3-3b76-47ec-b432-046db621571b",
        "type": "fill",
    }


def _documented_option_position() -> dict[str, object]:
    return {
        "asset_id": "fe4f43e5-60a4-4269-ba4c-3d304444d58b",
        "symbol": "PTON240126C00000500",
        "exchange": "",
        "asset_class": "us_option",
        "asset_marginable": True,
        "qty": "2",
        "avg_entry_price": "6.05",
        "side": "long",
        "market_value": "1068",
        "cost_basis": "1210",
        "unrealized_pl": "-142",
        "unrealized_plpc": "-0.1173553719008264",
        "unrealized_intraday_pl": "-142",
        "unrealized_intraday_plpc": "-0.1173553719008264",
        "current_price": "5.34",
        "lastday_price": "5.34",
        "change_today": "0",
        "qty_available": "2",
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
        "updated_at": "2026-08-28T17:31:05.987654321+02:00",
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

    for malformed_ratio in ("1_0", " 1", "1 ", "+1", "1.0"):
        plan = _debit_vertical()
        malformed_ratio_leg = dict(plan.legs[0])
        malformed_ratio_leg["ratio_qty"] = malformed_ratio
        object.__setattr__(plan, "legs", (malformed_ratio_leg, plan.legs[1]))
        with pytest.raises(OrderAdapterError, match=r"legs\[0\]\.ratio_qty"):
            build_mleg_order(plan, 1, Decimal("1.2500"), "client-debit-001")


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


def test_invalid_mleg_cardinality_or_duplicate_symbols_is_rejected_before_mapping() -> None:
    plan = _debit_vertical()
    long_leg = dict(plan.legs[0])
    five_distinct_legs = tuple(
        {**long_leg, "symbol": f"SPY260918C{strike:08d}"}
        for strike in (500000, 501000, 502000, 503000, 504000)
    )
    duplicate_leg = {**dict(plan.legs[1]), "symbol": long_leg["symbol"]}

    for legs, message in (
        ((plan.legs[0],), "between 2 and 4"),
        (five_distinct_legs, "between 2 and 4"),
        ((plan.legs[0], duplicate_leg), "unique"),
    ):
        object.__setattr__(plan, "legs", legs)
        with pytest.raises(OrderAdapterError, match=message):
            build_mleg_order(plan, 1, Decimal("1.2500"), "client-debit-001")


def test_truncated_broker_payload_raises_redacted_typed_adapter_error() -> None:
    credential_shaped_value = "credential-shaped-value"
    complete_payload = {
        "id": "4c51a4ba-53f9-4bf2-88a5-6d1c17b8e108",
        "client_order_id": "client-debit-001",
        "status": "new",
        "filled_qty": "0",
        "created_at": "2026-08-28T15:31:02Z",
        "updated_at": None,
        "submitted_at": "2026-08-28T15:31:02Z",
        "filled_at": None,
    }
    malformed_timestamp = {**complete_payload, "created_at": credential_shaped_value}
    non_rfc3339_timestamps = tuple(
        {**complete_payload, "created_at": value}
        for value in (
            "2026-08-28 15:31:02Z",
            "2026-W35-5T15:31:02Z",
            "2026-08-28T15:31:02+00:00:30",
        )
    )
    malformed_quantities = tuple(
        {**complete_payload, "filled_qty": value} for value in ("1_0", " 1", "1 ", "+1", "1e1")
    )
    missing_nullable_timestamps: list[dict[str, object]] = []
    for field in ("updated_at", "submitted_at", "filled_at"):
        truncated = dict(complete_payload)
        del truncated[field]
        missing_nullable_timestamps.append(truncated)
    payloads = (
        {
            "id": "4c51a4ba-53f9-4bf2-88a5-6d1c17b8e108",
            "authorization": credential_shaped_value,
        },
        malformed_timestamp,
        *non_rfc3339_timestamps,
        *malformed_quantities,
        *missing_nullable_timestamps,
    )

    for raw in payloads:
        with pytest.raises(OrderAdapterError) as error:
            parse_order(raw)

        formatted_error = "".join(traceback.format_exception(error.value))
        assert not isinstance(error.value, (KeyError, TypeError))
        assert credential_shaped_value not in formatted_error
        assert "authorization" not in formatted_error


@pytest.mark.parametrize(
    ("path", "replacement"),
    _HASH_MUTATIONS,
    ids=[path for path, _ in _HASH_MUTATIONS],
)
def test_mutating_any_top_level_or_leg_field_changes_the_risk_binding(
    path: str,
    replacement: object,
) -> None:
    payload = _expected_payload()
    before = order_payload_hash(payload)
    mutated = copy.deepcopy(payload)
    legs = cast(list[dict[str, object]], mutated["legs"])
    expected_paths = set(payload)
    expected_paths.update(
        f"legs[{index}].{field}" for index, leg in enumerate(legs) for field in leg
    )
    assert {mutation_path for mutation_path, _ in _HASH_MUTATIONS} == expected_paths

    if path == "legs":
        legs.reverse()
    elif path.startswith("legs["):
        leg_path, field = path.split(".", maxsplit=1)
        leg_index = int(leg_path.removeprefix("legs[").removesuffix("]"))
        legs[leg_index][field] = replacement
    else:
        mutated[path] = replacement

    assert order_payload_hash(mutated) != before


def test_documented_activity_and_position_parse_to_expected_frozen_records() -> None:
    parse_activity = getattr(order_adapter, "parse_activity", None)
    parse_position = getattr(order_adapter, "parse_position", None)
    assert callable(parse_activity), "parse_activity must form the typed restart boundary"
    assert callable(parse_position), "parse_position must form the typed restart boundary"

    activity = parse_activity(_documented_trade_activity())
    position = parse_position(_documented_option_position())

    assert activity.broker_id == "20190524113406977::8efc7b9a-8b2b-4000-9955-d36e7db0df74"
    assert activity.activity_type is order_adapter.BrokerActivityType.FILL
    assert activity.symbol == "LPCN"
    assert activity.signed_quantity == 1
    assert activity.price == Decimal("1.63")
    assert activity.transaction_time == datetime(2019, 5, 24, 15, 34, 6, 977000, tzinfo=UTC)
    assert position.symbol == "PTON240126C00000500"
    assert position.signed_quantity == 2
    assert position.average_entry_price == Decimal("6.05")
    assert position.side is order_adapter.BrokerPositionSide.LONG

    with pytest.raises(FrozenInstanceError):
        activity.price = Decimal("2.00")
    with pytest.raises(FrozenInstanceError):
        position.average_entry_price = Decimal("7.00")


def test_ambiguous_submit_reconstructs_leg_quantities_from_activities_and_positions() -> None:
    parse_activity = getattr(order_adapter, "parse_activity", None)
    parse_position = getattr(order_adapter, "parse_position", None)
    assert callable(parse_activity), "parse_activity must support restart reconciliation"
    assert callable(parse_position), "parse_position must support restart reconciliation"

    long_symbol = "SPY260918C00500000"
    short_symbol = "SPY260918C00505000"
    long_activity = {
        **_documented_trade_activity(),
        "id": "activity-long",
        "symbol": long_symbol,
        "price": "3.40",
    }
    short_activity = {
        **_documented_trade_activity(),
        "id": "activity-short",
        "symbol": short_symbol,
        "side": "sell",
        "price": "2.15",
        "type": "partial_fill",
    }
    long_position = {
        **_documented_option_position(),
        "symbol": long_symbol,
        "qty": "1",
        "avg_entry_price": "3.40",
    }
    short_position = {
        **_documented_option_position(),
        "symbol": short_symbol,
        "qty": "-1",
        "avg_entry_price": "2.15",
        "side": "short",
    }

    activities = tuple(parse_activity(raw) for raw in (long_activity, short_activity))
    positions = tuple(parse_position(raw) for raw in (long_position, short_position))

    activity_quantities = {activity.symbol: activity.signed_quantity for activity in activities}
    position_quantities = {position.symbol: position.signed_quantity for position in positions}
    assert activity_quantities == {long_symbol: 1, short_symbol: -1}
    assert position_quantities == activity_quantities


@pytest.mark.parametrize(
    ("parser_name", "payload_factory", "required_fields"),
    (
        (
            "parse_activity",
            _documented_trade_activity,
            ("id", "type", "symbol", "qty", "price", "side", "transaction_time"),
        ),
        (
            "parse_position",
            _documented_option_position,
            ("symbol", "qty", "avg_entry_price", "side"),
        ),
    ),
)
def test_truncated_activity_or_position_raises_redacted_typed_adapter_error(
    parser_name: str,
    payload_factory: object,
    required_fields: tuple[str, ...],
) -> None:
    parser = getattr(order_adapter, parser_name, None)
    assert callable(parser), f"{parser_name} must form the typed restart boundary"
    assert callable(payload_factory)

    for field in required_fields:
        raw = payload_factory()
        raw["authorization"] = "credential-shaped-value"
        del raw[field]

        with pytest.raises(OrderAdapterError) as error:
            parser(raw)

        formatted_error = "".join(traceback.format_exception(error.value))
        assert not isinstance(error.value, (KeyError, TypeError))
        assert "credential-shaped-value" not in formatted_error
        assert "authorization" not in formatted_error


def test_unrecognised_activity_type_and_position_side_remain_explicit_unknowns() -> None:
    parse_activity = getattr(order_adapter, "parse_activity", None)
    parse_position = getattr(order_adapter, "parse_position", None)
    assert callable(parse_activity), "parse_activity must preserve unknown broker truth"
    assert callable(parse_position), "parse_position must preserve unknown broker truth"
    activity_raw = {**_documented_trade_activity(), "type": "future_fill_type"}
    position_raw = {**_documented_option_position(), "side": "future_position_side"}

    activity = parse_activity(activity_raw)
    position = parse_position(position_raw)

    assert activity.activity_type is order_adapter.BrokerActivityType.UNKNOWN
    assert position.side is order_adapter.BrokerPositionSide.UNKNOWN


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
