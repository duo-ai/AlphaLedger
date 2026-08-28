"""Record raw observations under the point-in-time timestamp contract.

Design section 4 requires six fields on every observation: `event_time`,
`first_seen_time`, `source_time`, `received_time`, `feed`, and `as_of`.
`ObservationTimestamps` holds them and enforces exactly one ordering,
`first_seen_time >= source_time`. D-014 leaves every other ordering to this
module, because only an adapter knows what a given feed's timestamps mean.

The orderings enforced here, and why each one is a rule rather than a
preference:

1. `first_seen_time >= source_time`, every feed. Observing a record before its
   source emitted it is impossible. Checked here as well as in the domain type
   so the rejection names the field and the feed.
2. `received_time >= source_time`, every feed. `received_time` is either a live
   arrival or a backfill fetch, and both happen after emission. A feed that
   genuinely violates this has a clock problem worth stopping for rather than
   absorbing.
3. `first_seen_time <= as_of`, every feed. `as_of` is the knowledge cutoff the
   record is filed under. A record first seen after it was not knowable then,
   and admitting one would put a future observation inside a point-in-time
   snapshot.
4. `event_time <= first_seen_time`, unless the feed's policy declares that it
   publishes scheduled events. This is the exception D-014 names: an earnings
   date is known weeks ahead, so a calendar feed sets
   `event_time_may_follow_first_seen`, and a bar feed never does.
5. `first_seen_time >= received_time` for a feed that proves delivery. Claiming
   a record was available before it arrived is a leak with a plausible looking
   timestamp.

Where a feed cannot prove delivery, `first_seen_time` is not accepted from the
caller at all. It is derived as `source_time` plus the feed's documented
availability lag, and the record carries `availability_lag_applied` so that a
later audit can tell a proven arrival from a conservative estimate.

Reads are `as_of` queries. There is deliberately no interface returning a
record by wall clock time, because that is the shape of a leak.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, NewType

from alphaledger.data.storage import AppendOnlyStore, StoreCorruptionError
from alphaledger.domain.contracts import ObservationTimestamps, require_utc

__all__ = [
    "AVAILABILITY_LAG_APPLIED",
    "FeedPolicy",
    "Observation",
    "ObservationId",
    "ObservationRejectedError",
    "RawObservation",
    "Recorder",
]

ObservationId = NewType("ObservationId", str)

# Set when `first_seen_time` is an estimate derived from a published time plus
# a conservative buffer, rather than a delivery time the feed proved.
AVAILABILITY_LAG_APPLIED = "availability_lag_applied"

_TIMESTAMP_FIELDS = ("event_time", "first_seen_time", "source_time", "received_time", "as_of")


class ObservationRejectedError(ValueError):
    """An observation was refused, naming the field that made it impossible.

    The field is part of the contract, not decoration. A rejection that says
    only "invalid observation" leaves the caller to guess which timestamp
    carried the look-ahead, and guessing is how a leak survives a fix.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


@dataclass(frozen=True, slots=True)
class FeedPolicy:
    """What one feed's timestamps are known to mean.

    Registered explicitly per feed. An unregistered feed is rejected rather
    than handled by a default, because a default would be an assumption about
    semantics nobody checked.
    """

    feed: str
    proves_delivery_time: bool
    availability_lag: timedelta
    event_time_may_follow_first_seen: bool

    def __post_init__(self) -> None:
        if not self.feed.strip():
            raise ValueError("feed must identify the source; it is never defaulted")
        if self.availability_lag < timedelta(0):
            raise ValueError(
                f"availability_lag must not be negative; got {self.availability_lag}. "
                "A negative buffer would move availability earlier than publication"
            )
        if self.proves_delivery_time and self.availability_lag != timedelta(0):
            raise ValueError(
                f"feed {self.feed!r} proves delivery time, so an availability lag has "
                "nothing to estimate; record the proven arrival instead"
            )
        if not self.proves_delivery_time and self.availability_lag == timedelta(0):
            raise ValueError(
                f"feed {self.feed!r} cannot prove delivery time, so it needs a positive "
                "availability lag; a zero buffer is not a conservative estimate"
            )


@dataclass(frozen=True, slots=True)
class RawObservation:
    """One observation as an adapter received it, before validation.

    `first_seen_time` is optional because only a feed that proves delivery may
    supply it. For every other feed the recorder derives it, so that an
    optimistic value cannot enter the record at all.
    """

    feed: str
    subject_id: str
    event_time: datetime
    source_time: datetime
    received_time: datetime
    as_of: datetime
    payload: Mapping[str, object]
    first_seen_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    """A validated, persisted observation."""

    observation_id: ObservationId
    subject_id: str
    timestamps: ObservationTimestamps
    payload: Mapping[str, str]
    quality_flags: tuple[str, ...]
    availability_lag_seconds: int


class Recorder:
    """Append-only writer and point-in-time reader for raw observations."""

    def __init__(self, store: AppendOnlyStore, policies: Iterable[FeedPolicy]) -> None:
        registry: dict[str, FeedPolicy] = {}
        for policy in policies:
            if policy.feed in registry:
                raise ValueError(f"feed {policy.feed!r} is registered twice with two policies")
            registry[policy.feed] = policy
        if not registry:
            raise ValueError(
                "a recorder needs at least one feed policy; with none, every "
                "observation would be rejected as unregistered"
            )
        self._store = store
        self._policies: Mapping[str, FeedPolicy] = MappingProxyType(registry)
        # Rebuilt from the file rather than carried in memory, so a restart
        # cannot re-append what an earlier process already recorded. It is a
        # snapshot taken at construction: a second process appending to the
        # same store afterwards is not seen, which is the concurrent-writer
        # case this unit does not claim to support.
        self._recorded = {_stored_text(record, "observation_id") for record in store.read_all()}
        # Reading the whole history at construction couples the write path to
        # store integrity: a store with an unreadable line can no longer be
        # opened at all, where before the fix it could still be appended to.
        # That is deliberate. Truncating to the last readable record would
        # reopen the hole the raise exists to close.

    def record(self, observation: RawObservation) -> ObservationId:
        """Validate and append one observation, returning its content address.

        Nothing is written until every check has passed, so a rejected
        observation leaves no trace to be read back later.

        Recording the same observation twice writes one record. The address is
        the content, so a retry after an ambiguous write records the same fact
        rather than a second one, while a revision differs in at least one
        field and is stored separately.
        """
        policy = self._policy_for(observation.feed)
        if not observation.subject_id.strip():
            raise ObservationRejectedError(
                "subject_id",
                "must name what was observed, so a revision can be tied to its original",
            )
        event_time = _utc(observation.event_time, "event_time")
        source_time = _utc(observation.source_time, "source_time")
        received_time = _utc(observation.received_time, "received_time")
        as_of = _utc(observation.as_of, "as_of")
        payload = _payload(observation.payload)
        first_seen_time, flags, lag_seconds = _availability(policy, observation, source_time)

        _check_ordering(
            policy=policy,
            event_time=event_time,
            first_seen_time=first_seen_time,
            source_time=source_time,
            received_time=received_time,
            as_of=as_of,
        )

        timestamps = ObservationTimestamps(
            event_time=event_time,
            first_seen_time=first_seen_time,
            source_time=source_time,
            received_time=received_time,
            feed=policy.feed,
            as_of=as_of,
        )
        body: dict[str, Any] = {
            "feed": timestamps.feed,
            "subject_id": observation.subject_id,
            "event_time": timestamps.event_time.isoformat(),
            "first_seen_time": timestamps.first_seen_time.isoformat(),
            "source_time": timestamps.source_time.isoformat(),
            "received_time": timestamps.received_time.isoformat(),
            "as_of": timestamps.as_of.isoformat(),
            "availability_lag_seconds": lag_seconds,
            "quality_flags": list(flags),
            "payload": dict(payload),
        }
        observation_id = _address(body)
        if observation_id in self._recorded:
            return observation_id
        self._store.append({"observation_id": observation_id, **body})
        self._recorded.add(observation_id)
        return observation_id

    def read_as_of(
        self,
        as_of: datetime,
        *,
        feed: str | None = None,
        subject_id: str | None = None,
    ) -> tuple[Observation, ...]:
        """Every observation first seen at or before `as_of`, in record order.

        An empty result is an answer. It is never replaced by the most recent
        record, because a caller that asked what was knowable at an instant
        would then silently receive something knowable only later.

        A `feed` filter is checked against the registry and against the feeds
        the store actually holds. A typo belonging to neither is rejected
        rather than answered with that same empty result, while a feed present
        on disk stays queryable by a reader that does not write under it. The
        store is the evidence ledger; what it holds does not stop being
        readable because one instance's write registry is narrower.
        """
        cutoff = _utc(as_of, "as_of")
        if feed is not None and not feed.strip():
            raise ObservationRejectedError(
                "feed", "must identify the source; it is never defaulted"
            )
        stored_feeds: set[str] = set()
        visible: list[Observation] = []
        for record in self._store.read_all():
            observation = _decode(record)
            stored_feeds.add(observation.timestamps.feed)
            if observation.timestamps.first_seen_time > cutoff:
                continue
            if feed is not None and observation.timestamps.feed != feed:
                continue
            if subject_id is not None and observation.subject_id != subject_id:
                continue
            visible.append(observation)
        if feed is not None and feed not in self._policies and feed not in stored_feeds:
            known = ", ".join(sorted(set(self._policies) | stored_feeds)) or "none"
            raise ObservationRejectedError(
                "feed",
                f"{feed!r} is neither a registered feed nor present anywhere in the "
                f"store, so an empty result would report a typo as an absence of "
                f"evidence; known feeds: {known}",
            )
        return tuple(visible)

    def _policy_for(self, feed: str) -> FeedPolicy:
        if not feed.strip():
            raise ObservationRejectedError(
                "feed", "must identify the source; it is never defaulted"
            )
        policy = self._policies.get(feed)
        if policy is None:
            known = ", ".join(sorted(self._policies)) or "none"
            raise ObservationRejectedError(
                "feed",
                f"{feed!r} has no registered policy, so its timestamp semantics are "
                f"unknown and cannot be assumed; registered feeds: {known}",
            )
        return policy


def _utc(value: object, field: str) -> datetime:
    """Reject a naive or non-datetime value as an `ObservationRejectedError`."""
    try:
        return require_utc(value, field)
    except (TypeError, ValueError) as exc:
        raise ObservationRejectedError(field, str(exc)) from exc


def _payload(value: Mapping[str, object]) -> Mapping[str, str]:
    """Copy the raw payload, allowing only the strings the feed returned.

    A parsed number does not belong in a raw record. A float in particular is
    rejected: a price is money, and `alphaledger.domain.contracts.money`
    refuses floats for the same reason.
    """
    items = dict(value)
    if not items:
        raise ObservationRejectedError(
            "payload", "an observation with an empty payload records nothing observable"
        )
    out: dict[str, str] = {}
    for key, item in items.items():
        field = f"payload[{key}]"
        if isinstance(item, float):
            raise ObservationRejectedError(
                field,
                f"must not be float; a price is money and a binary float is not exact. "
                f"Store the string the feed returned; got {item!r}",
            )
        if isinstance(item, bool) or not isinstance(item, str):
            raise ObservationRejectedError(
                field,
                f"must be the string the feed returned, not {type(item).__name__}; "
                "parsing belongs in a feature, not in the raw record",
            )
        out[str(key)] = item
    return MappingProxyType(out)


def _availability(
    policy: FeedPolicy, observation: RawObservation, source_time: datetime
) -> tuple[datetime, tuple[str, ...], int]:
    """Resolve `first_seen_time` for this feed, with its flags and lag."""
    supplied = observation.first_seen_time
    if policy.proves_delivery_time:
        if supplied is None:
            raise ObservationRejectedError(
                "first_seen_time",
                f"feed {policy.feed!r} proves delivery time, so the arrival must be "
                "recorded; it is never defaulted",
            )
        return _utc(supplied, "first_seen_time"), (), 0
    if supplied is not None:
        raise ObservationRejectedError(
            "first_seen_time",
            f"feed {policy.feed!r} cannot prove delivery time, so availability is "
            f"derived as source_time plus the documented {policy.availability_lag} lag. "
            "Supplying one would assert knowledge the feed does not have",
        )
    lag_seconds = int(policy.availability_lag.total_seconds())
    return source_time + policy.availability_lag, (AVAILABILITY_LAG_APPLIED,), lag_seconds


def _check_ordering(
    *,
    policy: FeedPolicy,
    event_time: datetime,
    first_seen_time: datetime,
    source_time: datetime,
    received_time: datetime,
    as_of: datetime,
) -> None:
    """Apply the four universal orderings and the one feed-aware exception."""
    if first_seen_time < source_time:
        raise ObservationRejectedError(
            "first_seen_time",
            f"{first_seen_time.isoformat()} precedes source_time "
            f"{source_time.isoformat()}, which would mean observing a record before "
            "its source emitted it",
        )
    if received_time < source_time:
        raise ObservationRejectedError(
            "received_time",
            f"{received_time.isoformat()} precedes source_time "
            f"{source_time.isoformat()}; a record cannot arrive before it was emitted",
        )
    if policy.proves_delivery_time and first_seen_time < received_time:
        raise ObservationRejectedError(
            "first_seen_time",
            f"{first_seen_time.isoformat()} precedes received_time "
            f"{received_time.isoformat()} on a feed that proves delivery; the record "
            "was not available before it arrived",
        )
    if first_seen_time > as_of:
        raise ObservationRejectedError(
            "first_seen_time",
            f"{first_seen_time.isoformat()} is later than as_of {as_of.isoformat()}, "
            "so the record was not knowable at the instant it is filed under",
        )
    if event_time > first_seen_time and not policy.event_time_may_follow_first_seen:
        raise ObservationRejectedError(
            "event_time",
            f"{event_time.isoformat()} is later than first_seen_time "
            f"{first_seen_time.isoformat()}, and feed {policy.feed!r} reports events "
            "that have already happened. A feed that publishes scheduled events must "
            "declare event_time_may_follow_first_seen",
        )


def _address(body: Mapping[str, Any]) -> ObservationId:
    """Content address every field of the record except the address itself.

    Two identical observations get one identifier and a revision gets its own,
    which is what keeps an original and its correction distinguishable.
    """
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return ObservationId(hashlib.sha256(canonical.encode("utf-8")).hexdigest())


def _decode(record: Mapping[str, Any]) -> Observation:
    """Rebuild an observation from a stored record."""
    timestamps = ObservationTimestamps(
        event_time=_stored_time(record, "event_time"),
        first_seen_time=_stored_time(record, "first_seen_time"),
        source_time=_stored_time(record, "source_time"),
        received_time=_stored_time(record, "received_time"),
        feed=_stored_text(record, "feed"),
        as_of=_stored_time(record, "as_of"),
    )
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise StoreCorruptionError("a stored record has no payload mapping")
    flags = record.get("quality_flags")
    if not isinstance(flags, list):
        raise StoreCorruptionError("a stored record has no quality_flags list")
    lag = record.get("availability_lag_seconds")
    if not isinstance(lag, int) or isinstance(lag, bool):
        raise StoreCorruptionError("a stored record has no availability_lag_seconds")
    return Observation(
        observation_id=ObservationId(_stored_text(record, "observation_id")),
        subject_id=_stored_text(record, "subject_id"),
        timestamps=timestamps,
        payload=MappingProxyType({str(key): str(value) for key, value in payload.items()}),
        quality_flags=tuple(str(flag) for flag in flags),
        availability_lag_seconds=lag,
    )


def _stored_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise StoreCorruptionError(f"a stored record is missing {field}")
    return value


def _stored_time(record: Mapping[str, Any], field: str) -> datetime:
    if field not in _TIMESTAMP_FIELDS:
        raise StoreCorruptionError(f"{field} is not a timestamp field")
    return require_utc(datetime.fromisoformat(_stored_text(record, field)), field)
