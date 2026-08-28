# Start here

You are joining AlphaLedger mid-flight. This file is the shortest path from a
clone to a merged unit. It does not restate the architecture or the rules; it
points at them and tells you the order to do things in.

Read this whole file before running anything. If you are a coding agent, treat
every "stop" below as binding.

## What this project is

An autonomous, paper-only options trading agent. Two properties matter more
than features: nothing may reach a live trading endpoint, and every decision,
including every decision not to trade, must be explainable from a recorded
artifact. Both are enforced by hooks, not by good intentions.

## Prerequisites

- `uv`. It will fetch Python 3.14 itself; do not install a different version.
- No Alpaca credentials are needed to start. When you eventually pull real
  market data, keys live in your environment or an OS secret manager. Never in
  the repository, a `.env`, a commit, a log, or a chat message.

## 1. Set up

```bash
git clone https://github.com/duo-ai/AlphaLedger.git && cd AlphaLedger
bash scripts/gitflow-init.sh
cp .claude/settings.local.json.example .claude/settings.local.json
```

The clone lands on `develop`. That is deliberate and correct; `main` is
production and holds none of the current work.

Confirm the harness is healthy before you write anything:

```bash
bash scripts/verify_harness.sh
```

If that does not end in `ALL CHECKS PASSED`, stop and say so. Do not start work
on a broken harness.

## 2. Read, in this order

1. `AGENTS.md`. The contract. The safety boundary in it is not negotiable.
2. `specs/000-INTAKE.md`. How work is specified, claimed, and finished.
3. `project-state/STATUS.md`. Where the project actually is right now.
4. The unit file you are about to claim.

`.claude/rules/` holds the invariants that apply to specific paths. Read the
one matching the code you are about to touch.

## 3. Take a unit

Work is decomposed into units. One unit is one file in `specs/units/`, one
`feature/` branch, one worktree, one owner.

```bash
python3 scripts/coord.py list
python3 scripts/coord.py list --lane research
python3 scripts/coord.py claim UNIT-020 --owner <your-handle>/claude
```

`claim` refuses a unit that someone else holds and a unit whose dependencies
are not merged. A refusal is information, not an obstacle. Take a different
unit; do not edit the registry by hand to get past it.

The command prints your exact next steps: a one-line claim commit to push
immediately, then a worktree. Run them verbatim. Copy
`.claude/settings.local.json` into the new worktree; it is untracked and does
not carry across.

## 4. Do the work

Everything happens inside your worktree, never in the main clone.

Your unit file already contains a `## Test list`, written before the unit
became claimable. That list is the specification. Invoke the `tdd-workflow`
skill and follow it:

1. Write the tests from the list, covering all four paths the list names:
   success, failure, restart, and no-trade.
2. Run them. They must fail, and fail for the reason you expect.
3. Implement the minimum that makes them pass.
4. Refactor with the tests green.

If a test is hard to satisfy, change the code. Never weaken a test, relax an
assertion, or delete a case to reach green. If you believe a test in the list
is wrong, say so explicitly and fix the unit intake first, as its own commit.

## 5. Finish

```bash
# invoke the verification-loop skill, or run the gate directly
uv sync --frozen
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest

python3 scripts/coord.py state UNIT-020 in_review
```

Then request the reviewer named in your unit's frontmatter. Reviewers report;
they do not edit files. Address the findings, then merge into `develop` with
`--no-ff` and set the unit to `merged`.

## Lane briefs

If you are working the research lane, read `RESEARCH-LANE.md` after this file.
It is the delegation brief for that lane: what the three units are, why the
point-in-time discipline is shaped the way it is, what a real test looks like
there as opposed to one that passes against the defect, and the hazards already
hit on this repository so you do not rediscover them.

## Lanes

Path globs are disjoint so two people never write the same file.

| Lane | Paths | Reviewer |
|---|---|---|
| research | `src/alphaledger/{data,evidence,forecast}/**`, `research/**` | `backtest-auditor` |
| execution | `src/alphaledger/{broker,execution,risk,structure,ledger}/**` | `execution-safety-reviewer` |
| shared | `src/alphaledger/domain/**` | `code-reviewer` |

Never write outside the lane of the unit you hold. If a unit seems to require
it, the decomposition is wrong. Say so rather than reaching across.

## Rules you will hit mechanically

A `PreToolUse` hook blocks these before they happen, in both Claude Code and
Codex. They are not style preferences.

- No commits to `main`. `develop` accepts exactly one kind of direct commit,
  the registry claim. Everything else is a `feature/` branch.
- Branch names must start with `feature/`, `bugfix/`, `release/`, `hotfix/`,
  or `support/`.
- Conventional commit subjects: `feat(data): record point-in-time bars`.
- No AI attribution trailers, no "Generated with" lines, no robot emoji.
- No em dashes or en dashes, in commits or in project prose.
- No reads or writes of `.env`, credentials, or private keys.
- No live Alpaca host, no `--live` path, no disabling paper mode.
- The Alpaca MCP server is market-data-only. Order placement goes through
  tested application code, never a raw tool.

## If you drive Codex

Codex records hook trust as a hash. Editing `.codex/hooks.json` invalidates it,
and Codex then **skips the hook silently**: a dispatched agent runs with no
guard and nothing tells you. This was observed on 2026-08-28, when a command
carrying the live trading host ran cleanly inside `codex exec` while the same
command was blocked under Claude Code.

`scripts/verify_harness.sh` now fails when it detects stale trust. To restore
it, start Codex in this repository, inspect the hook with `/hooks`, and approve
it:

```bash
codex
/hooks
```

Re-approve after any change to `.codex/hooks.json`. Do not use
`--dangerously-bypass-hook-trust` as a routine workaround; it skips the review
step that makes trust meaningful.

## Watching a dispatched run

A Codex dispatch writes a JSONL event stream. Follow it live:

```bash
scripts/watch.sh                 every active dispatch
scripts/watch.sh UNIT-011        one of them
scripts/watch.sh --replay        what already happened, then stop
```

Ctrl-C stops watching, not the run.

Two things watch for you rather than the other way round. `scripts/notable.py`
stays silent while an agent works and speaks only when a run stops, finishes,
or dies, which is what a monitor should feed. And a SessionStart hook reports
any dispatch in flight when you open the repository, because `codex exec` is
detached and outlives the session that started it.

This is worth doing rather than waiting for the result file. An agent that is
about to stop on a source-of-truth conflict says so several turns before it
exits, and that is exactly the moment a human can decide whether the
specification is wrong rather than the agent.

## When to stop and ask

- Two sources of truth disagree. Surface the conflict; do not pick the more
  permissive reading.
- A gate fails and the fix would mean loosening the gate.
- Your unit appears to need a file in another lane.
- Anything about credentials, live endpoints, or real money.

`no_trade` is a valid and expected result in this system. So is a unit that
ends by reporting that the approach does not work. Neither is a failure.
