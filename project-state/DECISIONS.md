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
- Amended by D-019: specialists hold Write and Edit for their own memory
  directory, so the read-only guarantee below is now a stated boundary rather
  than a tool-enforced one.

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

## D-017: Secrets live in the environment, constants live in config

- Date: 2026-08-28
- Origin: a request to move constants into an environment file. Acting on it
  literally would have broken the evidence ledger, so the request is split.
- Decision: two locations with a test that decides which one a value gets.
  Secrets go in the process environment, seeded from a gitignored dotfile whose
  names are documented in `.env.example`. Non-secret operational constants go in
  `config/`, committed and hashed into the run manifest.
- The test: if a reader of the evidence ledger would need the value to
  understand why a decision was made, it is committed. If knowing it would let
  someone act as us, it is a secret. A value that is both is a design error and
  must be split.
- Rationale: the whole claim of this project is that a session can be
  reproduced and audited. `risk_config_hash`, `feature_version`, and
  `run_manifest_hash` exist to prove what configuration produced a decision. A
  risk limit read from an untracked file cannot be hashed, cannot be proven
  after the fact, and would make the ledger an assertion rather than evidence.
- The rules already anticipated this. `.claude/rules/30-execution.md` scopes
  `config/**/*risk*` and `config/**/*broker*`, and
  `.claude/rules/20-research-integrity.md` scopes `config/**/*model*` and
  `config/**/*feature*`. The globs existed; the directory did not.
- Money in these files is a string, never a TOML float, because `money()`
  rejects float outright.
- Status recorded rather than hidden: every value committed today mirrors a
  dataclass default in already-merged code and none has been selected on data.
  Design sections 4 and 5.1 require selection on development data, registration
  as a trial, and freezing before an autonomous session. UNIT-004 makes the
  files the source and pins them against the code defaults so the two cannot
  drift silently.
- Revisit only if: a value is found that is genuinely both secret and needed to
  explain a decision. Split it rather than relaxing the boundary.

## D-018: Review is a gate, not a convention

- Date: 2026-08-29
- Origin: UNIT-010 merged with its review outstanding. Nothing refused it; the
  rule existed only as prose.
- Decision: `coord.py state <unit> merged` refuses a unit with no recorded
  review, and refuses one whose last verdict was not `clear`. A review is
  recorded with `coord.py review <unit> --by <reviewer> --verdict
  clear|conditional|block`. Re-claiming a unit clears the verdict, because a
  verdict describes a branch state that a re-claim reopens.
- Routing: Codex-dispatched work is reviewed by the Codex specialist of the
  same role, through `codex exec review --base develop`, so a review does not
  mix model families. Claude-owned work is reviewed by the Claude specialist,
  which only an orchestrating session can spawn, and `scripts/review.sh` says
  so rather than pretending it can.
- Rationale: the reviews have paid for themselves repeatedly. On UNIT-010 they
  found a bare string shredded into characters across every audit field, NaN
  and Infinity admitted into forecast values, a test asserting on a double
  structurally incapable of the failure it named, and a defect introduced by
  the previous round's own fix. None of those were found by the implementer,
  by the quality gate, or by the harness.
- Amended 2026-08-29: the routing above is now enforced. `coord.py review`
  refuses a verdict recorded under any name but the one the unit's frontmatter
  declares. The merge gate only asks whether the last verdict was clear, so it
  could not tell a clearance from the declared specialist apart from one
  attributed to a specialist that never ran, and the routing was prose. Found by
  recording a UNIT-004 verdict under `backtest-auditor` when the unit names
  `execution-safety-reviewer`, which the registry accepted without complaint.
- Accepted cost: a unit cannot merge on a Friday because its reviewer has not
  run. That is the intended failure direction.
- Revisit only if: a reviewer becomes a bottleneck in practice, in which case
  the fix is more reviewers or narrower units, not a weaker gate.

## D-019: Specialists keep committed memory, and are no longer strictly read-only

- Date: 2026-08-29
- Origin: research into what Claude Code actually offers for agent memory,
  prompted by wanting reviewer knowledge to accumulate rather than being
  rediscovered every session.
- Finding that forced the choice: enabling `memory:` on a subagent
  automatically grants it Read, Write, and Edit, even where its `tools:` list
  omits them. There is no documented way to have durable agent memory and a
  tool-enforced read-only reviewer at the same time.
- Decision: amends D-004. The six specialists gain `memory: project`, writing
  to `.claude/agent-memory/<name>/`, which is committed and therefore shared
  between both developers and across machines. They consequently hold Write and
  Edit.
- The boundary that replaces the tool list: a specialist writes its own memory
  directory and nothing else. It does not edit application code, specifications,
  or tests. That is now stated in every agent's own instructions, because it is
  no longer enforced by the tool list. This is a weaker guarantee than D-004
  gave, and the weakening is deliberate and recorded rather than discovered.
- Why accept it: the reviews are where the real defects have been found, and
  each round currently starts from nothing. A reviewer that remembers a defect
  class it has already seen is worth more than one that cannot write a file.
- Rejected alternative: Claude Code's auto memory. It lives at
  `~/.claude/projects/<project>/memory/` and is explicitly machine-local, so it
  reaches one person on one machine. It cannot be the shared channel for a two
  person team, whatever else it is good for.
- Convention, because the documentation is silent on merging two versions of one
  memory index: `MEMORY.md` holds one line per entry and detail goes in topic
  files. Two appends merge; two rewrites do not.
- Revisit only if: a specialist is found editing outside its memory directory,
  in which case the answer is to remove memory from that agent rather than to
  add a rule nothing enforces.

## D-020: Codex keeps no memory; Claude specialists do

- Date: 2026-08-29
- Origin: research into what each runtime actually offers, before enabling
  anything.
- Decision, Codex: memory stays off. It is disabled by default, per user,
  cannot be governed through git, and is unavailable to subagents at all, since
  the write pipeline skips any session whose source is a subagent. OpenAI's own
  documentation settles it: "Keep required team guidance in `AGENTS.md` or
  checked-in documentation. Treat memories as a helpful recall layer, not as
  the only source for rules that must always apply." Nothing in this
  repository's safety boundary may live somewhere best-effort redacted and
  invisible to review.
- Decision, Claude: specialists keep committed memory under
  `.claude/agent-memory/`, per D-019. The difference between the runtimes is
  deliberate: that memory is a file in the repository, so it is shared,
  reviewable, and diffable, which is precisely what the Codex store is not.
- Consequence: `AGENTS.md` is the shared instruction channel for Codex, and it
  is not trust-gated, so it reaches a worktree regardless. It is capped at
  `project_doc_max_bytes`, 32 KiB, and exceeding the cap truncates silently.
  A harness check now guards that, because silent truncation of the safety
  contract is the worst failure this file can have.
- Verified rather than inferred: the documented rule that an untrusted project
  makes Codex ignore project `.codex/` layers suggested dispatched agents in
  worktrees would run unguarded, since the trust table names only the primary
  clone. A live probe inside a worktree returned "Command blocked by PreToolUse
  hook", so the guard does fire there. The documented rule does not apply the
  way it reads for worktrees of a trusted project.
- What the earlier claim actually proved: `verify_harness.sh` ran the guard
  script inside a worktree and observed its self-test pass. That shows the
  script works there. It never showed that Codex loads the hook there, which is
  a different question and is the one that matters on the dispatch path.
- Revisit only if: Codex memory becomes project-scoped, committable, and
  available to subagents. All three would have to change.

## D-021: Three mechanisms from spec-kit, and the reason for skipping the rest

- Date: 2026-08-29
- Source: <https://github.com/github/spec-kit> at v1.0.0, read on 2026-08-29.
- Adopted, because each one catches a failure this repository actually had:
  1. Claim-time path coverage. Every `src` or `tests` file a unit's Contract,
     Test list, or Verification names must be covered by its declared globs.
     `coord.py claim` refuses otherwise. Validated against UNIT-010 as it was
     originally written, where it correctly reports
     `tests/execution/test_endpoint.py` undeclared, which is the defect that
     stopped the first dispatch.
  2. `[NEEDS CLARIFICATION: question]` as an intake marker, taken from
     spec-kit's spec template. A unit carrying one is not claimable. This gives
     an author a legal way to say "I am not guessing", which the intake
     previously lacked: every section read as settled whether or not it was.
  3. A measurability pass in every reviewer's brief. For each acceptance
     criterion, name the observation that would falsify it and check that
     observation is available. Spec-kit grades an untestable criterion HIGH,
     and so do we now.
- Rejected, with reasons rather than taste:
  - The artifact split, spec plus plan plus research plus data-model plus
    contracts plus quickstart plus tasks per unit. Eight to ten files and
    fifteen to twenty-five model turns for a change our single intake already
    describes.
  - The WHAT versus HOW boundary, which is actively wrong here. UNIT-010's
    load-bearing clause is that no `paper: bool` exists anywhere, because a
    boolean can be set to `False`. That is a pure HOW statement and it is the
    entire point of the unit. Spec-kit's own spec-quality checklist would fail
    it as an implementation detail and exile it to a plan document, where it
    would stop being a criterion anything gates on. For a project whose
    invariants are type-shaped, that split is a liability.
  - The user-story P1/P2/P3 organisation. Our units are infrastructure slices,
    not user journeys.
  - `.specify/` and its CLI. It tracks a single active feature in one gitignored
    pointer file and has no concurrency model at all, which would fight the
    worktree protocol rather than support it.
  - Its parallelism marker. `[P] means different files, no dependencies`,
    judged per task by a model, is a weaker form of what `coord.py` already
    refuses at claim time by comparing declared globs.
- Honest limit of what was adopted: the measurability pass is a prompt to a
  competent reader, not a proof obligation. What actually caught the
  unsatisfiable AC was `execution-safety-reviewer`, a different reader with
  domain knowledge. Making the reading a named step improves the odds; it does
  not make it mechanical.
- Finding recorded because it was uncomfortable: UNIT-010's test list still
  contained the corrected AC's false premise, days after the AC itself was
  fixed. Writing tests first is not a measurability check when the same author
  writes both the criterion and the test.
- Revisit only if: units grow large enough that one intake stops being enough
  to implement from, at which point the plan and tasks split earns a second
  look.

## D-022: The review loop is bounded by a human decision, not by a lower bar

- Date: 2026-08-29
- Origin: UNIT-004 and UNIT-011 both returned `block` on their first review and
  went to a second pass. Nothing in the harness could have told a third round
  from a thirtieth, and nothing bounded what a reviewer could ask for.
- The failure this prevents: a reviewer with an unbounded mandate always finds
  something. The UNIT-011 review listed arm expiry, exact loss sizing, duplicate
  invocation timeout lookup, stale clock and feed faults, bounded exits, and
  ledger transitions as work still outstanding. Not one of those lives in
  `src/alphaledger/execution/orders.py`, and none of them is an acceptance
  criterion of that unit. A unit held open for work it was never asked to do
  does not close.
- Decision, three parts.
  1. Every verdict is kept, in order, in `review_log`. A unit reviewed before
     that field existed seeds it from the verdict it already carries, so the
     count is not short by one.
  2. `coord.py state <unit> claimed` refuses to reopen a unit whose last two
     verdicts were both not `clear`, unless `--another-pass` is passed. The
     refusal states the choice: if the outstanding findings are actionable
     inside the unit's own path globs and bear on its numbered acceptance
     criteria, spend the round; if they belong to a later unit, they are not
     findings against this one, so narrow the intake or open a new unit.
  3. `dispatch.sh --continue` refuses a unit that is not `claimed`, so a second
     pass cannot route around that transition. This is the part that makes the
     rest enforcement rather than convention: the dispatcher never called
     `coord.py state` and the reopen was being done by hand.
- The reviewer's mandate is bounded in its own prompt: a finding carries
  severity only if it is actionable inside the declared globs and bears on a
  numbered acceptance criterion. Everything else goes under "Out of scope",
  with no severity, and cannot move the verdict. A second pass brief now says
  the same thing from the other side: findings outside the intake are not the
  implementer's to fix, and the intake, not the reviewer, is the source of
  truth about scope.
- What was deliberately not done: no verdict is ever weakened, and no unit
  merges on anything but `clear`. `AGENTS.md` forbids weakening a gate to get a
  result, and a round limit that let a blocked unit through would be exactly
  that. The limit stops automatic re-dispatch and hands the decision to a
  person; it does not lower the bar the unit has to clear.
- Amended 2026-08-29, the same day, because the first version left the loop's
  engine running. Counting rounds and bounding what counts as a finding did not
  change the fact that every round re-read the unit's whole diff, `git diff
  develop...HEAD`. A full pass is a fresh chance to find something new in code
  two earlier passes already cleared, so the rounds had no natural end however
  well the fixes landed. A round after the first now asks a narrower question:
  for each recorded finding, is it fixed and what test would catch its
  regression; what did this round's own commits break, which is where two of
  this project's past findings actually came from; and is the unit's
  verification green. Code that neither changed nor relates to a recorded
  finding was read twice already and may not be raised again. Something new is
  admissible only against a numbered acceptance criterion, with the failure
  shown. The prompt also says outright that clearing a unit whose findings are
  fixed is the correct outcome, because a reviewer that never clears anything is
  not a stricter reviewer, it is a gate that does not open. Found by the user
  asking what a third review was for.
- Rejected: detecting a repeated finding by comparing its text across rounds.
  The wording changes between rounds, so the comparison would be fuzzy, and a
  fuzzy match that says "you already fixed this" is worse than no check.
- Revisit only if: a unit legitimately needs more than two rounds often enough
  that `--another-pass` becomes reflexive. That would mean units are too large,
  and the answer is a narrower decomposition, not a higher limit.


## D-023: The client order id is derived before the risk approval, not from it

- Date: 2026-08-29
- Origin: reading the UNIT-012 intake before dispatching it. Its contract named
  `client_order_id(plan_id, approval_id, intent)`, which cannot be implemented.
- The cycle: `build_mleg_order` places `client_order_id` inside the payload,
  `order_payload_hash` hashes that payload, and `RiskApproval.order_payload_hash`
  binds to that hash. An id derived from `approval_id` needs the approval first,
  and the approval needs the payload, and the payload needs the id.
- Decision: the id is derived from `(plan_id, quantity, limit_price)`, all of
  which are fixed before an approval exists. The order of operations is id, then
  payload, then payload hash, then approval. The approval therefore binds the
  exact bytes that will be submitted, id included.
- The conflict this resolves, recorded because two sources genuinely disagreed.
  `options-alpha-agent-design.md` section 11 step 3 and
  `orchestrator-system-prompt.md` both describe approval first, with the adapter
  owning the id and the caller observing it only after submission. UNIT-011,
  merged and reviewed clear, requires the id inside the hashed payload, and its
  AC-10 exists precisely so that an approval cannot authorise a changed
  quantity, price, or id. UNIT-011 wins. The alternative was to hash an economic
  payload that excludes the id, which reopens a merged acceptance criterion
  written to close that exact hole.
- Rejected alternative: dropping `order_payload_hash` from `RiskApproval` and
  re-deriving at submit time. That amends a frozen domain contract from UNIT-001
  and changes every consumer, to buy nothing the chosen ordering does not
  already give.
- Consequence that falls out rather than needing a mechanism: because
  `limit_price` is an input, a price ladder step yields a new deterministic id by
  construction, which is the fail-closed default UNIT-012 already prescribed for
  the unverified replace semantics. A retry at the same price yields the same
  id, which is what makes resolving an ambiguous submit safe.
- Obligation this creates: `plan_id` must be unique per plan instance. Two
  distinct decisions carrying one `plan_id` at the same quantity and price would
  derive one id and the second would be silently collapsed into the first.
  UNIT-012 AC-8 pins this as a stated precondition.
- Revisit only if: the Day-0 Alpaca smoke test shows replace semantics that make
  a stable id across ladder steps both possible and necessary. Record the
  observed behaviour before changing anything.
