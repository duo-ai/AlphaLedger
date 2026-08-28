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

- Amended by D-010: parallel writers are permitted in isolated worktrees.

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

- Superseded by D-012: the interpreter is now 3.14. The rest of D-005 stands.

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
- Amended 2026-08-28: the disjoint-globs condition is now enforced, not merely
  stated. `coord.py claim` refuses a unit whose declared paths overlap a unit
  already `claimed` or `in_review`, and `scripts/dispatch.sh` checks a whole
  batch before claiming any of it. The first real overlap this caught was
  UNIT-020's `src/alphaledger/data/**` swallowing UNIT-021's `universe.py`.
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

## D-013: ECC harness conventions

- Date: 2026-08-28
- Source: <https://github.com/affaan-m/ecc>, "Everything Claude Code", read on
  2026-08-28.
- Decision: adopt four ECC conventions. Conventional commit subjects, which
  amends the commit style in D-011. `origin:` frontmatter on every skill.
  `agents/openai.yaml` interface bindings on every Codex skill. Two ported
  skills, `tdd-workflow` and `verification-loop`, adapted to this repository's
  toolchain rather than copied.
- Deliberate deviation: ECC sets `allow_implicit_invocation: true` on every
  skill. AlphaLedger keeps every lifecycle skill manual-only, so no model can
  decide by itself to run a paper smoke test, freeze research, or audit a
  submission. Only `tdd-workflow` and `verification-loop` are implicitly
  invocable, because neither touches trading state. This deviation is enforced
  by a check in `scripts/verify_harness.sh`, not by convention.
- Finding that changed nothing: ECC's parallel-work skill, `dmux-workflows`,
  runs separate full agent sessions in tmux panes and recommends a git worktree
  per pane for conflict-prone work. That is the model already accepted in
  D-010. No write-capable subagent was introduced, and none is needed.
- Rationale: the repository already matched ECC's agent and skill file layout.
  The gaps were discoverability metadata and two missing workflow skills, not
  architecture.
- Revisit only if: ECC changes its skill schema, in which case re-read the
  source before changing files here.

## D-014: Where point-in-time ordering is enforced

- Date: 2026-08-28
- Origin: the UNIT-001 gating review found that `ObservationTimestamps`
  accepted any ordering of its six timestamps, and that `StructurePlan.legs`
  accepted unvalidated values.
- Decision, timestamps: the domain type enforces exactly one ordering,
  `first_seen_time >= source_time`. Design section 4 defines `first_seen_time`
  as the published time plus a conservative latency buffer, so this ordering is
  guaranteed by the contract itself, and its violation means observing a record
  before its source emitted it.
- Every other ordering is deferred to the data adapter in UNIT-020, and this is
  deliberate, not an oversight. `event_time` may legitimately fall after
  `first_seen_time`: a scheduled earnings date is known weeks ahead. A domain
  type that rejected that would corrupt exactly the point-in-time evidence it
  exists to protect. `AGENTS.md` already assigns point-in-time construction to
  data adapters, which hold the feed semantics needed to judge the rest.
- Decision, legs: leg values are restricted to `str`, `int`, `Decimal`, and
  `datetime`. `float` is rejected with a money-specific message, closing a path
  that would have smuggled a strike past `.claude/rules/01-safety.md`. Nested
  containers are rejected because a shared reference would let a caller mutate
  a plan after a `RiskApproval` was bound to its payload hash, making that
  binding false while every field-level immutability guarantee still held.
- Design section 14 leaves the leg schema open, so this bounds values without
  changing the shape. UNIT-014 may promote a leg to a typed record; that would
  be a narrowing, not a conflict.
- Revisit only if: UNIT-020 finds a real feed where `first_seen_time` precedes
  `source_time` for a legitimate reason. Record the feed and the mechanism
  before relaxing anything.

## D-015: Store integrity is checked when the recorder opens

- Date: 2026-08-28
- Origin: the UNIT-020 round two review, which asked what the round one fixes
  could have broken.
- Decision: `alphaledger.data.recorder.Recorder` reads the whole store when it
  is constructed, to rebuild the content-address index that makes `record`
  idempotent across a restart. A store holding a line that cannot be parsed
  therefore cannot be opened at all, so corruption blocks writes as well as
  reads. There is no recovery that truncates to the last readable record.
- Rationale: a torn final line, the shape an unclean kill leaves, is not
  distinguishable from a deliberate truncation. Recovering from one would
  recover from both, which reopens the hole the raise exists to close: a store
  that skipped what it could not parse would report a shorter history than the
  file holds, and no later audit could tell that from a session that simply
  recorded less.
- Cost accepted: a crash mid-append can wedge the writer until a human inspects
  the file. That is the intended failure direction. This is a change in blast
  radius from the first implementation, where corruption stopped reads only,
  and it is pinned by `test_a_corrupted_store_refuses_new_writes_and_not_only_reads`.
- Revisit only if: the store gains per-record framing, a length prefix or a
  checksum, that makes a torn final line provably distinguishable from a
  deliberate truncation. Recovery may then truncate to the last provably
  complete record, and to nothing else.

## D-016: The news label record holds what the labeler emits

- Date: 2026-08-28
- Origin: writing the UNIT-023 intake surfaced a conflict between two sources
  of truth. `orchestrator-system-prompt.md` Prompt B, the labeler's actual
  contract, emits `entity_match`, the ticker, `unknown` for novelty and
  relevance, and a list of stated limitations. `NewsLabel`, frozen by UNIT-001
  from design section 14, holds none of those and its `Novelty` and `Relevance`
  literals exclude `unknown`.
- Decision: amend the frozen contracts to hold what the labeler emits, rather
  than narrow the labeler to fit the record. UNIT-002 makes the change.
- Rationale: the alternative is lossy in the two ways that matter most.
  Dropping `entity_match` discards the only field that says an article is not
  about this company, and mapping `unknown` onto a defined value records more
  certainty than the model expressed. Both leave a downstream reader unable to
  tell a confident label from a hedged one, which is the shape of an
  unfalsifiable claim.
- Boundary preserved: this widens what may be stored, not what may be believed.
  Prompt B's consistency rules, such as `not_matched` forcing
  `relevance=incidental`, stay with the labeler adapter, which validates model
  output and excludes what is invalid. D-014 already draws that line: the
  frozen record enforces what is universally true of a field, the adapter
  enforces what is true of its source. Prompt B qualifies some of its own
  rules, so a record that enforced them would reject labels the contract
  permits.
- Blast radius: `NewsLabel` is referenced only by `domain/contracts.py`, its
  own `__init__`, and the UNIT-001 tests. No news code exists yet, so the
  amendment lands before there is anything to migrate. That is why it is being
  done now rather than after UNIT-023.
- Consequence, recorded because it changed a mechanism: the harness check that
  forbids two units declaring overlapping path globs compared every unit,
  including merged ones. UNIT-001 declared `src/alphaledger/domain/**`, so no
  later unit could ever declare a file under it and the amendment was
  impossible to specify. The check now considers only units that are not
  merged, which is what D-010 always meant, since the invariant is about
  concurrent writers, and it matches the filter `coord.py claim` already
  applies.
- Revisit only if: the labeler contract itself changes. Prompt B and
  `NewsLabel` are now two halves of one interface and have to move together.
