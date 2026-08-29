---
id: UNIT-023
title: Encode point-in-time news into features
lane: research
state: merged
owner: mazwy/claude
branch: feature/023-news-features
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-002, UNIT-003, UNIT-020]
paths: src/alphaledger/evidence/labeler.py, src/alphaledger/evidence/news.py, tests/research/test_news.py
claimed_at: 2026-08-29T14:28:20Z
reviewed_by: backtest-auditor
review_verdict: clear
reviewed_at: 2026-08-29T14:58:12Z
review_log: [clear]
---

## Problem

UNIT-022 built the price family as the control in a comparison that has no
other side. Without a news family there is nothing to answer the question the
whole project rests on, which is whether language data adds anything to a
market signal. The family also has to be built deterministically around the
label, because the moment feature construction depends on an LLM's judgment the
result stops being reproducible and the comparison stops being falsifiable.

## The contract conflict, and how it was resolved

Two sources of truth disagreed about the label schema. The conflict is
recorded here because it shaped this unit, and it is resolved by D-016 and
UNIT-002. This unit depends on UNIT-002 and on UNIT-003, which closes the one
enumerated field UNIT-002 left unvalidated, so `coord.py` refuses a claim until
both merge; the dependency does the enforcing rather than a note.

`options-alpha-agent-design.md` section 14, frozen in
`src/alphaledger/domain/contracts.py` by UNIT-001, defines `NewsLabel` with
`Novelty` as `new | follow_up | duplicate` and `Relevance` as `direct |
industry_linked | incidental`. It has no field for entity match and no field
for the ticker the label is about.

`orchestrator-system-prompt.md`, Prompt B, is the labeler's actual contract. It
allows `novelty: unknown` and `relevance: unknown`, requires
`entity_match: matched | not_matched | uncertain`, carries the `ticker`, and
adds a `limitations` list. Its consistency rules depend on those values: a
label may only claim `duplicate` when republication is established, and must
otherwise say `unknown`, and `not_matched` forces `relevance=incidental` with
no company-direction claim.

A conforming labeler therefore emits values the frozen record cannot hold. The
permissive resolution, mapping `unknown` onto a defined value and dropping
`entity_match`, would record more certainty than the model expressed and would
lose the one field that says an article is not about this company at all. That
is the reading this repository forbids taking silently.

D-016 accepts the first reading: the frozen contracts are amended to hold what
the labeler emits, rather than the labeler narrowed to fit them. UNIT-002 makes
that change. Prompt B's consistency rules stay with the labeler adapter, per
D-014, so this unit consumes labels that are already valid and does not
re-judge them.

## Source of truth

- `options-alpha-agent-design.md` sections 5.2 and 4.
- `orchestrator-system-prompt.md`, Prompt B and its consistency rules.
- `.claude/rules/20-research-integrity.md`.
- `src/alphaledger/domain/contracts.py`, `NewsLabel` and `EvidenceCard`.

## Scope

In:

- a `NewsLabeler` protocol, so the deterministic pipeline is testable without
  a network call or a model;
- deterministic duplicate clustering and syndication detection, so one wire
  story republished by many outlets counts once;
- independent source counting on top of that clustering;
- ticker mapping and entity-match handling;
- encoding labels into a feature mapping as of an instant, with recency decay
  and category weights as versioned configuration;
- quality flags for an unlabelled article, an uncertain entity match, and an
  article excluded for either reason.

Out:

- the LLM client, its caching by article and prompt hash, and its output
  validation. Those need credentials and a network boundary and belong to a
  later unit.
- price features (UNIT-022), the forecast (UNIT-025), and the baselines that
  compare the two families (UNIT-026).

## Contract

`alphaledger.evidence.news.build(symbol, as_of, articles, labels, config) ->
NewsFeatureBlock`, pure and deterministic, no clock read, consuming articles
already restricted to `as_of` exactly as UNIT-022 consumes bars. `articles`
carry the `ObservationTimestamps` contract; `labels` are `NewsLabel` records
keyed by article. The block's `.features` is the `Mapping[str, float]` that
populates `EvidenceCard.news_features`.

`NewsFeatureBlock` duplicates the shape of UNIT-022's `FeatureBlock`
deliberately. Unifying them means editing `price_volume.py`, which belongs to
another unit, and the coordination model forbids reaching across. Record the
duplication and unify it in a later refactor unit that owns both files.

## Acceptance criteria

- AC-1: an article first seen after `as_of` stops the build rather than being
  filtered, matching UNIT-021 and UNIT-022.
- AC-2: one wire story republished by many outlets contributes one source, not
  one per outlet.
- AC-3: an article whose label says the entity is not matched contributes
  nothing to the features and is recorded as excluded, with the reason.
- AC-4: an article with no label yields a flag naming it, never a neutral
  default label.
- AC-5: a label referring to an article absent from the input is refused rather
  than ignored.
- AC-6: recency decay, category weights, and the clustering window are
  configuration, and any change to them changes `feature_version`.

## Test list

- success: a hand-computed fixture reproduces each feature, with the decay
  applied to a known article age.
- success: five outlets carrying one wire story produce a source count of one,
  and two genuinely independent reports produce two.
- failure: an article first seen after `as_of` is rejected, naming the article
  and the field. This is the leaked fixture the research rules require.
- failure: a label whose `article_id` matches no supplied article is rejected,
  naming it.
- failure: an unlabelled article sets a flag and is excluded, and the block
  does not fall back to neutral.
- failure: an entity match of `not_matched` excludes the article and records
  the reason, and `uncertain` is treated as its own case rather than as
  matched.
- restart: rebuilding the same `as_of` from the same articles and labels in a
  separate process reproduces the block byte for byte.
- no-trade: a symbol with no articles at or before `as_of` yields an empty
  block with a flag, which the forecast layer must read as ineligible rather
  than as neutral sentiment.

## Verification

```bash
uv run pytest tests/research/test_news.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

Implemented 2026-08-29 by mazwy/claude. Sixty-one tests, quality gate green.

### What the features are, and why these

Design section 5.2 specifies the label schema and requires deterministic
"label-to-feature encoding", but it does not enumerate the features. Eight are
emitted, each a weighted count of labels and nothing else:
`news_volume_decayed`, `independent_source_count`, `recency_weight_max`,
`direction_weighted`, `ambiguity_weighted`, `novelty_new_share`,
`relevance_direct_share`, and `surprise_weighted`.

Every ratio divides by one weight, the recency decay times the category
weight, so the family is commensurable: changing a category weight moves all
of them the same way rather than some of them. None of these eight has been
selected on data, and neither has any constant behind them.

### Decisions taken here that a later unit may need to revisit

Clustering is exact after canonicalisation, not fuzzy. An outlet that rewrites
a headline rather than restyling it will not cluster, so
`independent_source_count` overstates corroboration by one per rewrite. The
alternative needs a similarity threshold, and a threshold selected on nothing
is an unregistered trial sitting inside a feature definition. The limitation is
stated in the module docstring rather than hidden.

`entity_match: uncertain` excludes the article, with its own reason and its own
flag. Prompt B offers three values and folding `uncertain` into either
neighbour would record a certainty the labeler refused to state. Down-weighting
it instead would need a weight nobody has selected.

`surprise: unknown` drops that one article from `surprise_weighted` alone and
keeps it in every other feature, because `expected` already scores zero and
reusing zero for absence would make a hedged label and a stated one
indistinguishable.

`NO_ARTICLES` and `NO_QUALIFYING_ARTICLES` are separate flags. A symbol nobody
wrote about and a symbol whose every article was rejected are different states,
and the forecast layer has to read both as ineligible for different reasons.

The label's own timestamps are checked against `as_of` and against the
article's, which AC-1 does not ask for. A label is knowledge too, and one drawn
from a later observation of the same article is a leak the article's timestamp
cannot catch.

### Bounded and unbounded features, and why there is no cap

Six of the eight features are bounded by construction. The four ratios and the
two shares divide by the same total weight, so `direction_weighted` lies in
[-1, 1] and `ambiguity_weighted`, `novelty_new_share`, `relevance_direct_share`
and `surprise_weighted` lie in [0, 1]. `recency_weight_max` lies in (0, 1]
because a decay weight is `0.5 ** (age / half_life)` and the age of a surviving
article is never negative.

Two are not bounded. `news_volume_decayed` is a sum of weights, so it grows
with the number of independent stories and with any category weight above one.
`independent_source_count` is a raw cluster count.

Neither is winsorized, and that is a deliberate difference from UNIT-022, which
does winsorize. The price family's limits are two numbers that would have to be
selected on development data, and UNIT-022 declares them as unselected defaults
for exactly that reason. Adding a third and a fourth here would add two more
unselected thresholds to a family that already has four, and a cap chosen by
eye is the kind of number `.claude/rules/20-research-integrity.md` exists to
keep out of a feature definition.

The exposure this leaves is real and is stated rather than hidden: a symbol
with an unusually heavy news day contributes a larger value than any other
feature can, so a model fit on these features without its own scaling would let
that day dominate. The lookback bounds it in one direction, since only articles
inside the window count at all, but nothing bounds it above. UNIT-025 either
scales the family or registers a winsorization limit as a trial. That decision
belongs with whoever fits the model, because the right bound depends on the
estimator, and this unit has no basis to guess it.

### Open questions this unit did not settle

Configuration lives in a frozen `NewsFeatureConfig` dataclass rather than in
`config/`, because `config/**` is outside this unit's declared path globs and
UNIT-004's drift test pins `config/feature.toml` to `price_volume.py`. D-017
argues the other way: a value a ledger reader needs in order to understand a
decision should be committed and hashed. Promoting these four settings to
`config/` belongs to the unit that owns both files. The conflict is named here
rather than resolved silently.

`NewsFeatureBlock` duplicates the shape of UNIT-022's `FeatureBlock`, as the
contract above anticipated, and adds `exclusions`, which has no price
counterpart. Unification belongs to a later refactor unit owning both files.

The half life, cluster window, lookback, and all nine category weights are
declared defaults. Design section 4 requires selection on development data,
registration as a trial, and a freeze before any autonomous session. That gate
is untouched; `feature_version` exists so the selection is auditable when it
happens.

Nothing here has met a real feed. Every value is proven self consistent against
fixtures, not against Alpaca, and no article has ever been labelled by a model,
since the LLM client is deliberately out of scope.

### Verification actually run

`uv run pytest tests/research/test_news.py -q`, the full `uv run pytest`,
`ruff check`, `ruff format --check`, `mypy src` under strict, and
`scripts/verify_harness.sh`. All green.

Twelve deliberate defects were injected one at a time to check the tests catch
what they claim. Ten failed a named test. Two survived and both were acted on:
disabling the article leak check passed, because the leaked fixture also
carried a label whose own leak check caught it first, so AC-1 was covered only
by accident. A leaked article carrying no label is now its own test, and it
fails against that mutation. Replacing `hashlib` with the salted builtin `hash`
also survived, and that one is correct: the digest is a grouping key that is
never emitted, and representatives are re-sorted by time and id afterwards, so
the output genuinely does not change. The docstring claimed otherwise and has
been corrected to say what is actually true.

### Review round one, backtest-auditor, 2026-08-29

Verdict clear. All six acceptance criteria hold and were independently
falsified, the gate was re-run rather than taken on trust, and the eight
feature values, the D-014 exemption, and the two-process determinism were
checked by hand and by an independent subprocess run.

One finding, non-blocking, acted on. The reviewer ran four mutations of its own
and found two survivors beyond the two recorded above, which means the claim in
those notes describes the twelve defects that were injected and should not be
read as a statement about the suite as a whole. It has been left as written
rather than revised, because it was true of what it described, and this
paragraph is the correction.

The reportable survivor: `_clusters` compares every article with the cluster
anchor, and rewriting it to compare each article with its predecessor instead,
which is chained or transitive windowing, passed the entire suite. The two
readings differ materially. Three articles sharing a headline at eighty, forty
and zero hours before `as_of` under a forty-eight hour window give two
independent sources under anchor-relative windowing and one under chained,
because each consecutive gap is inside the window while the span is not.

Anchor-relative is the correct reading and is what was implemented: it bounds a
cluster's span to the configured window, whereas chained windowing lets a story
republished every window-minus-a-moment chain without limit and understate
corroboration by however long the chain runs. So this was a missing regression
guard on correct behaviour rather than a live defect, and it bears on AC-2
because a later refactor of `_clusters` could flip the semantics silently.
`test_a_chain_of_republications_beyond_the_window_still_splits` now pins it,
and it is the only test in the file that fails against that mutation.

The second survivor, `age > horizon` widened to `age >= horizon` on the
lookback boundary, was filed by the reviewer as out of scope and is not acted
on. Both operators keep the article at or before `as_of`, so it is not a
leakage control, and no numbered acceptance criterion governs the exact
boundary. Recorded here so a later reader does not rediscover it and assume it
was missed.
