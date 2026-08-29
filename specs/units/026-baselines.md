---
id: UNIT-026
title: Run the required baselines and ablations
lane: research
state: available
owner: -
branch: -
reviewer: backtest-auditor
preferred_runtime: claude
depends_on: [UNIT-001, UNIT-022, UNIT-023, UNIT-024, UNIT-025, UNIT-027]
paths: src/alphaledger/forecast/baselines.py, src/alphaledger/forecast/metrics.py, tests/research/test_baselines.py, tests/research/test_metrics.py
---

## Problem

The research lane has built two feature families, a label, purged chronological
folds, and a trial registry, and it has not yet answered the one question it
exists to answer: does language data add anything to a market signal. D-002
states that claim, and nothing in the repository currently tests it.

Without this unit the project can report that a model was fitted. It cannot
report that the model beat a coin, that news contributed anything the price
family did not already carry, or that the combination is better than either
part. Those are three different claims and each needs its own control.

The failure this unit is built against is not a bug, it is a plausible number.
A model fitted on residual returns will produce an information coefficient, and
that number will be positive about half the time by construction. Reporting it
without a shuffled control, without an effective sample size that accounts for
overlapping labels, and without counting how many configurations were tried to
find it, produces a result that is indistinguishable from noise and reads like
evidence. `.claude/rules/20-research-integrity.md` requires all three controls,
and none of them exists.

## Source of truth

- `options-alpha-agent-design.md` section 7, the validation protocol.
- `options-alpha-agent-design.md` section 6 for what the model emits.
- `.claude/rules/20-research-integrity.md`, specifically the requirement to
  report random/shuffled, price-only, news-only, and combined baselines on the
  same split under one conservative cost model, and to persist per-symbol,
  sector, fold, and regime contributions.
- `project-state/DECISIONS.md` D-002, which is the claim under test.
- `src/alphaledger/forecast/splits.py` and `registry.py`, merged by UNIT-024.
- `src/alphaledger/evidence/labels.py`, merged by UNIT-027, for `uniqueness`.

## Scope

In:

- the four required arms: shuffled, price-only, news-only, and combined, each
  fitted and evaluated on identical folds through UNIT-025;
- cross-sectional information coefficient per date, its mean, and a t-statistic
  computed against an effective sample size rather than a row count;
- an effective sample size derived from the `uniqueness` weights UNIT-027
  emits, because overlapping labels are not independent observations;
- a multiple-testing adjustment that reads the trial count from UNIT-024's
  registry rather than being told it;
- hit rate and decile spread after a conservative round-trip cost;
- attribution of the result by symbol, sector, fold, and volatility regime;
- registration of every arm as a trial before its result is examined.

Out:

- the model itself (UNIT-025), the features (UNIT-022, UNIT-023), and the label
  (UNIT-027);
- option pricing, payoff, and any conversion of a forecast into an expected
  value. `.claude/rules/20-research-integrity.md` forbids turning a stress mark
  into POP or EV without a separately validated pre-expiry pricing model, and
  this unit does not have one. Everything here is measured in residual return
  space.
- threshold selection. This unit reports; it does not choose the probability
  floor or any gate. Choosing one on these outputs is a separate registered
  trial, and doing it here would be selecting on the test slice.
- the shadow book for the price-only fallback that design section 6 describes.
  That is an operational path, not a measurement.

## Contract

`alphaledger.forecast.baselines.run(folds, features, labels, arms, config,
registry, registered_at) -> BaselineReport`, pure apart from the registry
writes it is required to make, and deterministic.

`arms` is the fixed tuple `("shuffled", "price_only", "news_only",
"combined")`. Every arm sees the same folds and the same labels; only the
feature subset differs, except `shuffled`, which sees the combined features and
a label permutation.

`alphaledger.forecast.metrics.information_coefficient(predictions, outcomes)
-> float` is the Spearman rank correlation across the symbols scored on one
date. Ranking rather than levels, because a single extreme residual return
would otherwise dominate a cross-section of thirty.

`alphaledger.forecast.metrics.effective_sample_size(uniqueness) -> float` is
the sum of the uniqueness weights, not the count. A t-statistic built on the
count would be inflated by roughly the square root of the horizon.

`alphaledger.forecast.metrics.deflated_t(observed_t, trials) -> float` adjusts
for the number of configurations tried, read from the registry.

`BaselineReport` carries one `ArmResult` per arm and the fold and attribution
breakdowns. `ArmResult` carries `mean_ic`, `ic_t_statistic`,
`effective_sample_size`, `hit_rate_after_cost`, `decile_spread_after_cost`,
`trial_id`, and `quality_flags`.

Errors: `ArmMismatchError` when two arms did not see identical folds or labels,
because a comparison across different splits is not a comparison.

## Assumptions

The shuffled arm permutes labels within each date's cross-section rather than
across the whole panel. Permuting globally would destroy the time structure as
well as the signal, which makes the null too easy to beat: any model that
learned the market's drift would appear to have found alpha. Permuting within a
date leaves the cross-sectional and temporal structure intact and removes only
the symbol-to-outcome association, which is the thing under test.

The information coefficient is computed per date and then averaged, rather than
pooled across all rows at once. A pooled correlation over a panel mixes
cross-sectional and time-series variation and is dominated by whichever has
more spread, which is the standard way a panel study overstates itself.

The cost model is a fixed conservative round-trip charge in residual return
space, applied identically to every arm. It is deliberately not a fill model:
`AGENTS.md` forbids midpoint fills as a headline result, and a real fill model
belongs with the execution lane. Applying the same charge to every arm means
the comparison between arms is unaffected by its exact level, which is stated
here because it is the reason a declared constant is acceptable where a
selected one would not be.

`effective_sample_size` sums uniqueness weights. This is the standard
correction and it is still an approximation: it accounts for overlap between
labels on one symbol and not for correlation across symbols on one date. That
residual dependence makes the reported t-statistic optimistic, and the unit
says so in its output rather than implying a precision it does not have.

Every threshold here is declared, not selected.

## Acceptance criteria

- AC-1: all four arms are fitted on identical folds and identical labels, and
  an attempt to compare arms built on different folds raises. Falsified by
  passing two arms different fold sets and observing a report.
- AC-2: the shuffled arm's mean information coefficient is statistically
  indistinguishable from zero on a fixture with no signal, and the combined arm
  recovers a positive coefficient on a fixture with a planted signal. Falsified
  by a shuffled arm that scores like the real one, which would mean the
  permutation did not remove the association.
- AC-3: the permutation is within date, not across the panel. Falsified by
  observing that a shuffled label was moved to a different date.
- AC-4: `effective_sample_size` equals the sum of uniqueness weights and is
  strictly less than the row count whenever any label overlaps another.
  Falsified by observing it equal the row count on an overlapping fixture.
- AC-5: the reported t-statistic uses the effective sample size. Falsified by
  observing the same t-statistic for two fixtures identical except that one
  has overlapping labels and the other does not.
- AC-6: every arm registers a trial before its result is computed, and the
  registry's trial count is what the multiple-testing adjustment reads.
  Falsified by observing an unchanged registry count after a run, or an
  adjustment that ignores a trial registered by an earlier run.
- AC-7: the report attributes the result by symbol, sector, fold, and
  volatility regime, and the per-fold results reconcile with the aggregate.
  Falsified by an aggregate that is not recoverable from the breakdown.
- AC-8: the cost charge is applied identically to every arm, and changing it
  moves every arm's post-cost figures in the same direction. Falsified by an
  arm whose ranking against another changes when only the shared cost changes.
- AC-9: a fold in which an arm has too few scored symbols to rank is excluded
  from that arm's mean with a reason, and never contributes a zero coefficient.
  Falsified by observing a zero contribution from a fold with one symbol.
- AC-10: rerunning the same folds, features, labels, and configuration in a
  separate process reproduces every reported number, including the shuffled
  arm, whose permutation is therefore seeded from the configuration rather than
  from entropy. Falsified by any difference under two `PYTHONHASHSEED` values.
- AC-11: the report states, in its own output, that the effective sample size
  does not correct for cross-sectional dependence. Falsified by a report that
  presents the t-statistic with no such qualification.

## Test list

- success: a planted linear signal is recovered by the combined arm with a
  positive mean information coefficient, and by the shuffled arm at
  approximately zero.
- success: a fixture where only the price features carry the signal shows the
  price-only and combined arms scoring and the news-only arm at approximately
  zero, which is the ablation the whole unit exists to make.
- success: a fixture where only the news features carry the signal shows the
  mirror image, so the ablation is not merely detecting which family is larger.
- success: `information_coefficient` on a perfectly ranked cross-section is
  one, on a reversed one is minus one, and on a constant prediction is refused
  rather than reported as zero.
- success: `effective_sample_size` on non-overlapping labels equals the count.
- failure: two arms given different folds raise `ArmMismatchError` naming the
  fold that differs.
- failure: a within-date permutation never moves a label across dates, checked
  by comparing the multiset of dates before and after.
- failure: a fold with one scored symbol is excluded with a reason rather than
  contributing a coefficient, because a rank correlation over one point is
  undefined.
- failure: a run against a registry that refuses the registration propagates
  the error rather than reporting a result that was never registered.
- restart: the same inputs in a separate process reproduce every number under
  two hash seeds, the shuffled arm included.
- restart: the permutation seed is derived from the configuration, so two runs
  of one configuration shuffle identically and two configurations do not.
- no-trade: an arm whose every fold was excluded reports no coefficient and a
  reason, rather than a mean over an empty sequence.
- no-trade: a panel with no labels at all produces a report saying so, which a
  reader must not be able to mistake for a result of zero.

## Verification

```bash
uv run pytest tests/research/test_baselines.py tests/research/test_metrics.py -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Handoff notes
