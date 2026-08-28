---
name: research-gate
description: Evaluate whether the current alpha candidate may be frozen for autonomous paper trading under Gate G3.
disable-model-invocation: true
---

# Evaluate research Gate G3

This is an audit, not a tuning session. Do not change features, thresholds,
costs, or the test window after viewing the result.

1. Identify the exact immutable data, feature, prompt, model, risk, and run
   configuration versions under review.
2. Invoke `quant-researcher` for the hypothesis and point-in-time design.
3. Invoke `backtest-auditor` for the implementation and artifacts.
4. Require chronological purged results for random/shuffled, price-only,
   news-only, and combined models under the same conservative cost model.
5. Inspect calibration, rank IC, directional precision, deciles, turnover,
   drawdown, concentration, threshold sensitivity, and the complete trial
   registry.
6. Verify the combined candidate improves on at least one single-family
   baseline without an unacceptable deterioration elsewhere and is not driven
   by one symbol, sector, event, fold, or narrow regime.
7. Confirm all known data revisions, feed limitations, and option-cost
   assumptions are disclosed.

Return `PASS`, `CONDITIONAL`, or `FAIL` with links or paths to the decisive
artifacts. `PASS` creates no trade permission by itself. On `FAIL`, preserve the
result and follow the documented fallback; never lower the gate.
