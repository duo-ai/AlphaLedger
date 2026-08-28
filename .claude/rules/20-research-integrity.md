---
paths:
  - "research/**/*.py"
  - "src/**/research/**/*.py"
  - "src/**/features/**/*.py"
  - "src/**/forecast/**/*.py"
  - "tests/research/**/*.py"
  - "config/**/*model*"
  - "config/**/*feature*"
---

# Research integrity rules

- Assert point-in-time availability at feature construction, not only in a
  notebook narrative. Store source and first-seen timestamps and reject future
  observations.
- Universe membership is lagged and reproducible. Never filter historical rows
  using current tradability, optionability, constituents, or future liquidity.
- Separate fitting, calibration/threshold selection, and locked testing in
  chronological order; purge overlapping labels by at least the horizon.
- Register every attempted configuration before examining its final result.
  A failed or abandoned trial remains in the registry.
- Report random/shuffled, price-only, news-only, and combined baselines using
  the same split and conservative cost model.
- Persist per-symbol, sector, event-category, fold, and regime contributions so
  aggregate performance cannot hide concentration.
- Tests include deliberately leaked fixtures that the pipeline must reject.
- Never convert a stress mark into POP or EV without a separately validated
  pre-expiry pricing model.
