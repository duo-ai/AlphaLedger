"""Point-in-time news features, from design section 5.2.

UNIT-022 built the price family as the control in a comparison that had no
other side. This is the other side. Its whole value is being a strict function
of labels that were knowable at `as_of`, because the comparison it exists to
support is only falsifiable if neither family can see the future.

Four rules hold everywhere in this module.

Nothing here judges an article. The labels arrive already formed, and every
number below is a weighted count of them. The moment feature construction
depended on a model's judgement the result would stop being reproducible, so
the model's contribution is confined to `NewsLabel` and the seam in
`labeler.py`.

An observation that was not knowable at `as_of` stops the build. It is never
filtered out, because a silent drop leaves a caller believing a cutoff was
honoured that was never checked. Both the article and its label are checked:
a label is knowledge too, and one produced from a later observation of the
same article is a leak the article's own timestamp cannot catch. `event_time`
is deliberately exempt, per D-014, because a scheduled earnings date is known
weeks ahead and rejecting it would corrupt exactly the evidence the check
protects.

A feature that cannot be computed is absent from the output and named in a
quality flag, never an imputed zero. Zero is already the score for `expected`
surprise and for `neutral` direction, so reusing it for absence would make a
hedged label and a stated one indistinguishable. `EvidenceCard` rejects NaN
outright, so a zero denominator, which is routine here, is handled rather than
produced.

Decay half life, category weights, the clustering window, and the lookback are
configuration rather than judgement. They are versioned, and `feature_version`
changes whenever any of them changes. None of them has been selected on
development data yet; design section 4 requires that selection, registration as
a trial, and a freeze before any autonomous session, and `feature_version`
exists so the selection is auditable when it happens.

Nothing reads a clock. Rebuilding a past `as_of` from cached articles has to
give the same numbers a year later, which it cannot do if anything inside
depends on when it ran.

What the syndication collapse can and cannot do:

Design section 5.2 requires that a headline is never treated as corroborated
merely because several outlets carried the same wire story. Clustering here is
exact after canonicalisation: the headline is normalised, case folded, stripped
of everything that is not a letter, a digit, or a space, and hashed, and two
articles cluster when their hashes match and they fall inside the configured
window of each other.

That is deliberately less than a similarity metric could do. An outlet that
rewrites the headline will not cluster, and the source count will overstate
corroboration by one for each such rewrite. The alternative is a similarity
threshold, and a threshold is a number that would have to be selected on
development data before it could be trusted; adopting one now would put an
unregistered trial inside the feature definition, which is what
`.claude/rules/20-research-integrity.md` exists to prevent. The exact match is
honest about what it knows, and `SYNDICATION_COLLAPSED` records when it fired
so an auditor can see whether it ever did.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from alphaledger.domain.contracts import CATEGORIES, NewsLabel, ObservationTimestamps, require_utc

__all__ = [
    "ENTITY_NOT_MATCHED",
    "ENTITY_UNCERTAIN",
    "EXCLUDED_NOT_MATCHED",
    "EXCLUDED_OUTSIDE_LOOKBACK",
    "EXCLUDED_UNCERTAIN",
    "EXCLUDED_UNLABELLED",
    "NO_ARTICLES",
    "NO_QUALIFYING_ARTICLES",
    "SURPRISE_UNKNOWN",
    "SYNDICATION_COLLAPSED",
    "UNLABELLED_ARTICLE",
    "ZERO_DENOMINATOR",
    "AmbiguousArticleError",
    "Article",
    "LabelMismatchError",
    "LeakedNewsError",
    "NewsFeatureBlock",
    "NewsFeatureConfig",
    "UnknownArticleError",
    "build",
]

NO_ARTICLES = "no_articles"
NO_QUALIFYING_ARTICLES = "no_qualifying_articles"
UNLABELLED_ARTICLE = "unlabelled_article"
ENTITY_NOT_MATCHED = "entity_not_matched"
ENTITY_UNCERTAIN = "entity_uncertain"
SYNDICATION_COLLAPSED = "syndication_collapsed"
SURPRISE_UNKNOWN = "surprise_unknown"
ZERO_DENOMINATOR = "zero_denominator"

# An exclusion reason is recorded per article, so a reader can tell which
# article was dropped and why. A flag alone would say only that something was.
EXCLUDED_UNLABELLED = "unlabelled"
EXCLUDED_NOT_MATCHED = "entity_not_matched"
EXCLUDED_UNCERTAIN = "entity_uncertain"
EXCLUDED_OUTSIDE_LOOKBACK = "outside_lookback"

# Direction is the article's apparent company-specific economic implication,
# per Prompt B, so it is signed. `mixed` and `neutral` both score zero because
# neither states a direction; they remain distinguishable in the label itself,
# which is where a later unit can separate them if the data justifies it.
DIRECTION_SCORE = {"positive": 1.0, "negative": -1.0, "mixed": 0.0, "neutral": 0.0}

# Surprise has no score for `unknown`. Prompt B emits it when the text does not
# say whether the event differed from an expectation, and `expected` already
# owns zero, so scoring both the same would erase the distinction the label was
# careful to make. An article whose surprise is unknown is left out of this
# feature alone and stays in every other.
SURPRISE_SCORE = {"unexpected": 1.0, "partly_expected": 0.5, "expected": 0.0}

AMBIGUITY_SCORE = {"low": 0.0, "medium": 0.5, "high": 1.0}

_NOT_CANONICAL = re.compile(r"[^0-9a-z ]+")
_RUNS_OF_SPACE = re.compile(r" +")

SECONDS_PER_HOUR = 3600.0


class LeakedNewsError(ValueError):
    """An article or a label in the input was not knowable at `as_of`."""


class UnknownArticleError(ValueError):
    """A label refers to an article that was not supplied."""


class LabelMismatchError(ValueError):
    """A label and the article it is filed against disagree."""


class AmbiguousArticleError(ValueError):
    """Two articles share an id and disagree.

    Raised rather than resolved, for the same reason UNIT-022 refuses two
    disagreeing bars: choosing between them would make the features depend on
    the order the panel was assembled in.
    """


def _symbols(value: Iterable[object]) -> tuple[str, ...]:
    """Copy the tickers an article was tagged with, refusing a bare string.

    Typed as `Iterable[object]` rather than `tuple[str, ...]` so the run-time
    checks below are reachable. The annotation on the field is a static claim,
    and these values arrive from a feed adapter, which is exactly where a
    static claim does not hold. `contracts._strings` exists for the same
    reason: a bare string is iterable and would be shredded into one
    single-character ticker per letter.
    """
    if isinstance(value, str | bytes):
        raise TypeError(
            "symbols must be a sequence of tickers, not a bare string. A string is "
            f"iterable and would tag one symbol per character; got {value!r}"
        )
    symbols = tuple(str(item).strip() for item in value)
    if not symbols or any(not item for item in symbols):
        raise ValueError(
            f"symbols must name at least one ticker and none may be blank; got "
            f"{value!r}. An untagged article cannot be attributed to a company"
        )
    return symbols


@dataclass(frozen=True, slots=True)
class Article:
    """One news article as it was observed, with its point-in-time contract.

    Defined here rather than in `domain/contracts.py` for the same reason
    UNIT-022 defines `Bar` in its own module: the frozen domain records are
    another unit's file, and an article is an input to feature construction
    rather than a record the ledger holds.
    """

    article_id: str
    symbols: tuple[str, ...]
    headline: str
    source_domain: str
    timestamps: ObservationTimestamps

    def __post_init__(self) -> None:
        for name in ("article_id", "source_domain"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must be recorded; it is never defaulted")
        if not isinstance(self.timestamps, ObservationTimestamps):
            raise TypeError(
                "timestamps must be an ObservationTimestamps; the point-in-time contract "
                f"is not optional. Got {type(self.timestamps).__name__}"
            )
        object.__setattr__(self, "symbols", _symbols(self.symbols))
        if not str(self.headline).strip():
            raise ValueError("headline must be recorded; clustering is a function of it")
        if not _canonical_headline(self.headline):
            raise ValueError(
                f"headline {self.headline!r} canonicalises to nothing, so it would cluster "
                "with every other such headline and count them as one wire story"
            )


@dataclass(frozen=True, slots=True)
class NewsFeatureConfig:
    """Frozen news configuration. Any change changes `feature_version`.

    Every default here is declared, not selected. Design section 4 requires
    selection on development data, registration as a trial, and a freeze
    before an autonomous session; none of that has happened.
    """

    half_life_hours: float = 24.0
    cluster_window_hours: float = 48.0
    lookback_hours: float = 168.0
    category_weights: Mapping[str, float] = MappingProxyType({})
    feature_version: str = field(init=False, default="")

    def __post_init__(self) -> None:
        for name in ("half_life_hours", "cluster_window_hours", "lookback_hours"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"{name} must be a real number of hours; got {value!r}")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(
                    f"{name} must be a positive, finite number of hours; got {value!r}. A "
                    "non-positive value would make the decay or the window meaningless"
                )
            object.__setattr__(self, name, float(value))
        if self.lookback_hours < self.cluster_window_hours:
            raise ValueError(
                f"lookback_hours {self.lookback_hours} is shorter than cluster_window_hours "
                f"{self.cluster_window_hours}. Clustering could never reach across a window "
                "the lookback already cut, so the configuration would silently mean "
                "something other than what it says"
            )
        object.__setattr__(self, "category_weights", self._weights())
        object.__setattr__(self, "feature_version", self._version())

    def _weights(self) -> Mapping[str, float]:
        """Every category carries a weight, defaulting to one.

        Materialising the full set rather than defaulting at lookup keeps the
        version hash a statement about all nine categories, so adding a
        category later cannot silently leave the version unchanged.
        """
        given = dict(self.category_weights)
        unknown = sorted(set(given) - set(CATEGORIES))
        if unknown:
            raise ValueError(
                f"category_weights names {', '.join(unknown)}, which the label schema "
                f"cannot emit. Allowed categories are {', '.join(CATEGORIES)}"
            )
        resolved: dict[str, float] = {}
        for name in CATEGORIES:
            value = given.get(name, 1.0)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"category_weights[{name}] must be a real number; got {value!r}")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"category_weights[{name}] must be finite; got {value!r}")
            if number < 0.0:
                raise ValueError(
                    f"category_weights[{name}] must not be negative; got {value!r}. A "
                    "negative weight would invert the sign of direction while looking "
                    "like an emphasis setting"
                )
            resolved[name] = number
        return MappingProxyType(resolved)

    def _version(self) -> str:
        body = {
            "half_life_hours": repr(self.half_life_hours),
            "cluster_window_hours": repr(self.cluster_window_hours),
            "lookback_hours": repr(self.lookback_hours),
            "category_weights": {k: repr(v) for k, v in sorted(self.category_weights.items())},
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return "news-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class NewsFeatureBlock:
    """The news features for one symbol at one instant, with why any are missing.

    This duplicates the shape of UNIT-022's `FeatureBlock` deliberately.
    Unifying the two means editing `price_volume.py`, which belongs to another
    unit, and the coordination model forbids reaching across. The duplication
    is recorded in the intake for a later refactor unit that owns both files.

    `exclusions` is the field `FeatureBlock` has no counterpart for. A price
    feature is missing because the arithmetic could not be done; a news article
    is excluded because of something the label said, and the reader needs to
    know which article and which reason.
    """

    symbol: str
    as_of: datetime
    features: Mapping[str, float]
    quality_flags: tuple[str, ...]
    exclusions: Mapping[str, str]
    feature_version: str


def build(
    symbol: str,
    as_of: datetime,
    articles: Iterable[Article],
    labels: Mapping[str, NewsLabel],
    config: NewsFeatureConfig,
) -> NewsFeatureBlock:
    """Return the point-in-time news block for `symbol` at `as_of`.

    `articles` is the panel the caller has already restricted to `as_of`, and
    every one of them must be tagged with `symbol`. `labels` is keyed by
    `article_id`. Anything that was not knowable at `as_of`, and any
    disagreement between a label and its article, stops the build.
    """
    cutoff = require_utc(as_of, "as_of")
    held = _articles(articles, symbol, cutoff)
    _check_labels(labels, held, symbol, cutoff)

    if not held:
        return _empty(symbol, cutoff, config, (NO_ARTICLES,), {})

    flags: list[str] = []
    exclusions: dict[str, str] = {}
    kept = _kept(held, labels, cutoff, config, flags, exclusions)
    if not kept:
        flags.append(NO_QUALIFYING_ARTICLES)
        return _empty(symbol, cutoff, config, tuple(sorted(set(flags))), exclusions)

    clusters = _clusters(kept, config, flags)
    features = _features(clusters, labels, cutoff, config, flags)
    return NewsFeatureBlock(
        symbol=symbol,
        as_of=cutoff,
        features=MappingProxyType(features),
        quality_flags=tuple(sorted(set(flags))),
        exclusions=MappingProxyType(dict(sorted(exclusions.items()))),
        feature_version=config.feature_version,
    )


def _empty(
    symbol: str,
    as_of: datetime,
    config: NewsFeatureConfig,
    flags: tuple[str, ...],
    exclusions: Mapping[str, str],
) -> NewsFeatureBlock:
    """An empty block is an answer.

    The forecast layer reads it as ineligible rather than as neutral
    sentiment, which is why `NO_ARTICLES` and `NO_QUALIFYING_ARTICLES` are
    distinct: a symbol nobody wrote about and a symbol whose every article was
    rejected are different states, and a reader that cannot tell them apart
    cannot audit either.
    """
    return NewsFeatureBlock(
        symbol=symbol,
        as_of=as_of,
        features=MappingProxyType({}),
        quality_flags=flags,
        exclusions=MappingProxyType(dict(sorted(exclusions.items()))),
        feature_version=config.feature_version,
    )


def _articles(articles: Iterable[Article], symbol: str, cutoff: datetime) -> dict[str, Article]:
    """Articles by id, rejecting anything unknowable or wrongly assembled."""
    held: dict[str, Article] = {}
    for item in articles:
        if symbol not in item.symbols:
            raise LabelMismatchError(
                f"{item.article_id} is tagged {item.symbols} and not {symbol}, so it does "
                "not belong to this symbol's panel. Whatever assembled the panel is wrong"
            )
        if item.timestamps.first_seen_time > cutoff:
            raise LeakedNewsError(
                f"{item.article_id}: first_seen_time "
                f"{item.timestamps.first_seen_time.isoformat()} is later than as_of "
                f"{cutoff.isoformat()}, so this article was not knowable when the "
                "features are claimed to have been built"
            )
        seen = held.get(item.article_id)
        if seen is None:
            held[item.article_id] = item
        elif seen != item:
            raise AmbiguousArticleError(
                f"two articles share the id {item.article_id} and disagree. Choosing "
                "between them would make the features depend on the order the panel "
                "was assembled in"
            )
    return held


def _check_labels(
    labels: Mapping[str, NewsLabel],
    held: Mapping[str, Article],
    symbol: str,
    cutoff: datetime,
) -> None:
    """Every label must be about a supplied article, this symbol, and the past."""
    for key in sorted(labels):
        label = labels[key]
        if key != label.article_id:
            raise LabelMismatchError(
                f"a label is filed under {key!r} but says it is about "
                f"{label.article_id!r}. One of those two claims is wrong"
            )
        for name in ("first_seen_time", "source_time"):
            stamp = getattr(label, name)
            if stamp > cutoff:
                raise LeakedNewsError(
                    f"the label for {label.article_id} has {name} {stamp.isoformat()}, "
                    f"later than as_of {cutoff.isoformat()}. A label is knowledge too, "
                    "and one drawn from a later observation is a leak the article's own "
                    "timestamp cannot catch"
                )
        article = held.get(label.article_id)
        if article is None:
            raise UnknownArticleError(
                f"a label refers to article {label.article_id!r}, which was not supplied. "
                "Ignoring it would silently drop whatever the caller believed it "
                "was labelling"
            )
        if label.ticker != symbol:
            raise LabelMismatchError(
                f"the label for {label.article_id} is about {label.ticker} and not "
                f"{symbol}, so it cannot contribute to this symbol's features"
            )
        for name in ("first_seen_time", "source_time"):
            stamp = getattr(label, name)
            observed = getattr(article.timestamps, name)
            if stamp != observed:
                raise LabelMismatchError(
                    f"the label for {label.article_id} has {name} {stamp.isoformat()} but "
                    f"the article was observed with {observed.isoformat()}. The label "
                    "describes a different observation of the same article"
                )


def _kept(
    held: Mapping[str, Article],
    labels: Mapping[str, NewsLabel],
    cutoff: datetime,
    config: NewsFeatureConfig,
    flags: list[str],
    exclusions: dict[str, str],
) -> Sequence[Article]:
    """The articles that contribute, with every exclusion named.

    Exclusion happens before clustering so an excluded article can never
    become a cluster's representative and supply its label.
    """
    horizon = config.lookback_hours * SECONDS_PER_HOUR
    kept: list[Article] = []
    for article_id in sorted(held):
        article = held[article_id]
        age = (cutoff - article.timestamps.first_seen_time).total_seconds()
        if age > horizon:
            exclusions[article_id] = EXCLUDED_OUTSIDE_LOOKBACK
            continue
        label = labels.get(article_id)
        if label is None:
            exclusions[article_id] = EXCLUDED_UNLABELLED
            flags.append(UNLABELLED_ARTICLE)
            continue
        if label.entity_match == "not_matched":
            exclusions[article_id] = EXCLUDED_NOT_MATCHED
            flags.append(ENTITY_NOT_MATCHED)
            continue
        if label.entity_match == "uncertain":
            # Prompt B offers three values, and folding `uncertain` into either
            # neighbour would record a certainty the labeler refused to state.
            # Excluding it fails closed; down-weighting it would need a weight
            # nobody has selected on data.
            exclusions[article_id] = EXCLUDED_UNCERTAIN
            flags.append(ENTITY_UNCERTAIN)
            continue
        kept.append(article)
    return kept


def _clusters(
    kept: Sequence[Article], config: NewsFeatureConfig, flags: list[str]
) -> Sequence[Article]:
    """One representative article per wire story, oldest first.

    Articles sharing a canonical headline are grouped, and inside a group a new
    cluster starts whenever an article falls further than the window from the
    one that anchors the cluster it would otherwise join. The representative is
    the earliest article in the cluster: the wire story is the observation, and
    a reprint's own label must not displace it.
    """
    window = config.cluster_window_hours * SECONDS_PER_HOUR
    grouped: dict[str, list[Article]] = {}
    for article in kept:
        grouped.setdefault(_canonical_hash(article.headline), []).append(article)

    representatives: list[Article] = []
    collapsed = False
    for digest in sorted(grouped):
        ordered = sorted(
            grouped[digest],
            key=lambda item: (item.timestamps.first_seen_time, item.article_id),
        )
        anchor = ordered[0]
        size = 0
        for article in ordered:
            gap = article.timestamps.first_seen_time - anchor.timestamps.first_seen_time
            if gap.total_seconds() > window:
                collapsed = collapsed or size > 1
                representatives.append(anchor)
                anchor = article
                size = 1
                continue
            size += 1
        collapsed = collapsed or size > 1
        representatives.append(anchor)

    if collapsed:
        flags.append(SYNDICATION_COLLAPSED)
    return sorted(
        representatives,
        key=lambda item: (item.timestamps.first_seen_time, item.article_id),
    )


def _features(
    clusters: Sequence[Article],
    labels: Mapping[str, NewsLabel],
    cutoff: datetime,
    config: NewsFeatureConfig,
    flags: list[str],
) -> dict[str, float]:
    """Encode the surviving labels into the feature mapping.

    Every ratio uses one weight, the recency decay times the category weight,
    so the features are commensurable: a change to a category weight moves all
    of them the same way rather than some of them.
    """
    decays: list[float] = []
    scored: list[tuple[NewsLabel, float]] = []
    for article in clusters:
        label = labels[article.article_id]
        seconds = (cutoff - article.timestamps.first_seen_time).total_seconds()
        decay = 0.5 ** (seconds / SECONDS_PER_HOUR / config.half_life_hours)
        decays.append(decay)
        scored.append((label, decay * config.category_weights[label.category]))

    total = sum(weight for _, weight in scored)
    features: dict[str, float] = {
        "news_volume_decayed": total,
        "independent_source_count": float(len(clusters)),
        "recency_weight_max": max(decays),
    }

    if total <= 0.0:
        # Every surviving article carries a zero category weight, so no ratio
        # has a denominator. The count features above still stand: the stories
        # exist, they were simply weighted out of the scored features.
        flags.append(ZERO_DENOMINATOR)
        return features

    features["direction_weighted"] = _ratio(scored, total, DIRECTION_SCORE, "direction")
    features["ambiguity_weighted"] = _ratio(scored, total, AMBIGUITY_SCORE, "ambiguity")
    features["novelty_new_share"] = _share(scored, total, "novelty", "new")
    features["relevance_direct_share"] = _share(scored, total, "relevance", "direct")

    known = [(label, weight) for label, weight in scored if label.surprise in SURPRISE_SCORE]
    if len(known) < len(scored):
        flags.append(SURPRISE_UNKNOWN)
    known_total = sum(weight for _, weight in known)
    if known and known_total > 0.0:
        features["surprise_weighted"] = _ratio(known, known_total, SURPRISE_SCORE, "surprise")
    return features


def _ratio(
    scored: Sequence[tuple[NewsLabel, float]],
    total: float,
    table: Mapping[str, float],
    field_name: str,
) -> float:
    """A weight-normalised score, bounded by the extremes of `table`."""
    return sum(table[getattr(label, field_name)] * weight for label, weight in scored) / total


def _share(
    scored: Sequence[tuple[NewsLabel, float]],
    total: float,
    field_name: str,
    wanted: str,
) -> float:
    """The weighted share of labels whose `field_name` equals `wanted`."""
    matched = sum(weight for label, weight in scored if getattr(label, field_name) == wanted)
    return matched / total


def _canonical_headline(headline: str) -> str:
    """Normalise a headline so restyling by an outlet does not split a story.

    Compatibility normalisation folds typographic variants, case folding
    removes an outlet's capitalisation house style, and dropping everything
    that is not a letter, a digit, or a space removes its punctuation style.
    What survives is the words, in order.
    """
    normalised = unicodedata.normalize("NFKC", headline).casefold()
    stripped = _NOT_CANONICAL.sub(" ", normalised)
    return _RUNS_OF_SPACE.sub(" ", stripped).strip()


def _canonical_hash(headline: str) -> str:
    """A stable digest of the canonical headline.

    `hashlib` rather than the builtin `hash`, whose per-process salt would make
    this value differ between two runs of one frozen configuration. Today that
    salt would not change the block, because the digest is only a grouping key
    and the representatives are re-sorted by time and id before they are used.
    The digest is stable anyway so that a later unit may record a cluster
    identity in the ledger without first having to discover that it could not.
    """
    return hashlib.sha256(_canonical_headline(headline).encode("utf-8")).hexdigest()
