---
id: UNIT-027
title: Construct forward residual return labels
lane: research
state: merged
owner: mazwy/claude
branch: feature/027-forward-residual-labels
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-020, UNIT-021, UNIT-022, UNIT-024]
paths: src/alphaledger/evidence/labels.py, tests/research/test_labels.py
claimed_at: 2026-08-29T15:16:48Z
reviewed_by: backtest-auditor
review_verdict: clear
reviewed_at: 2026-08-30T10:45:57Z
review_log: [block, clear]
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

Errors: `InsufficientHistoryError` when the panel itself cannot reach the
entry session, meaning no symbol in it could be labelled; `AmbiguousBarError`
when two bars describe one session and disagree, matching UNIT-022 rather than
resolving it; `DuplicateLabelError` when `with_uniqueness` is handed one label
identity twice.

A symbol whose own bars stop while the rest of the panel keeps trading is not
an error. That is a delisting, and AC-4 makes it a `None`. The discriminator is
whether the symbol's last session precedes the panel's last session, which the
caller cannot compute for itself, because it would have to know which of its
symbols stopped early and that is the question it is asking.

`DuplicateLabelError` is a deliberate asymmetry against `_series`, which accepts
a bar repeated identically. A repeated bar is idempotent; a repeated label is
not, because it makes the label concurrent with itself and halves the very
uniqueness weight being computed.

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
- AC-4: a label whose horizon does not complete returns a bare `None` and is
  never a zero return, whether the horizon runs past the end of the panel or the symbol
  stops trading first, and including the case where it stops on the decision
  session itself so no entry session exists for it. Falsified by holding the
  panel at twenty sessions, truncating one symbol to six, deciding on that
  symbol's last session, and observing anything other than `None`. The earlier
  falsification, truncating the panel and observing a zero, could not
  distinguish `None` from a raise, since neither is zero; that is why round one
  raised here and the test written from this criterion still passed. The phrase
  "with the reason recorded" is struck from this criterion rather than left
  aspirational: `build` returns `Label | None` and no channel carries a reason,
  so the words described nothing observable. Distinguishing a panel that ended
  from a symbol that delisted would widen the return type, which is a change to
  the contract UNIT-024 and UNIT-025 consume and belongs to whichever unit
  needs the distinction, not to this one.
- AC-4a: a panel that is itself too short to reach the entry session raises
  `InsufficientHistoryError`, because no symbol in it could be labelled and the
  caller built it wrong. Falsified by truncating every symbol in the panel and
  observing a `None`. AC-4 and AC-4a are the two halves of one condition and
  are separated because the observable outcome differs.
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
- failure: a panel in which every symbol ends before the entry session raises
  `InsufficientHistoryError` naming the symbol and the session (AC-4a).
- failure: a symbol whose own bars end before the entry session, while the rest
  of the panel keeps trading, returns `None` rather than raising (AC-4). This
  line and the one above were a single line in round one, which asserted the
  raise for both cases and so contradicted AC-4's prose.
- failure: a symbol that stops partway through the horizon, with the entry
  session present and the exit session absent, returns `None` (AC-4).
- failure: a panel holding one symbol and no peers, ending before the entry
  session, still raises, since the delisting discriminator compares the symbol
  against the panel and the two are equal by construction there (AC-4a).
- failure: `with_uniqueness` handed one label twice raises
  `DuplicateLabelError` rather than silently weighting it one half.
- leakage: a peer missing two consecutive in-window sessions makes its next
  return reach back to a bar outside the window; a revision to that bar moves
  `outcome_time` (AC-3).
- leakage: the label from that same gapped panel is purged from a fold whose
  training window would otherwise have held it, built with
  `alphaledger.forecast.splits.walk_forward` (AC-10). This is AC-10's own
  stated falsification, which round one never implemented.
- coverage: a three-peer cross-section where the median and the mean differ
  pins AC-2's median wording; a two-peer fixture cannot, since the median of
  two numbers is their mean.
- coverage: a return landing exactly on `implausible_return` is not flagged,
  pinning the bound as exclusive.
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
- no-trade: a horizon that does not complete returns a bare `None`, and a
  caller that treats `None` as zero is refused by the type rather than by
  convention. "With a reason" is struck here for the same cause as in AC-4:
  `build` returns `Label | None` and no channel carries a reason, so the phrase
  named nothing a test could observe.
- no-trade: a symbol with no bars at all returns `None` rather than raising, so
  an empty universe member is an ordinary outcome.

## Verification

```bash
uv run pytest tests/research/test_labels.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes

Implemented 2026-08-29 by mazwy/claude. Forty tests, quality gate green.

### The three quant decisions this unit actually makes

The entry offset. `entry_offset_sessions` defaults to one, so the label runs
from the close of the session after the decision. The excluded move is the
overnight gap, which is where news is repriced, so including it is the single
easiest way to manufacture an alpha that does not survive contact with a
broker. The fixture makes the size of that error visible on purpose: the same
panel scores 0.20 at offset one and 0.60 at offset zero. Offset zero is
permitted and carries `untradeable_entry`.

Uniqueness weights. Daily sampling at a multi-session horizon makes consecutive
labels share most of their outcome window, so counting rows counts the same
information repeatedly and every significance estimate built on that count is
inflated. `with_uniqueness` gives each label the average over its own outcome
sessions of one over the concurrent count, per symbol and session. Two symbols
resolving on the same dates stay independent, because sharing a date is not
sharing an outcome. This unit measures the weight; UNIT-025 has to carry it
into the fit, and if it does not, the weights are decoration.

An incomplete horizon is `None`, never zero. A delisting scored as a flat
return converts the worst outcome in the dataset into an average one, which is
the most flattering error available. The return type carries this rather than a
convention, so a caller has to handle it.

### Consistency with the feature family, and how it is enforced

The label demeans against the sector peer median session by session, which is
UNIT-022's definition, and sums rather than compounds, which matches
`cumulative_abnormal_return` and `residual_return_5s`. A geometric definition
would be defensible alone and inconsistent here.

`_returns` and `_peers` duplicate `price_volume._return_by_session` and
`_peers`, because those are private members of a merged unit whose file this
unit does not own. `test_the_demeaning_agrees_with_the_price_feature_family`
pins the two against one shared fixture: the label's one-session forward
residual must equal the price family's `residual_return_1s` for that same
session. Unification belongs to the refactor unit owning both files, exactly as
UNIT-023 records for `NewsFeatureBlock`.

`NO_PEER_DATA`, `SECTOR_FALLBACK_MARKET`, and `AmbiguousBarError` are
re-exported from UNIT-022 rather than redefined, so one condition keeps one
name and an `except` clause cannot be silently partial.

### What this unit cannot do

It cannot verify that its bars are split and dividend adjusted. An adjustment
is invisible in a single price series, and the only available detector is a
magnitude threshold, which would be an unselected number inside a label
definition. `implausible_return` therefore flags and never filters, so an
artefact stays visible rather than being quietly removed, and the adjustment
obligation belongs to whichever adapter feeds this unit. That is the same shape
as the durability obligation UNIT-012 states and cannot enforce.

Every default is declared, not selected. The horizon of five sessions, the
offset of one, the two-peer floor, and the half implausibility bound have not
been chosen on data. Design section 4 requires selection, registration as a
trial, and a freeze before an autonomous session; `label_version` exists so the
selection is auditable when it happens, and it is inside `label_id` so
relabelling under a changed definition cannot collide with the old labels.

### Verification actually run

`uv run pytest tests/research/test_labels.py -q`, the full `uv run pytest`,
`ruff check`, `ruff format --check`, `mypy src` under strict, and
`scripts/verify_harness.sh`. All green.

Twelve deliberate defects were injected one at a time. Nine were caught
immediately. Two survived and both were real coverage gaps, now closed and
each verified to fail against the mutation that exposed it: dropping peer bars
from the outcome instant, which no test on the symbol's own timestamps could
see, and removing `label_version` from `label_id`, which would let two
definitions share one address. A twelfth mutation did not apply because its
anchor was not unique; it was rewritten and then caught. The current count is
twelve injected, twelve caught, zero survivors, which is a statement about
these twelve and not about the suite as a whole.

That distinction is drawn deliberately. On UNIT-023 the same claim was read as
the stronger one, and `backtest-auditor` found two survivors beyond the ones
recorded by running its own probes.

### Round two, addressing the `backtest-auditor` block

The round one verdict was `block` on two findings, both demonstrated on
constructed input rather than argued from reading. Both are fixed, and the
reviewer's own counterexamples are now tests.

**Finding 1, `outcome_time` did not cover a peer bar reached through a gap.**
`_residual_sum` computed each peer's returns over that peer's whole series, so
a peer missing sessions inside the holding window produced a multi-session
return whose predecessor bar could sit outside the window entirely.
`_outcome_time` scanned only the window, so that bar was consumed and never
counted, and a revision to it left `outcome_time` unmoved. UNIT-024 would then
admit the label into a window the purge exists to keep it out of.

The correction is structural rather than a patch. `_returns` now returns a
`_Move` carrying the two bars each return was measured across, `_residual_sum`
accumulates the `first_seen_time` of every bar it actually consumed and returns
the outcome instant alongside the value, and `_outcome_time` is deleted. There
is no longer a second function walking the window that could disagree with the
first, so the class of defect is closed rather than the instance.

The economic half of the same finding is deliberately not fixed here, matching
the reviewer's own routing. A stale multi-session peer return still enters the
median unflagged, because correcting it changes the number and would break
`test_the_demeaning_agrees_with_the_price_feature_family`, which pins this
module against UNIT-022's `_return_by_session`. Extending what round one
recorded: `own` has the identical defect and it was not named. `window` is a
slice of the symbol's own session list, so a symbol missing three mid-window
sessions contributes a return spanning eight calendar sessions to a window
called five, against a peer cross-section measured over one. Both halves belong
to the refactor unit that owns both files, and both are now written down so
that unit inherits the whole problem rather than half of it. `_returns` says so
in its own docstring.

**Finding 2, a delisting raised instead of returning `None`.** This was a
specification defect before it was a code defect, which is why the intake
changed above and not only the module. AC-4's prose made a symbol that stops
trading a `None`, while the test list asserted a raise for the same input, and
the same author wrote both, so writing the test first did not catch it. AC-4's
stated falsification ("truncate the panel and observe a label whose value is
zero") could not distinguish `None` from a raise, since neither is zero.

AC-4 is now split from AC-4a on the discriminator that actually separates the
two cases: whether this symbol's last session precedes the panel's last
session. A panel too short for anything still raises, and the existing test
covering it still passes unchanged, because its fixture truncates every symbol.

**Also addressed, from the reviewer's independent mutation probes.** All three
of the surviving mutations it reported are now killed, each verified by
re-running the exact mutation against the suite. `statistics.median` swapped for
`statistics.mean` survived because the fixture had exactly two peers and the
median of two numbers is their mean; a three-peer test now separates them.
`abs(value) > config.implausible_return` swapped for `>=` survived on the
boundary; a test now pins the bound as exclusive. A duplicate `label_id` passed
to `with_uniqueness` silently produced 0.5 for both copies; it now raises
`DuplicateLabelError`, and the intake records why that is refused where
`_series` tolerates an identically repeated bar.

AC-10's stated falsification, never implemented in round one, now exists: it
builds a real fold with `alphaledger.forecast.splits.walk_forward` from the
gapped panel and asserts the label is purged from a training window that would
otherwise have held it. It is the end-to-end form of Finding 1 and fails on the
round one code.

### Verification actually run, round two

The three regression tests were confirmed to fail on the round one code before
anything was changed, each for its own reason rather than by collateral error.
Four mutations were then run against the fixed code, one at a time, restoring
the file between each: dropping the peer predecessor from the consumed set
fails the gap test, removing the delisting branch fails the delisting test, and
the reviewer's median and boundary mutations fail their new tests. All four are
caught.

The claim these numbers support is bounded: four mutations aimed at this
round's four changes, all caught. It is not a statement about the suite as a
whole, and the round one note above already records why that distinction is
drawn.
