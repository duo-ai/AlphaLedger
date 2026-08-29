import importlib
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType

import pytest

from alphaledger.execution.lifecycle import (
    BROKER_TRUTH_UNAVAILABLE_REASON,
    SUBMISSION_ATTEMPT_RECORD_REQUIRED_REASON,
    OrderState,
    RecordedSubmissionAttempt,
    RecoveryAction,
)
from alphaledger.execution.orders import (
    BrokerActivity,
    BrokerActivityType,
    BrokerOrder,
    BrokerOrderStatus,
    BrokerPosition,
    BrokerPositionSide,
)

_NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)
_OPTION_SYMBOL = "SPY260918C00500000"


def _reconciliation() -> ModuleType:
    try:
        return importlib.import_module("alphaledger.execution.reconcile")
    except ModuleNotFoundError as error:
        if error.name == "alphaledger.execution.reconcile":
            pytest.fail("alphaledger.execution.reconcile must implement broker reconciliation")
        raise


def _broker_order(
    client_order_id: str,
    status: BrokerOrderStatus = BrokerOrderStatus.NEW,
    *,
    broker_id: str | None = None,
) -> BrokerOrder:
    return BrokerOrder(
        broker_id=broker_id or f"broker-{client_order_id}",
        client_order_id=client_order_id,
        status=status,
        filled_quantity=Decimal("1") if status is BrokerOrderStatus.FILLED else Decimal("0"),
        created_at=_NOW,
        updated_at=_NOW,
        submitted_at=_NOW,
        filled_at=_NOW if status is BrokerOrderStatus.FILLED else None,
    )


def _position(symbol: str = _OPTION_SYMBOL) -> BrokerPosition:
    return BrokerPosition(
        symbol=symbol,
        signed_quantity=1,
        average_entry_price=Decimal("1.25"),
        side=BrokerPositionSide.LONG,
    )


def _activity(symbol: str, order_id: str) -> BrokerActivity:
    return BrokerActivity(
        broker_id=f"activity-{order_id}",
        order_id=order_id,
        activity_type=BrokerActivityType.FILL,
        symbol=symbol,
        signed_quantity=1,
        price=Decimal("1.25"),
        transaction_time=_NOW,
    )


def _recorded_attempt(client_order_id: str) -> RecordedSubmissionAttempt:
    return RecordedSubmissionAttempt(
        client_order_id=client_order_id,
        record_id=f"record-{client_order_id}",
    )


def _known_order(
    module: ModuleType,
    client_order_id: str,
    *,
    local_state: OrderState | None = OrderState.SUBMITTED,
    recorded_attempt: RecordedSubmissionAttempt | None = None,
    covered_symbols: frozenset[str] = frozenset(),
) -> object:
    return module.KnownOrder(
        client_order_id=client_order_id,
        recorded_attempt=recorded_attempt or _recorded_attempt(client_order_id),
        local_state=local_state,
        covered_symbols=covered_symbols,
    )


class MemoryBroker:
    def __init__(
        self,
        orders: tuple[BrokerOrder, ...] = (),
        *,
        open_orders: tuple[BrokerOrder, ...] = (),
        positions: tuple[BrokerPosition, ...] = (),
        activities: tuple[BrokerActivity, ...] = (),
        failing_boundary: str | None = None,
    ) -> None:
        self.orders_by_client_id = {order.client_order_id: order for order in orders}
        self.open_order_snapshot = open_orders
        self.position_snapshot = positions
        self.activity_snapshot = activities
        self.failing_boundary = failing_boundary
        self.queries: list[str] = []

    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        self.queries.append(client_order_id)
        if self.failing_boundary == "order_lookup":
            raise ConnectionError("broker order lookup unavailable")
        return self.orders_by_client_id.get(client_order_id)

    def open_orders(self) -> tuple[BrokerOrder, ...]:
        if self.failing_boundary == "open_orders":
            raise ConnectionError("broker open orders unavailable")
        return self.open_order_snapshot

    def positions(self) -> tuple[BrokerPosition, ...]:
        if self.failing_boundary == "positions":
            raise ConnectionError("broker positions unavailable")
        return self.position_snapshot

    def activities(self) -> tuple[BrokerActivity, ...]:
        if self.failing_boundary == "activities":
            raise ConnectionError("broker activities unavailable")
        return self.activity_snapshot


def test_three_known_orders_are_resolved_independently_in_input_order() -> None:
    reconciliation = _reconciliation()
    orders = (
        _broker_order("known-working", BrokerOrderStatus.NEW),
        _broker_order("known-partial", BrokerOrderStatus.PARTIALLY_FILLED),
        _broker_order("known-filled", BrokerOrderStatus.FILLED),
    )
    position = _position()
    broker = MemoryBroker(
        orders,
        open_orders=orders[:2],
        positions=(position,),
        activities=(_activity(position.symbol, orders[0].broker_id),),
    )
    known_orders = (
        _known_order(
            reconciliation,
            orders[0].client_order_id,
            covered_symbols=frozenset({position.symbol}),
        ),
        _known_order(reconciliation, orders[1].client_order_id),
        _known_order(reconciliation, orders[2].client_order_id),
    )

    report = reconciliation.reconcile(broker, broker, known_orders)

    assert tuple(item.client_order_id for item in report.orders) == tuple(
        order.client_order_id for order in orders
    )
    assert tuple(item.decision.state for item in report.orders) == (
        OrderState.WORKING,
        OrderState.PARTIAL,
        OrderState.FILLED,
    )
    assert all(item.decision.action is RecoveryAction.ADOPT_EXISTING for item in report.orders)
    assert report.unexplained_orders == ()
    assert report.unexplained_positions == ()


def test_open_order_without_matching_known_order_is_reported_by_specific_reason() -> None:
    reconciliation = _reconciliation()
    known_broker_order = _broker_order("known-order", BrokerOrderStatus.FILLED)
    unexplained_broker_order = _broker_order("outside-order", BrokerOrderStatus.NEW)
    broker = MemoryBroker(
        (known_broker_order,),
        open_orders=(unexplained_broker_order,),
    )
    known_orders = (_known_order(reconciliation, known_broker_order.client_order_id),)

    report = reconciliation.reconcile(broker, broker, known_orders)

    assert report.unexplained_orders == (
        reconciliation.UnexplainedOrder(
            order=unexplained_broker_order,
            reason=reconciliation.UNEXPLAINED_ORDER_REASON,
        ),
    )
    assert reconciliation.UNEXPLAINED_ORDER_REASON == "unexplained_order"
    assert reconciliation.UNEXPLAINED_ORDER_REASON in report.reasons


def test_known_order_without_durable_attempt_blocks_before_adoption() -> None:
    reconciliation = _reconciliation()
    broker_order = _broker_order("unrecorded-order", BrokerOrderStatus.NEW)
    broker = MemoryBroker((broker_order,))
    known_order = reconciliation.KnownOrder(
        client_order_id=broker_order.client_order_id,
        recorded_attempt=None,
        local_state=OrderState.SUBMITTED,
        covered_symbols=frozenset(),
    )

    report = reconciliation.reconcile(broker, broker, (known_order,))

    assert report.orders[0].decision.action is RecoveryAction.BLOCK
    assert report.orders[0].decision.reason == SUBMISSION_ATTEMPT_RECORD_REQUIRED_REASON
    assert SUBMISSION_ATTEMPT_RECORD_REQUIRED_REASON in report.reasons
    assert report.blocks_new_entries


def test_open_orders_failure_is_not_treated_as_an_empty_snapshot() -> None:
    reconciliation = _reconciliation()
    broker = MemoryBroker(failing_boundary="open_orders")

    report = reconciliation.reconcile(broker, broker, ())

    assert BROKER_TRUTH_UNAVAILABLE_REASON in report.reasons
    assert report.blocks_new_entries


def test_positions_failure_is_not_treated_as_an_empty_snapshot() -> None:
    reconciliation = _reconciliation()
    broker = MemoryBroker(failing_boundary="positions")

    report = reconciliation.reconcile(broker, broker, ())

    assert BROKER_TRUTH_UNAVAILABLE_REASON in report.reasons
    assert report.blocks_new_entries


def test_activities_failure_is_reached_for_a_covered_position_and_blocks() -> None:
    reconciliation = _reconciliation()
    broker_order = _broker_order("covered-order", BrokerOrderStatus.FILLED)
    position = _position()
    broker = MemoryBroker(
        (broker_order,),
        positions=(position,),
        failing_boundary="activities",
    )
    known_orders = (
        _known_order(
            reconciliation,
            broker_order.client_order_id,
            covered_symbols=frozenset({position.symbol}),
        ),
    )

    report = reconciliation.reconcile(broker, broker, known_orders)

    assert BROKER_TRUTH_UNAVAILABLE_REASON in report.reasons
    assert report.blocks_new_entries


def test_order_lookup_failure_with_known_order_blocks_on_unavailable_truth() -> None:
    reconciliation = _reconciliation()
    broker = MemoryBroker(failing_boundary="order_lookup")
    known_orders = (_known_order(reconciliation, "lookup-failure"),)

    report = reconciliation.reconcile(broker, broker, known_orders)

    assert report.orders[0].decision.action is RecoveryAction.BLOCK
    assert report.orders[0].decision.reason == BROKER_TRUTH_UNAVAILABLE_REASON
    assert BROKER_TRUTH_UNAVAILABLE_REASON in report.reasons


def test_position_without_symbol_coverage_is_reported_as_unexplained() -> None:
    reconciliation = _reconciliation()
    position = _position("QQQ260918P00450000")
    broker = MemoryBroker(positions=(position,))

    report = reconciliation.reconcile(broker, broker, ())

    assert report.unexplained_positions == (
        reconciliation.UnexplainedPosition(
            position=position,
            reason=reconciliation.UNEXPLAINED_POSITION_REASON,
        ),
    )
    assert reconciliation.UNEXPLAINED_POSITION_REASON == "unexplained_position"
    assert reconciliation.UNEXPLAINED_POSITION_REASON in report.reasons


def test_covered_position_attributed_to_different_broker_order_is_unexplained() -> None:
    reconciliation = _reconciliation()
    broker_order = _broker_order("known-position-order", BrokerOrderStatus.FILLED)
    position = _position()
    mismatched_activity = _activity(position.symbol, "different-broker-order")
    broker = MemoryBroker(
        (broker_order,),
        positions=(position,),
        activities=(mismatched_activity,),
    )
    known_orders = (
        _known_order(
            reconciliation,
            broker_order.client_order_id,
            covered_symbols=frozenset({position.symbol}),
        ),
    )

    report = reconciliation.reconcile(broker, broker, known_orders)

    assert report.unexplained_positions == (
        reconciliation.UnexplainedPosition(
            position=position,
            reason=reconciliation.UNEXPLAINED_POSITION_REASON,
        ),
    )
    assert reconciliation.UNEXPLAINED_POSITION_REASON in report.reasons


def test_restart_prefers_filled_broker_truth_over_working_local_state() -> None:
    reconciliation = _reconciliation()
    broker_order = _broker_order("restart-filled", BrokerOrderStatus.FILLED)
    broker = MemoryBroker((broker_order,))
    known_orders = (
        _known_order(
            reconciliation,
            broker_order.client_order_id,
            local_state=OrderState.WORKING,
        ),
    )

    report = reconciliation.reconcile(broker, broker, known_orders)

    assert report.orders[0].decision.state is OrderState.FILLED


def test_restart_replaces_reconciled_local_belief_with_working_broker_truth() -> None:
    reconciliation = _reconciliation()
    broker_order = _broker_order("restart-working", BrokerOrderStatus.NEW)
    broker = MemoryBroker((broker_order,))
    known_orders = (
        _known_order(
            reconciliation,
            broker_order.client_order_id,
            local_state=OrderState.RECONCILED,
        ),
    )

    report = reconciliation.reconcile(broker, broker, known_orders)

    assert report.orders[0].decision.state is OrderState.WORKING
    assert report.orders[0].decision.state is not OrderState.RECONCILED


def test_startup_and_scheduled_cycle_with_equal_inputs_produce_equal_reports() -> None:
    reconciliation = _reconciliation()
    broker_orders = (
        _broker_order("cycle-working", BrokerOrderStatus.NEW),
        _broker_order("cycle-partial", BrokerOrderStatus.PARTIALLY_FILLED),
        _broker_order("cycle-filled", BrokerOrderStatus.FILLED),
    )
    known_orders = tuple(
        _known_order(reconciliation, order.client_order_id) for order in broker_orders
    )

    startup_report = reconciliation.reconcile(
        MemoryBroker(tuple(broker_orders)),
        MemoryBroker(tuple(broker_orders)),
        tuple(known_orders),
    )
    scheduled_report = reconciliation.reconcile(
        MemoryBroker(tuple(broker_orders)),
        MemoryBroker(tuple(broker_orders)),
        tuple(known_orders),
    )

    assert startup_report == scheduled_report


def test_empty_broker_and_local_snapshots_permit_new_entries() -> None:
    reconciliation = _reconciliation()
    broker = MemoryBroker()

    report = reconciliation.reconcile(broker, broker, ())

    assert report.orders == ()
    assert report.unexplained_orders == ()
    assert report.unexplained_positions == ()
    assert not report.blocks_new_entries
    assert report.reasons == ()


@pytest.mark.parametrize(
    ("status", "expected_state"),
    (
        (BrokerOrderStatus.ACCEPTED, OrderState.SUBMITTED),
        (BrokerOrderStatus.NEW, OrderState.WORKING),
        (BrokerOrderStatus.PARTIALLY_FILLED, OrderState.PARTIAL),
        (BrokerOrderStatus.FILLED, OrderState.FILLED),
        (BrokerOrderStatus.PENDING_CANCEL, OrderState.CANCEL_PENDING),
        (BrokerOrderStatus.CANCELED, OrderState.CANCELED),
        (BrokerOrderStatus.EXPIRED, OrderState.EXPIRED),
        (BrokerOrderStatus.REJECTED, OrderState.REJECTED),
    ),
)
def test_each_adopted_broker_state_blocks_until_locally_reconciled(
    status: BrokerOrderStatus,
    expected_state: OrderState,
) -> None:
    reconciliation = _reconciliation()
    broker_order = _broker_order("unfinished-order", status)
    broker = MemoryBroker((broker_order,))
    known_orders = (_known_order(reconciliation, broker_order.client_order_id),)

    report = reconciliation.reconcile(broker, broker, known_orders)

    assert report.orders[0].decision.action is RecoveryAction.ADOPT_EXISTING
    assert report.orders[0].decision.state is expected_state
    assert reconciliation.ORDER_NOT_RECONCILED_REASON == "order_not_reconciled"
    assert reconciliation.ORDER_NOT_RECONCILED_REASON in report.reasons
    assert report.blocks_new_entries
