"""Point-in-time recorder tests.

Every test here asks the same question in a different form: could this record
have been known, by us, at the instant a decision claims to have used it. A
leak in this module does not raise anywhere downstream; it produces a better
looking number, which is why the assertions are on rejection and on the exact
field named, not merely on a happy path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alphaledger.data.recorder import (
    AVAILABILITY_LAG_APPLIED,
    FeedPolicy,
    ObservationRejectedError,
    RawObservation,
    Recorder,
)
from alphaledger.data.storage import AppendOnlyStore

# A feed whose delivery time is proven by the transport: an intraday bar
# arrives with the timestamp at which we received it.
BARS = FeedPolicy(
    feed="iex_bars",
    proves_delivery_time=True,
    availability_lag=timedelta(0),
    event_time_may_follow_first_seen=False,
)
# A historical news feed cannot prove when an article reached a subscriber, so
# availability is the published time plus a documented conservative buffer.
NEWS = FeedPolicy(
    feed="alpaca_news_historical",
    proves_delivery_time=False,
    availability_lag=timedelta(minutes=1),
    event_time_may_follow_first_seen=False,
)
# A calendar publishes events that have not happened yet. This is the feed
# D-014 exists for: event_time legitimately follows first_seen_time.
CALENDAR = FeedPolicy(
    feed="earnings_calendar",
    proves_delivery_time=True,
    availability_lag=timedelta(0),
    event_time_may_follow_first_seen=True,
)

SESSION = datetime(2026, 8, 27, 14, 30, tzinfo=UTC)


def utc(**offset: float) -> datetime:
    return SESSION + timedelta(**offset)


def recorder(tmp_path: Path) -> Recorder:
    return Recorder(AppendOnlyStore(tmp_path / "observations.jsonl"), (BARS, NEWS, CALENDAR))


def bar(
    *,
    subject_id: str = "AAPL|2026-08-27T14:30:00Z",
    event_time: datetime | None = None,
    source_time: datetime | None = None,
    received_time: datetime | None = None,
    first_seen_time: datetime | None = None,
    as_of: datetime | None = None,
    payload: dict[str, object] | None = None,
) -> RawObservation:
    """A well formed bar observation, mutated per test to express one defect."""
    return RawObservation(
        feed=BARS.feed,
        subject_id=subject_id,
        event_time=event_time or utc(),
        source_time=source_time or utc(),
        received_time=received_time if received_time is not None else utc(seconds=1),
        first_seen_time=first_seen_time if first_seen_time is not None else utc(seconds=1),
        as_of=as_of or utc(minutes=5),
        payload=payload if payload is not None else {"close": "191.2500"},
    )


def article(
    *,
    subject_id: str = "article-1",
    source_time: datetime | None = None,
    event_time: datetime | None = None,
    as_of: datetime | None = None,
    first_seen_time: datetime | None = None,
    payload: dict[str, object] | None = None,
) -> RawObservation:
    return RawObservation(
        feed=NEWS.feed,
        subject_id=subject_id,
        event_time=event_time or utc(minutes=-10),
        source_time=source_time or utc(),
        received_time=utc(days=30),
        first_seen_time=first_seen_time,
        as_of=as_of or utc(hours=1),
        payload=payload if payload is not None else {"headline": "first version"},
    )


# --- success ------------------------------------------------------------


def test_observation_is_retrievable_at_an_as_of_at_or_after_its_first_seen_time(
    tmp_path: Path,
) -> None:
    store = recorder(tmp_path)
    observation_id = store.record(bar())

    at_first_seen = store.read_as_of(utc(seconds=1))
    later = store.read_as_of(utc(hours=4))

    assert [item.observation_id for item in at_first_seen] == [observation_id]
    assert [item.observation_id for item in later] == [observation_id]
    assert at_first_seen[0].timestamps.feed == BARS.feed


def test_as_of_read_excludes_an_observation_first_seen_after_the_requested_instant(
    tmp_path: Path,
) -> None:
    """AC-2. The read is the only interface, so this is the leak that matters."""
    store = recorder(tmp_path)
    store.record(bar())

    assert store.read_as_of(utc(seconds=0)) == ()
    assert store.read_as_of(utc(seconds=-1)) == ()


def test_revision_and_original_are_both_retained_and_distinguishable(tmp_path: Path) -> None:
    """AC-4. A revision is a new observation, never an update of an old one."""
    store = recorder(tmp_path)
    original = store.record(article(payload={"headline": "first version"}))
    revised = store.record(
        article(source_time=utc(minutes=30), payload={"headline": "corrected version"})
    )

    both = store.read_as_of(utc(hours=2), subject_id="article-1")

    assert original != revised
    assert [item.observation_id for item in both] == [original, revised]
    assert [item.payload["headline"] for item in both] == ["first version", "corrected version"]


def test_as_of_between_original_and_revision_returns_only_the_original(tmp_path: Path) -> None:
    store = recorder(tmp_path)
    original = store.record(article(payload={"headline": "first version"}))
    store.record(article(source_time=utc(minutes=30), payload={"headline": "corrected version"}))

    visible = store.read_as_of(utc(minutes=10), subject_id="article-1")

    assert [item.observation_id for item in visible] == [original]


def test_a_scheduled_event_time_after_first_seen_is_accepted_for_a_calendar_feed(
    tmp_path: Path,
) -> None:
    """D-014: an earnings date known weeks ahead is not a leak, it is the data."""
    store = recorder(tmp_path)
    scheduled = RawObservation(
        feed=CALENDAR.feed,
        subject_id="AAPL|2026-10-29",
        event_time=utc(days=60),
        source_time=utc(),
        received_time=utc(seconds=2),
        first_seen_time=utc(seconds=2),
        as_of=utc(minutes=5),
        payload={"session": "after_close"},
    )

    recorded = store.record(scheduled)

    assert [item.observation_id for item in store.read_as_of(utc(minutes=5))] == [recorded]


def test_unproven_delivery_applies_the_documented_lag_and_flags_the_record(
    tmp_path: Path,
) -> None:
    """AC-5. Published time is a lower bound, so availability is later than it."""
    store = recorder(tmp_path)
    store.record(article())

    [observation] = store.read_as_of(utc(hours=2))

    assert observation.timestamps.first_seen_time == utc() + NEWS.availability_lag
    assert AVAILABILITY_LAG_APPLIED in observation.quality_flags
    assert observation.availability_lag_seconds == int(NEWS.availability_lag.total_seconds())
    assert store.read_as_of(utc(seconds=30)) == ()


def test_every_persisted_record_carries_six_timestamps_and_the_feed(tmp_path: Path) -> None:
    """AC-1, asserted on the bytes on disk rather than on the in-memory object."""
    path = tmp_path / "observations.jsonl"
    Recorder(AppendOnlyStore(path), (BARS,)).record(bar())

    [line] = path.read_text().splitlines()
    record = json.loads(line)

    assert set(record) >= {
        "event_time",
        "first_seen_time",
        "source_time",
        "received_time",
        "feed",
        "as_of",
    }
    assert record["feed"] == BARS.feed
    assert all(record[field] for field in ("event_time", "first_seen_time", "source_time"))


def test_observation_id_is_content_addressed_so_a_revision_gets_its_own_id(
    tmp_path: Path,
) -> None:
    first = recorder(tmp_path).record(bar())
    second = recorder(tmp_path / "other").record(bar())
    revised = recorder(tmp_path / "third").record(bar(payload={"close": "191.5000"}))

    assert first == second
    assert first != revised


# --- failure ------------------------------------------------------------


def test_observation_first_seen_after_its_own_as_of_is_rejected_naming_the_field(
    tmp_path: Path,
) -> None:
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(as_of=utc(seconds=-30)))

    assert raised.value.field == "first_seen_time"
    assert "as_of" in str(raised.value)


def test_a_record_without_a_feed_is_rejected_rather_than_defaulted(tmp_path: Path) -> None:
    store = recorder(tmp_path)
    empty = RawObservation(
        feed="",
        subject_id="AAPL",
        event_time=utc(),
        source_time=utc(),
        received_time=utc(seconds=1),
        first_seen_time=utc(seconds=1),
        as_of=utc(minutes=5),
        payload={"close": "191.2500"},
    )

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(empty)

    assert raised.value.field == "feed"


def test_a_record_from_an_unregistered_feed_is_rejected_rather_than_assumed(
    tmp_path: Path,
) -> None:
    """A feed with no declared policy has no declared ordering rules either."""
    store = recorder(tmp_path)
    unknown = RawObservation(
        feed="some_vendor_csv",
        subject_id="AAPL",
        event_time=utc(),
        source_time=utc(),
        received_time=utc(seconds=1),
        first_seen_time=utc(seconds=1),
        as_of=utc(minutes=5),
        payload={"close": "191.2500"},
    )

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(unknown)

    assert raised.value.field == "feed"
    assert "some_vendor_csv" in str(raised.value)


def test_leaked_first_seen_before_source_time_is_rejected_naming_the_field(
    tmp_path: Path,
) -> None:
    """The leaked fixture required by .claude/rules/20-research-integrity.md.

    Observing a record before its source emitted it is impossible, so this is
    rejected rather than filtered. A silent filter is how a leak becomes
    invisible in production.
    """
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(source_time=utc(minutes=5), first_seen_time=utc()))

    assert raised.value.field == "first_seen_time"
    assert "source_time" in str(raised.value)


def test_a_rejected_observation_is_not_persisted(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    store = Recorder(AppendOnlyStore(path), (BARS,))

    with pytest.raises(ObservationRejectedError):
        store.record(bar(source_time=utc(minutes=5), first_seen_time=utc()))

    assert not path.exists()
    assert store.read_as_of(utc(days=1)) == ()


def test_received_before_source_is_rejected_naming_the_field(tmp_path: Path) -> None:
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(received_time=utc(seconds=-5)))

    assert raised.value.field == "received_time"


def test_event_time_after_first_seen_is_rejected_for_a_feed_that_reports_the_past(
    tmp_path: Path,
) -> None:
    """A bar cannot be observed before the session minute it summarises closed."""
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(event_time=utc(minutes=1)))

    assert raised.value.field == "event_time"


def test_a_proven_feed_rejects_a_first_seen_time_before_delivery(tmp_path: Path) -> None:
    """Feed aware, per D-014: availability cannot precede the proven arrival."""
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(received_time=utc(seconds=30), first_seen_time=utc(seconds=1)))

    assert raised.value.field == "first_seen_time"
    assert "received_time" in str(raised.value)


def test_an_unproven_feed_rejects_a_caller_supplied_first_seen_time(tmp_path: Path) -> None:
    """The feed cannot prove delivery, so a caller cannot assert it either."""
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(article(first_seen_time=utc(seconds=1)))

    assert raised.value.field == "first_seen_time"


def test_a_delivery_proving_feed_requires_a_first_seen_time(tmp_path: Path) -> None:
    """Built without the helper: the case is the absence of the field itself."""
    store = recorder(tmp_path)
    undelivered = RawObservation(
        feed=BARS.feed,
        subject_id="AAPL|2026-08-27T14:30:00Z",
        event_time=utc(),
        source_time=utc(),
        received_time=utc(seconds=1),
        as_of=utc(minutes=5),
        payload={"close": "191.2500"},
    )
    assert undelivered.first_seen_time is None

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(undelivered)

    assert raised.value.field == "first_seen_time"


def test_a_naive_timestamp_is_rejected_naming_the_field(tmp_path: Path) -> None:
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(as_of=datetime(2026, 8, 27, 15, 0)))

    assert raised.value.field == "as_of"


def test_a_naive_as_of_read_is_rejected(tmp_path: Path) -> None:
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.read_as_of(datetime(2026, 8, 27, 15, 0))

    assert raised.value.field == "as_of"


def test_a_float_payload_value_is_rejected_because_a_price_is_money(tmp_path: Path) -> None:
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(payload={"close": 191.25}))

    assert raised.value.field == "payload[close]"


def test_a_nested_payload_value_is_rejected(tmp_path: Path) -> None:
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(payload={"quotes": ["191.25"]}))

    assert raised.value.field == "payload[quotes]"


def test_an_empty_payload_is_rejected_because_a_record_of_nothing_is_not_evidence(
    tmp_path: Path,
) -> None:
    store = recorder(tmp_path)

    with pytest.raises(ObservationRejectedError) as raised:
        store.record(bar(payload={}))

    assert raised.value.field == "payload"


# --- restart ------------------------------------------------------------


RESTART_SCRIPT = """
import sys
from datetime import UTC, datetime, timedelta

from alphaledger.data.recorder import FeedPolicy, RawObservation, Recorder
from alphaledger.data.storage import AppendOnlyStore

path, subject = sys.argv[1], sys.argv[2]
policy = FeedPolicy(
    feed="iex_bars",
    proves_delivery_time=True,
    availability_lag=timedelta(0),
    event_time_may_follow_first_seen=False,
)
recorder = Recorder(AppendOnlyStore(path), (policy,))
moment = datetime(2026, 8, 27, 14, 30, tzinfo=UTC)
print("read_at_start=%d" % len(recorder.read_as_of(moment + timedelta(days=1))))
recorder.record(
    RawObservation(
        feed="iex_bars",
        subject_id=subject,
        event_time=moment,
        source_time=moment,
        received_time=moment + timedelta(seconds=1),
        first_seen_time=moment + timedelta(seconds=1),
        as_of=moment + timedelta(minutes=5),
        payload={"close": "191.2500"},
    )
)
"""


def run_restart(path: Path, subject: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", RESTART_SCRIPT, str(path), subject],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_restart_reopens_the_store_append_only_and_preserves_prior_bytes(tmp_path: Path) -> None:
    """A real process boundary. An in-process call would only prove the data model."""
    path = tmp_path / "observations.jsonl"

    assert run_restart(path, "first") == "read_at_start=0"
    after_first = path.read_bytes()
    assert run_restart(path, "second") == "read_at_start=1"
    after_second = path.read_bytes()
    assert run_restart(path, "third") == "read_at_start=2"
    after_third = path.read_bytes()

    assert after_second.startswith(after_first)
    assert after_third.startswith(after_second)
    subjects = [json.loads(line)["subject_id"] for line in path.read_text().splitlines()]
    assert subjects == ["first", "second", "third"]


def test_a_restarted_reader_sees_records_written_by_the_previous_process(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    run_restart(path, "first")
    run_restart(path, "second")

    reopened = Recorder(AppendOnlyStore(path), (BARS,))
    visible = reopened.read_as_of(utc(days=1))

    assert [item.subject_id for item in visible] == ["first", "second"]


# --- no trade -----------------------------------------------------------


def test_an_as_of_read_with_no_qualifying_observation_returns_empty_not_the_latest(
    tmp_path: Path,
) -> None:
    """An empty result is an answer. Returning the most recent record instead
    is the single most damaging bug this module can have, because every caller
    would silently receive a future observation."""
    store = recorder(tmp_path)
    store.record(bar(subject_id="AAPL|late"))

    assert store.read_as_of(utc(hours=-3)) == ()
    assert store.read_as_of(utc(hours=-3), subject_id="AAPL|late") == ()


def test_an_as_of_read_of_an_empty_store_is_empty_rather_than_an_error(tmp_path: Path) -> None:
    assert recorder(tmp_path).read_as_of(utc()) == ()


def test_a_filter_that_matches_nothing_returns_empty_rather_than_everything(
    tmp_path: Path,
) -> None:
    store = recorder(tmp_path)
    store.record(bar())

    assert store.read_as_of(utc(days=1), subject_id="MSFT|missing") == ()
    assert store.read_as_of(utc(days=1), feed=CALENDAR.feed) == ()


# --- interface shape ----------------------------------------------------


def test_the_recorder_exposes_no_wall_clock_read_interface(tmp_path: Path) -> None:
    """Design section 4: there is no read that returns a record by wall clock
    time alone, because that is the shape of a leak."""
    public = sorted(name for name in dir(Recorder) if not name.startswith("_"))

    assert public == ["read_as_of", "record"]
