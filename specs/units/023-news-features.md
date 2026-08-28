---
id: UNIT-023
title: Encode point-in-time news into features
lane: research
state: available
owner: -
branch: -
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-002, UNIT-003, UNIT-020]
paths: src/alphaledger/evidence/labeler.py, src/alphaledger/evidence/news.py, tests/research/test_news.py
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
