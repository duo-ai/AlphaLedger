---
id: UNIT-027
title: Construct forward residual return labels
lane: research
state: claimed
owner: mazwy/claude
branch: feature/027-forward-residual-labels
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-020, UNIT-021, UNIT-022, UNIT-024]
paths: src/alphaledger/evidence/labels.py, tests/research/test_labels.py
claimed_at: 2026-08-29T15:16:48Z
reviewed_by: backtest-auditor
review_verdict: block
reviewed_at: 2026-08-30T08:08:18Z
review_log: [block]
---

## Problem

Nothing in the decomposition produces the thing the model is supposed to
predict. UNIT-022 and UNIT-023 build two feature families and no outcome.
UNIT-024 consumes a `Labelled` record carrying an identity, a prediction
instant, and an outcome instant, and never a value. UNIT-025 is specified,
blocked, and cannot be fitted without labelled outcomes.

This is the highest-leverage definition in the project. The label is the
prediction target, so an error here is not one bad number among many: it
silently redefines what every downstream result means, and no amount of care in
the model or the baselines recovers it. Three specific errors are routine in
cross-sectional equity research and each would produce a backtest that looks
better than reality.

The first is measuring a return the strategy could not have captured. A
decision made from session `t`'s close cannot be filled at session `t`'s close,
so a label running from that price collects the overnight gap, which is exactly
where news is repriced and exactly the part a next-morning entry misses.

The second is treating overlapping labels as independent observations. Sampling
daily at a multi-session horizon makes consecutive labels share most of their
outcome window, so the effective sample size is a fraction of the row count and
every significance estimate built on the row count is inflated.

The third is computing a return across an unadjusted corporate action. A two
for one split reads as a fifty percent loss, and a handful of those in a
training window will dominate a least-squares fit.

## Source of truth

- `options-alpha-agent-design.md` section 5.1 for the residual definition the
  feature family already uses, and section 6 for what the model consumes.
- `options-alpha-agent-design.md` section 7 for the validation protocol.
- `.claude/rules/20-research-integrity.md`.
- `src/alphaledger/evidence/price_volume.py`, `Bar`, and the close to close
  return minus peer median definition in `_return_by_session` and `_demeaned`,
  merged by UNIT-022.
- `src/alphaledger/forecast/splits.py`, `Labelled`, merged by UNIT-024.

## Scope

In:

- the forward residual return over a configured horizon, demeaned exactly as
  UNIT-022 demeans its trailing residuals;
- a tradeable entry offset, so the label measures a return an order could
  actually have earned;
- the outcome instant at which the label first became knowable, which is what
  UNIT-024 purges against;
- average uniqueness per label, so UNIT-025 can weight overlapping observations
  rather than counting them as independent;
- exclusion, with a named reason, of a label whose horizon does not complete;
- quality flags for an implausible magnitude and for an untradeable entry.

Out:

- the model that consumes these labels (UNIT-025) and the baselines that judge
  it (UNIT-026);
- price and news features (UNIT-022, UNIT-023);
- split and dividend adjustment itself. This unit consumes adjusted bars and
  states the obligation it cannot enforce, in the same shape UNIT-012 states
  its durability obligation. See `## Assumptions`.
- triple barrier and meta labelling. A fixed horizon matches a defined-risk
  option held to a fixed expiry, and a path-dependent barrier would need a
  separately validated intraday price path this project does not have.

## Contract

`alphaledger.evidence.labels.build(symbol, decision_session, bars, config) ->
Label | None`, pure and deterministic, no clock read.

`bars` is the panel covering the symbol and its sector peers, including
sessions after `decision_session`, because a label is allowed to see the
future. That is the difference between a label and a feature and it is the
point of the two timestamps: `prediction_time` records when the decision was
made and `outcome_time` records when the outcome became knowable, and UNIT-024
purges on exactly that pair. Returning `None` is reserved for a horizon that
does not complete.

`Label` carries `label_id`, `symbol`, `prediction_time`, `outcome_time`,
`forward_residual_return`, `entry_session`, `exit_session`, `sessions_used`,
`uniqueness`, `quality_flags`, and `label_version`. It exposes
`as_labelled() -> Labelled` so UNIT-024's `walk_forward` consumes it directly
without a shim.

`alphaledger.evidence.labels.with_uniqueness(labels) -> tuple[Label, ...]`
returns the same labels carrying `uniqueness`, the average over each label's
own outcome sessions of one divided by the number of labels concurrently open
on that session for that symbol. A label overlapping nothing has uniqueness
one; two labels overlapping completely have one half each.

`LabelConfig` holds `horizon_sessions`, `entry_offset_sessions`,
`min_sector_peers`, `implausible_return`, and `sector_by_symbol`, and derives
`label_version` as a content hash the same way `FeatureConfig` derives
`feature_version`.

Errors: `InsufficientHistoryError` when the panel cannot reach the entry
session; `AmbiguousBarError` when two bars describe one session and disagree,
matching UNIT-022 rather than resolving it.

## Assumptions

The residual is the sum of per-session residual returns over the holding
window, not the compounded product. This matches the cumulative abnormal
return convention of the event-study literature and, more importantly, matches
`cumulative_abnormal_return` in UNIT-022, so the feature and the label are the
same quantity pointed in opposite directions in time. A geometric definition
would be defensible in isolation and inconsistent here.

The peer median demeaning is reimplemented rather than imported, because
`price_volume._demeaned` is private and belongs to a merged unit whose file
this unit does not own. A test pins the two against one shared fixture so they
cannot drift silently. Unifying them belongs to the later refactor unit that
owns both files, exactly as UNIT-023 records for `NewsFeatureBlock`.

`entry_offset_sessions` defaults to one. The decision is made from
`decision_session`'s close, entry is taken at the close of the next session,
and the return runs from there to the close of the session `horizon_sessions`
later. An offset of zero is permitted, because a later intraday variant may
want it, and it is flagged rather than refused so no result built on it can be
mistaken for a tradeable one.

Bars are assumed split and dividend adjusted. This unit cannot verify that: an
adjustment is invisible in a single price series, and the only detector
available is a magnitude threshold, which would be an unselected number inside
a label definition. `implausible_return` therefore flags rather than filters,
and the obligation is stated here so the adapter that feeds this unit owns it.

Every default is declared, not selected. Design section 4 requires selection on
development data, registration as a trial, and a freeze before an autonomous
session, and `label_version` exists so that selection is auditable.

## Acceptance criteria

- AC-1: the label is measured from the close of
  `decision_session + entry_offset_sessions` to the close of that session plus
  `horizon_sessions`, and never from `decision_session`'s own close when the
  offset is one. Falsified by a hand-computed fixture whose sessions have
  distinct known returns, observing which sessions the value sums.
- AC-2: the residual equals the symbol's per-session return minus the median
  peer return for that same session, summed over the holding window. Falsified
  by a fixture whose peers move and whose symbol does not, observing that the
  label is the negative of the peer median sum rather than zero.
- AC-3: `outcome_time` is the latest `first_seen_time` among the bars the label
  consumed, not the exit session's timestamp. Falsified by delaying one bar's
  `first_seen_time` past the others and observing `outcome_time` unchanged.
- AC-4: a label whose horizon does not complete, because the panel ends or the
  symbol stops trading, returns `None` with the reason recorded, and is never
  a zero return. Falsified by truncating the panel and observing a label whose
  value is zero.
- AC-5: `uniqueness` is the average over a label's outcome sessions of one over
  the concurrent label count. Falsified by two labels overlapping completely
  and observing a uniqueness other than one half, or by one isolated label and
  observing other than one.
- AC-6: an entry offset of zero sets a flag naming the return as untradeable,
  and the flag is absent at an offset of one. Falsified by observing the same
  flags at both offsets.
- AC-7: a return whose magnitude exceeds `implausible_return` is flagged and
  still emitted, so a corporate action artefact is visible rather than removed.
  Falsified by observing such a label suppressed, or emitted without the flag.
- AC-8: any change to `horizon_sessions`, `entry_offset_sessions`,
  `implausible_return`, `min_sector_peers`, or the sector map changes
  `label_version`. Falsified by changing one and observing the version hold.
- AC-9: rebuilding the same label from the same bars in a separate process
  reproduces every field byte for byte. Falsified by any difference under two
  `PYTHONHASHSEED` values.
- AC-10: `as_labelled()` produces a `Labelled` that `walk_forward` accepts, and
  whose `outcome_time` is the one AC-3 defines. Falsified by constructing a
  fold from the emitted labels and observing a label placed in a window its
  outcome instant should have purged it from.

## Test list

- success: a hand-computed fixture with known per-session returns reproduces
  the label exactly, and the sessions summed are the ones AC-1 names.
- success: a flat symbol against rising peers yields a negative label equal to
  the negated peer median sum.
- success: an entry offset of one excludes the session immediately after the
  decision, and an offset of two excludes two, so the offset means what it says.
- success: a single isolated label has uniqueness one.
- success: two labels sharing every outcome session each have uniqueness one
  half, and a partial overlap gives a value strictly between one half and one.
- failure: a panel ending before the entry session raises
  `InsufficientHistoryError` naming the symbol and the session.
- failure: two bars describing one session and disagreeing raise
  `AmbiguousBarError` rather than one being chosen.
- failure: a session with no peer observation is not demeaned and the count is
  recorded, matching UNIT-022 rather than silently treating the raw return as
  residual.
- failure: a label whose magnitude exceeds `implausible_return` carries the
  flag and still carries its value.
- failure: an entry offset of zero carries the untradeable flag.
- restart: the same panel and session in a separate process reproduce the label
  under two hash seeds.
- restart: the demeaning agrees with `price_volume`'s trailing residual on one
  shared fixture, so the two definitions cannot drift apart unnoticed.
- no-trade: a horizon that does not complete returns `None` with a reason, and
  a caller that treats `None` as zero is refused by the type rather than by
  convention.
- no-trade: a symbol with no bars at all returns `None` rather than raising, so
  an empty universe member is an ordinary outcome.

## Verification

```bash
uv run pytest tests/research/test_labels.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
