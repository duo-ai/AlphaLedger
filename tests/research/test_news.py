"""Point-in-time news feature tests.

This family is the other side of the comparison UNIT-022 built the control for,
so its whole value is being a strict function of labels that were knowable at
`as_of`. The fixture is built so every expected number can be computed by hand:
the decay half life equals the age of the second article, which makes its
weight exactly one half, and every category weight is one, which keeps the
weighted ratios readable as small fractions.
"""

from __future__ import annotations

import math
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alphaledger.domain.contracts import NewsLabel, ObservationTimestamps
from alphaledger.evidence.labeler import (
    LabelerContractError,
    NewsLabeler,
    labels_by_article,
)
from alphaledger.evidence.news import (
    ENTITY_NOT_MATCHED,
    ENTITY_UNCERTAIN,
    EXCLUDED_NOT_MATCHED,
    EXCLUDED_OUTSIDE_LOOKBACK,
    EXCLUDED_UNCERTAIN,
    EXCLUDED_UNLABELLED,
    NO_ARTICLES,
    NO_QUALIFYING_ARTICLES,
    SURPRISE_UNKNOWN,
    SYNDICATION_COLLAPSED,
    UNLABELLED_ARTICLE,
    ZERO_DENOMINATOR,
    AmbiguousArticleError,
    Article,
    LabelMismatchError,
    LeakedNewsError,
    NewsFeatureBlock,
    NewsFeatureConfig,
    UnknownArticleError,
    build,
)

SYMBOL = "ACME"
AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
FEED = "alpaca_news"


def article(
    article_id: str,
    headline: str,
    *,
    age_hours: float = 0.0,
    domain: str = "wire.example",
    symbols: tuple[str, ...] = (SYMBOL,),
    event_time: datetime | None = None,
    summary: str | None = None,
) -> Article:
    seen = AS_OF - timedelta(hours=age_hours)
    return Article(
        article_id=article_id,
        symbols=symbols,
        headline=headline,
        # The default is distinct from the headline so the ordinary fixture
        # exercises a real summary. `Article` itself has no default, which is
        # AC-1: losing the field must fail at construction, not silently.
        summary=f"{headline}, the wire reports." if summary is None else summary,
        source_domain=domain,
        timestamps=ObservationTimestamps(
            event_time=seen if event_time is None else event_time,
            first_seen_time=seen,
            source_time=seen - timedelta(minutes=5),
            received_time=seen,
            feed=FEED,
            as_of=seen,
        ),
    )


def label(
    subject: Article,
    *,
    direction: str = "positive",
    category: str = "earnings",
    novelty: str = "new",
    relevance: str = "direct",
    surprise: str = "unexpected",
    ambiguity: str = "low",
    entity_match: str = "matched",
    ticker: str = SYMBOL,
) -> NewsLabel:
    return NewsLabel(
        article_id=subject.article_id,
        ticker=ticker,
        entity_match=entity_match,  # type: ignore[arg-type]
        source_time=subject.timestamps.source_time,
        first_seen_time=subject.timestamps.first_seen_time,
        direction=direction,  # type: ignore[arg-type]
        category=category,  # type: ignore[arg-type]
        novelty=novelty,  # type: ignore[arg-type]
        relevance=relevance,  # type: ignore[arg-type]
        surprise=surprise,  # type: ignore[arg-type]
        ambiguity=ambiguity,  # type: ignore[arg-type]
        evidence_spans=("beat consensus",),
        limitations=(),
        labeler_version="test-labeler-1",
    )


def keyed(*labels: NewsLabel) -> dict[str, NewsLabel]:
    return {item.article_id: item for item in labels}


CONFIG = NewsFeatureConfig()


# --- success: the hand-computed fixture ---------------------------------


FRESH = article("a1", "Acme beats earnings")
DAY_OLD = article("a2", "Acme names new chief financial officer", age_hours=24.0)
FRESH_LABEL = label(FRESH)
DAY_OLD_LABEL = label(
    DAY_OLD,
    direction="neutral",
    category="management",
    surprise="expected",
    ambiguity="medium",
)


def two_article_block() -> NewsFeatureBlock:
    return build(SYMBOL, AS_OF, (FRESH, DAY_OLD), keyed(FRESH_LABEL, DAY_OLD_LABEL), CONFIG)


def test_the_hand_computed_fixture_reproduces_every_feature() -> None:
    """The fresh article weighs one and the day old one weighs one half,
    because its age is exactly the configured half life."""
    block = two_article_block()
    assert block.quality_flags == ()
    assert dict(block.exclusions) == {}
    assert set(block.features) == {
        "ambiguity_weighted",
        "direction_weighted",
        "independent_source_count",
        "news_volume_decayed",
        "novelty_new_share",
        "recency_weight_max",
        "relevance_direct_share",
        "surprise_weighted",
    }
    assert block.features["news_volume_decayed"] == pytest.approx(1.5)
    assert block.features["independent_source_count"] == pytest.approx(2.0)
    assert block.features["direction_weighted"] == pytest.approx(1.0 / 1.5)
    assert block.features["surprise_weighted"] == pytest.approx(1.0 / 1.5)
    assert block.features["novelty_new_share"] == pytest.approx(1.0)
    assert block.features["relevance_direct_share"] == pytest.approx(1.0)
    assert block.features["ambiguity_weighted"] == pytest.approx(0.25 / 1.5)
    assert block.features["recency_weight_max"] == pytest.approx(1.0)


def test_a_negative_direction_pulls_the_weighted_direction_below_zero() -> None:
    """Direction is signed, so the feature has to be able to say bad news."""
    bad = article("b1", "Acme sued by regulator")
    block = build(SYMBOL, AS_OF, (bad,), keyed(label(bad, direction="negative")), CONFIG)
    assert block.features["direction_weighted"] == pytest.approx(-1.0)


def test_a_decayed_weight_halves_once_per_configured_half_life() -> None:
    """Two half lives of age weigh a quarter, which is what makes the decay a
    documented function of age rather than an arbitrary discount."""
    old = article("c1", "Acme beats earnings", age_hours=48.0)
    block = build(SYMBOL, AS_OF, (old,), keyed(label(old)), CONFIG)
    assert block.features["news_volume_decayed"] == pytest.approx(0.25)
    assert block.features["recency_weight_max"] == pytest.approx(0.25)


def test_a_category_weight_of_zero_removes_the_article_from_every_ratio() -> None:
    """Category weights are configuration, and a zero weight has to leave no
    residue in a ratio, or the weighting would be advisory."""
    config = NewsFeatureConfig(category_weights={"analyst": 0.0})
    chatter = article("d1", "Analyst raises Acme target")
    block = build(SYMBOL, AS_OF, (chatter,), keyed(label(chatter, category="analyst")), config)
    assert block.features["news_volume_decayed"] == pytest.approx(0.0)
    assert ZERO_DENOMINATOR in block.quality_flags
    assert "direction_weighted" not in block.features


# --- success: syndication collapses to one independent source -----------


def test_five_outlets_carrying_one_wire_story_count_as_one_source() -> None:
    """AC-2. Corroboration is the point of the count, and five reprints of one
    wire story corroborate nothing."""
    outlets = tuple(
        article(f"s{index}", "Acme beats earnings", domain=f"outlet{index}.example")
        for index in range(5)
    )
    block = build(SYMBOL, AS_OF, outlets, keyed(*(label(item) for item in outlets)), CONFIG)
    assert block.features["independent_source_count"] == pytest.approx(1.0)
    assert SYNDICATION_COLLAPSED in block.quality_flags


def test_two_genuinely_independent_reports_count_as_two_sources() -> None:
    """AC-2, the other direction. Collapsing everything would be just as wrong
    as collapsing nothing."""
    first = article("i1", "Acme beats earnings", domain="one.example")
    second = article("i2", "Acme wins federal contract", domain="two.example")
    block = build(SYMBOL, AS_OF, (first, second), keyed(label(first), label(second)), CONFIG)
    assert block.features["independent_source_count"] == pytest.approx(2.0)
    assert SYNDICATION_COLLAPSED not in block.quality_flags


def test_punctuation_and_case_do_not_split_one_wire_story_in_two() -> None:
    """Outlets restyle a headline without rewriting it, so canonicalisation is
    what makes the collapse hold in practice."""
    plain = article("p1", "Acme beats earnings", domain="one.example")
    styled = article("p2", "ACME  BEATS, EARNINGS!", domain="two.example")
    block = build(SYMBOL, AS_OF, (plain, styled), keyed(label(plain), label(styled)), CONFIG)
    assert block.features["independent_source_count"] == pytest.approx(1.0)


def test_the_same_headline_outside_the_cluster_window_is_a_separate_story() -> None:
    """A recurring headline months apart is a second event, not a reprint, and
    the window is what separates them."""
    config = NewsFeatureConfig(cluster_window_hours=6.0, lookback_hours=720.0)
    early = article("w1", "Acme beats earnings", age_hours=48.0, domain="one.example")
    late = article("w2", "Acme beats earnings", age_hours=0.0, domain="two.example")
    block = build(SYMBOL, AS_OF, (early, late), keyed(label(early), label(late)), config)
    assert block.features["independent_source_count"] == pytest.approx(2.0)


def test_the_earliest_article_in_a_cluster_supplies_its_label() -> None:
    """The wire story is the observation; a reprint's own label must not
    displace it, or the features would depend on which outlet was read last."""
    first = article("r1", "Acme beats earnings", age_hours=2.0, domain="wire.example")
    reprint = article("r2", "Acme beats earnings", age_hours=1.0, domain="copy.example")
    labels = keyed(label(first, direction="positive"), label(reprint, direction="negative"))
    block = build(SYMBOL, AS_OF, (first, reprint), labels, CONFIG)
    assert block.features["direction_weighted"] == pytest.approx(1.0)


# --- failure: the deliberately leaked fixtures --------------------------


def test_an_article_first_seen_after_as_of_is_rejected_and_named() -> None:
    """AC-1. The leaked fixture the research rules require: a future article
    stops the build rather than being quietly filtered out."""
    leaked = article("x1", "Acme beats earnings", age_hours=-1.0)
    with pytest.raises(LeakedNewsError, match="x1"):
        build(SYMBOL, AS_OF, (leaked,), keyed(label(leaked)), CONFIG)


def test_the_rejection_of_a_leaked_article_names_the_offending_field() -> None:
    """A message that says only 'leaked' leaves the caller guessing which of
    six timestamps was wrong."""
    leaked = article("x2", "Acme beats earnings", age_hours=-1.0)
    with pytest.raises(LeakedNewsError, match="first_seen_time"):
        build(SYMBOL, AS_OF, (leaked,), keyed(label(leaked)), CONFIG)


def test_a_leaked_article_carrying_no_label_at_all_is_still_rejected() -> None:
    """AC-1, guarded against passing for the wrong reason. When the leaked
    article also has a label, the label's own leak check would catch it and
    the article check could be deleted without any test noticing. An unlabelled
    leaked article is the case only the article check can refuse."""
    leaked = article("x4", "Acme beats earnings", age_hours=-1.0)
    with pytest.raises(LeakedNewsError, match="not knowable"):
        build(SYMBOL, AS_OF, (leaked,), {}, CONFIG)


def test_a_label_first_seen_after_as_of_is_rejected_even_when_its_article_is_not() -> None:
    """A label is knowledge too. One produced from a later observation of the
    same article is a leak the article's own timestamp cannot catch."""
    subject = article("x3", "Acme beats earnings", age_hours=1.0)
    later = NewsLabel(
        article_id=subject.article_id,
        ticker=SYMBOL,
        entity_match="matched",
        source_time=AS_OF + timedelta(hours=1),
        first_seen_time=AS_OF + timedelta(hours=1),
        direction="positive",
        category="earnings",
        novelty="new",
        relevance="direct",
        surprise="unexpected",
        ambiguity="low",
        evidence_spans=(),
        limitations=(),
        labeler_version="test-labeler-1",
    )
    with pytest.raises(LeakedNewsError, match="label"):
        build(SYMBOL, AS_OF, (subject,), keyed(later), CONFIG)


def test_a_scheduled_future_event_time_does_not_stop_the_build() -> None:
    """D-014: `event_time` may legitimately lie ahead of `as_of`, because a
    scheduled earnings date is known weeks before it happens. Rejecting it
    would corrupt exactly the evidence the leak check exists to protect."""
    scheduled = article(
        "e1",
        "Acme to report on the fifteenth",
        age_hours=1.0,
        event_time=AS_OF + timedelta(days=14),
    )
    block = build(SYMBOL, AS_OF, (scheduled,), keyed(label(scheduled)), CONFIG)
    assert block.features["independent_source_count"] == pytest.approx(1.0)


def test_a_label_for_an_article_that_was_not_supplied_is_refused() -> None:
    """AC-5. Ignoring it would silently drop whatever the caller believed it
    was labelling."""
    present = article("k1", "Acme beats earnings")
    orphan = article("k2", "Acme wins federal contract")
    with pytest.raises(UnknownArticleError, match="k2"):
        build(SYMBOL, AS_OF, (present,), keyed(label(present), label(orphan)), CONFIG)


def test_a_label_filed_under_a_key_that_is_not_its_article_id_is_refused() -> None:
    """The mapping key and the label's own id are two claims about the same
    thing, and a disagreement means one of them is wrong."""
    subject = article("k3", "Acme beats earnings")
    with pytest.raises(LabelMismatchError, match="k3"):
        build(SYMBOL, AS_OF, (subject,), {"not-k3": label(subject)}, CONFIG)


def test_a_label_whose_first_seen_time_differs_from_its_article_is_refused() -> None:
    """The label describes one observation of one article. A different
    timestamp means it describes a different observation."""
    subject = article("k4", "Acme beats earnings", age_hours=1.0)
    other = article("k4", "Acme beats earnings", age_hours=5.0)
    with pytest.raises(LabelMismatchError, match="first_seen_time"):
        build(SYMBOL, AS_OF, (subject,), keyed(label(other)), CONFIG)


def test_a_label_about_another_ticker_is_refused() -> None:
    """A label carries its own ticker precisely so this cannot pass silently."""
    subject = article("k5", "Acme beats earnings")
    with pytest.raises(LabelMismatchError, match="OTHER"):
        build(SYMBOL, AS_OF, (subject,), keyed(label(subject, ticker="OTHER")), CONFIG)


def test_an_article_not_tagged_with_the_symbol_is_refused() -> None:
    """Whatever assembled the panel is claiming this article is about the
    symbol. A wrongly assembled panel is a defect, not a filter."""
    foreign = article("k6", "Beta beats earnings", symbols=("BETA",))
    with pytest.raises(LabelMismatchError, match="k6"):
        build(SYMBOL, AS_OF, (foreign,), keyed(label(foreign)), CONFIG)


def test_two_articles_sharing_an_id_and_disagreeing_stop_the_build() -> None:
    """Choosing between them would make the features depend on the order the
    panel was assembled in, which is the reason UNIT-022 raises as well."""
    first = article("dup", "Acme beats earnings", domain="one.example")
    second = article("dup", "Acme misses badly", domain="two.example")
    with pytest.raises(AmbiguousArticleError, match="dup"):
        build(SYMBOL, AS_OF, (first, second), keyed(label(first)), CONFIG)


def test_an_article_repeated_identically_is_not_ambiguous() -> None:
    """Two equal records are one observation seen twice, which is a duplicate
    delivery rather than a contradiction."""
    once = article("same", "Acme beats earnings")
    twice = article("same", "Acme beats earnings")
    block = build(SYMBOL, AS_OF, (once, twice), keyed(label(once)), CONFIG)
    assert block.features["independent_source_count"] == pytest.approx(1.0)


# --- failure: exclusions are named, never defaulted ----------------------


def test_an_unlabelled_article_is_flagged_and_excluded_without_a_neutral_default() -> None:
    """AC-4. A neutral default would record an opinion nobody formed."""
    labelled = article("u1", "Acme beats earnings")
    unlabelled = article("u2", "Acme wins federal contract")
    block = build(SYMBOL, AS_OF, (labelled, unlabelled), keyed(label(labelled)), CONFIG)
    assert UNLABELLED_ARTICLE in block.quality_flags
    assert block.exclusions["u2"] == EXCLUDED_UNLABELLED
    assert block.features["independent_source_count"] == pytest.approx(1.0)
    assert block.features["direction_weighted"] == pytest.approx(1.0)


def test_an_unmatched_entity_contributes_nothing_and_records_the_reason() -> None:
    """AC-3. `not_matched` is the one label that says the article is not about
    this company at all."""
    kept = article("m1", "Acme beats earnings")
    other = article("m2", "Acme Corp of Ohio files for bankruptcy", domain="local.example")
    labels = keyed(label(kept), label(other, entity_match="not_matched", direction="negative"))
    block = build(SYMBOL, AS_OF, (kept, other), labels, CONFIG)
    assert ENTITY_NOT_MATCHED in block.quality_flags
    assert block.exclusions["m2"] == EXCLUDED_NOT_MATCHED
    assert block.features["independent_source_count"] == pytest.approx(1.0)
    assert block.features["direction_weighted"] == pytest.approx(1.0)


def test_an_uncertain_entity_match_is_its_own_case_and_not_treated_as_matched() -> None:
    """AC-3. Prompt B offers three values and folding `uncertain` into either
    neighbour would record a certainty the labeler refused to state."""
    unsure = article("m3", "Acme unit under review", domain="one.example")
    block = build(SYMBOL, AS_OF, (unsure,), keyed(label(unsure, entity_match="uncertain")), CONFIG)
    assert ENTITY_UNCERTAIN in block.quality_flags
    assert ENTITY_NOT_MATCHED not in block.quality_flags
    assert block.exclusions["m3"] == EXCLUDED_UNCERTAIN
    assert dict(block.features) == {}
    assert NO_QUALIFYING_ARTICLES in block.quality_flags


def test_an_article_older_than_the_lookback_is_excluded_and_says_so() -> None:
    """The lookback bounds the window; without it the decayed count would grow
    with the depth of history rather than with the news."""
    config = NewsFeatureConfig(lookback_hours=12.0, cluster_window_hours=6.0)
    stale = article("l1", "Acme beat earnings last quarter", age_hours=48.0)
    block = build(SYMBOL, AS_OF, (stale,), keyed(label(stale)), config)
    assert block.exclusions["l1"] == EXCLUDED_OUTSIDE_LOOKBACK
    assert NO_QUALIFYING_ARTICLES in block.quality_flags


def test_an_unknown_surprise_omits_the_feature_rather_than_scoring_it_zero() -> None:
    """Prompt B allows `unknown`, and zero is the score for `expected`. Using
    it for both would make the two indistinguishable."""
    vague = article("q1", "Acme issues statement")
    block = build(SYMBOL, AS_OF, (vague,), keyed(label(vague, surprise="unknown")), CONFIG)
    assert SURPRISE_UNKNOWN in block.quality_flags
    assert "surprise_weighted" not in block.features
    assert block.features["direction_weighted"] == pytest.approx(1.0)


def test_one_unknown_surprise_among_several_leaves_the_feature_on_the_rest() -> None:
    """Dropping the whole feature for one hedged label would discard evidence
    the other labels did state."""
    known = article("q2", "Acme beats earnings", domain="one.example")
    vague = article("q3", "Acme issues statement", domain="two.example")
    labels = keyed(label(known, surprise="unexpected"), label(vague, surprise="unknown"))
    block = build(SYMBOL, AS_OF, (known, vague), labels, CONFIG)
    assert SURPRISE_UNKNOWN in block.quality_flags
    assert block.features["surprise_weighted"] == pytest.approx(1.0)


# --- no-trade: an empty block is an answer -------------------------------


def test_a_symbol_with_no_articles_yields_an_empty_flagged_block() -> None:
    """The forecast layer must read this as ineligible, not as neutral
    sentiment, which is why the flag is not optional."""
    block = build(SYMBOL, AS_OF, (), {}, CONFIG)
    assert dict(block.features) == {}
    assert block.quality_flags == (NO_ARTICLES,)
    assert block.feature_version == CONFIG.feature_version


def test_no_articles_and_all_articles_excluded_are_distinguishable() -> None:
    """An empty universe and a fully rejected one are different states, and a
    reader that cannot tell them apart cannot audit either."""
    silent = build(SYMBOL, AS_OF, (), {}, CONFIG)
    rejected_article = article("z1", "Acme Corp of Ohio files for bankruptcy")
    rejected = build(
        SYMBOL,
        AS_OF,
        (rejected_article,),
        keyed(label(rejected_article, entity_match="not_matched")),
        CONFIG,
    )
    assert dict(silent.features) == dict(rejected.features) == {}
    assert NO_ARTICLES in silent.quality_flags
    assert NO_ARTICLES not in rejected.quality_flags
    assert NO_QUALIFYING_ARTICLES in rejected.quality_flags
    assert NO_QUALIFYING_ARTICLES not in silent.quality_flags


def test_an_empty_block_still_carries_the_feature_version() -> None:
    """A no-trade decision is evidence, and evidence has to say which
    configuration produced it."""
    block = build(SYMBOL, AS_OF, (), {}, CONFIG)
    assert block.feature_version.startswith("news-")


# --- configuration is versioned ------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"half_life_hours": 12.0},
        {"cluster_window_hours": 6.0},
        {"lookback_hours": 96.0},
        {"category_weights": {"earnings": 2.0}},
    ],
)
def test_any_configuration_change_changes_the_feature_version(override: dict[str, object]) -> None:
    """AC-6. A version that did not move would let two different feature sets
    share one identity in the ledger."""
    changed = NewsFeatureConfig(**override)  # type: ignore[arg-type]
    assert changed.feature_version != CONFIG.feature_version


def test_the_feature_version_does_not_depend_on_the_order_weights_were_given() -> None:
    """Two spellings of one configuration are one configuration."""
    first = NewsFeatureConfig(category_weights={"earnings": 2.0, "product": 0.5})
    second = NewsFeatureConfig(category_weights={"product": 0.5, "earnings": 2.0})
    assert first.feature_version == second.feature_version


def test_an_unknown_category_weight_is_refused() -> None:
    """A weight for a category the label schema cannot emit is a typo that
    would otherwise sit in the configuration doing nothing."""
    with pytest.raises(ValueError, match="sentiment"):
        NewsFeatureConfig(category_weights={"sentiment": 1.0})


def test_a_negative_category_weight_is_refused() -> None:
    """A negative weight would invert the sign of direction while looking like
    an emphasis setting."""
    with pytest.raises(ValueError, match="earnings"):
        NewsFeatureConfig(category_weights={"earnings": -1.0})


def test_a_non_positive_half_life_is_refused() -> None:
    with pytest.raises(ValueError, match="half_life_hours"):
        NewsFeatureConfig(half_life_hours=0.0)


def test_a_lookback_shorter_than_the_cluster_window_is_refused() -> None:
    """Clustering could never reach across a window the lookback already cut,
    so the configuration would silently mean something else."""
    with pytest.raises(ValueError, match="lookback_hours"):
        NewsFeatureConfig(lookback_hours=4.0, cluster_window_hours=8.0)


def test_a_config_is_frozen_against_mutation_of_its_weights() -> None:
    """The version is computed once, so a mutable mapping would let the
    configuration drift away from the hash that identifies it."""
    config = NewsFeatureConfig(category_weights={"earnings": 2.0})
    with pytest.raises(TypeError):
        config.category_weights["earnings"] = 3.0  # type: ignore[index]


def test_a_block_is_frozen_against_mutation_of_its_features() -> None:
    block = two_article_block()
    with pytest.raises(TypeError):
        block.features["direction_weighted"] = 0.0  # type: ignore[index]


# --- contract guards ------------------------------------------------------


def test_a_naive_as_of_is_rejected() -> None:
    with pytest.raises(ValueError, match="as_of"):
        build(SYMBOL, datetime(2026, 6, 1, 12, 0), (), {}, CONFIG)


def test_a_blank_article_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="article_id"):
        article("   ", "Acme beats earnings")


def test_a_blank_headline_is_rejected() -> None:
    """Clustering is a function of the headline, so a blank one would make
    every unrelated blank article the same wire story."""
    with pytest.raises(ValueError, match="headline"):
        article("h1", "   ")


def test_a_headline_of_only_punctuation_is_rejected() -> None:
    """It survives the blank check and then canonicalises to nothing, which
    would collapse with every other such headline."""
    with pytest.raises(ValueError, match="headline"):
        article("h2", "--- ... ---")


def test_a_bare_string_of_symbols_is_rejected_rather_than_split_into_letters() -> None:
    """A string is iterable, and accepting one would tag the article with one
    single-letter symbol per character."""
    with pytest.raises(TypeError, match="symbols"):
        Article(
            article_id="h3",
            symbols="ACME",  # type: ignore[arg-type]
            headline="Acme beats earnings",
            summary="Acme beat consensus on both lines.",
            source_domain="wire.example",
            timestamps=FRESH.timestamps,
        )


def test_an_article_with_no_symbols_is_rejected() -> None:
    with pytest.raises(ValueError, match="symbols"):
        article("h4", "Acme beats earnings", symbols=())


def test_no_feature_value_is_ever_nan_or_infinite() -> None:
    """`EvidenceCard` rejects both outright, so producing one here would only
    move the failure to a place with less context."""
    block = two_article_block()
    for name, value in block.features.items():
        assert math.isfinite(value), name


# --- restart and determinism ---------------------------------------------


DETERMINISM_SCRIPT = """
from datetime import UTC, datetime, timedelta

from alphaledger.domain.contracts import NewsLabel, ObservationTimestamps
from alphaledger.evidence.labeler import (
    LabelerContractError,
    NewsLabeler,
    labels_by_article,
)
from alphaledger.evidence.news import Article, NewsFeatureConfig, build

AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def article(article_id, headline, age_hours, domain):
    seen = AS_OF - timedelta(hours=age_hours)
    return Article(
        article_id=article_id,
        symbols=("ACME",),
        headline=headline,
        summary=headline + ", the wire reports.",
        source_domain=domain,
        timestamps=ObservationTimestamps(
            event_time=seen,
            first_seen_time=seen,
            source_time=seen - timedelta(minutes=5),
            received_time=seen,
            feed="alpaca_news",
            as_of=seen,
        ),
    )


def label(subject, direction, category, surprise, ambiguity, entity_match):
    return NewsLabel(
        article_id=subject.article_id,
        ticker="ACME",
        entity_match=entity_match,
        source_time=subject.timestamps.source_time,
        first_seen_time=subject.timestamps.first_seen_time,
        direction=direction,
        category=category,
        novelty="new",
        relevance="direct",
        surprise=surprise,
        ambiguity=ambiguity,
        evidence_spans=(),
        limitations=(),
        labeler_version="test-labeler-1",
    )


specs = [
    ("a1", "Acme beats earnings", 0.0, "one.example", "positive", "earnings",
     "unexpected", "low", "matched"),
    ("a2", "ACME BEATS EARNINGS", 0.5, "two.example", "negative", "earnings",
     "expected", "high", "matched"),
    ("a3", "Acme names new chief financial officer", 24.0, "three.example", "neutral",
     "management", "unknown", "medium", "matched"),
    ("a4", "Acme Corp of Ohio files", 3.0, "four.example", "negative", "other",
     "expected", "high", "not_matched"),
    ("a5", "Acme unit under review", 5.0, "five.example", "mixed", "regulatory_legal",
     "partly_expected", "medium", "uncertain"),
    ("a6", "Acme wins federal contract", 10.0, "six.example", "positive", "product",
     "unexpected", "low", "matched"),
]

articles = []
labels = {}
for spec in specs:
    item = article(spec[0], spec[1], spec[2], spec[3])
    articles.append(item)
    labels[item.article_id] = label(item, spec[4], spec[5], spec[6], spec[7], spec[8])

articles.append(article("a7", "Acme quiet day", 40.0, "seven.example"))

config = NewsFeatureConfig(category_weights={"earnings": 2.0, "product": 0.5})
block = build("ACME", AS_OF, tuple(articles), labels, config)
print(config.feature_version)
for name in sorted(block.features):
    print(f"{name}={block.features[name]!r}")
print(",".join(block.quality_flags))
for name in sorted(block.exclusions):
    print(f"{name}:{block.exclusions[name]}")
"""


def in_a_new_process(hash_seed: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", DETERMINISM_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": hash_seed, "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_two_processes_produce_byte_identical_output() -> None:
    """The restart criterion, checked to the repr rather than to a tolerance,
    and under two hash seeds so any dependence on dict or set ordering shows."""
    assert in_a_new_process("0") == in_a_new_process("54321")


def test_the_determinism_fixture_actually_exercises_the_interesting_paths() -> None:
    """A byte-identical comparison of two empty blocks would pass while
    proving nothing, so the fixture is checked for content."""
    output = in_a_new_process("0")
    assert "direction_weighted=" in output
    assert "a4:" in output
    assert "a5:" in output
    assert "a7:" in output


def test_rebuilding_the_same_instant_reproduces_the_same_block() -> None:
    """A frozen run stays reproducible: the same articles and the same instant
    give the same numbers, whatever has been recorded since."""
    first = two_article_block()
    second = two_article_block()
    assert dict(first.features) == dict(second.features)
    assert first.quality_flags == second.quality_flags
    assert dict(first.exclusions) == dict(second.exclusions)


def test_the_block_does_not_depend_on_the_order_the_panel_was_assembled_in() -> None:
    """Nothing downstream controls the order a feed returns articles in."""
    forward = build(SYMBOL, AS_OF, (FRESH, DAY_OLD), keyed(FRESH_LABEL, DAY_OLD_LABEL), CONFIG)
    reverse = build(SYMBOL, AS_OF, (DAY_OLD, FRESH), keyed(DAY_OLD_LABEL, FRESH_LABEL), CONFIG)
    assert dict(forward.features) == dict(reverse.features)
    assert forward.quality_flags == reverse.quality_flags


def test_nothing_in_the_module_reads_a_clock() -> None:
    """A feature that consulted the wall clock could not be rebuilt a year
    later, which is the whole point of a point-in-time family."""
    import alphaledger.evidence.news as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    for forbidden in ("datetime.now", "datetime.utcnow", "time.time", "date.today"):
        assert forbidden not in source, forbidden


# --- the labeler seam ------------------------------------------------------
#
# These live here rather than in a test_labeler.py because UNIT-023 declares
# exactly three paths and tests/research/test_labeler.py is not one of them.
# Writing outside a unit's declared globs is what D-010 forbids.


class Honest:
    """A labeler that answers about the article it was handed."""

    def label(self, subject: Article, ticker: str, prior_context: tuple[Article, ...]) -> NewsLabel:
        return label(subject, ticker=ticker)


class AnswersAboutTheWrongArticle:
    def label(self, subject: Article, ticker: str, prior_context: tuple[Article, ...]) -> NewsLabel:
        impostor = article("some-other-article", subject.headline)
        return label(impostor, ticker=ticker)


class AnswersAboutTheWrongTicker:
    def label(self, subject: Article, ticker: str, prior_context: tuple[Article, ...]) -> NewsLabel:
        return label(subject, ticker="OTHER")


class RecordsWhatItWasGiven:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def label(self, subject: Article, ticker: str, prior_context: tuple[Article, ...]) -> NewsLabel:
        self.calls.append((subject.article_id, tuple(item.article_id for item in prior_context)))
        return label(subject, ticker=ticker)


def test_an_honest_labeler_produces_a_mapping_keyed_by_article_id() -> None:
    articles = (
        article("n1", "Acme beats earnings"),
        article("n2", "Acme wins contract", age_hours=1.0),
    )
    labels = labels_by_article(Honest(), SYMBOL, articles)
    assert sorted(labels) == ["n1", "n2"]
    assert labels["n1"].article_id == "n1"


def test_the_labeler_output_feeds_build_without_further_massaging() -> None:
    """The seam's whole purpose is that the pipeline is exercisable without a
    model, so its output has to be exactly what `build` consumes."""
    articles = (article("n3", "Acme beats earnings"),)
    block = build(SYMBOL, AS_OF, articles, labels_by_article(Honest(), SYMBOL, articles), CONFIG)
    assert block.features["direction_weighted"] == pytest.approx(1.0)


def test_a_labeler_answering_about_another_article_is_refused() -> None:
    """Filing the answer under the article it was asked about would attach a
    judgement to a story nobody judged."""
    with pytest.raises(LabelerContractError, match="some-other-article"):
        labels_by_article(AnswersAboutTheWrongArticle(), SYMBOL, (article("n4", "Acme beats"),))


def test_a_labeler_answering_about_another_ticker_is_refused() -> None:
    with pytest.raises(LabelerContractError, match="OTHER"):
        labels_by_article(AnswersAboutTheWrongTicker(), SYMBOL, (article("n5", "Acme beats"),))


def test_prior_context_holds_only_articles_already_seen_at_the_subject() -> None:
    """Prompt B says the prior context is selected without using future
    information, so a later story must never appear in an earlier one's."""
    oldest = article("n8", "Acme names chief financial officer", age_hours=10.0)
    middle = article("n7", "Acme wins contract", age_hours=5.0)
    newest = article("n6", "Acme beats earnings", age_hours=0.0)
    recorder = RecordsWhatItWasGiven()
    labels_by_article(recorder, SYMBOL, (newest, oldest, middle))
    assert recorder.calls == [("n8", ()), ("n7", ("n8",)), ("n6", ("n8", "n7"))]


def test_prior_context_is_capped_by_the_configured_limit() -> None:
    """An unbounded context would grow the prompt without bound and change the
    labels of a busy symbol for a reason that is not the news."""
    articles = tuple(
        article(f"c{index}", f"Acme story {index}", age_hours=10.0 - index) for index in range(5)
    )
    recorder = RecordsWhatItWasGiven()
    labels_by_article(recorder, SYMBOL, articles, max_prior_context=2)
    assert recorder.calls[-1] == ("c4", ("c2", "c3"))


def test_an_article_not_tagged_with_the_ticker_is_refused_before_the_model_is_called() -> None:
    """Spending a model call on an article the panel mis-assembled would pay
    for an answer that must be thrown away."""
    foreign = article("n9", "Beta beats earnings", symbols=("BETA",))
    recorder = RecordsWhatItWasGiven()
    with pytest.raises(LabelerContractError, match="n9"):
        labels_by_article(recorder, SYMBOL, (foreign,))
    assert recorder.calls == []


def test_the_protocol_is_satisfied_structurally_without_inheritance() -> None:
    """The seam exists so a test double needs no import from this module."""
    labeler: NewsLabeler = Honest()
    assert labeler.label(article("n10", "Acme beats"), SYMBOL, ()).article_id == "n10"


def test_a_chain_of_republications_beyond_the_window_still_splits() -> None:
    """AC-2, pinning the anchor-relative choice a refactor could silently undo.

    A cluster's span is bounded by the window because every article is
    compared with the anchor. Comparing each article with its predecessor
    instead would let a story republished every window-minus-a-moment chain
    without limit, and the source count would understate corroboration by
    however long the chain ran. Both readings pass every other test here.
    """
    config = NewsFeatureConfig(cluster_window_hours=48.0, lookback_hours=200.0)
    first = article("ch1", "Acme beats earnings", age_hours=80.0, domain="one.example")
    middle = article("ch2", "Acme beats earnings", age_hours=40.0, domain="two.example")
    last = article("ch3", "Acme beats earnings", age_hours=0.0, domain="three.example")
    labels = keyed(label(first), label(middle), label(last))
    block = build(SYMBOL, AS_OF, (first, middle, last), labels, config)
    assert block.features["independent_source_count"] == pytest.approx(2.0)
    assert SYNDICATION_COLLAPSED in block.quality_flags


# --- UNIT-030: the article summary --------------------------------------
#
# D-025 decides that the news family carries the summary rather than the
# headline alone, because a label derived from ten words chosen to be clicked
# on would answer a smaller question than the one the research lane exists to
# ask. This unit widens the record; UNIT-028 populates it and UNIT-029 sends it
# to a model.


def test_an_article_carries_a_summary_distinct_from_its_headline() -> None:
    """AC-1. The field is real and independent of the headline, which is the
    entire reason for the unit: a summary that could only ever restate the
    headline would buy nothing."""
    item = article("s1", "Acme beats earnings", summary="Acme beat consensus on both lines.")

    assert item.headline == "Acme beats earnings"
    assert item.summary == "Acme beat consensus on both lines."


def test_omitting_the_summary_fails_at_construction_rather_than_defaulting() -> None:
    """AC-1. A default of empty string would let an adapter drop the field and
    never learn, and every downstream label would be built from a headline
    while the record claimed to hold a summary."""
    with pytest.raises(TypeError, match="summary"):
        Article(  # type: ignore[call-arg]
            article_id="s2",
            symbols=(SYMBOL,),
            headline="Acme beats earnings",
            source_domain="wire.example",
            timestamps=FRESH.timestamps,
        )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_summary_is_refused_naming_the_field(blank: str) -> None:
    """AC-2. The Alpaca reference lists `summary` as required on every article,
    so an absent one is a feed contract violation rather than a thin article,
    and it is refused on the same terms `headline` and `article_id` already
    are."""
    with pytest.raises(ValueError, match="summary"):
        article("s3", "Acme beats earnings", summary=blank)


def test_a_summary_that_canonicalises_to_nothing_is_still_accepted() -> None:
    """AC-2, and the one place this unit deliberately does NOT copy `headline`.

    `headline` refuses a value that canonicalises to nothing, and its own error
    message says why: such a headline would cluster with every other one and
    count unrelated stories as a single wire story. That reason is about
    clustering, and clustering is a function of the headline alone. Nothing
    clusters on the summary.

    Copying the check anyway would refuse an article on how informative its
    text is, and D-025 is explicit that selecting articles on a content
    property is a selection effect correlated with the outcome, not a cleaning
    step. It names `exclude_contentless` as the thing not to reach for; a
    validator doing the same job at construction is the same mistake wearing a
    different hat, and harder to see because it would look like validation.

    The line this unit draws: refuse what the feed contract says cannot happen,
    never refuse on informativeness.
    """
    item = article("s4", "Acme beats earnings", summary="... --- ...")

    assert item.summary == "... --- ..."


def test_a_summary_equal_to_its_headline_is_ordinary_input() -> None:
    """AC-3. The Alpaca reference's own example is a headline-only article
    whose summary restates the headline, so this is the documented common case
    and not a degenerate one."""
    repeated = "Acme beats earnings"
    item = article("s5", repeated, summary=repeated)

    assert item.summary == item.headline


def test_a_summary_equal_to_the_headline_changes_no_feature_outcome() -> None:
    """AC-3, proven against UNIT-023's behaviour rather than asserted.

    Syndication clustering is exact after canonicalising the headline. Three
    outlets carrying one wire story cluster as one whether their summaries
    restate their headlines or not, because the summary is not an input to
    clustering and this unit must not quietly make it one.
    """
    headline = "Acme beats earnings"
    restated = tuple(
        article(f"s{index}", headline, domain=f"outlet{index}.example", summary=headline)
        for index in range(3)
    )
    # Same ids and same headlines, so the only difference is the summary.
    distinct = tuple(
        article(f"s{index}", headline, domain=f"outlet{index}.example", summary=f"Body {index}.")
        for index in range(3)
    )

    restated_block = build(SYMBOL, AS_OF, restated, keyed(*map(label, restated)), CONFIG)
    distinct_block = build(SYMBOL, AS_OF, distinct, keyed(*map(label, distinct)), CONFIG)

    # Pinned first, so the comparison below cannot pass by both sides being
    # equally wrong: three outlets carrying one wire story are one source.
    assert restated_block.features["independent_source_count"] == pytest.approx(1.0)
    assert restated_block.features == distinct_block.features
    assert restated_block.quality_flags == distinct_block.quality_flags


def test_the_summary_survives_a_field_by_field_reconstruction() -> None:
    """Restart. Whatever path UNIT-020 stores an observation through, the
    record has to come back whole: a field that round-trips as an empty string
    would be a silent truncation of exactly the text the labeler reads."""
    original = article("s6", "Acme beats earnings", summary="Acme beat consensus on both lines.")

    rebuilt = Article(
        article_id=original.article_id,
        symbols=original.symbols,
        headline=original.headline,
        summary=original.summary,
        source_domain=original.source_domain,
        timestamps=original.timestamps,
    )

    assert rebuilt == original
    assert rebuilt.summary == original.summary
