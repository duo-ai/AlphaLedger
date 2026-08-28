"""Contract tests for the frozen domain types.

Names state the invariant and the failure condition, per
`.claude/rules/40-tests.md`. The list covers the four paths the definition of
done in `AGENTS.md` requires: success, failure, restart, and no-trade.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from alphaledger.domain import (
    CATEGORIES,
    ENTITY_MATCHES,
    EvidenceCard,
    Forecast,
    NewsLabel,
    ObservationTimestamps,
    RiskApproval,
    StructurePlan,
    money,
)

T0 = datetime(2026, 8, 28, 14, 30, tzinfo=UTC)


def a_news_label(**overrides: object) -> NewsLabel:
    fields: dict[str, object] = {
        "article_id": "art-1",
        "source_time": T0,
        "first_seen_time": T0,
        "direction": "positive",
        "category": "earnings",
        "novelty": "new",
        "relevance": "direct",
        "surprise": "unexpected",
        "ambiguity": "low",
        "evidence_spans": ("beat consensus",),
        "labeler_version": "v1",
        "ticker": "AAPL",
        "entity_match": "matched",
        "limitations": (),
    }
    fields.update(overrides)
    return NewsLabel(**fields)  # type: ignore[arg-type]


def an_evidence_card(**overrides: object) -> EvidenceCard:
    fields: dict[str, object] = {
        "candidate_id": "cand-1",
        "symbol": "AAPL",
        "as_of": T0,
        "data_mode": "opra",
        "price_volume_features": {"resid_5d": 0.01},
        "news_features": {"surprise": 1.0},
        "options_features": None,
        "quality_flags": (),
        "raw_data_hashes": ("sha256:abc",),
    }
    fields.update(overrides)
    return EvidenceCard(**fields)  # type: ignore[arg-type]


def a_forecast(**overrides: object) -> Forecast:
    fields: dict[str, object] = {
        "candidate_id": "cand-1",
        "horizon_sessions": 3,
        "p_up": 0.58,
        "expected_residual_return": 0.004,
        "quantiles": {"p10": -0.02, "p90": 0.03},
        "contribution_by_family": {"price": 0.6, "news": 0.4},
        "calibration_error": 0.02,
        "effective_sample_size": 800.0,
        "eligible": True,
        "rejection_reasons": (),
        "model_version": "m1",
    }
    fields.update(overrides)
    return Forecast(**fields)  # type: ignore[arg-type]


def a_structure_plan(**overrides: object) -> StructurePlan:
    fields: dict[str, object] = {
        "plan_id": "plan-1",
        "candidate_id": "cand-1",
        "legs": ({"symbol": "AAPL260918C00200000", "side": "buy", "ratio": 1},),
        "quantity": 1,
        "entry_limit_bound": Decimal("2.35"),
        "exact_max_loss": Decimal("235.00"),
        "exact_max_profit": Decimal("265.00"),
        "expiry_breakeven": Decimal("202.35"),
        "quote_times": (T0,),
        "stress_pnl": {"down_10pct": Decimal("-235.00")},
    }
    fields.update(overrides)
    return StructurePlan(**fields)  # type: ignore[arg-type]


def a_risk_approval(**overrides: object) -> RiskApproval:
    fields: dict[str, object] = {
        "approval_id": "appr-1",
        "plan_id": "plan-1",
        "account_snapshot_hash": "sha256:acct",
        "order_payload_hash": "sha256:payload",
        "expires_at": T0 + timedelta(minutes=5),
        "approved": True,
        "failed_gates": (),
    }
    fields.update(overrides)
    return RiskApproval(**fields)  # type: ignore[arg-type]


# success


def test_each_contract_constructs_from_a_valid_payload_and_compares_equal() -> None:
    for build in (a_news_label, an_evidence_card, a_forecast, a_structure_plan, a_risk_approval):
        assert build() == build(), f"{build.__name__} must compare equal to an identical instance"


def test_observation_timestamps_round_trip_without_losing_the_utc_offset() -> None:
    stamps = ObservationTimestamps(
        event_time=T0,
        first_seen_time=T0 + timedelta(seconds=30),
        source_time=T0,
        received_time=T0 + timedelta(seconds=31),
        feed="iex",
        as_of=T0 + timedelta(minutes=1),
    )
    for field in ("event_time", "first_seen_time", "source_time", "received_time", "as_of"):
        value = getattr(stamps, field)
        assert value.tzinfo is not None, f"{field} lost its timezone"
        assert value.utcoffset() == timedelta(0), f"{field} is not UTC"


def test_money_accepts_decimal_and_string_and_parses_the_string_exactly() -> None:
    assert money("2.35", "entry_limit_bound") == Decimal("2.35")
    assert money(Decimal("2.35"), "entry_limit_bound") == Decimal("2.35")
    assert money(7, "entry_limit_bound") == Decimal("7")


def test_a_non_utc_aware_timestamp_is_normalised_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    stamps = ObservationTimestamps(
        event_time=datetime(2026, 8, 28, 10, 30, tzinfo=eastern),
        first_seen_time=T0,
        source_time=T0,
        received_time=T0,
        feed="iex",
        as_of=T0,
    )
    assert stamps.event_time == T0, "an offset-aware timestamp must convert to the same instant"
    assert stamps.event_time.utcoffset() == timedelta(0), "stored timestamps must be UTC"


# failure


def test_naive_event_time_is_rejected_and_the_message_names_the_field() -> None:
    with pytest.raises(ValueError, match="event_time") as excinfo:
        ObservationTimestamps(
            event_time=datetime(2026, 8, 28, 14, 30),
            first_seen_time=T0,
            source_time=T0,
            received_time=T0,
            feed="iex",
            as_of=T0,
        )
    assert "naive" in str(excinfo.value).lower(), "the message should say the value was naive"


def test_naive_expiry_on_a_risk_approval_is_rejected() -> None:
    with pytest.raises(ValueError, match="expires_at"):
        a_risk_approval(expires_at=datetime(2026, 8, 28, 14, 35))


def test_money_field_given_a_float_is_rejected_rather_than_silently_converted() -> None:
    with pytest.raises(TypeError, match="exact_max_loss"):
        a_structure_plan(exact_max_loss=235.0)


def test_a_float_inside_stress_pnl_is_rejected() -> None:
    with pytest.raises(TypeError, match="stress_pnl"):
        a_structure_plan(stress_pnl={"down_10pct": -235.0})


def test_a_bool_is_not_accepted_as_money() -> None:
    with pytest.raises(TypeError, match="exact_max_loss"):
        a_structure_plan(exact_max_loss=True)


def test_assigning_to_a_constructed_risk_approval_raises() -> None:
    approval = a_risk_approval()
    with pytest.raises(AttributeError):
        approval.approved = False  # type: ignore[misc]


def test_mapping_fields_cannot_be_mutated_through_the_instance() -> None:
    card = an_evidence_card()
    with pytest.raises(TypeError):
        card.price_volume_features["resid_5d"] = 99.0  # type: ignore[index]


def test_mutating_the_dict_passed_in_does_not_change_the_instance() -> None:
    supplied = {"resid_5d": 0.01}
    card = an_evidence_card(price_volume_features=supplied)
    supplied["resid_5d"] = 99.0
    assert card.price_volume_features["resid_5d"] == 0.01, "the instance must own its own copy"


# restart


def test_risk_approval_rebuilt_from_recorded_values_hashes_equal_to_the_original() -> None:
    original = a_risk_approval()
    rebuilt = RiskApproval(
        approval_id=original.approval_id,
        plan_id=original.plan_id,
        account_snapshot_hash=original.account_snapshot_hash,
        order_payload_hash=original.order_payload_hash,
        expires_at=original.expires_at,
        approved=original.approved,
        failed_gates=original.failed_gates,
    )
    assert hash(rebuilt) == hash(original), "a restart must not turn one approval into two intents"
    assert rebuilt == original


# no-trade


def test_forecast_with_eligible_false_and_rejection_reasons_is_valid() -> None:
    forecast = a_forecast(eligible=False, rejection_reasons=("stale_quote", "below_threshold"))
    assert forecast.eligible is False
    assert forecast.rejection_reasons == ("stale_quote", "below_threshold")


def test_a_rejected_risk_approval_records_its_failed_gates() -> None:
    approval = a_risk_approval(approved=False, failed_gates=("daily_loss_limit",))
    assert approval.approved is False
    assert approval.failed_gates == ("daily_loss_limit",)


# import hygiene


def test_importing_the_domain_package_pulls_in_no_adapter_broker_or_model_module() -> None:
    probe = (
        "import sys; import alphaledger.domain; "
        "bad=[m for m in sys.modules "
        "if any(p in m for p in ('alpaca','httpx','requests','sklearn','pandas')) "
        "or m.startswith(('alphaledger.broker','alphaledger.execution','alphaledger.data'))]; "
        "print(','.join(sorted(bad)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"domain import pulled in {result.stdout.strip()}"


# regressions from the UNIT-001 gating review


def test_a_bare_string_is_rejected_where_a_tuple_of_strings_is_required() -> None:
    """A str is iterable, so an unguarded coercion shreds it into characters and
    destroys the reason it was meant to record."""
    with pytest.raises(TypeError, match="rejection_reasons"):
        a_forecast(eligible=False, rejection_reasons="below_threshold")


def test_a_bare_string_is_rejected_for_failed_gates() -> None:
    with pytest.raises(TypeError, match="failed_gates"):
        a_risk_approval(approved=False, failed_gates="daily_loss_limit")


def test_a_bare_string_is_rejected_for_evidence_spans() -> None:
    with pytest.raises(TypeError, match="evidence_spans"):
        a_news_label(evidence_spans="beat consensus")


def test_a_non_finite_feature_value_is_rejected() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="price_volume_features"):
            an_evidence_card(price_volume_features={"resid_5d": bad})


def test_a_non_finite_forecast_scalar_is_rejected() -> None:
    with pytest.raises(ValueError, match="expected_residual_return"):
        a_forecast(expected_residual_return=float("nan"))
    with pytest.raises(ValueError, match="calibration_error"):
        a_forecast(calibration_error=float("inf"))


def test_money_rounds_half_even_as_declared() -> None:
    """ROUND_HALF_EVEN is declared in the module. Pin it, or swapping the
    constant would not fail a single test."""
    assert money("2.00005", "premium") == Decimal("2.0000")
    assert money("2.00015", "premium") == Decimal("2.0002")


def test_money_rejects_a_magnitude_it_cannot_quantize() -> None:
    with pytest.raises(ValueError, match="premium"):
        money(Decimal("1E+24"), "premium")


def test_a_rejected_risk_approval_must_record_a_failed_gate() -> None:
    with pytest.raises(ValueError, match="failed_gates"):
        a_risk_approval(approved=False, failed_gates=())


def test_a_risk_approval_survives_a_restart_from_differently_shaped_values() -> None:
    """The restart hazard is values coming back from storage in an equivalent
    but differently shaped form, not identical objects in one process."""
    original = a_risk_approval(approved=False, failed_gates=("daily_loss_limit",))
    eastern = timezone(timedelta(hours=-4))
    rebuilt = RiskApproval(
        approval_id=original.approval_id,
        plan_id=original.plan_id,
        account_snapshot_hash=original.account_snapshot_hash,
        order_payload_hash=original.order_payload_hash,
        expires_at=original.expires_at.astimezone(eastern),
        approved=original.approved,
        failed_gates=["daily_loss_limit"],
    )
    assert rebuilt == original, "a restart must not create a second intent"
    assert hash(rebuilt) == hash(original)


def test_records_without_mapping_fields_are_hashable() -> None:
    for build in (a_news_label, a_risk_approval):
        assert isinstance(hash(build()), int), f"{build.__name__} must be hashable"


def test_records_with_mapping_fields_are_not_hashable() -> None:
    """Resolved conflict 2 in the intake. Pin it so the deviation is visible."""
    for build in (an_evidence_card, a_forecast, a_structure_plan):
        with pytest.raises(TypeError):
            hash(build())


# design decisions settled after the UNIT-001 review


def test_a_first_seen_time_before_its_source_time_is_rejected() -> None:
    """You cannot observe a record before its source emitted it. Design section
    4 sets first_seen to the published time plus a conservative lag, so this
    ordering is the one the contract guarantees."""
    with pytest.raises(ValueError, match="first_seen_time"):
        ObservationTimestamps(
            event_time=T0,
            first_seen_time=T0 - timedelta(seconds=1),
            source_time=T0,
            received_time=T0,
            feed="iex",
            as_of=T0,
        )


def test_a_first_seen_time_equal_to_its_source_time_is_accepted() -> None:
    stamps = ObservationTimestamps(
        event_time=T0,
        first_seen_time=T0,
        source_time=T0,
        received_time=T0,
        feed="iex",
        as_of=T0,
    )
    assert stamps.first_seen_time == stamps.source_time


def test_an_event_scheduled_after_it_was_announced_is_accepted() -> None:
    """A scheduled earnings date is known weeks in advance, so event_time after
    first_seen_time is legitimate and must not be rejected."""
    stamps = ObservationTimestamps(
        event_time=T0 + timedelta(days=14),
        first_seen_time=T0,
        source_time=T0,
        received_time=T0,
        feed="benzinga",
        as_of=T0,
    )
    assert stamps.event_time > stamps.first_seen_time


def test_a_leg_value_that_is_not_a_scalar_is_rejected() -> None:
    """A nested container would be shared by reference, so a caller could mutate
    a plan after its payload hash was computed."""
    with pytest.raises(TypeError, match="legs"):
        a_structure_plan(legs=({"symbol": "AAPL", "greeks": [1, 2, 3]},))


def test_a_float_leg_value_is_rejected() -> None:
    """A strike is money. rules/01-safety.md forbids float for it."""
    with pytest.raises(TypeError, match="legs"):
        a_structure_plan(legs=({"symbol": "AAPL", "strike": 200.0},))


# --- UNIT-002: the label holds what the labeler emits --------------------


def test_a_label_carries_the_ticker_the_entity_match_and_its_limitations() -> None:
    """Prompt B emits all three. Without them a label cannot say which company
    it is about, whether it matched at all, or what it could not determine."""
    label = a_news_label(
        ticker="MSFT",
        entity_match="uncertain",
        limitations=("body was empty", "no expectation stated"),
    )

    assert label.ticker == "MSFT"
    assert label.entity_match == "uncertain"
    assert label.limitations == ("body was empty", "no expectation stated")


def test_a_labeler_may_say_it_does_not_know_the_novelty_or_the_relevance() -> None:
    """Prompt B's consistency rules require `unknown` when republication is not
    established. The frozen record previously made that impossible to store, so
    the label had to claim a certainty the model refused to claim."""
    label = a_news_label(novelty="unknown", relevance="unknown")

    assert label.novelty == "unknown"
    assert label.relevance == "unknown"


def test_a_not_matched_label_constructs_whatever_its_relevance_says() -> None:
    """Prompt B's consistency rules belong to the adapter that validates model
    output, per D-014 and D-016. A record that enforced them here would reject
    labels the contract itself permits, because Prompt B qualifies its own
    rules."""
    label = a_news_label(entity_match="not_matched", relevance="direct", ambiguity="low")

    assert label.entity_match == "not_matched"
    assert label.relevance == "direct"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_label_without_a_ticker_is_refused_rather_than_defaulted(blank: str) -> None:
    with pytest.raises(ValueError, match="ticker"):
        a_news_label(ticker=blank)


def test_an_entity_match_outside_the_allowed_values_is_refused() -> None:
    with pytest.raises(ValueError, match="entity_match"):
        a_news_label(entity_match="probably")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("direction", "bullish"),
        ("novelty", "fresh"),
        ("relevance", "related"),
        ("surprise", "shocking"),
        ("ambiguity", "none"),
        ("entity_match", "maybe"),
    ],
)
def test_every_enumerated_label_field_is_checked_at_run_time(field: str, value: str) -> None:
    """A Literal is a static annotation and stops nothing at run time. These
    records are built from model output parsed out of JSON, so the type
    annotation is exactly the guarantee that does not hold where it matters."""
    with pytest.raises(ValueError, match=field):
        a_news_label(**{field: value})


def test_a_bare_string_of_limitations_is_refused_rather_than_shredded() -> None:
    """The same defect UNIT-001's review found on evidence_spans: a string is
    iterable, so one limitation would become a tuple of characters."""
    with pytest.raises(TypeError, match="limitations"):
        a_news_label(limitations="body was empty")


def test_a_label_that_states_nothing_extra_still_constructs() -> None:
    """Saying nothing is a valid label. An empty tuple is not an error."""
    label = a_news_label(evidence_spans=(), limitations=())

    assert label.evidence_spans == ()
    assert label.limitations == ()


def test_the_allowed_entity_matches_are_exactly_prompt_b_s_three() -> None:
    assert ENTITY_MATCHES == ("matched", "not_matched", "uncertain")


# UNIT-003: category is the last enumerated field left unchecked at run time


def test_the_allowed_categories_are_exactly_prompt_b_s_nine() -> None:
    """Pinned by literal equality, not by iterating the module's own tuple.

    Iterating CATEGORIES and asserting each constructs cannot fail: _one_of
    checks membership in that same tuple. A typo such as regulatory-legal would
    keep the suite green while every real label was rejected at run time.
    """
    assert CATEGORIES == (
        "earnings",
        "guidance",
        "analyst",
        "regulatory_legal",
        "product",
        "financing_ma",
        "management",
        "macro_industry",
        "other",
    )


def test_every_prompt_b_category_constructs() -> None:
    for category in CATEGORIES:
        assert a_news_label(category=category).category == category


def test_an_unknown_category_is_refused_and_the_message_lists_the_allowed_values() -> None:
    with pytest.raises(ValueError, match="category") as excinfo:
        a_news_label(category="lawsuit")
    message = str(excinfo.value)
    assert "earnings" in message, "the refusal should say what is allowed"


def test_an_empty_category_is_refused_rather_than_defaulted() -> None:
    """Choosing `other` on the caller's behalf is the labeler's judgment, not
    the record's. A blank means the labeler did not answer."""
    for blank in ("", "   ", "\t"):
        with pytest.raises(ValueError, match="category"):
            a_news_label(category=blank)


def test_a_category_differing_only_in_case_is_refused() -> None:
    """Normalising here would hide a labeler that is not following its schema."""
    for variant in ("Earnings", "EARNINGS", "Financing_MA"):
        with pytest.raises(ValueError, match="category"):
            a_news_label(category=variant)


def test_other_is_a_real_answer_and_constructs() -> None:
    """None of these fits is a first-class result, not a missing value."""
    assert a_news_label(category="other").category == "other"
