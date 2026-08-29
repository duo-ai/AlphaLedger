import importlib
import inspect
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType

import pytest

from alphaledger.execution.orders import BrokerOrder, BrokerOrderStatus

_NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


def _lifecycle() -> ModuleType:
    try:
        return importlib.import_module("alphaledger.execution.lifecycle")
    except ModuleNotFoundError:
        pytest.fail("alphaledger.execution.lifecycle must implement the order lifecycle")


def _broker_order(
    client_order_id: str,
    status: BrokerOrderStatus = BrokerOrderStatus.FILLED,
) -> BrokerOrder:
    return BrokerOrder(
        broker_id=f"broker-{client_order_id}",
        client_order_id=client_order_id,
        status=status,
        filled_quantity=Decimal("1") if status is BrokerOrderStatus.FILLED else Decimal("0"),
        created_at=_NOW,
        updated_at=_NOW,
        submitted_at=_NOW,
        filled_at=_NOW if status is BrokerOrderStatus.FILLED else None,
    )


class MemoryLookup:
    def __init__(self, order: BrokerOrder | None) -> None:
        self.order = order
        self.queries: list[str] = []

    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        self.queries.append(client_order_id)
        return self.order


def _subprocess_client_order_id() -> str:
    script = """
from decimal import Decimal
from alphaledger.execution.lifecycle import client_order_id

print(client_order_id("plan-012", 1, Decimal("1.2500")))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_full_order_path_reaches_reconciled_without_skipping_a_state() -> None:
    lifecycle = _lifecycle()
    state = lifecycle.OrderState.PROPOSED
    path = (
        lifecycle.OrderEvent.SUBMITTED,
        lifecycle.OrderEvent.WORKING,
        lifecycle.OrderEvent.PARTIAL,
        lifecycle.OrderEvent.FILLED,
        lifecycle.OrderEvent.CLOSING,
        lifecycle.OrderEvent.RECONCILED,
    )

    observed = []
    for event in path:
        state = lifecycle.transition(state, event)
        observed.append(state.value)

    assert observed == [
        "submitted",
        "working",
        "partial",
        "filled",
        "closing",
        "reconciled",
    ]
    assert lifecycle.is_broker_terminal(lifecycle.OrderState.FILLED)
    assert not lifecycle.is_lifecycle_terminal(lifecycle.OrderState.FILLED)
    assert lifecycle.is_lifecycle_terminal(state)


def test_same_intent_is_stable_across_processes_and_changed_inputs_have_distinct_ids() -> None:
    lifecycle = _lifecycle()

    first = _subprocess_client_order_id()
    second = _subprocess_client_order_id()
    variants = {
        lifecycle.client_order_id("plan-012", 1, Decimal("1.2500")),
        lifecycle.client_order_id("plan-013", 1, Decimal("1.2500")),
        lifecycle.client_order_id("plan-012", 2, Decimal("1.2500")),
        lifecycle.client_order_id("plan-012", 1, Decimal("1.2600")),
    }

    assert first == second
    assert first in variants
    assert len(variants) == 4
    assert len(first) <= 48


def test_cancel_pending_accepts_a_fill_when_cancel_loses_the_race() -> None:
    lifecycle = _lifecycle()
    state = lifecycle.OrderState.WORKING

    state = lifecycle.transition(state, lifecycle.OrderEvent.CANCEL_PENDING)
    state = lifecycle.transition(state, lifecycle.OrderEvent.FILLED)

    assert state is lifecycle.OrderState.FILLED


def test_every_undeclared_transition_raises_and_names_states_and_event() -> None:
    lifecycle = _lifecycle()
    expected = {
        ("proposed", "submitted"): "submitted",
        ("proposed", "rejected"): "rejected",
        ("submitted", "working"): "working",
        ("submitted", "partial"): "partial",
        ("submitted", "filled"): "filled",
        ("submitted", "rejected"): "rejected",
        ("submitted", "canceled"): "canceled",
        ("submitted", "expired"): "expired",
        ("working", "partial"): "partial",
        ("working", "filled"): "filled",
        ("working", "cancel_pending"): "cancel_pending",
        ("working", "canceled"): "canceled",
        ("working", "expired"): "expired",
        ("partial", "filled"): "filled",
        ("partial", "cancel_pending"): "cancel_pending",
        ("partial", "canceled"): "canceled",
        ("partial", "expired"): "expired",
        ("cancel_pending", "canceled"): "canceled",
        ("cancel_pending", "partial"): "partial",
        ("cancel_pending", "filled"): "filled",
        ("filled", "closing"): "closing",
        ("filled", "reconciled"): "reconciled",
        ("rejected", "reconciled"): "reconciled",
        ("canceled", "reconciled"): "reconciled",
        ("expired", "reconciled"): "reconciled",
        ("closing", "reconciled"): "reconciled",
    }

    for current in lifecycle.OrderState:
        for event in lifecycle.OrderEvent:
            key = (current.value, event.value)
            if key in expected:
                assert lifecycle.transition(current, event).value == expected[key]
                continue

            with pytest.raises(ValueError) as error:
                lifecycle.transition(current, event)
            message = str(error.value)
            assert current.value in message
            assert event.value in message
            assert lifecycle.OrderState(event.value).value in message


def test_reconciled_refuses_every_further_transition() -> None:
    lifecycle = _lifecycle()

    for event in lifecycle.OrderEvent:
        with pytest.raises(ValueError, match=rf"reconciled.*{event.value}"):
            lifecycle.transition(lifecycle.OrderState.RECONCILED, event)


def test_ambiguous_submit_queries_once_by_id_and_never_submits_a_second_intent() -> None:
    lifecycle = _lifecycle()
    stable_id = lifecycle.client_order_id("ambiguous-plan", 1, Decimal("1.25"))

    class AmbiguousBroker(MemoryLookup):
        def __init__(self) -> None:
            super().__init__(None)
            self.submissions: list[str] = []

        def submit(self, client_order_id: str) -> None:
            self.submissions.append(client_order_id)

    broker = AmbiguousBroker()
    broker.submit(stable_id)

    state = lifecycle.resolve_ambiguous_submit(broker, stable_id)

    assert state is None
    assert broker.queries == [stable_id]
    assert broker.submissions == [stable_id]


def test_two_invocations_of_one_intent_create_one_broker_intent() -> None:
    lifecycle = _lifecycle()
    stable_id = lifecycle.client_order_id("duplicate-plan", 1, Decimal("0.80"))

    class RecordingBroker(MemoryLookup):
        def __init__(self) -> None:
            super().__init__(None)
            self.submissions: list[str] = []

        def invoke(self) -> object:
            decision = lifecycle.decide_submission(self, stable_id)
            if decision.action is lifecycle.SubmissionAction.SUBMIT:
                self.submissions.append(stable_id)
                self.order = _broker_order(stable_id, BrokerOrderStatus.NEW)
            return decision

    broker = RecordingBroker()

    first = broker.invoke()
    second = broker.invoke()

    assert first.action is lifecycle.SubmissionAction.SUBMIT
    assert second.action is lifecycle.SubmissionAction.ADOPT_EXISTING
    assert second.state is lifecycle.OrderState.WORKING
    assert broker.submissions == [stable_id]
    assert broker.queries == [stable_id, stable_id]


def test_order_state_has_exactly_the_eleven_per_order_members() -> None:
    lifecycle = _lifecycle()
    expected_names = (
        "proposed",
        "rejected",
        "submitted",
        "working",
        "partial",
        "filled",
        "cancel_pending",
        "canceled",
        "expired",
        "closing",
        "reconciled",
    )
    broker_terminal = {"filled", "rejected", "canceled", "expired"}

    assert tuple(state.value for state in lifecycle.OrderState) == expected_names
    assert {
        state.value for state in lifecycle.OrderState if lifecycle.is_broker_terminal(state)
    } == (broker_terminal)
    assert {
        state.value for state in lifecycle.OrderState if lifecycle.is_lifecycle_terminal(state)
    } == {"reconciled"}
    assert not {"disarmed", "ready", "open", "exiting", "closed", "halted"} & set(expected_names)


def test_restart_rebuilds_the_same_state_and_broker_truth_overrides_local_state() -> None:
    lifecycle = _lifecycle()
    recorded_id = lifecycle.client_order_id("restart-plan", 1, Decimal("1.10"))
    broker_order = _broker_order(recorded_id, BrokerOrderStatus.FILLED)
    before_restart = lifecycle.resolve_ambiguous_submit(MemoryLookup(broker_order), recorded_id)
    stale_local_state = lifecycle.OrderState.WORKING

    after_restart = lifecycle.resolve_ambiguous_submit(
        MemoryLookup(broker_order),
        recorded_id,
    )

    assert before_restart is lifecycle.OrderState.FILLED
    assert after_restart is before_restart
    assert after_restart is not stale_local_state


def test_subprocess_rederives_recorded_id_after_crash_before_submission() -> None:
    lifecycle = _lifecycle()
    recorded_before_crash = lifecycle.client_order_id("plan-012", 1, Decimal("1.2500"))

    recovered_after_restart = _subprocess_client_order_id()

    assert recovered_after_restart == recorded_before_crash
    signature = inspect.signature(lifecycle.client_order_id)
    assert tuple(signature.parameters) == ("plan_id", "quantity", "limit_price")
    assert "unique per plan instance" in inspect.getdoc(lifecycle.client_order_id)


def test_unknown_order_state_blocks_entry_and_records_the_no_trade_reason() -> None:
    lifecycle = _lifecycle()
    stable_id = lifecycle.client_order_id("unknown-plan", 1, Decimal("0.50"))
    unknown_order = _broker_order(stable_id, BrokerOrderStatus.UNKNOWN)
    decision = lifecycle.decide_submission(MemoryLookup(unknown_order), stable_id)
    explicitly_unsafe = {
        None,
        lifecycle.OrderState.PROPOSED,
        lifecycle.OrderState.REJECTED,
        lifecycle.OrderState.SUBMITTED,
        lifecycle.OrderState.WORKING,
        lifecycle.OrderState.PARTIAL,
        lifecycle.OrderState.FILLED,
        lifecycle.OrderState.CANCEL_PENDING,
        lifecycle.OrderState.CANCELED,
        lifecycle.OrderState.EXPIRED,
        lifecycle.OrderState.CLOSING,
    }

    assert all(lifecycle.blocks_new_entries(state) for state in explicitly_unsafe)
    assert not lifecycle.blocks_new_entries(lifecycle.OrderState.RECONCILED)
    assert decision.action is lifecycle.SubmissionAction.BLOCK
    assert decision.state is None
    assert decision.reason == "unknown_order_state"
