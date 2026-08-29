"""Append-only decision ledger contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from alphaledger.data.storage import AppendOnlyStore, StoreCorruptionError
from alphaledger.execution.lifecycle import OrderState, RecordedSubmissionAttempt
from alphaledger.ledger.decisions import (
    ORDER_STATE_KIND,
    SUBMISSION_ATTEMPT_KIND,
    DecisionLedger,
    SubmissionAttemptConflictError,
)

T0 = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def a_ledger(tmp_path: Path, name: str = "decisions.jsonl") -> DecisionLedger:
    return DecisionLedger(AppendOnlyStore(tmp_path / name))


# --- success ------------------------------------------------------------


def test_an_identical_decision_retry_returns_one_content_address_and_one_entry(
    tmp_path: Path,
) -> None:
    ledger = a_ledger(tmp_path)

    first = ledger.record_decision("candidate-1", "forecast", {"signal": "up"}, T0)
    second = ledger.record_decision("candidate-1", "forecast", {"signal": "up"}, T0)

    assert first == second
    entries = ledger.entries_for("candidate-1")
    assert len(entries) == 1
    assert entries[0].entry_id == first


def test_a_decision_repeated_at_a_later_instant_remains_a_second_ordered_fact(
    tmp_path: Path,
) -> None:
    ledger = a_ledger(tmp_path)
    later = T0 + timedelta(days=1)

    first = ledger.record_decision("candidate-1", "forecast", {"signal": "up"}, T0)
    second = ledger.record_decision("candidate-1", "forecast", {"signal": "up"}, later)

    assert first != second
    entries = ledger.entries_for("candidate-1")
    assert tuple(entry.recorded_at for entry in entries) == (T0, later)
    assert tuple(entry.entry_id for entry in entries) == (first, second)


def test_a_durably_recorded_submission_attempt_is_immediately_retrievable(
    tmp_path: Path,
) -> None:
    ledger = a_ledger(tmp_path)

    recorded = ledger.record_submission_attempt(
        "client-order-1", {"payload_hash": "sha256:abc"}, T0
    )

    assert recorded == ledger.submission_attempt_for("client-order-1")
    assert isinstance(recorded, RecordedSubmissionAttempt)


def test_the_latest_order_state_follows_append_order_without_hiding_prior_states(
    tmp_path: Path,
) -> None:
    ledger = a_ledger(tmp_path)

    ledger.record_order_state("client-order-1", OrderState.WORKING, T0)
    assert ledger.latest_order_state_for("client-order-1") is OrderState.WORKING

    ledger.record_order_state("client-order-1", OrderState.FILLED, T0 + timedelta(minutes=1))

    assert ledger.latest_order_state_for("client-order-1") is OrderState.FILLED
    assert tuple(entry.payload["state"] for entry in ledger.entries_for("client-order-1")) == (
        OrderState.WORKING.value,
        OrderState.FILLED.value,
    )


def test_decimal_precision_and_a_datetime_instant_round_trip_without_loss(
    tmp_path: Path,
) -> None:
    ledger = a_ledger(tmp_path)
    exact = Decimal("12.34567")
    observed = datetime(2026, 8, 29, 14, 15, tzinfo=timezone(timedelta(hours=2)))

    ledger.record_decision(
        "candidate-1",
        "structure",
        {"exact_value": exact, "observed_at": observed},
        T0,
    )

    [entry] = ledger.entries_for("candidate-1")
    assert Decimal(entry.payload["exact_value"]) == exact
    assert datetime.fromisoformat(entry.payload["observed_at"]) == observed
    assert entry.payload["exact_value"] == "12.34567"
    assert entry.payload["observed_at"] == observed.astimezone(UTC).isoformat()


def test_no_trade_is_a_complete_first_decision_in_an_empty_ledger(tmp_path: Path) -> None:
    ledger = a_ledger(tmp_path)

    entry_id = ledger.record_decision(
        "candidate-1",
        "no_trade",
        {"outcome": "no_trade", "failed_gates": "stale_quote|wide_spread"},
        T0,
    )

    [entry] = ledger.entries_for("candidate-1")
    assert entry.entry_id == entry_id
    assert entry.kind == "no_trade"
    assert entry.payload["outcome"] == "no_trade"


# --- failure ------------------------------------------------------------


def test_a_conflicting_submission_retry_is_refused_without_changing_the_first_attempt(
    tmp_path: Path,
) -> None:
    ledger = a_ledger(tmp_path)
    first = ledger.record_submission_attempt("client-order-1", {"payload_hash": "sha256:first"}, T0)

    with pytest.raises(SubmissionAttemptConflictError):
        ledger.record_submission_attempt(
            "client-order-1",
            {"payload_hash": "sha256:different"},
            T0 + timedelta(minutes=1),
        )

    assert ledger.submission_attempt_for("client-order-1") == first
    assert len(ledger.entries_for("client-order-1")) == 1


@pytest.mark.parametrize("reserved_kind", [SUBMISSION_ATTEMPT_KIND, ORDER_STATE_KIND])
def test_generic_decisions_cannot_bypass_typed_identity_for_reserved_kinds(
    tmp_path: Path,
    reserved_kind: str,
) -> None:
    ledger = a_ledger(tmp_path)

    with pytest.raises(ValueError, match=reserved_kind):
        ledger.record_decision("candidate-1", reserved_kind, {"value": "x"}, T0)

    assert ledger.entries_for("candidate-1") == ()


@pytest.mark.parametrize(
    ("invalid_value", "type_name"),
    [(0.125, "float"), (True, "bool")],
)
def test_inexact_or_boolean_payload_values_are_refused_before_append_naming_the_field(
    tmp_path: Path,
    invalid_value: object,
    type_name: str,
) -> None:
    ledger = a_ledger(tmp_path)

    with pytest.raises(TypeError) as raised:
        ledger.record_decision("candidate-1", "forecast", {"confidence": invalid_value}, T0)

    assert "payload[confidence]" in str(raised.value)
    assert type_name in str(raised.value)
    assert ledger.entries_for("candidate-1") == ()


def test_an_unparseable_store_blocks_every_read_instead_of_becoming_empty(
    tmp_path: Path,
) -> None:
    path = tmp_path / "decisions.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")
    ledger = DecisionLedger(AppendOnlyStore(path))

    with pytest.raises(StoreCorruptionError):
        ledger.entries_for("candidate-1")
    with pytest.raises(StoreCorruptionError):
        ledger.submission_attempt_for("client-order-1")


def test_two_submission_attempt_facts_for_one_id_fail_closed_as_store_corruption(
    tmp_path: Path,
) -> None:
    store = AppendOnlyStore(tmp_path / "decisions.jsonl")
    for entry_id, payload_hash in (("record-1", "sha256:first"), ("record-2", "sha256:second")):
        store.append(
            {
                "entry_id": entry_id,
                "subject_id": "client-order-1",
                "kind": SUBMISSION_ATTEMPT_KIND,
                "payload": {"payload_hash": payload_hash},
                "recorded_at": T0.isoformat(),
            }
        )

    with pytest.raises(StoreCorruptionError):
        DecisionLedger(store).submission_attempt_for("client-order-1")


# --- restart ------------------------------------------------------------


def test_submission_retry_normalizes_semantic_values_and_ignores_the_new_instant(
    tmp_path: Path,
) -> None:
    path = tmp_path / "decisions.jsonl"
    ledger = DecisionLedger(AppendOnlyStore(path))
    payload = {
        "limit_price": Decimal("1.23456"),
        "approved_at": datetime(2026, 8, 29, 14, 0, tzinfo=timezone(timedelta(hours=2))),
    }

    first = ledger.record_submission_attempt("client-order-1", payload, T0)
    second = ledger.record_submission_attempt("client-order-1", payload, T0 + timedelta(minutes=5))

    assert first == second
    assert first.record_id == second.record_id
    assert len(ledger.entries_for("client-order-1")) == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_a_fresh_ledger_recovers_the_exact_pre_transport_attempt_after_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "decisions.jsonl"
    first_process = DecisionLedger(AppendOnlyStore(path))
    recorded = first_process.record_submission_attempt(
        "client-order-1", {"payload_hash": "sha256:abc"}, T0
    )

    restarted = DecisionLedger(AppendOnlyStore(path))

    assert restarted.submission_attempt_for("client-order-1") == recorded


def test_repeating_one_order_state_after_restart_does_not_duplicate_the_fact(
    tmp_path: Path,
) -> None:
    path = tmp_path / "decisions.jsonl"
    first = DecisionLedger(AppendOnlyStore(path)).record_order_state(
        "client-order-1", OrderState.WORKING, T0
    )
    restarted = DecisionLedger(AppendOnlyStore(path))

    second = restarted.record_order_state(
        "client-order-1", OrderState.WORKING, T0 + timedelta(minutes=5)
    )

    assert first == second
    assert len(restarted.entries_for("client-order-1")) == 1


# --- no-trade -----------------------------------------------------------


def test_an_unknown_id_has_empty_projections_without_raising(tmp_path: Path) -> None:
    ledger = a_ledger(tmp_path)

    assert ledger.submission_attempt_for("never-recorded") is None
    assert ledger.latest_order_state_for("never-recorded") is None
    assert ledger.entries_for("never-recorded") == ()


def test_a_no_trade_candidate_needs_no_prior_candidate_entry(tmp_path: Path) -> None:
    ledger = a_ledger(tmp_path)
    ledger.record_decision("unrelated", "forecast", {"signal": "up"}, T0)

    ledger.record_decision(
        "candidate-no-trade",
        "no_trade",
        {"outcome": "no_trade", "failed_gates": "insufficient_edge"},
        T0,
    )

    [entry] = ledger.entries_for("candidate-no-trade")
    assert entry.kind == "no_trade"
    assert entry.payload == {
        "outcome": "no_trade",
        "failed_gates": "insufficient_edge",
    }
