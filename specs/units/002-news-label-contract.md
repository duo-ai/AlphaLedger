---
id: UNIT-002
title: Amend the news label contract to hold what the labeler emits
lane: shared
state: claimed
owner: mazwy/claude
branch: feature/002-news-label-contract
reviewer: code-reviewer
preferred_runtime: claude
depends_on: [UNIT-001]
paths: src/alphaledger/domain/contracts.py, src/alphaledger/domain/__init__.py, tests/domain/test_contracts.py
claimed_at: 2026-08-28T20:53:56Z
---

## Problem

`NewsLabel` cannot hold what a conforming labeler returns. Prompt B in
`orchestrator-system-prompt.md` emits `entity_match`, the ticker the label is
about, `unknown` for novelty and relevance, and a list of stated limitations.
The frozen record has none of them, and its `Novelty` and `Relevance` literals
exclude `unknown` outright.

Until this is fixed, every news label has to be narrowed on the way in. That
narrowing is not cosmetic: dropping `entity_match` loses the only field that
says an article is not about this company, and mapping `unknown` onto a defined
value records more certainty than the model expressed. Both make the news
family's evidence unfalsifiable in exactly the way the research rules exist to
prevent, so UNIT-023 does not start until this lands.

## Source of truth

- `project-state/DECISIONS.md`, D-016, which accepts this change and states its
  scope.
- `orchestrator-system-prompt.md`, Prompt B, its allowed values, its schema,
  and its consistency rules.
- `options-alpha-agent-design.md` sections 5.2 and 14.
- `project-state/DECISIONS.md`, D-014, for where validation belongs.

## Scope

In:

- `EntityMatch` as `matched | not_matched | uncertain`;
- `unknown` added to `Novelty` and to `Relevance`;
- `ticker`, `entity_match`, and `limitations` added to `NewsLabel`;
- the same construction discipline the record already applies: UTC timestamps,
  a tuple of strings that refuses a bare string, and no defaulted identity.

Out:

- Prompt B's consistency rules, such as `not_matched` forcing
  `relevance=incidental`. Those are enforced by the labeler adapter, which
  validates and excludes invalid model output, not by the domain type. D-014
  already draws this line: the frozen record enforces what is universally true
  of the field, and the adapter enforces what is true of its source. A record
  that raised on a rule Prompt B itself qualifies would reject labels the
  contract permits.
- Feature encoding (UNIT-023) and the labeler client itself.

## Contract

`NewsLabel` gains three fields and two literals widen. Every existing field
keeps its meaning and its validation. `EntityMatch` is exported from
`alphaledger.domain`.

The three new fields are required, not optional. A label whose entity match or
ticker is unknown to the caller is not a label this system should store, and a
default would be the caller quietly deciding.

## Acceptance criteria

- AC-1: `NewsLabel` carries `ticker`, `entity_match`, and `limitations`, and
  refuses construction when `ticker` or `entity_match` is missing.
- AC-2: `Novelty` and `Relevance` accept `unknown`, and every previously valid
  value is still valid.
- AC-3: `limitations` refuses a bare string, the same way `evidence_spans`
  does, so one limitation is not shredded into characters.
- AC-4: an empty `ticker` is refused rather than defaulted.
- AC-5: no consistency rule from Prompt B is enforced here; a `not_matched`
  label with any relevance value constructs, because that judgment belongs to
  the adapter.
- AC-6: the existing UNIT-001 tests still pass unchanged in meaning, so the
  amendment is additive rather than a rewrite.

## Test list

- success: a label carrying `matched`, a ticker, and two limitations
  constructs, and every field reads back unchanged.
- success: `novelty=unknown` and `relevance=unknown` construct, which the
  frozen record previously made impossible.
- failure: a missing or empty `ticker` is refused, naming the field.
- failure: an `entity_match` outside the three allowed values is refused.
- failure: a bare string passed as `limitations` is refused, naming the field
  and saying it would be split into characters.
- restart: the module still imports nothing outside `domain`, asserted the way
  UNIT-001 asserts it, so the amendment does not smuggle in a dependency.
- no-trade: a label with an empty `limitations` tuple and empty
  `evidence_spans` constructs, because saying nothing is a valid label rather
  than an error.

## Verification

```bash
uv run pytest tests/domain/test_contracts.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
