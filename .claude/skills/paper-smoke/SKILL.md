---
name: paper-smoke
description: Run the human-controlled, one-contract AlphaLedger paper-order lifecycle smoke test after dry-run evidence is complete.
origin: AlphaLedger
argument-hint: "[dry-run|submit]"
disable-model-invocation: true
---

# Paper lifecycle smoke test

Treat `$ARGUMENTS` as `dry-run` unless it is exactly `submit`. This skill may
never use raw Alpaca MCP order tools.

## Preconditions for both modes

1. Start at the repository root and read Gate G0/G1 in
   `hackathon-build-plan.md`.
2. Confirm the application reports paper mode and the exact host
   `https://paper-api.alpaca.markets` without printing credentials.
3. Confirm market clock, options permission, feed mode, working orders,
   positions, arm state, risk hashes, and kill switch through the application.
4. Run unit and paper-adapter contract tests. Invoke
   `execution-safety-reviewer` on the current execution diff.
5. Build one one-contract, defined-risk debit vertical. Show the canonical
   order payload, debit, width, maximum loss/profit, breakeven, quote age,
   liquidity gates, client order ID, and intended cancel/close plan.

## `dry-run`

Run only the application's no-submit path and show the evidence-ledger record.
Do not arm, submit, cancel, or close anything.

## `submit`

Proceed only after all preconditions pass and the user, in the current
interactive session, explicitly confirms this exact statement after reviewing
the payload:

`I ACKNOWLEDGE ONE PAPER OPTIONS ORDER`

Then use only the application's smoke-test command. Enforce one contract, DAY
limit, frozen sandbox risk, idempotent client order ID, bounded price ladder,
and a single intent. Reconcile by client order ID after every ambiguous result.
Cancel or close according to the declared plan and prove orders and positions
are flat from broker truth. If any state is unknown, disarm and stop; never
retry blindly or claim the account is flat.

Return the ledger identifiers and actual state transitions. A successful smoke
test passes only the execution plumbing gate, not the alpha gate.
