---
paths:
  - "src/**/execution/**/*.py"
  - "src/**/risk/**/*.py"
  - "src/**/broker/**/*.py"
  - "tests/execution/**/*.py"
  - "tests/risk/**/*.py"
  - "config/**/*risk*"
  - "config/**/*broker*"
---

# Paper execution and risk rules

- Assert the exact paper host at process start and immediately before submit.
  Reject redirects, alternate hosts, or a configurable live fallback.
- Submission requires a time-limited human arm state plus a deterministic risk
  approval token bound to the canonical order payload and frozen config hashes.
- Use one stable client order ID per intent. On timeout or transport ambiguity,
  query broker truth by that ID; never create a second intent implicitly.
- Model the complete state machine: proposed, rejected, submitted, working,
  partial, filled, cancel-pending, canceled, expired, closing, and reconciled.
- On startup and on a schedule, reconcile orders, activities, and positions.
  Broker truth outranks local state; unexplained state disarms new entries.
- New entries fail closed on stale or crossed quotes, insufficient size,
  closed/closing market, data-feed change, spread-width violation, loss limit,
  concentration limit, unknown order state, or stale risk approval.
- Test duplicate invocation, ambiguous submit, partial fill, rejection, restart,
  orphan position, stale clock/data, kill switch, and flatten failure.
- Emergency flatten is observable and idempotent; failure escalates and keeps
  entry disabled. It is never presented as guaranteed liquidation.
