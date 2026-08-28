---
name: submission-readiness
description: Audit the frozen AlphaLedger repository and competition artifacts before final submission and wind-down.
origin: AlphaLedger
disable-model-invocation: true
---

# Audit submission readiness

Do not change model, thresholds, risk, universe, strategy, or competition P&L
during this audit.

1. Read the current official requirements copied into the run manifest; flag
   any item that still depends on memory or an unrecorded webpage.
2. Verify the repository is reproducible from a clean clone with pinned
   dependencies, no secrets, documented setup, and frozen version hashes.
3. Verify the demo exposes current risk, orders, positions, fills, P&L,
   evidence cards, no-trades, and shadow baselines without manual ticker or
   order selection.
4. Trace every headline metric and claim to an immutable artifact. Remove or
   qualify anything that implies live-money readiness, statistical certainty,
   or future profit.
5. Invoke `submission-reviewer` for an independent blocking audit.
6. Reconcile broker orders and positions and follow Gate G6 wind-down. Unknown
   or non-flat state blocks completion.
7. Produce a final checklist with owner, evidence path, status, and deadline.

Do not submit, publish, commit, push, or alter broker state unless the user
separately asks for that action.
