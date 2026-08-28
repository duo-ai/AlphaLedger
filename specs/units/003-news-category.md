---
id: UNIT-003
title: Enumerate the news category on the label
lane: shared
state: merged
owner: pablo/claude
branch: feature/003-news-category
reviewer: code-reviewer
preferred_runtime: claude
depends_on: [UNIT-002]
paths: src/alphaledger/domain/contracts.py, src/alphaledger/domain/__init__.py, tests/domain/test_contracts.py
claimed_at: 2026-08-28T22:06:46Z
reviewed_by: code-reviewer
review_verdict: clear
reviewed_at: 2026-08-28T22:27:21Z
---

## Problem

`category` is the only enumerated field on `NewsLabel` that is not checked at
run time. It accepts any string, including an empty one and any text a model
happens to return.

UNIT-002 is what made this inconsistent. Before it, no enumerated field was
checked at run time, so a bare `str` category was uniform with its neighbours.
After it, `direction`, `novelty`, `relevance`, `surprise`, `ambiguity`, and
`entity_match` are all validated and `category` alone is not, which reads as a
deliberate exemption rather than the oversight it is.

The consequence is not cosmetic. UNIT-023 encodes the category into a feature.
An unvalidated category reaching that encoding produces a feature keyed on
whatever a model said, which is the unfalsifiable evidence D-016's rationale
argues against for the other fields.

## Source of truth

- `orchestrator-system-prompt.md`, Prompt B, allowed values and schema.
- `options-alpha-agent-design.md` section 5.2, the same nine categories.
- `project-state/DECISIONS.md`, D-016, which set the pattern this follows.
- `specs/units/002-news-label-contract.md`, review round one, medium finding.

## Scope

In:

- `Category` as the nine values Prompt B allows: earnings, guidance, analyst,
  regulatory_legal, product, financing_ma, management, macro_industry, other;
- `CATEGORIES` exported beside the other allowed-value tuples;
- `category` added to the run-time validation loop `NewsLabel` already runs.

Out:

- any other field. This unit closes one gap and does not reopen D-016.
- category weighting or encoding, which is UNIT-023.

## Contract

`NewsLabel.category` narrows from `str` to `Category`. `CATEGORIES` is exported
from `alphaledger.domain`. Nothing else changes.

## Acceptance criteria

- AC-1: every one of the nine Prompt B categories constructs.
- AC-2: a category outside the nine is refused, naming the field, in the same
  form the other enumerated fields already use.
- AC-3: an empty category is refused rather than treated as `other`. Choosing
  `other` on the caller's behalf is the labeler's judgment, not the record's.
- AC-4: no other field's behaviour changes, and the UNIT-002 tests pass
  unchanged.

## Test list

- success: each of the nine categories constructs and reads back.
- failure: an unknown category is refused, naming the field and listing the
  allowed values.
- failure: an empty or whitespace category is refused rather than defaulted.
- failure: a category differing only in case, for example `Earnings`, is
  refused, because normalising it here would hide a labeler that is not
  following its schema.
- restart: the domain package still imports nothing outside `domain`, asserted
  the way UNIT-001 asserts it.
- no-trade: a label carrying `other` constructs, because "none of these fits"
  is a real answer and not a missing value.

## Verification

```bash
uv run pytest tests/domain/test_contracts.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

- 2026-08-29 pablo/claude: the declared paths omitted
  `src/alphaledger/domain/__init__.py`, while the Contract section requires
  `CATEGORIES` to be exported from `alphaledger.domain`, which is that file.
  The unit could not satisfy its own contract inside its own globs. Paths
  widened. Same defect class that stopped UNIT-010 on its first dispatch, so it
  is worth asking of any new intake: does the declared path set contain
  everything the contract names?
- 2026-08-29 pablo/claude: `code-reviewer` returned conditional. The success
  test iterated `CATEGORIES` and asserted each value constructs, which cannot
  fail because `_one_of` checks membership in that same tuple. A typo would
  have kept the suite green while every real label was rejected. Replaced with
  a literal pin, matching the pattern already used for `ENTITY_MATCHES`, and
  proved by mutation: the pin fails on a deliberate `regulatory-legal`, the old
  test passes.
- 2026-08-29 pablo/claude: design section 5.2 spells these in prose as
  `regulatory/legal`, `financing/M&A` and `macro/industry`, while Prompt B's
  schema block uses the underscore forms. The code follows Prompt B, because
  that is the literal wire format the labeler returns. Recorded so the next
  reader does not read the prose as a conflict.
- 2026-08-29 pablo/claude: a unit's `paths` govern code, but every unit is also
  expected to append here. The declared globs do not include the unit's own
  intake, so writing a handoff note is technically outside them. Worth fixing
  in the template rather than per unit.

