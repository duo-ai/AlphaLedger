---
name: research-gate
description: Use only when the user explicitly invokes $research-gate to audit whether an AlphaLedger candidate may be frozen under Gate G3.
---

# Evaluate research Gate G3

This is an audit, not a tuning session. Do not change features, thresholds,
costs, or the test window after viewing the result.

1. Identify the immutable data, feature, prompt, model, risk, and run
   configuration versions under review.
2. Ask `quant_researcher` to challenge the hypothesis and point-in-time design.
3. Ask `backtest_auditor` to inspect the implementation and artifacts.
4. Require chronological purged results for random or shuffled, price-only,
   news-only, and combined models under one conservative cost model.
5. Inspect calibration, rank IC, directional precision, deciles, turnover,
   drawdown, concentration, threshold sensitivity, and the complete trial
   registry.
6. Verify the combined candidate improves on at least one single-family
   baseline without unacceptable deterioration elsewhere and is not driven by
   one symbol, sector, event, fold, or narrow regime.
7. Confirm all known revisions, feed limitations, and option-cost assumptions
   are disclosed.

Return `PASS`, `CONDITIONAL`, or `FAIL` with paths to decisive artifacts.
`PASS` creates no trade permission. On `FAIL`, preserve the result and follow
the documented fallback; never lower the gate.
