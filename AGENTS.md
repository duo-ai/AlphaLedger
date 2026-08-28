# AlphaLedger agent contract

This file is the canonical instruction layer for coding agents. Claude Code
loads it through `.claude/CLAUDE.md`; Codex discovers it directly from the
repository root.

## Mission

Build the system specified in `options-alpha-agent-design.md` and sequence the
work according to `hackathon-build-plan.md`. Preserve the narrow claim:
chronologically validated cross-sectional signals, defined-risk paper options,
and a complete evidence ledger.

## Non-negotiable safety boundary

- Paper trading only. Executable configuration must use
  `https://paper-api.alpaca.markets`; the live trading host is forbidden.
- Never read, print, log, commit, or copy API keys, secret keys, `.env` files,
  private keys, credentials, or secret-store contents.
- Every coding-agent Alpaca MCP connection is market-data-only. It must not place,
  replace, cancel, close, exercise, or configure anything.
- The application order adapter is the only order path. It must enforce the
  paper endpoint, an explicit arm state, risk approval, idempotent client order
  IDs, broker reconciliation, and the one-contract smoke-test cap.
- An LLM may classify language and explain deterministic output. It may not
  calculate returns or payoffs, select arbitrary structures, size positions,
  modify frozen thresholds, or improvise orders.
- Do not weaken a gate to obtain a trade, a prettier backtest, or a demo win.
  `no_trade` is a valid and expected result.

## Source-of-truth order

1. The user's current request.
2. `options-alpha-agent-design.md` for architecture and invariants.
3. `hackathon-build-plan.md` for sequence, gates, and descope decisions.
4. `orchestrator-system-prompt.md` for runtime orchestration and the news schema.
5. `project-state/DECISIONS.md` for accepted implementation choices.
6. `project-state/STATUS.md` for the current checkpoint.

If two sources conflict, stop and surface the conflict. Do not silently choose
the more permissive interpretation.

## Engineering boundaries

Keep deterministic responsibilities separated:

- data adapters record raw point-in-time observations and feed identity;
- evidence code creates features and quality flags;
- forecast code loads frozen, versioned models;
- structure code enumerates real chains and exact bounded payoffs;
- risk code produces an approval token bound to the exact order payload;
- execution code owns Alpaca schema mapping and the order state machine;
- ledger code is append-only and records every decision, including no-trades;
- presentation code reads projections and never changes trading state.

Use Python 3.14, `uv`, strict typing at domain boundaries, UTC internally, and
the exchange calendar for sessions. Keep broker and LLM clients behind small
interfaces so unit tests never require network access.

## Point-in-time and research rules

- Every observation carries `event_time`, `first_seen_time`, `source_time`,
  `received_time`, `feed`, and `as_of` where applicable.
- No feature may observe a timestamp later than the prediction timestamp.
- Fit, calibration, and test windows are chronological and purged by at least
  the forecast horizon.
- Register every model or threshold trial. Never tune on competition P&L.
- Compare random/shuffled, price-only, news-only, and combined baselines using
  conservative costs; midpoint fills are not a headline result.
- Freeze model, feature, risk, prompt, and run-manifest hashes before an
  autonomous session.

## Change workflow

1. Start at the repository root and read the current status and relevant spec.
2. State the bounded acceptance criteria before editing.
3. Inspect existing code and user changes; preserve unrelated work.
4. Implement the smallest coherent vertical change.
5. Add or update tests for success, failure, restart, and no-trade paths.
6. Run the narrow tests, then the repository quality gate.
7. Request the appropriate read-only specialist review for high-risk changes.
8. End meaningful sessions with `/handoff` in Claude Code or `$handoff` in
   Codex; do not commit unless asked.

When the Python project exists, the expected quality gate is:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

If those commands are not yet defined, report that fact. Do not invent a
parallel toolchain.

## Parallel work protocol

Two people and three coding-agent runtimes share this repository. Read
`specs/000-INTAKE.md` before starting work. The short version follows.

### Roster and lanes

| Owner | Runtime | Lane | Paths |
|---|---|---|---|
| `pablo/codex` | Codex | execution | `src/alphaledger/{broker,execution,risk,structure,ledger}/**` |
| `pablo/claude` | Claude Code | execution and shared | intake authoring, review, integration |
| `teammate/claude` | Claude Code | research | `src/alphaledger/{data,evidence,forecast}/**`, `research/**` |

Lanes have disjoint path globs. Never write outside the lane of the unit you
hold. Codex carries the larger budget, so units marked
`preferred_runtime: codex` are implementation-heavy and belong there; Claude
sessions are better spent authoring intakes, running specialist reviews, and
integrating. That field is a hint for a human, not routing logic.

### Claiming a unit

```bash
git switch develop && git pull --rebase origin develop
python3 scripts/coord.py list --state available
python3 scripts/coord.py claim UNIT-010 --owner pablo/codex
```

Claim from the primary clone, not from a worktree. Git refuses to check the
same branch out twice, so only one working copy can sit on `develop`. Keep the
primary clone on `develop` as the claiming station and let worktrees hold
`feature/` branches only.

`claim` refuses a unit that is already owned, one whose dependencies are not
`merged`, and an owner string that does not name both a person and a runtime.
It then prints the exact commit and worktree commands. Push the claim to
`develop` immediately: it touches one file, so concurrent claims on different
units never conflict. A rejected push means someone claimed first. Rebase,
re-read, and take a different unit.

`UNIT-001` freezes the domain contracts and blocks every other unit. That is
enforced by the dependency check, not by convention.

### Branching

Git Flow. `main` is production, `develop` is integration, one unit is one
`feature/` branch in its own worktree cut from `develop`. Run
`scripts/gitflow-init.sh` once per clone and once per worktree. Full rules in
`.claude/rules/50-git.md`, which applies to both runtimes despite its path.

`.claude/settings.local.json` is untracked and does not carry into a worktree,
so a fresh worktree has no MCP server enabled until it is copied in. Both guard
hooks are tracked and have been verified to fire inside a worktree.

### Finishing

Move the unit to `in_review`, request the reviewer named in its frontmatter,
address the findings, then merge into `develop` with `--no-ff` and set the unit
to `merged`. Reviewers report; they do not edit files.

## Code Review Rules

- Review the current bounded diff before widening scope to the repository.
- Report only actionable, high-confidence defects, ordered by severity.
- Every finding names the affected file or artifact, the failure scenario,
  the violated invariant, and a focused correction or decisive test.
- Treat paper/live isolation, secret exposure, point-in-time leakage,
  idempotency, restart recovery, and broker reconciliation as blocking areas.
- If no material issue is found, state what was inspected, which commands were
  actually run, and what remains unverified.
- Reviewers do not edit files or weaken gates to clear a change.

## Specialist routing

- `quant-researcher` / `quant_researcher`: challenge alpha hypotheses and
  point-in-time evidence.
- `backtest-auditor` / `backtest_auditor`: inspect leakage, purging, trial accounting, metrics, and
  cost assumptions after research code changes.
- `execution-safety-reviewer` / `execution_safety_reviewer`: review order,
  risk, reconciliation, state, and
  kill-switch changes before paper submission is enabled.
- `alpaca-docs-researcher` / `alpaca_docs_researcher`: verify current Alpaca schemas and capabilities from
  official sources and the market-data-only MCP server.
- `code-reviewer` / `code_reviewer`: review the current diff after a bounded implementation.
- `submission-reviewer` / `submission_reviewer`: audit the frozen demo, claims, evidence, and required
  competition artifacts.

Specialists return findings; they do not edit files. The main session owns
writes so concurrent agents cannot mutate the same checkout.

## Definition of done

A change is done only when the requested behavior works, relevant tests pass,
paper/live isolation still holds, failure and restart behavior are explicit,
observability covers the path, and documentation/state reflect any accepted
decision. Never call a path verified when it was only inspected.
