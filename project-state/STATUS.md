# AlphaLedger project status

Last updated: 2026-08-28

## Current phase

Released as v0.1.0. The development harness and the first vertical unit are
done, and `main` now holds them. The Python
project exists on 3.14 with a committed lockfile, and the frozen domain
contracts are merged, which unblocks both lanes. No broker, data, or research
code exists yet.

The dates in `hackathon-build-plan.md` are stale, confirmed by the user on
2026-08-28. Treat the G0 to G6 sequence as binding and the calendar attached to
it as not binding. Do not schedule work from that document until a real
deadline is recorded here.

## Active gate

G0. Competition rules, account, permissions, data entitlements, integration
versions, and submission requirements remain unverified for the actual event
environment.

## Verified artifacts

- `specs/`: the SDD intake, the unit template, and five unit intakes. UNIT-001
  merged; UNIT-010, UNIT-020, UNIT-021, UNIT-022 claimable.
- `src/alphaledger/domain/`: the five records from design section 14 plus
  `ObservationTimestamps`. Money is `Decimal`, not the `float` the design
  sketched; the conflict and its resolution are recorded in the UNIT-001
  intake.
- Quality gate passes end to end on 3.14: `uv sync --frozen`, `ruff check`,
  `ruff format --check`, `mypy src` under strict, and 32 tests. The gate now
  runs inside `verify_harness.sh` too, so the script cannot be green while
  the repository gate is red.
- `scripts/coord.py`: claiming across runtimes. Self-test passes with 11 cases.
  The dependency gate was exercised on the real files in both directions:
  refused while UNIT-001 was unmerged, allowed once it merged.
- `scripts/verify_harness.sh`: 33 checks, all passing, including both guards
  firing inside a worktree.
- `.claude/hooks/guard.py` and `.codex/hooks/guard.py`: 23 and 25 cases.
- `scripts/dispatch.sh`: one-line Codex dispatch for a unit. Codex is the
  standing default runtime for implementation work; see the parallel work
  protocol in `AGENTS.md`.
- UNIT-001 was reviewed by `code-reviewer` after the fact. Two high findings,
  a bare string shredded into characters across every audit field and NaN or
  Infinity admitted into float fields, are fixed with regression tests.
- Eight skills across both runtimes, each with `origin` and, on the Codex side,
  an `agents/openai.yaml` binding. `tdd-workflow` and `verification-loop` were
  ported from ECC and adapted; the six lifecycle skills stay manual-only.
- Commit subjects follow conventional commits, enforced by both guards.
- Git flow is live. `develop` is on `origin` and is the GitHub default branch,
  so a fresh clone lands on the work rather than on stale `main`.

## Not yet verified

- competition paper account identity, starting balance, and options level;
- OPRA versus indicative options entitlement and equity feed mode;
- current MLeg request behavior in the competition environment;
- event rules on pre-kickoff code and required submission artifacts;
- the real submission deadline, which the build plan no longer supplies;
- every G1 to G6 artifact.

## Known gaps

- `main` and `develop` are level at v0.1.0, but no release process is exercised
  beyond this first cut.
- The roster still names `teammate/claude` as a placeholder. `coord.py` refuses
  any owner that does not match `handle/claude` or `handle/codex`.
- No broker, data, or research code exists. Every G1 to G6 artifact is open.

## Next three tasks

1. Dispatch UNIT-010, the paper endpoint assertion, to Codex with
   `scripts/dispatch.sh UNIT-010 pablo/codex`. It is the gate every later order
   path depends on.
2. Record the real competition dates and account facts in the run manifest,
   then pass or block G0.
3. Write the intakes for UNIT-011 and UNIT-012 so the execution lane has a
   queue deeper than one unit.

## Read first next session

1. `AGENTS.md`, including the parallel work protocol
2. `specs/000-INTAKE.md`
3. `project-state/DECISIONS.md`, D-009 through D-012
4. `options-alpha-agent-design.md` sections 0 to 4 and 14
