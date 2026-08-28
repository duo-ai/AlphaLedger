# AlphaLedger project status

Last updated: 2026-08-28

## Current phase

Development harness complete; application scaffolding has not started. The
spec-driven operating model, the branching model, the coordination tool, and
the first three unit intakes exist. There is no `pyproject.toml`, no `src/`,
and no application tests.

The dates in `hackathon-build-plan.md` are stale, confirmed by the user on
2026-08-28. Treat the G0 to G6 sequence as binding and the calendar attached to
it as not binding. Do not schedule work from that document until a real
deadline is recorded here.

## Active gate

G0. Competition rules, account, permissions, data entitlements, integration
versions, and submission requirements remain unverified for the actual event
environment.

## Verified artifacts

- `options-alpha-agent-design.md`, `hackathon-build-plan.md`, and
  `orchestrator-system-prompt.md`: canonical design, sequence, and runtime
  orchestration.
- `specs/000-INTAKE.md`, `specs/TEMPLATE.md`, `specs/units/`: the SDD intake,
  the unit template, and UNIT-001, UNIT-010, UNIT-020.
- `scripts/coord.py`: unit claiming across runtimes. Self-test passes with 11
  cases. The dependency gate and owner validation were exercised against the
  real unit files, and refused claims leave the tree untouched.
- `scripts/gitflow-init.sh`: configures `main` as production and `develop` as
  integration. Both branches exist locally; only `main` exists on `origin`.
- `.claude/hooks/guard.py` and `.codex/hooks/guard.py`: self-tests pass with 17
  and 19 cases. Both were verified to fire inside a git worktree.
- Python 3.14: the full stack was installed into a real cp314 venv and
  imported, including the XNYS exchange calendar. See D-012 for the versions.
- All six Claude specialists run on sonnet at high effort.

## Not yet verified

- competition paper account identity, starting balance, and options level;
- OPRA versus indicative options entitlement and equity feed mode;
- current MLeg request behavior in the competition environment;
- event rules on pre-kickoff code and required submission artifacts;
- Python project, lockfile, application tests, and every G1 to G6 artifact;
- the real submission deadline, which the build plan no longer supplies;
- whether `develop` should be pushed to `origin` and made the default branch.

## Next three tasks

1. Claim and implement UNIT-001, which freezes the domain contracts and blocks
   every other unit. Scaffold `pyproject.toml` on 3.14 as part of it.
2. Record the real competition dates and account facts in the run manifest,
   then pass or block G0.
3. Write the intakes for UNIT-011 and UNIT-012 so the execution lane has a
   queue deeper than one unit.

## Read first next session

1. `AGENTS.md`, including the parallel work protocol
2. `specs/000-INTAKE.md`
3. `project-state/DECISIONS.md`, D-009 through D-012
4. `options-alpha-agent-design.md` sections 0 to 4 and 14
