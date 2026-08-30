# AlphaLedger project status

Last updated: 2026-08-30

## Current phase

Released as v0.1.0, and `develop` is well past it. This checkpoint was verified
against `develop` at `556bebd` on 2026-08-30 by running the commands it cites,
not by carrying the previous checkpoint forward.

Twenty-one of twenty-six units are merged, code and registry both: UNIT-001
through UNIT-004, UNIT-010 through UNIT-018, UNIT-020 through UNIT-025,
UNIT-027, and UNIT-030. The quality gate passes end to end on that ref:
`uv sync --frozen`, `ruff check`, `ruff format --check`, `mypy src` under
strict across 32 source files, 707 tests, and `scripts/verify_harness.sh`.

Four units are available and genuinely claimable, meaning every dependency is
merged and `coord.py check` passes for each: UNIT-005, UNIT-019, UNIT-026, and
UNIT-028. One is claimed and in progress, UNIT-029, by `mazwy/claude`.

Three units merged on 2026-08-30, all in the research lane.

UNIT-027, the forward residual labels, took two rounds. Round one was blocked
on two defects the reviewer demonstrated on constructed input rather than
argued from reading. `outcome_time` did not cover a peer bar reached through a
gap: a peer missing sessions inside the holding window produced a multi-session
return whose predecessor bar sat outside the window, and a separate function
scanning only the window could not see it, so a revision to a consumed bar left
the outcome instant unmoved and UNIT-024 would have admitted the label into a
window the purge exists to exclude it from. The fix is structural rather than a
patch: the returns now carry the bars each was measured across, the residual
sum reports the outcome instant alongside the value, and the second function is
deleted, so no two derivations remain that could disagree. The second defect
was a specification defect first: AC-4 made a delisting a `None` while the test
list asserted a raise for the same input, and the same author wrote both, so
writing the test first did not catch it.

UNIT-030 widened `Article` to carry the article summary, per D-025, and cleared
on its first round with no surviving mutations. It deliberately does not copy
`headline`'s canonicalisation refusal, because that check exists for a
clustering reason that does not transfer and copying it would refuse an article
on how informative its text is, which D-025 records as a selection effect
rather than a cleaning step.

UNIT-025, the pooled forecast and the section 6 eligibility gates, took two
rounds and is the largest unit in the research lane. Its round one verdict was
`conditional` on four findings. The one worth reading is that AC-2c, a
criterion the implementer added during its own pre-implementation read,
promised `fit` refuses any supplied label outside the training and calibration
windows, and only the test-window subset was built. The criterion's own stated
falsification exercised only the half that existed, so nothing in the test list
could have caught it. It was closed by implementing the full prose rather than
narrowing the criterion.

D-027 was recorded on 2026-08-30: `numpy` and `scikit-learn` enter the
dependency set, pinned, and are the first runtime dependencies the application
carries. Everything merged before UNIT-025 is standard library only. The
decision record states plainly that it widened UNIT-025's path globs onto
`pyproject.toml` and `uv.lock`, that this bends D-010, that it was safe only
because UNIT-025 was the sole claimed unit at the time, and that it is not a
precedent.

Two decomposition gaps were closed on 2026-08-30 by writing the intakes that
were missing rather than by recording the gaps again. UNIT-019 owns the
function that turns a structure's quotes into the ordered candidate rung prices
UNIT-018 consumes, which no row had claimed while both the ladder and the chain
enumeration were merged. UNIT-005 commits the three design section 10
thresholds `config/risk.toml` does not carry, which is why UNIT-013 and
UNIT-017 each take them as required explicit parameters.

The execution lane is unchanged since 2026-08-29 and no transport submits
anything to Alpaca.

The dates in `hackathon-build-plan.md` are stale, confirmed by the user on
2026-08-28. Treat the G0 to G6 sequence as binding and the calendar attached to
it as not binding. Do not schedule work from that document until a real
deadline is recorded here.

## Active gate

G0. Competition rules, account, permissions, data entitlements, integration
versions, and submission requirements remain unverified for the actual event
environment.

## Verified artifacts

- `specs/`: the SDD intake, the unit template, and twenty-six unit intakes.
  Twenty-one units are merged, code and registry both. UNIT-029 is `claimed` by
  `mazwy/claude`. UNIT-005, UNIT-019, UNIT-026, and UNIT-028 are `available`
  and each is genuinely claimable, confirmed by running `coord.py check` for
  all four rather than by reading their dependency lists. Every row in
  `specs/000-INTAKE.md` has an intake file; that file's prose named four units
  as intake-less backlog rows until 2026-08-30 and was corrected in the same
  change that wrote the last two intakes.
  The price ladder design section 11 step 4 requires is owned by UNIT-018,
  entry side only, and the function that turns a structure's quotes into the
  ordered candidate rung prices it consumes is now owned by UNIT-019, written
  on 2026-08-30. That was the longest-standing decomposition gap in the
  execution lane: the ladder and the chain enumeration both merged with the
  function between them owned by nobody. UNIT-018 remains claimable and
  testable without it, exactly as UNIT-013 and UNIT-017 were each written and
  merged before their real callers existed.
- `src/alphaledger/domain/`: the five records from design section 14 plus
  `ObservationTimestamps`. Money is `Decimal`, not the `float` the design
  sketched; the conflict and its resolution are recorded in the UNIT-001
  intake.
- Quality gate passes end to end on 3.14: `uv sync --frozen`, `ruff check`,
  `ruff format --check`, `mypy src` under strict across 29 source files, and
  590 tests, verified against `develop` at `e8932b9`. The gate now runs inside
  `verify_harness.sh` too, so the script cannot be green while the repository
  gate is red. `verify_harness.sh` is at 43 checks, all passing; that count is
  unaffected by which units are merged, since it tests tooling, not unit code.
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
- UNIT-020, UNIT-021, UNIT-022, and UNIT-024 each went through two
  `backtest-auditor` rounds before clearing; UNIT-023 cleared on its first,
  recorded separately below. Across the four two-round units the reviews found
  real defects, including one that blocked a merge and one same-bar leak, and
  at least two were regressions introduced by an earlier round's own fix,
  which is the pattern `RESEARCH-LANE.md` predicts. Each unit's own intake
  records its exact finding and defect-injection counts; the aggregate this
  bullet used to carry was stale against the five now-merged units and has
  been dropped rather than re-summed without rereading all five in full.
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
- `scripts/coord.py`: claiming across runtimes. Self-test passes with 28 cases.
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
- every schema claim in D-024, read from the published API reference rather
  than observed: the one credentialed call made against it, on 2026-08-29,
  returned 401, so this is blocked on access, not on further research effort;
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
- No real feed is connected anywhere, in either lane. Every timestamp rule,
  screening condition, and feature value in the research lane is proven self
  consistent against fixtures, not against Alpaca; the one credentialed call
  made against a live endpoint, for D-024, returned 401. The execution lane is
  no different: risk approval, chain enumeration, broker reconciliation, the
  kill switch, the ledger, and the entry price ladder are each tested against
  in-memory doubles and stubs, and none of them has ever submitted anything to
  a broker, paper or otherwise. This is the largest unproven claim in the
  project, and G0 does not resolve it by itself: it unblocks credentials, it
  does not exercise one.
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
- The function that turns a structure's quotes into the ordered candidate rung
  price sequence UNIT-018 consumes is now owned by UNIT-019, written on
  2026-08-30 and available. It is specified, not implemented, so the gap in the
  code is unchanged; what changed is that a row owns it. UNIT-018 remains
  merged and tested against fixture sequences, as it was written to be.
- Three thresholds design section 10 requires are still not committed
  anywhere, verified against `config/risk.toml` on 2026-08-30 rather than
  carried forward: it has no `max_snapshot_age`, so UNIT-013's `approve` takes
  it as a required explicit parameter rather than a frozen default, and no
  `daily_loss_stop_fraction` or `peak_to_valley_fraction`, so UNIT-017's
  `evaluate_kill_switch` takes both explicitly too. Per D-017 an uncommitted
  threshold is meant to be the exception, not the steady state, for exactly the
  values that most need freezing before an autonomous session, and a limit
  passed as a bare argument is not in `risk_config_hash`, so a session that
  halted on one cannot prove which one. UNIT-005 now owns closing this and is
  available; the values are still uncommitted until it merges. Section 10
  supplies two of the three numbers and none for the staleness bound, which
  that intake records rather than hides.
- Model code now exists on `develop`: UNIT-025 merged a ridge magnitude model,
  a logistic direction model, and the section 6 eligibility gates. It has never
  been fitted on real data. Every number comes from a fixture with a known
  linear relationship, and `eligibility.decide` evaluates gates 1 to 4 only,
  exporting `UNEVALUATED_GATES` so a caller cannot read `eligible` as "cleared
  section 6": gate 5 is a property of the held-out evaluation across all
  candidates and gate 6 is execution-lane state. News features exist per
  UNIT-023, but nothing labels an article: the LLM client, its caching, and its
  output validation are deliberately out of that unit and belong to UNIT-029,
  which has an intake and is claimed by `mazwy/claude` as of 2026-08-30 but is
  not merged, so the news family still cannot run on real data at all. The order lifecycle, risk
  approval, chain enumeration, broker reconciliation, the kill switch, and now
  the ledger are all on `develop`, and a durable store behind
  `RecordedSubmissionAttempt` exists in `src/alphaledger/ledger/decisions.py`,
  a durability UNIT-012 states as a caller obligation and could not itself
  enforce. But nothing submits through any of this: there is still no
  transport that reaches Alpaca, so the ledger's durability has never been
  exercised by a real order, only by fixtures.

## Next three tasks

1. G0 is owned by `mazwy` as of 2026-08-29, handed over by the user. It is the
   single largest open item in the project by a wide margin: account identity,
   starting balance, options level, entitlement, MLeg behaviour, and the real
   submission deadline are all still missing. The credentialed call recorded in
   D-024 returned 401, which confirms this gate is blocked on access rather
   than on remaining effort, so no amount of further unit work substitutes for
   it. The deliverable is `run_manifest.example.yaml` with every null field
   settled and the frozen copy hashed; the working list, the constraint that
   D-006 keeps the agent MCP market-data-only so account facts cannot be read
   through it, and the MLeg contract test are written up for the owner in
   `RESEARCH-LANE.md` under "G0 is yours now". Note that the kickoff and
   deadline already populated in that manifest are unverified placeholders, not
   settled values.
2. UNIT-028, the Alpaca market-data adapter. It is claimable, every dependency
   merged, and it is the single thing standing between this project and its
   first real number: every value in the research lane today comes from a
   fixture. It carries the `source_domain` question D-024 raised, since
   Alpaca's `source` is an originator name and not a domain, so the field is
   either derived or renamed, and that is a decision to record rather than one
   to make inside an adapter. It is Codex-preferred and its reviewer is
   `alpaca-docs-researcher` rather than `backtest-auditor`.
3. UNIT-026, the required baselines and ablations, unblocked by UNIT-025's
   merge on 2026-08-30. This is the comparison the whole research lane exists
   to make, price-only against news-only against combined against
   random, and until it runs the project has a forecast and no evidence that
   the forecast is worth anything. It is Claude-preferred.

Also available and unclaimed, both written on 2026-08-30 to close gaps the
decomposition had left open, and neither on the critical path: UNIT-005 commits
the three section 10 risk thresholds `config/risk.toml` does not carry, and
UNIT-019 owns the rung price sequence UNIT-018 consumes. Both are
execution-lane and Codex-preferred.

UNIT-029 is claimed by `mazwy/claude` and in progress.

Every intake exists. `specs/000-INTAKE.md` has no backlog row without a file,
so the next unit of work is a claim rather than an authoring step. What is
worth saying instead is the shape of what remains: nothing in this project has
ever fetched a real bar, labelled a real article, submitted a real order, or
compared the news family against anything. Twenty-one merged units are twenty-
one units of proven internal consistency, and that is a different claim from a
working system.
