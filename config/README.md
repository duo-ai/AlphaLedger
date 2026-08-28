# Committed configuration

Everything here is a non-secret operational constant, and everything here is
hashed into the run manifest so a session can be reproduced and audited.

That is the whole reason these values are not kept in an environment file. A
risk limit read from an untracked file cannot be proven after the fact, so the
evidence ledger could not answer the one question it exists to answer: what
configuration produced this decision.

## The distinction

| Committed here | Kept in the environment |
|---|---|
| risk limits, position caps, kill-switch thresholds | API keys and secret keys |
| universe rule, size cap, liquidity floors | machine-local paths and cache directories |
| feature lookbacks, winsorization limits, sector map | anything whose value must never be committed |
| scan times, session cutoffs, strategy allowlist | |
| feed mode and expected broker host | |

The test to apply to a new value: if a reader of the evidence ledger would need
it to understand why a decision was made, it is committed. If knowing it would
let someone act as us, it is a secret. A value that is both is a design error;
split it.

A third category exists and belongs in neither: anything derived. If a number
can be computed from what is already here, compute it. Two sources for one
value is how a frozen run stops being frozen.

## Status of these numbers

Every value in this directory is a **declared default, not a selected one**.

Design section 4 and section 5.1 require the universe floors, the feature
lookbacks, and the winsorization limits to be chosen on development data,
registered as trials, and frozen before any autonomous session. That has not
happened. Until it does, nothing here may be cited as validated, and G3 stays
unpassed. `project-state/STATUS.md` carries the same warning.

The files are structured for that selection to happen later without moving
anything: each value already sits where a trial would write it.

## Changing a value

Changing anything here changes the hash of any run that used it. That is the
point, not a side effect.

Do not edit these during a competition session. `.claude/rules/01-safety.md`
forbids mutating frozen alpha, thresholds, universe, risk limits, or strategy
allowlists mid-session, and the arm state is bound to the hashes these files
produce.
