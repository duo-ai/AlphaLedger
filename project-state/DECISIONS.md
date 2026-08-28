# AlphaLedger accepted decisions

Only accepted, consequential choices belong here. Experiments and open ideas
belong in the trial registry or status file.

## D-001: Paper-only system boundary

- Date: 2026-08-27
- Decision: AlphaLedger has no live-money endpoint or generic live-mode path.
- Rationale: competition scope and irreversible-risk containment.
- Revisit only if: a separate future project is explicitly authorized and
  independently threat-modeled. Do not relax this repository in place.

## D-002: Cross-sectional forward alpha

- Date: 2026-08-27
- Decision: scan a frozen liquid universe and forecast future residual returns
  from independent price/volume and point-in-time news families.
- Rationale: replaces the original single-ticker, contemporaneous-event story
  with a pooled, falsifiable prediction problem.
- Revisit only if: chronological evidence rejects the design; the fallback is
  a separately validated price-volume model or no live alpha, not ticker hunting.

## D-003: Execution-first vertical slice

- Date: 2026-08-27
- Decision: prove submit, reconciliation, monitoring, exit, restart recovery,
  and ledger behavior before UI or additional strategies.
- Rationale: autonomous paper operation is core evidence, not a cuttable extra.
- Revisit only if: official rules prohibit paper access; then preserve the state
  machine with recorded fixtures and disclose the limitation.

## D-004: One writer, specialist reviewers

- Date: 2026-08-27
- Decision: the main coding-agent session owns edits; project subagents are
  bounded, read-only research and review specialists.
- Rationale: avoids concurrent checkout mutation and keeps a human-visible
  permission boundary around changes to trading code.
- Alternatives rejected: autonomous write agents and a default coordinator
  agent, which add state, permission, and merge complexity during a solo sprint.
- Revisit only if: work is split into independent repositories or explicitly
  isolated worktrees with a reviewed integration protocol.

## D-005: Python 3.12 with uv

- Date: 2026-08-27
- Decision: use Python 3.12, `uv`, a committed lockfile, and typed boundaries.
- Rationale: strongest fit for Alpaca, data research, modeling, and a one-week
  implementation while keeping deterministic services testable.
- Revisit only if: event infrastructure mandates another runtime before code is
  scaffolded. Do not introduce a second application language during the sprint.

## D-006: Agent Alpaca MCP is market-data-only

- Date: 2026-08-27
- Decision: commit Alpaca MCP with `assets`, `stock-data`, `options-data`,
  `corporate-actions`, and `news`; omit `account` and `trading` in both coding
  harnesses.
- Rationale: official toolset filtering provides a simpler least-privilege
  boundary. Application adapters own account validation and paper orders.
- Revisit only if: a read-only account toolset becomes separately enforceable.
  Never add the trading toolset to committed coding-agent configuration.

## D-007: Pin Alpaca MCP 2.3.0 at harness creation

- Date: 2026-08-27
- Decision: `.mcp.json` and `.codex/config.toml` pin
  `alpaca-mcp-server==2.3.0`.
- Rationale: 2.3.0 is the version declared by the official repository when this
  harness was built; an unpinned `uvx` dependency is not reproducible.
- Revisit only if: Day-0 contract tests justify a version change. Record the new
  version, source, schema delta, and test result before changing the pin.

## D-008: Tool-neutral project state

- Date: 2026-08-27
- Decision: `project-state/` is the single checkpoint and decision-log location
  shared by Claude Code and Codex.
- Rationale: duplicated runtime-specific state would drift and make a restart
  dependent on which harness ran last.
- Revisit only if: a future runtime needs generated local state that cannot be
  represented in the canonical Markdown checkpoint.

## D-009: Spec-driven unit intake with a file-per-unit registry

- Date: 2026-08-28
- Decision: work is decomposed into units, each specified by one Markdown
  intake file in `specs/units/` carrying frontmatter that records lane, owner,
  branch, state, reviewer, and dependencies. `scripts/coord.py` is the only
  supported way to claim and transition a unit.
- Rationale: the repository already held the constitution, the gates, and the
  review roles. The missing layer was per-unit ownership and state, which is
  what made parallel work unsafe. One file per unit means two people claiming
  two different units never touch the same file, so claims merge cleanly
  instead of conflicting inside a shared registry.
- A unit is claimable only when its contract, acceptance criteria, and test
  list are written. The test list precedes implementation; that is where TDD
  enters the process.
- Revisit only if: the unit count grows past what a directory listing can
  convey, at which point the registry needs an index, not a different model.

## D-010: Parallel writers in isolated worktrees

- Date: 2026-08-28
- Decision: amends D-004. More than one coding-agent session may write, but
  only in a git worktree of its own, on a `feature/` branch, holding a claimed
  unit whose path globs are disjoint from every other in-progress unit.
- Rationale: D-004 named this exact exception as its revisit condition. The
  integration protocol it required is `specs/000-INTAKE.md` plus
  `.claude/rules/50-git.md`.
- Evidence: both guard hooks were verified to fire inside a worktree, and the
  tracked contents of `.claude/` and `.codex/` are present there. The one gap
  is `.claude/settings.local.json`, which is untracked and must be copied into
  each worktree or the Alpaca MCP server is silently absent.
- D-004 otherwise stands: a session still owns its checkout alone, and the
  specialists remain read-only.
- Revisit only if: two units are found to need the same files, which means the
  decomposition is wrong and the units should be merged, not the isolation
  relaxed.

## D-011: Git Flow branching model

- Date: 2026-08-28
- Decision: `main` is production and `develop` is integration. Units are
  `feature/` branches cut from `develop`. Release and hotfix branches merge to
  `main` with `--no-ff` and are tagged `v<version>`. `scripts/gitflow-init.sh`
  configures a clone or worktree; the `git-flow` tool itself is optional.
- Rationale: two people and three agent runtimes need one branching model that
  is written down rather than inferred. A registry claim is the single
  permitted direct commit to `develop`, because a claim must land fast to keep
  the double-claim window small.
- Enforcement: both guard hooks block direct commits to `main`, branch names
  outside the model prefixes, force pushes, fast-forward merges into shared
  branches, and AI attribution or em dashes in commit messages.
- Revisit only if: the project moves to trunk-based delivery with real
  continuous deployment, which it does not have.

## D-012: Python 3.14

- Date: 2026-08-28
- Decision: amends D-005. The implementation targets Python 3.14 with `uv` and
  a committed lockfile. Everything else in D-005 stands.
- Rationale: 3.14 is the newest stable release and is already the system
  interpreter on the development machine. 3.15 is at alpha and is excluded.
- Evidence: the full stack resolves, installs, and imports on cp314. alpaca-py
  0.44.0, pandas 3.0.5, numpy 2.5.2, scikit-learn 1.9.0, exchange-calendars
  4.13.2 with the XNYS calendar loading, pydantic 2.13.5, httpx 0.28.1, pytest
  9.1.1, ruff 0.16.5, mypy 2.3.1. This was a real venv install, not a
  resolution check. `alpaca-mcp-server==2.3.0` also resolves under cp314,
  which is informational only since it runs in its own uvx environment.
- D-005's revisit condition required any change to land before code is
  scaffolded. No application code exists yet, so the condition holds.
- Revisit only if: a required dependency is found to lack a cp314 wheel during
  scaffolding. Record the package and fall back to 3.13, not to 3.12.
