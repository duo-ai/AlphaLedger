---
name: paper-smoke
description: Use only when the user explicitly invokes $paper-smoke for the human-controlled one-contract AlphaLedger paper-order lifecycle after dry-run evidence exists.
---

# Paper lifecycle smoke test

Interpret text following `$paper-smoke` as `dry-run` unless it is exactly
`submit`. Never use raw Alpaca MCP order tools.

## Preconditions for both modes

1. Start at the repository root and read Gates G0 and G1 in
   `hackathon-build-plan.md`.
2. Confirm through the application that it is in paper mode and uses exactly
   `https://paper-api.alpaca.markets`, without printing credentials.
3. Confirm market clock, options permission, feed mode, working orders,
   positions, arm state, risk hashes, and kill switch through the application.
4. Run unit and paper-adapter contract tests. Ask the
   `execution_safety_reviewer` agent to review the current execution diff.
5. Build one one-contract, defined-risk debit vertical. Show the canonical
   payload, debit, width, maximum loss and profit, breakeven, quote age,
   liquidity gates, client order ID, and intended cancel or close plan.

## `dry-run`

Run only the application's no-submit path and show the evidence-ledger record.
Do not arm, submit, cancel, or close anything.

## `submit`

Proceed only after every precondition passes and the user, in the current
interactive session, explicitly confirms this exact statement after reviewing
the payload:

`I ACKNOWLEDGE ONE PAPER OPTIONS ORDER`

Then use only the application's smoke-test command. Enforce one contract, DAY
limit, frozen sandbox risk, idempotent client order ID, bounded price ladder,
and a single intent. After any ambiguous result, reconcile by client order ID;
never retry blindly. Cancel or close according to the declared plan and prove
orders and positions are flat from broker truth. Unknown state means disarm
and stop.

Return ledger identifiers and actual state transitions. A successful smoke
test passes execution plumbing only, not the alpha gate.
