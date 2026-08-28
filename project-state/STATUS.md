# AlphaLedger project status

Last updated: 2026-08-28

## Current phase

Released as v0.1.0, and `develop` has moved well past it. The research lane
delegated in `RESEARCH-LANE.md` is complete: UNIT-020, UNIT-021, and UNIT-022
are merged, so point-in-time recording, the lagged frozen universe, and the
residual price and volume baseline all exist and are reviewed. The execution
lane has the paper endpoint assertion and nothing after it. No news, forecast,
structure, risk, order, or ledger code exists.

Every number in the research lane comes from a fixture. Nothing has touched
Alpaca.

The dates in `hackathon-build-plan.md` are stale, confirmed by the user on
2026-08-28. Treat the G0 to G6 sequence as binding and the calendar attached to
it as not binding. Do not schedule work from that document until a real
deadline is recorded here.

## Active gate

G0. Competition rules, account, permissions, data entitlements, integration
versions, and submission requirements remain unverified for the actual event
environment.

## Verified artifacts

- `specs/`: the SDD intake, the unit template, and seven unit intakes. Five
  merged; UNIT-011 and UNIT-012 claimable and both in the execution lane.
- `src/alphaledger/domain/`: the five records from design section 14 plus
  `ObservationTimestamps`. Money is `Decimal`, not the `float` the design
  sketched; the conflict and its resolution are recorded in the UNIT-001
  intake.
- Quality gate passes end to end on 3.14: `uv sync --frozen`, `ruff check`,
  `ruff format --check`, `mypy src` under strict, and 176 tests. The gate now
  runs inside `verify_harness.sh` too, so the script cannot be green while
  the repository gate is red.
- `src/alphaledger/data/recorder.py` and `storage.py`, UNIT-020. Six
  timestamps and a feed on every record, an `as_of` read with no wall-clock
  alternative, five orderings enforced feed by feed under the obligation D-014
  hands the adapter, availability derived from a documented lag where delivery
  cannot be proven, and `record` idempotent across a restart.
- `src/alphaledger/data/universe.py`, UNIT-021. Membership decided at the prior
  close from evidence knowable then, capped at thirty, ranked by median dollar
  volume, hashed so a frozen run can be verified in another process. Tied
  timestamps and unregistered feeds are refused rather than resolved. The
  static fallback substitutes for optionability evidence alone and always
  discloses itself.
- `src/alphaledger/evidence/price_volume.py`, UNIT-022. All eight features from
  design section 5.1 over a rolling median demeaning against sector peers. A
  missing feature is absent and named in a flag, never an imputed zero. The
  event window admits a session only when its whole return period follows the
  event.
- Every research unit went through two `backtest-auditor` rounds. Across the
  three, the reviews produced fifteen findings, including one that blocked a
  merge and one same-bar leak. Two of those were regressions introduced by an
  earlier round's own fix, which is the pattern `RESEARCH-LANE.md` predicts.
  Sixty-eight injected defects are each caught by a named test.
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
- The roster in `AGENTS.md` still names `teammate/claude` as a placeholder,
  while the research lane is in fact being worked by `mazwy/claude`. The roster
  table is stale, not the registry.
- No real feed is connected anywhere. Every timestamp rule, screening
  condition, and feature value is proven self consistent against fixtures, not
  against Alpaca.
- No threshold in the research lane has been selected on data. The universe
  floors, the feature lookbacks, the winsorization limits, and the sector map
  are declared defaults. Design section 4 and section 5.1 require them to be
  chosen on development data, registered as trials, and frozen before any
  autonomous session. That gate is untouched, and `feature_version` and the
  universe hash exist so the selection is auditable when it happens.
- `Bar` refuses a close outside its own high and low, which is tautologically
  true of a well formed bar but would halt on a vendor inconsistency around a
  corporate action. Whether Alpaca ever emits one is a question for
  `alpaca-docs-researcher` before UNIT-020's adapter feeds UNIT-022. Recorded
  in the UNIT-022 intake.
- Concurrent writers on one store are unsupported and untested. A second
  already-open recorder can still duplicate a fact the first committed.
- Nothing compares the price family against news or combined baselines, which
  is the comparison the whole lane exists to make.
- The labeler contract and the frozen `NewsLabel` record disagree. Prompt B in
  `orchestrator-system-prompt.md` emits `entity_match`, a ticker, and `unknown`
  for novelty and relevance; design section 14 and
  `src/alphaledger/domain/contracts.py` hold none of those. A conforming
  labeler cannot be recorded without either amending the frozen contracts or
  discarding what the model said it was unsure about. UNIT-023 is `blocked` on
  it and the full statement is in that intake.
- No news, forecast, structure, risk, order, or ledger code exists. Every G1 to
  G6 artifact is open.

## Next three tasks

1. Record the real competition dates and account facts in the run manifest,
   then pass or block G0. It is the oldest open item and now the only thing
   holding the shape of everything after it.
2. Dispatch UNIT-011 and UNIT-012 to Codex. The execution lane is two units
   behind the research lane and owns the harder safety surface.
3. Resolve the news label conflict recorded in the UNIT-023 intake, then write
   the intakes for UNIT-025, the pooled forecast model, and UNIT-026, the
   baselines and metrics. UNIT-023 and UNIT-024 are written; UNIT-024 is
   claimable now and UNIT-023 is blocked on that conflict.

## Read first next session

1. `AGENTS.md`, including the parallel work protocol
2. `specs/000-INTAKE.md`
3. `project-state/DECISIONS.md`, D-009 through D-015
4. `RESEARCH-LANE.md`, then the handoff notes in the three merged research
   unit intakes, which carry the findings and the open questions
5. `options-alpha-agent-design.md` sections 0 to 5 and 14
