---
id: UNIT-030
title: Carry the article summary on the news record
lane: research
state: claimed
owner: mazwy/claude
branch: feature/030-article-summary
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-023]
paths: src/alphaledger/evidence/news.py, tests/research/test_news.py
claimed_at: 2026-08-30T10:41:18Z
---

## Problem

`Article`, merged by UNIT-023, carries `article_id`, `symbols`, `headline`,
`source_domain`, and `timestamps`. It carries no article text beyond the
headline. Prompt B, the labeler contract in `orchestrator-system-prompt.md`,
lists a summary among its inputs, and UNIT-029 cannot assemble the payload that
contract specifies from what the record holds today.

A headline is roughly ten words chosen to be clicked on. The research lane
exists to test whether news carries forward information, and testing that on
headlines alone would answer a smaller question than the one being asked.

## Source of truth

- `project-state/DECISIONS.md`, D-025, which decides this and records the
  schema facts behind it.
- `project-state/DECISIONS.md`, D-024, for the news schema and the revision
  rule.
- `orchestrator-system-prompt.md`, Prompt B, for what the labeler consumes.
- `specs/units/023-news-features.md`, whose file this amends.

## Scope

In:

- One new field on `Article` holding the article summary.
- Validation consistent with the rest of the record, and with what the feed
  guarantees.
- Updating UNIT-023's existing tests and any construction site inside
  `evidence/news.py` so the record still round-trips.

Out:

- Fetching the summary from Alpaca (UNIT-028). This unit widens the record;
  it does not populate it from a feed.
- Sending the summary to a model (UNIT-029).
- The `content` field, which D-025 deliberately defers. It is HTML, it is
  fetched only under `include_content`, and it enlarges an untrusted input
  surface. Adding it is a separate decision, not an extension of this one.
- Changing clustering, features, or any other UNIT-023 behaviour. A wider
  record must not quietly become a different feature family.

## Contract

`alphaledger.evidence.news.Article` gains:

```python
summary: str
```

The Alpaca reference lists `summary` as required on every article, so a record
without one is a feed contract violation rather than a normal case. Validate it
the way the record already validates `headline`, and read the existing
`__post_init__` before choosing: match what is there rather than inventing a
second convention in the same class.

One thing the reference makes explicit and the implementer must not treat as a
fault: its own example shows a headline-only article whose summary restates the
headline. A summary equal to the headline is normal input, not an error, and
nothing here may reject or deduplicate on that basis.

## Acceptance criteria

- AC-1: `Article` carries `summary`, and constructing one without it fails at
  construction rather than defaulting to an empty string. A silent default
  would let a caller lose the field and never learn.
- AC-2: `summary` is validated on the same terms `headline` already is, proven
  by a test that feeds each rejected shape the headline rejects and observes
  the same refusal, naming the field.
- AC-3: a summary identical to the headline is accepted and changes no
  clustering or feature outcome, proven against the existing UNIT-023
  behaviour rather than asserted.
- AC-4: every existing test in `tests/research/test_news.py` still passes, and
  none was weakened to accommodate the new field. A test that previously
  constructed an `Article` now supplies a summary; it does not drop an
  assertion.
- AC-5: no clustering, feature, or timestamp behaviour changes. The diff
  touches the record, its validation, and test construction, and nothing else.

## Test list

- success: an `Article` with a distinct summary constructs and round-trips.
- success: a summary equal to the headline constructs, and syndication
  clustering groups exactly as it did before the field existed.
- failure: omitting `summary` refuses at construction, naming the field.
- failure: each shape `headline` refuses, `summary` refuses identically.
- restart: an `Article` reconstructed from a recorded observation carries the
  summary, so the field survives whatever path UNIT-020 stores it through.
- no-trade: an article that yields no usable signal is unchanged by this unit.
  Widening the record must not alter which articles are usable.

## Verification

```bash
uv run pytest tests/research/test_news.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
