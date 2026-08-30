---
id: UNIT-030
title: Carry the article summary on the news record
lane: research
state: in_review
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
- AC-2: `summary` is required and refused when blank, on the same terms
  `article_id`, `source_domain`, and `headline` already are, naming the field.
  Falsified by constructing an article with an empty or whitespace summary and
  observing it accepted.
- AC-2a: `summary` is NOT refused for canonicalising to nothing, which is the
  one check `headline` carries that this field does not. Falsified by
  constructing an article whose summary is punctuation only and observing a
  refusal.

  AC-2 originally read "validated on the same terms `headline` already is,
  proven by a test that feeds each rejected shape the headline rejects". Read
  literally against the merged code that is unsatisfiable without contradicting
  D-025, which is why it is split rather than implemented as written.
  `headline` refuses two shapes, and its second refusal states its own reason:
  a headline canonicalising to nothing would cluster with every other such
  headline and collapse unrelated stories into one wire story. Clustering is a
  function of the headline alone, so the reason does not transfer to a field
  nothing clusters on.

  Copying the check anyway would refuse an article on how informative its text
  is. D-025 records that selecting articles on a content property correlated
  with the outcome is a selection effect and not a cleaning step, and names
  `exclude_contentless` as the thing not to reach for. A validator doing that
  work at construction is the same mistake in a place where it would read as
  rigour. The reference's own example is a headline-only article whose summary
  restates its headline, so an uninformative summary is documented ordinary
  input.

  The line this draws, and the reason the split clarifies the criterion rather
  than weakening it: refuse what the feed contract says cannot happen, never
  refuse on informativeness. A blank summary is the first; a terse one is the
  second.
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
- failure: a blank or whitespace-only summary is refused, naming the field
  (AC-2).
- failure: a summary that canonicalises to nothing is accepted, because
  refusing it would be a D-025 selection effect wearing a validator's hat
  (AC-2a). This line replaces "each shape `headline` refuses, `summary`
  refuses identically", which contradicted D-025.
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

`Article` gains one required field, `summary`, placed next to `headline`
because the two are read together and validated as a pair.

### The one place this unit does not copy `headline`

Written up because it is a deliberate divergence from the criterion as
originally worded, not an omission. AC-2 above records the amendment; this is
the reasoning behind it.

`headline` carries two refusals. The first, that it must be non-blank, is the
record's ordinary convention and `summary` copies it exactly. The second, that
it must not canonicalise to nothing, states its own reason in its own error
message: such a headline would cluster with every other one and collapse
unrelated stories into a single wire story. That reason is about clustering,
clustering is computed from the headline alone, and nothing clusters on the
summary.

Copying it anyway would have refused an article on how much its text says.
D-025 records that selecting articles on a content property correlated with the
outcome is a selection effect rather than a cleaning step, and names
`exclude_contentless` as the thing not to reach for. A validator doing that same
work inside `__post_init__` is the same mistake in the one place it would read
as rigour instead of as filtering, and it would be invisible afterwards: the
articles would simply not be in the dataset, with no flag and no count.

The distinction the unit settles on is between the two things a refusal can
mean. Refuse what the feed contract says cannot happen, which is why a blank
summary raises: the Alpaca reference lists `summary` as required on every
article, so an absent one is a broken contract and failing loudly is right.
Never refuse on informativeness, which is why a punctuation-only summary is
accepted. The reference's own example is a headline-only article whose summary
restates its headline, so terse summaries are documented ordinary input rather
than a degenerate case to be cleaned away.

### Verification actually run

`uv run pytest tests/research/test_news.py`, 71 passing against a 62 passing
baseline, so nine tests were added and none removed. The full `uv run pytest`
at 599, `ruff check`, `ruff format --check`, and `mypy src` under strict across
29 files. All green.

Every existing construction site was widened rather than defaulted around: the
shared `article` factory, the bare-symbols test that builds an `Article`
directly, and the fixture embedded in the determinism subprocess. The factory
gained a default so existing tests read unchanged, and that default is
deliberately distinct from the headline so the ordinary fixture exercises a
real summary. `Article` itself has no default, which is AC-1. A search of `src`
and `tests` finds no other construction site.

Three mutations were run, one at a time, restoring the file between each. Each
is caught. Giving `summary` a default and moving it past `timestamps`, the real
shape of a silent default, fails the AC-1 test. Removing the blank check fails
three tests. Copying the canonicalisation check onto `summary` fails the AC-2a
test, which is the point of that test: the divergence is pinned, so a later
reader restoring symmetry between the two fields is told why not.

One earlier probe was miscounted and is recorded rather than quietly dropped.
Adding a default to `summary` in place produced zero `FAILED` lines, which
looked like a survivor and was not: a defaulted field followed by two
non-defaulted ones is a dataclass definition error, so the suite failed at
collection with an `ERROR` the grep was not counting. The mutation was rewritten
into the shape above and is caught.

The claim these numbers support is bounded to these three mutations against
this unit's own change. It is not a statement about the suite as a whole.
