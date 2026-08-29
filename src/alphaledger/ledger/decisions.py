"""Append-only decisions and durable order facts.

Every write is explicit: callers supply the subject, kind, flat payload, and
UTC instant. The module never captures an environment, exception, request, or
response implicitly, which keeps secret-bearing values outside the ledger
unless a caller deliberately supplies one.

Generic decisions are content-addressed over their complete normalized body.
Submission attempts and order states instead use their semantic payload as the
retry identity, because a restarted caller cannot be required to remember the
instant attached to its first durable write.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, NewType

from alphaledger.data.storage import AppendOnlyStore, StoreCorruptionError
from alphaledger.domain.contracts import require_utc
from alphaledger.execution.lifecycle import OrderState, RecordedSubmissionAttempt

__all__ = [
    "ORDER_STATE_KIND",
    "SUBMISSION_ATTEMPT_KIND",
    "DecisionLedger",
    "LedgerEntry",
    "LedgerEntryId",
    "SubmissionAttemptConflictError",
]

LedgerEntryId = NewType("LedgerEntryId", str)

SUBMISSION_ATTEMPT_KIND: Final[str] = "submission_attempt"
ORDER_STATE_KIND: Final[str] = "order_state"


class SubmissionAttemptConflictError(ValueError):
    """A client order id already names a different submission payload."""


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One immutable projection of a stored ledger entry."""

    entry_id: LedgerEntryId
    subject_id: str
    kind: str
    payload: Mapping[str, str]
    recorded_at: datetime


class DecisionLedger:
    """Append-only decisions and durable order lifecycle facts."""

    def __init__(self, store: AppendOnlyStore) -> None:
        self._store = store

    def record_decision(
        self,
        subject_id: str,
        kind: str,
        payload: Mapping[str, object],
        recorded_at: datetime,
    ) -> LedgerEntryId:
        """Append one generic decision, idempotent over its complete content."""
        subject = _non_blank(subject_id, "subject_id")
        decision_kind = _non_blank(kind, "kind")
        if decision_kind in (SUBMISSION_ATTEMPT_KIND, ORDER_STATE_KIND):
            raise ValueError(
                f"kind {decision_kind!r} is reserved for its typed ledger method; "
                "generic recording would bypass its retry identity"
            )
        values = _payload(payload)
        moment = require_utc(recorded_at, "recorded_at")
        body = _entry_body(subject, decision_kind, values, moment)
        entry_id = LedgerEntryId(_address(body))
        if any(entry.entry_id == entry_id for entry in self.entries_for(subject)):
            return entry_id
        self._append(entry_id, body)
        return entry_id

    def record_submission_attempt(
        self,
        client_order_id: str,
        payload: Mapping[str, object],
        recorded_at: datetime,
    ) -> RecordedSubmissionAttempt:
        """Durably record an attempt before transport, or resolve its retry."""
        subject = _non_blank(client_order_id, "client_order_id")
        values = _payload(payload)
        moment = require_utc(recorded_at, "recorded_at")
        existing = self._submission_entry_for(subject)
        if existing is not None:
            if existing.payload == values:
                return _recorded_attempt(existing)
            raise SubmissionAttemptConflictError(
                f"client_order_id {subject!r} already has submission attempt "
                f"{existing.entry_id}; a different payload cannot replace it"
            )
        entry_id = self._append_new(subject, SUBMISSION_ATTEMPT_KIND, values, moment)
        return RecordedSubmissionAttempt(client_order_id=subject, record_id=entry_id)

    def submission_attempt_for(self, client_order_id: str) -> RecordedSubmissionAttempt | None:
        """Return the one durable attempt for an id, failing on ambiguity."""
        subject = _non_blank(client_order_id, "client_order_id")
        entry = self._submission_entry_for(subject)
        if entry is None:
            return None
        return _recorded_attempt(entry)

    def record_order_state(
        self,
        client_order_id: str,
        state: OrderState,
        recorded_at: datetime,
    ) -> LedgerEntryId:
        """Append a caller-validated state, coalescing an immediate retry."""
        subject = _non_blank(client_order_id, "client_order_id")
        if not isinstance(state, OrderState):
            raise TypeError(f"state must be OrderState; got {type(state).__name__}")
        moment = require_utc(recorded_at, "recorded_at")
        entries = tuple(
            (entry, _order_state(entry))
            for entry in self.entries_for(subject)
            if entry.kind == ORDER_STATE_KIND
        )
        if entries:
            latest_entry, latest_state = entries[-1]
            if latest_state is state:
                return latest_entry.entry_id
        return self._append_new(
            subject,
            ORDER_STATE_KIND,
            MappingProxyType({"state": state.value}),
            moment,
        )

    def latest_order_state_for(self, client_order_id: str) -> OrderState | None:
        """Return the last appended state for an id, independent of timestamps."""
        subject = _non_blank(client_order_id, "client_order_id")
        states = tuple(
            _order_state(entry)
            for entry in self.entries_for(subject)
            if entry.kind == ORDER_STATE_KIND
        )
        if not states:
            return None
        return states[-1]

    def entries_for(self, subject_id: str) -> tuple[LedgerEntry, ...]:
        """Return one subject's complete history in first-recorded order."""
        subject = _non_blank(subject_id, "subject_id")
        entries = tuple(_decode(record) for record in self._store.read_all())
        return tuple(entry for entry in entries if entry.subject_id == subject)

    def _submission_entry_for(self, client_order_id: str) -> LedgerEntry | None:
        attempts = tuple(
            entry
            for entry in self.entries_for(client_order_id)
            if entry.kind == SUBMISSION_ATTEMPT_KIND
        )
        if len(attempts) > 1:
            ids = ", ".join(str(entry.entry_id) for entry in attempts)
            raise StoreCorruptionError(
                f"{client_order_id} has multiple submission attempts ({ids}); "
                "choosing one would make an ambiguous transport retry look safe"
            )
        if not attempts:
            return None
        return attempts[0]

    def _append_new(
        self,
        subject_id: str,
        kind: str,
        payload: Mapping[str, str],
        recorded_at: datetime,
    ) -> LedgerEntryId:
        body = _entry_body(subject_id, kind, payload, recorded_at)
        entry_id = LedgerEntryId(_address(body))
        self._append(entry_id, body)
        return entry_id

    def _append(self, entry_id: LedgerEntryId, body: Mapping[str, object]) -> None:
        self._store.append({"entry_id": entry_id, **body})


def _non_blank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value


def _payload(value: Mapping[str, object]) -> Mapping[str, str]:
    """Normalize the exact scalar forms the ledger can reproduce."""
    if not isinstance(value, Mapping):
        raise TypeError(f"payload must be a mapping; got {type(value).__name__}")
    items = dict(value)
    if not items:
        raise ValueError("payload must not be empty; an empty entry records nothing observable")
    normalized: dict[str, str] = {}
    for key, item in items.items():
        if not isinstance(key, str) or not key.strip():
            raise TypeError("payload keys must be non-blank strings")
        field = f"payload[{key}]"
        if isinstance(item, bool):
            raise TypeError(f"{field} must not be bool; bool is not a ledger integer")
        if isinstance(item, float):
            raise TypeError(f"{field} must not be float; record the exact Decimal or source string")
        if isinstance(item, str | int):
            normalized[key] = str(item)
        elif isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError(f"{field} must be a finite Decimal; got {item!r}")
            normalized[key] = str(item)
        elif isinstance(item, datetime):
            normalized[key] = require_utc(item, field).isoformat()
        else:
            raise TypeError(
                f"{field} must be str, int, Decimal, or datetime; got {type(item).__name__}"
            )
    return MappingProxyType(normalized)


def _entry_body(
    subject_id: str,
    kind: str,
    payload: Mapping[str, str],
    recorded_at: datetime,
) -> dict[str, object]:
    return {
        "subject_id": subject_id,
        "kind": kind,
        "payload": dict(payload),
        "recorded_at": recorded_at.isoformat(),
    }


def _address(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decode(record: Mapping[str, Any]) -> LedgerEntry:
    entry_id = LedgerEntryId(_stored_text(record, "entry_id"))
    subject_id = _stored_text(record, "subject_id")
    kind = _stored_text(record, "kind")
    raw_payload = record.get("payload")
    if not isinstance(raw_payload, dict) or not raw_payload:
        raise StoreCorruptionError(
            f"{entry_id}: a stored ledger entry has no non-empty payload mapping"
        )
    payload: dict[str, str] = {}
    for key, value in raw_payload.items():
        if not isinstance(key, str) or not key.strip():
            raise StoreCorruptionError(f"{entry_id}: a payload key is not a non-blank string")
        if not isinstance(value, str):
            raise StoreCorruptionError(
                f"{entry_id}: payload[{key}] is {type(value).__name__}, not stored text"
            )
        payload[key] = value
    raw_recorded_at = _stored_text(record, "recorded_at")
    try:
        recorded_at = require_utc(datetime.fromisoformat(raw_recorded_at), "recorded_at")
    except (TypeError, ValueError) as exc:
        raise StoreCorruptionError(
            f"{entry_id}: recorded_at is not a timezone-aware timestamp"
        ) from exc
    return LedgerEntry(
        entry_id=entry_id,
        subject_id=subject_id,
        kind=kind,
        payload=MappingProxyType(payload),
        recorded_at=recorded_at,
    )


def _stored_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StoreCorruptionError(f"a stored ledger entry is missing {field}")
    return value


def _recorded_attempt(entry: LedgerEntry) -> RecordedSubmissionAttempt:
    return RecordedSubmissionAttempt(
        client_order_id=entry.subject_id,
        record_id=entry.entry_id,
    )


def _order_state(entry: LedgerEntry) -> OrderState:
    value = entry.payload.get("state")
    if not isinstance(value, str):
        raise StoreCorruptionError(
            f"{entry.entry_id}: an order_state entry has invalid state {value!r}"
        )
    try:
        return OrderState(value)
    except ValueError as exc:
        raise StoreCorruptionError(
            f"{entry.entry_id}: an order_state entry has invalid state {value!r}"
        ) from exc
