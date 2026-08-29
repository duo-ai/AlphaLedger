# AlphaLedger project status

Last updated: 2026-08-29

## Current phase

Released as v0.1.0, and `develop` has moved well past it. Ten of twelve units
are merged. UNIT-004 and UNIT-011 each went through three implementation
passes and three review rounds, the first two returning `block` and the third
`clear`, and both merged into `develop` today. UNIT-012, the order state
machine and idempotent client order ids, is claimed by pablo/codex and being
implemented in a separate worktree. UNIT-023 is available in the research
lane. The research lane delegated in `RESEARCH-LANE.md` is complete, and the
validation discipline that has to exist before any model is fit is in place:
point-in-time recording, the lagged frozen universe, the residual price and
volume baseline, chronological purged splits, and the trial registry. The
frozen label contract now holds what the labeler emits, and every enumerated
field on it is checked at run time.

The execution lane now has the paper endpoint assertion and the order schema
adapter merged, and the order state machine is being implemented against them.
No news, model, structure, risk, order lifecycle, or ledger code exists on
`develop` yet.

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

- `specs/`: the SDD intake, the unit template, and twelve unit intakes. Ten
  merged. UNIT-012 is claimed by pablo/codex and in progress in its own
  worktree, and UNIT-023 is available in the research lane. UNIT-013,
  UNIT-014, and UNIT-015 are referenced by D-023 and by the UNIT-012 intake,
  but no intake file exists for any of them yet, verified against
  `ls specs/units/`.
- `src/alphaledger/domain/`: the five records from design section 14 plus
  `ObservationTimestamps`. Money is `Decimal`, not the `float` the design
  sketched; the conflict and its resolution are recorded in the UNIT-001
  intake.
- Quality gate passes end to end on 3.14: `uv sync --frozen`, `ruff check`,
  `ruff format --check`, `mypy src` under strict, and 350 tests. The gate now
  runs inside `verify_harness.sh` too, so the script cannot be green while
  the repository gate is red. `verify_harness.sh` is at 40 checks.
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
- `src/alphaledger/domain/contracts.py`, UNIT-002. `NewsLabel` holds the entity
  match, the ticker, and the labeler's stated limitations, and novelty and
  relevance may say `unknown`. Every enumerated field is checked at run time,
  because a Literal stops nothing where the value came out of a model's JSON.
  Prompt B's consistency rules stay with the adapter, per D-016 and D-014.
- `src/alphaledger/forecast/`, UNIT-024. An expanding walk-forward whose windows
  are purged by at least the horizon, where a label is usable only when both its
  prediction and its outcome fall inside one window, and an append-only trial
  registry that refuses a result for an unregistered trial and refuses a second
  result over the first, on write and again on read.
- Every research unit went through two `backtest-auditor` rounds. Across the
  three, the reviews produced fifteen findings, including one that blocked a
  merge and one same-bar leak. Two of those were regressions introduced by an
  earlier round's own fix, which is the pattern `RESEARCH-LANE.md` predicts.
  Sixty-eight injected defects are each caught by a named test.
- `src/alphaledger/domain/contracts.py`, UNIT-003. `category` is checked at
  run time against a literal list, closing the last enumerated label field that
  a `Literal` alone could not defend once the value came out of a model's JSON.
  UNIT-023 depends on it.
- `config/` and `.env.example`, per D-017. Non-secret operational constants are
  committed so they can be hashed into a run manifest; secrets are named in
  `.env.example` and live only in the environment. Every value there currently
  mirrors a dataclass default and none has been selected on data. UNIT-004 is
  merged: `alphaledger.config` now loads these files into frozen records and
  produces the content hash, and its drift test keeps `universe.toml` and
  `feature.toml` equal to the dataclass defaults in `data/universe.py` and
  `evidence/price_volume.py`. Those dataclass defaults still exist and are
  redundant rather than removed; the intake calls removing them a later,
  separate change.
- `scripts/dispatch.sh`, `review.sh`, `watch.py`, `notable.py`, and
  `dispatch_status.py`: dispatch a unit to Codex, dispatch its reviewer, follow
  either as a live coloured stream, and be told when one stops or ends. A
  `--continue` dispatch rebases the branch onto `develop` first, so a second
  pass reads the intake amendment that carries the review findings rather than
  the specification it already implemented. Both scripts now rotate a previous
  round's artifacts aside instead of truncating them; `review.sh` gained a
  `--self-test` covering two cases, and `verify_harness.sh` checks it.
- `scripts/coord.py`: claiming across runtimes. Self-test passes with 23 cases.
  The dependency gate was exercised on the real files in both directions:
  refused while UNIT-001 was unmerged, allowed once it merged.
- `scripts/verify_harness.sh`: all checks passing, including both guard scripts
  self-testing inside a worktree. Note the precision: that shows the script
  runs there, not that a runtime loads the hook there. The second question was
  answered separately by a live probe under `codex exec`, which returned
  "Command blocked by PreToolUse hook" from inside a worktree. See D-020.
- `.claude/hooks/guard.py` and `.codex/hooks/guard.py`: 40 and 42 cases.
- UNIT-001 was reviewed by `code-reviewer` after the fact. Two high findings,
  a bare string shredded into characters across every audit field and NaN or
  Infinity admitted into float fields, are fixed with regression tests.
- Thirteen skills across both runtimes, each with `origin` and, on the Codex
  side, an `agents/openai.yaml` binding. `tdd-workflow` and `verification-loop`
  were ported from ECC and adapted; five more, `spec-plot`, `spec-analyze`,
  `spec-clarify`, `spec-plan`, and `spec-tasks`, implement the
  `spec-plot -> spec-analyze -> spec-clarify -> spec-plan -> spec-tasks` chain
  `AGENTS.md` names for work larger than one unit; the six lifecycle skills
  stay manual-only.
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
- The Codex CLI changed under the dispatcher on 2026-08-29: 0.150.1 refuses
  `--approve-for-me` together with `-s`, and both second-pass dispatches died on
  the argument error while reporting a pid as though they had started. The
  dispatcher now waits for a first event and refuses to report a launch that
  never began, and it rotates a previous stream rather than truncating it. The
  first-pass event streams for UNIT-004 and UNIT-011 were destroyed before that
  rotation existed; their `.result.md` summaries and review artifacts survive,
  the turn-by-turn record does not.
- A review that omits its `VERDICT:` line is silent on the monitor, because
  `scripts/notable.py` announces only a verdict it can see. This has now
  happened twice, noted in each unit's own handoff notes: the UNIT-004 review
  did exactly that, and so did UNIT-011's round three review, and both were
  graded from their findings by the session, which is what D-018 puts on the
  session anyway.
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
- The trial registry detects a duplicate result written by two racing processes
  and fails closed on the next read, but does not prevent the race. The
  reasoning for not adding an untested lock is in the UNIT-024 intake.
- No model consumes a fold and no result is ever recorded, so the registry is
  proven to refuse what it should and never proven against a real research run.
- No news, model, structure, risk, order lifecycle, or ledger code exists. The
  order schema adapter merged with UNIT-011, but nothing manages an order
  through its states until UNIT-012 lands. Every G1 to G6 artifact is open.

## Next three tasks

1. Take UNIT-012 through review once pablo/codex's implementation lands:
   `scripts/review.sh UNIT-012`, then `coord.py review` and merge if clear. Its
   intake carries the corrected transition table and the identifier ordering
   settled in D-023, so a clean first pass is plausible but not assumed.
2. Record the real competition dates and account facts in the run manifest,
   then pass or block G0. It is the oldest open item and the only thing holding
   the shape of everything after it. It needs facts only the user has.
3. Write intakes for UNIT-013, UNIT-014, and UNIT-015, referenced by D-023 and
   by the UNIT-012 intake, none of which has an intake file yet. UNIT-014 is
   building legs from a real chain and UNIT-015 is the scheduled reconcile
   loop, both named consistently wherever they appear. UNIT-013 is not: UNIT-011
   and UNIT-012 call it the limit price and its ladder, while UNIT-004's own
   Out list calls it the arm state and what it binds to. That disagreement is
   unresolved and belongs to whoever writes the intake, not to this file.
   UNIT-023 is claimable in parallel in the research lane; it shares no file
   with UNIT-012.

## Read first next session

1. `AGENTS.md`, including the parallel work protocol
2. `specs/000-INTAKE.md`
3. `project-state/DECISIONS.md`, D-009 through D-023
4. `RESEARCH-LANE.md`, then the handoff notes in the four merged research
   unit intakes, which carry the findings and the open questions
5. `options-alpha-agent-design.md` sections 0 to 5 and 14
