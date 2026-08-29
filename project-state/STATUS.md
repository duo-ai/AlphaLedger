# AlphaLedger project status

Last updated: 2026-08-29

## Current phase

Released as v0.1.0, and `develop` has moved well past it. Fourteen units are
merged: UNIT-001 through UNIT-004, UNIT-010 through UNIT-012, UNIT-014,
UNIT-015, and UNIT-020 through UNIT-024. UNIT-013, the risk approval token, is
held by `pablo/codex` and is the only unit in flight. It is at `in_review`
with a first-round verdict of `block`, so it needs a second pass, and D-022
bounds that pass: a finding counts only if it is actionable inside UNIT-013's
own path globs and bears on one of its numbered acceptance criteria. UNIT-025 exists as an
intake and is not claimable, because it depends on UNIT-027, which is a backlog
row with no intake file; `coord.py` refuses the claim by name rather than
letting it through.

UNIT-004 and UNIT-011 each took three implementation passes and three review
rounds, the first two returning `block` and the third `clear`. UNIT-012 took
two, `block` on a duplicate submit that survived a crash, then `clear`.
UNIT-023 cleared on its first round, and its review still found a real gap: a
rewrite of the clustering from anchor-relative to chained windowing passed the
entire suite, so a correct design choice had no regression guard. It has one
now.

The research lane delegated in `RESEARCH-LANE.md` is complete, and both feature
families now exist. The validation discipline that has to exist before any
model is fit is in place: point-in-time recording, the lagged frozen universe,
the residual price and volume family, the point-in-time news family,
chronological purged splits, and the trial registry. The frozen label contract
holds what the labeler emits, and every enumerated field on it is checked at
run time.

The execution lane has the paper endpoint assertion, the order schema adapter,
the order state machine, chain enumeration with exact payoffs, and broker
reconciliation merged. No risk, ledger, kill switch, or price ladder code
exists on `develop` yet, and no transport submits anything.

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

- `specs/`: the SDD intake, the unit template, and twelve unit intakes. Eleven
  merged, with UNIT-023 available in the research lane. UNIT-013 through
  UNIT-017 are backlog rows in `specs/000-INTAKE.md` with no intake file yet.
  That file is the master decomposition and it assigns UNIT-013 to the risk
  approval token; UNIT-011 and UNIT-012 had both named it as the limit price
  ladder, which was wrong in each and is corrected in place. The ladder design
  section 11 step 4 requires is consequently owned by no row at all, which is
  recorded there as a gap rather than resolved by inventing a unit.
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
- `src/alphaledger/evidence/news.py` and `labeler.py`, UNIT-023. Eight features
  encoded from labels alone, every ratio dividing by one weight so the family
  is commensurable. Syndication clustering is exact after canonicalisation
  rather than a similarity threshold, because a threshold would be an
  unregistered trial inside a feature definition, and the limitation is stated
  rather than hidden. An article and its label are both checked against
  `as_of`; `event_time` stays exempt per D-014. Cleared by `backtest-auditor`
  on round one.
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
- OPRA versus indicative options entitlement and equity feed mode, and whether
  the account has real-time access or the documented fifteen minute delay;
- every schema claim in D-024, which is read from the API reference and has
  never been checked against a live payload;
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
  happened three times: UNIT-004's round two, UNIT-011's round three, and
  UNIT-012's round two, each graded from its findings by the session, which is
  what D-018 puts on the session anyway. `codex exec review` states its
  conclusion as a prose `VERDICT:` line, as a JSON `overall_correctness` field,
  or as neither, and only the third is a problem. `review.sh` now appends an
  explicit "NO VERDICT STATED" notice to an artifact carrying neither shape, so
  a reader is told rather than left to notice an absence. It still grades
  nothing; that stays with the session on purpose.
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
- No model, risk, or ledger code exists. News features exist per UNIT-023, but
  nothing labels an article: the LLM client, its caching, and its output
  validation are deliberately out of that unit and belong to a later one, so
  the news family cannot run on real data at all yet. The order lifecycle and
  chain enumeration exist, but nothing submits through them: there is no
  transport, no risk approval, and no durable store behind
  `RecordedSubmissionAttempt`, whose durability is a caller obligation UNIT-012
  states and cannot enforce. Every G1 to G6 artifact is open.

## Next three tasks

1. Record the real competition dates and account facts in the run manifest,
   then pass or block G0. It is now the oldest open item by a wide margin and
   the only thing holding the shape of everything after it. It needs facts only
   the user has, and no amount of further unit work substitutes for it. This
   item has been first on the list for three checkpoints and has not moved.
2. Write the UNIT-027 intake, forward residual label construction. It is the
   nearest thing to the critical path: UNIT-025 is specified and blocked on it
   by name, and nothing else in the research lane can move until labelled
   outcomes exist. The row was created on 2026-08-29 after writing UNIT-025
   surfaced that no unit owned the work, which is the third hole of that shape
   this decomposition has had to close.
3. Write the UNIT-026 intake, the required baselines. Design section 4 and
   `.claude/rules/20-research-integrity.md` demand random/shuffled, price-only,
   news-only, and combined baselines on one split under one conservative cost
   model. Nothing compares the two families today, which is the comparison the
   whole research lane exists to make, so until UNIT-026 lands the lane has
   built two families and answered nothing. It depends on UNIT-025.

The execution lane's open backlog rows are UNIT-016, the append-only decision
and trade ledger, UNIT-017, the kill switch and emergency flatten, and
UNIT-018, the bounded entry price ladder. None has an intake. `AGENTS.md`
assigns intake authoring to `pablo/claude`, so they are noted here rather than
claimed from the research lane.

## Read first next session

1. `AGENTS.md`, including the parallel work protocol
2. `specs/000-INTAKE.md`
3. `project-state/DECISIONS.md`, D-009 through D-023
4. `RESEARCH-LANE.md`, then the handoff notes in the four merged research
   unit intakes, which carry the findings and the open questions
5. `options-alpha-agent-design.md` sections 0 to 5 and 14
