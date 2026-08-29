import importlib
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType

import pytest

from alphaledger.execution import lifecycle
from alphaledger.execution.lifecycle import (
    OrderState,
    RecordedSubmissionAttempt,
    RecoveryAction,
)
from alphaledger.execution.orders import (
    BrokerOrder,
    BrokerOrderStatus,
    BrokerPosition,
    BrokerPositionSide,
)

_NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)
_FIRST_SYMBOL = "SPY260918C00500000"
_SECOND_SYMBOL = "QQQ260918P00450000"


def _killswitch() -> ModuleType:
    try:
        return importlib.import_module("alphaledger.execution.killswitch")
    except ModuleNotFoundError as error:
        if error.name == "alphaledger.execution.killswitch":
            pytest.fail("alphaledger.execution.killswitch must implement UNIT-017")
        raise


def _equity_state(
    module: ModuleType,
    *,
    session_start: str = "100",
    peak: str = "100",
    current: str = "100",
) -> object:
    return module.EquityState(
        session_start_equity=Decimal(session_start),
        peak_equity=Decimal(peak),
        current_equity=Decimal(current),
        as_of=_NOW,
    )


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


def _recorded_attempt(client_order_id: str) -> RecordedSubmissionAttempt:
    return RecordedSubmissionAttempt(
        client_order_id=client_order_id,
        record_id=f"record-{client_order_id}",
    )


def _target(
    module: ModuleType,
    client_order_id: str,
    symbol: str,
    *,
    recorded_attempt: RecordedSubmissionAttempt | None = None,
) -> object:
    return module.KnownOrder(
        client_order_id=client_order_id,
        recorded_attempt=recorded_attempt or _recorded_attempt(client_order_id),
        local_state=OrderState.CLOSING,
        covered_symbols=frozenset({symbol}),
    )


def _position(symbol: str, signed_quantity: int) -> BrokerPosition:
    return BrokerPosition(
        symbol=symbol,
        signed_quantity=signed_quantity,
        average_entry_price=Decimal("1.25"),
        side=BrokerPositionSide.LONG,
    )


class MemoryBroker:
    def __init__(
        self,
        orders: tuple[BrokerOrder, ...] = (),
        *,
        positions: tuple[BrokerPosition, ...] = (),
        failing_order_ids: frozenset[str] = frozenset(),
        positions_available: bool = True,
    ) -> None:
        self.orders_by_client_id = {order.client_order_id: order for order in orders}
        self.position_snapshot = positions
        self.failing_order_ids = failing_order_ids
        self.positions_available = positions_available
        self.queries: list[str] = []
        self.position_queries = 0

    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        self.queries.append(client_order_id)
        if client_order_id in self.failing_order_ids:
            raise ConnectionError("broker order lookup unavailable")
        return self.orders_by_client_id.get(client_order_id)

    def positions(self) -> tuple[BrokerPosition, ...]:
        self.position_queries += 1
        if not self.positions_available:
            raise ConnectionError("broker positions unavailable")
        return self.position_snapshot


def test_daily_loss_stop_binds_at_its_threshold_and_not_strictly_short() -> None:
    killswitch = _killswitch()
    cases = (
        ("98.51", False),
        ("98.50", True),
        ("98.49", True),
    )

    for current, should_trigger in cases:
        decision = killswitch.evaluate_kill_switch(
            _equity_state(killswitch, current=current),
            daily_loss_stop_fraction=Decimal("0.015"),
            peak_to_valley_fraction=Decimal("0.50"),
        )

        assert (killswitch.DAILY_LOSS_STOP_REASON in decision.reasons) is should_trigger
        assert decision.triggered is should_trigger


def test_peak_to_valley_switch_binds_at_its_threshold_and_not_strictly_short() -> None:
    killswitch = _killswitch()
    cases = (
        ("97.01", False),
        ("97.00", True),
        ("96.99", True),
    )

    for current, should_trigger in cases:
        decision = killswitch.evaluate_kill_switch(
            _equity_state(
                killswitch,
                session_start="80",
                peak="100",
                current=current,
            ),
            daily_loss_stop_fraction=Decimal("1"),
            peak_to_valley_fraction=Decimal("0.03"),
        )

        assert (killswitch.PEAK_TO_VALLEY_KILL_SWITCH_REASON in decision.reasons) is should_trigger
        assert decision.triggered is should_trigger


def test_one_reading_breaching_both_thresholds_reports_each_reason_once() -> None:
    killswitch = _killswitch()

    decision = killswitch.evaluate_kill_switch(
        _equity_state(killswitch, session_start="100", peak="110", current="90"),
        daily_loss_stop_fraction=Decimal("0.10"),
        peak_to_valley_fraction=Decimal("0.15"),
    )

    assert decision.triggered
    assert decision.reasons == (
        killswitch.DAILY_LOSS_STOP_REASON,
        killswitch.PEAK_TO_VALLEY_KILL_SWITCH_REASON,
    )
    assert decision.reasons.count(killswitch.DAILY_LOSS_STOP_REASON) == 1
    assert decision.reasons.count(killswitch.PEAK_TO_VALLEY_KILL_SWITCH_REASON) == 1


def test_every_clean_target_is_resolved_in_order_and_closed_positions_do_not_block() -> None:
    killswitch = _killswitch()
    orders = (_broker_order("close-first"), _broker_order("close-second"))
    broker = MemoryBroker(
        orders,
        positions=(_position(_FIRST_SYMBOL, 0), _position(_SECOND_SYMBOL, 0)),
    )
    targets = (
        _target(killswitch, orders[0].client_order_id, _FIRST_SYMBOL),
        _target(killswitch, orders[1].client_order_id, _SECOND_SYMBOL),
    )

    report = killswitch.flatten(broker, broker, targets)

    assert broker.queries == [order.client_order_id for order in orders]
    assert broker.position_queries == 1
    assert tuple(target.client_order_id for target in report.targets) == tuple(
        order.client_order_id for order in orders
    )
    assert all(target.decision.action is RecoveryAction.ADOPT_EXISTING for target in report.targets)
    assert report.still_open_symbols == frozenset()
    assert report.reasons == ()
    assert not report.blocks_new_entries


def test_equal_value_evaluations_and_flatten_inputs_produce_equal_results() -> None:
    killswitch = _killswitch()
    equity_inputs = (
        _equity_state(killswitch, current="98.5"),
        _equity_state(killswitch, current="98.5"),
    )
    decisions = tuple(
        killswitch.evaluate_kill_switch(
            equity,
            daily_loss_stop_fraction=Decimal("0.015"),
            peak_to_valley_fraction=Decimal("0.03"),
        )
        for equity in equity_inputs
    )
    order = _broker_order("equal-values")
    reports = tuple(
        killswitch.flatten(
            MemoryBroker((order,)),
            MemoryBroker(positions=()),
            (_target(killswitch, order.client_order_id, _FIRST_SYMBOL),),
        )
        for _ in range(2)
    )

    assert decisions[0] == decisions[1]
    assert reports[0] == reports[1]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("session_start_equity", Decimal("0")),
        ("session_start_equity", Decimal("-0.01")),
        ("peak_equity", Decimal("0")),
        ("peak_equity", Decimal("-0.01")),
    ),
)
def test_non_positive_equity_divisors_are_rejected_and_name_the_field(
    field: str,
    value: Decimal,
) -> None:
    killswitch = _killswitch()
    values = {
        "session_start_equity": Decimal("100"),
        "peak_equity": Decimal("100"),
        "current_equity": Decimal("90"),
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        killswitch.EquityState(as_of=_NOW, **values)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("daily_loss_stop_fraction", Decimal("0")),
        ("daily_loss_stop_fraction", Decimal("-0.01")),
        ("daily_loss_stop_fraction", Decimal("1.01")),
        ("peak_to_valley_fraction", Decimal("0")),
        ("peak_to_valley_fraction", Decimal("-0.01")),
        ("peak_to_valley_fraction", Decimal("1.01")),
    ),
)
def test_out_of_range_thresholds_are_rejected_and_name_the_argument(
    field: str,
    value: Decimal,
) -> None:
    killswitch = _killswitch()
    thresholds = {
        "daily_loss_stop_fraction": Decimal("0.015"),
        "peak_to_valley_fraction": Decimal("0.03"),
    }
    thresholds[field] = value

    with pytest.raises(ValueError, match=field):
        killswitch.evaluate_kill_switch(
            _equity_state(killswitch),
            **thresholds,
        )


def test_target_without_a_durable_attempt_blocks_before_adoption() -> None:
    killswitch = _killswitch()
    order = _broker_order("unrecorded-close")
    broker = MemoryBroker((order,))
    target = killswitch.KnownOrder(
        client_order_id=order.client_order_id,
        recorded_attempt=None,
        local_state=OrderState.CLOSING,
        covered_symbols=frozenset({_FIRST_SYMBOL}),
    )

    report = killswitch.flatten(broker, broker, (target,))

    assert report.targets[0].decision.action is RecoveryAction.BLOCK
    assert report.targets[0].decision.reason == lifecycle.SUBMISSION_ATTEMPT_RECORD_REQUIRED_REASON
    assert lifecycle.SUBMISSION_ATTEMPT_RECORD_REQUIRED_REASON in report.reasons
    assert report.blocks_new_entries


def test_filled_close_with_a_nonzero_position_is_not_reported_as_flat() -> None:
    killswitch = _killswitch()
    order = _broker_order("partially-effective-close", BrokerOrderStatus.FILLED)
    broker = MemoryBroker((order,), positions=(_position(_FIRST_SYMBOL, 1),))
    target = _target(killswitch, order.client_order_id, _FIRST_SYMBOL)

    report = killswitch.flatten(broker, broker, (target,))

    assert report.targets[0].decision.action is RecoveryAction.ADOPT_EXISTING
    assert report.targets[0].decision.state is OrderState.FILLED
    assert report.still_open_symbols == frozenset({_FIRST_SYMBOL})
    assert killswitch.POSITION_STILL_OPEN_REASON in report.reasons
    assert report.blocks_new_entries


def test_rejected_close_keeps_its_nonzero_position_reported_as_open() -> None:
    killswitch = _killswitch()
    order = _broker_order("rejected-close", BrokerOrderStatus.REJECTED)
    broker = MemoryBroker((order,), positions=(_position(_FIRST_SYMBOL, -1),))
    target = _target(killswitch, order.client_order_id, _FIRST_SYMBOL)

    report = killswitch.flatten(broker, broker, (target,))

    assert report.targets[0].decision.action is RecoveryAction.ADOPT_EXISTING
    assert report.targets[0].decision.state is OrderState.REJECTED
    assert report.still_open_symbols == frozenset({_FIRST_SYMBOL})
    assert killswitch.POSITION_STILL_OPEN_REASON in report.reasons
    assert report.blocks_new_entries


def test_unavailable_positions_block_and_conservatively_union_target_symbols() -> None:
    killswitch = _killswitch()
    orders = (_broker_order("first-close"), _broker_order("second-close"))
    targets = (
        _target(killswitch, orders[0].client_order_id, _FIRST_SYMBOL),
        _target(killswitch, orders[1].client_order_id, _SECOND_SYMBOL),
    )
    clean_report = killswitch.flatten(
        MemoryBroker(orders),
        MemoryBroker(positions=()),
        targets,
    )

    failed_report = killswitch.flatten(
        MemoryBroker(orders),
        MemoryBroker(positions_available=False),
        targets,
    )

    assert not clean_report.blocks_new_entries
    assert clean_report.still_open_symbols == frozenset()
    assert lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON in failed_report.reasons
    assert failed_report.still_open_symbols == frozenset({_FIRST_SYMBOL, _SECOND_SYMBOL})
    assert failed_report.blocks_new_entries


def test_unavailable_order_lookup_blocks_only_that_target_recovery() -> None:
    killswitch = _killswitch()
    orders = (_broker_order("available-close"), _broker_order("unavailable-close"))
    broker = MemoryBroker(
        orders,
        failing_order_ids=frozenset({orders[1].client_order_id}),
    )
    targets = (
        _target(killswitch, orders[0].client_order_id, _FIRST_SYMBOL),
        _target(killswitch, orders[1].client_order_id, _SECOND_SYMBOL),
    )

    report = killswitch.flatten(broker, broker, targets)

    assert report.targets[0].decision.action is RecoveryAction.ADOPT_EXISTING
    assert report.targets[1].decision.action is RecoveryAction.BLOCK
    assert report.targets[1].decision.reason == lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON
    assert lifecycle.BROKER_TRUTH_UNAVAILABLE_REASON in report.reasons
    assert report.blocks_new_entries


def test_restart_retry_with_equal_materialized_state_returns_the_same_report() -> None:
    killswitch = _killswitch()
    order = _broker_order("restart-close")
    first_target = _target(killswitch, order.client_order_id, _FIRST_SYMBOL)
    restarted_target = _target(killswitch, order.client_order_id, _FIRST_SYMBOL)

    first_report = killswitch.flatten(
        MemoryBroker((order,)),
        MemoryBroker(positions=(_position(_FIRST_SYMBOL, 0),)),
        (first_target,),
    )
    restarted_report = killswitch.flatten(
        MemoryBroker((order,)),
        MemoryBroker(positions=(_position(_FIRST_SYMBOL, 0),)),
        (restarted_target,),
    )

    assert first_report == restarted_report


@pytest.mark.parametrize("current", ("100", "110"))
def test_non_loss_and_fresh_high_equity_readings_never_trigger(current: str) -> None:
    killswitch = _killswitch()

    decision = killswitch.evaluate_kill_switch(
        _equity_state(killswitch, current=current),
        daily_loss_stop_fraction=Decimal("0.015"),
        peak_to_valley_fraction=Decimal("0.03"),
    )

    assert not decision.triggered
    assert decision.reasons == ()


def test_zero_current_equity_remains_representable_for_a_wiped_out_account() -> None:
    killswitch = _killswitch()

    equity = _equity_state(killswitch, current="0")

    assert equity.current_equity == Decimal("0.0000")


def test_empty_targets_and_positions_do_not_block_new_entries() -> None:
    killswitch = _killswitch()
    broker = MemoryBroker()

    report = killswitch.flatten(broker, broker, ())

    assert report.targets == ()
    assert report.still_open_symbols == frozenset()
    assert report.reasons == ()
    assert not report.blocks_new_entries
    assert broker.queries == []
    assert broker.position_queries == 1


def test_recovery_action_has_no_member_that_can_authorize_submission() -> None:
    assert tuple(RecoveryAction.__members__) == ("ADOPT_EXISTING", "BLOCK")
