---
name: submission-readiness
description: Use only when the user explicitly invokes $submission-readiness to audit the frozen AlphaLedger repository and competition artifacts before final submission and wind-down.
---

# Audit submission readiness

Do not change model, thresholds, risk, universe, strategy, or competition P&L
during this audit.

1. Read the official requirements recorded in the run manifest; flag every
   item that still depends on memory or an unrecorded page.
2. Verify clean-clone reproducibility with pinned dependencies, no secrets,
   documented setup, and frozen version hashes.
3. Verify the demo exposes current risk, orders, positions, fills, P&L,
   evidence cards, no-trades, and shadow baselines without manual ticker or
   order selection.
4. Trace every headline number and claim to an immutable artifact. Remove or
   qualify implications of live-money readiness, statistical certainty, or
   future profitability.
5. Ask `submission_reviewer` for an independent blocking audit.
6. Reconcile broker orders and positions and follow Gate G6 wind-down. Unknown
   or non-flat state blocks completion.
7. Produce a checklist with owner, evidence path, status, and deadline.

Do not submit, publish, commit, push, or alter broker state unless the user
separately asks for that action.
