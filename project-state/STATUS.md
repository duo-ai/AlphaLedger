# AlphaLedger project status

Last updated: 2026-08-29

## Current phase

Released as v0.1.0, and `develop` has moved well past it. This checkpoint was
verified against `develop` at `e8932b9` on 2026-08-29; it moved twice while
this file was being written, so treat any later commit as ahead of what
follows. Eighteen units are merged, in the sense that their code is on
`develop`: UNIT-001 through UNIT-004, UNIT-010 through UNIT-018, and UNIT-020
through UNIT-024.

UNIT-016 (the append-only decision and trade ledger) and UNIT-018 (the bounded
entry price ladder) reached `develop` by `--no-ff` merge, verified directly:
`git ls-tree -r develop -- src` shows 29 source files, and a full quality gate
run against that exact ref passes, `ruff check`, `ruff format --check`,
`mypy src` across 29 files, and 590 tests. Both carry a recorded
`execution-safety-reviewer` verdict of `clear` and both read `state: merged`.
UNIT-016 needed two rounds; UNIT-018 cleared on its first.

UNIT-013, the risk approval token, took three rounds: `block`, `conditional`,
`clear`. Round one found that a mutable payload could be evaluated against one
state and hashed against another, so an approval could be granted for a
payload that no longer existed, and that a foreign payload could be sized
using a different plan's lower loss cap. Both are closed by taking one
immutable snapshot of the supplied payload before any gate or hash reads it.
Round two found the snapshot still let one gate's failure go unrecorded
alongside another's, fixed, and found that
`test_approval_id_changes_under_every_single_bound_field_mutation` compared the
approval id function against a spy on itself, which cannot fail on a wrong
quantity, payload hash, or mode. Round three was a deliberate, D-022-justified
exception to fix that one test against independently computed inputs, with no
production code reopened.

UNIT-016, the ledger, went `block` then `clear` across two rounds. Round one
found `record_order_state` coalesced a new observation against every prior
entry for an id rather than the most recent one, so the legal recurrence
`partial`, `cancel_pending`, `partial` silently dropped its third entry, and a
restart would answer from a state the order had already left. AC-7 conflated
an idempotent retry with a genuine recurrence; it was split, with AC-7a
describing the recurrence that was being lost. Round two, recorded on
`develop`'s tip as `review_log: [block, clear]`, has no handoff narrative
beyond that verdict.

UNIT-014, UNIT-015, UNIT-017, and UNIT-018 each cleared on their first review
round, with no handoff notes recorded beyond the frontmatter verdict.

D-023 was recorded today: the client order id derives from `(plan_id,
quantity, limit_price)`, all fixed before a risk approval exists, not from
`approval_id`. This resolves a real conflict: `options-alpha-agent-design.md`
section 11 and `orchestrator-system-prompt.md` both describe the id as
something assigned after approval, while UNIT-011's merged AC-10 requires the
id inside the hashed payload precisely so an approval cannot authorise a
changed quantity, price, or id. UNIT-011 won; reopening it would have reopened
a criterion written to close that exact hole.

The execution lane now has the paper endpoint assertion, the order schema
adapter, the order state machine, chain enumeration with exact payoffs, broker
reconciliation, the risk approval token, the kill switch, the ledger, and the
entry price ladder all on `develop`. No transport submits anything to Alpaca.

The research lane, owned by `mazwy/claude`, merged UNIT-023 (already counted
above) and specified four more units today: UNIT-025, the pooled forecast;
UNIT-026, the required baselines; UNIT-027, forward residual labels, which is
`claimed` and in progress; and UNIT-028, the Alpaca market-data adapter,
`available` with every dependency already merged. UNIT-025 and UNIT-026 both
depend on UNIT-027, so neither is actually claimable until it merges, even
though `coord.py list` shows them `available`. UNIT-029, the LLM labeler
adapter, was added to the decomposition table in `specs/000-INTAKE.md` but has
no intake file yet, so it is not in the registry at all.

D-024 was also recorded today: four Alpaca API defaults that would corrupt
research silently if the adapter relied on them, unadjusted bars, an `asof`
that defaults to today and can relabel history under a renamed ticker, a bar
price that has to arrive as a string rather than a float, and pagination that
can return only one symbol of a multi-symbol request. These come from the
published API reference, not from an observed payload: the one credentialed
call made against it returned 401, so G0 stays unverified for want of access,
not of research effort.

Every number in the research lane comes from a fixture, and the execution
lane's own tests run entirely against in-memory doubles. Nothing in this
project has ever touched a live Alpaca endpoint, credentialed or otherwise,
beyond that one 401.

The dates in `hackathon-build-plan.md` are stale, confirmed by the user on
2026-08-28. Treat the G0 to G6 sequence as binding and the calendar attached to
it as not binding. Do not schedule work from that document until a real
deadline is recorded here.

## Active gate

G0. Competition rules, account, permissions, data entitlements, integration
versions, and submission requirements remain unverified for the actual event
environment.

## Verified artifacts

- `specs/`: the SDD intake, the unit template, and twenty-two unit intakes.
  Eighteen units are merged, code and registry both. UNIT-027 is `claimed`
  by `mazwy/claude`, and UNIT-025, UNIT-026, and UNIT-028 are `available`,
  though UNIT-025 and UNIT-026 cannot actually be claimed until UNIT-027
  merges. UNIT-029 is named in `specs/000-INTAKE.md`'s decomposition table with
  no intake file yet; that file's own prose still describes UNIT-016 through
  UNIT-018 as backlog rows without intakes, which is now stale and was not
  corrected here, since `specs/000-INTAKE.md` is outside this file's scope.
  The price ladder design section 11 step 4 requires is now owned by UNIT-018,
  entry side only. What is not owned by any row is the function that turns a
  structure's bid, ask, and quote metadata into the ordered sequence of
  candidate rung prices the ladder consumes; UNIT-018's own intake names this
  gap and is claimable and testable without it, exactly as UNIT-013 and
  UNIT-017 were each written and merged before their real callers existed.
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
- No unit intake names the function that turns a structure's bid, ask, and
  quote metadata into the ordered sequence of candidate rung prices UNIT-018's
  ladder consumes. UNIT-014's `ChainContract` carries `bid` and `ask`, but
  nothing exposes a midpoint-to-natural price sequence for a plan, and no
  backlog row owns it; UNIT-018's own intake records this as a real gap that
  does not block it, since it is written to consume an already-built sequence
  from fixtures.
- Several thresholds design section 10 requires are still not committed
  anywhere. `config/risk.toml` has no `max_snapshot_age`, so UNIT-013's
  `approve` takes it as a required explicit parameter rather than a frozen
  default. The same file has no `daily_loss_stop_fraction` or
  `peak_to_valley_fraction`, so UNIT-017's `evaluate_kill_switch` takes both as
  required explicit parameters too. Per D-017, an uncommitted threshold is
  meant to be the exception, not the steady state, for exactly the values that
  most need to be frozen before an autonomous session.
- No model code exists on `develop`. UNIT-025, the pooled forecast, is
  specified but not claimable until UNIT-027 merges. News features exist per
  UNIT-023, but nothing labels an article: the LLM client, its caching, and its
  output validation are deliberately out of that unit and belong to UNIT-029,
  which is named in the decomposition but has no intake file yet, so the news
  family still cannot run on real data at all. The order lifecycle, risk
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
2. Claim UNIT-030, which widens `Article` to carry the summary. It is small,
   it is claimable now, and both UNIT-028 and UNIT-029 depend on it, so it is
   the single thing standing between the research lane and the news family.
   D-025 records why the summary was chosen over a headline-only family, and
   records that `exclude_contentless` must never be used to build a research
   sample because it selects on a property correlated with the outcome.
3. Then UNIT-028, the Alpaca market-data adapter, which populates that field
   and carries the `source_domain` question D-024 raised: Alpaca's `source` is
   an originator name, not a domain, so the field is either derived or renamed,
   and that is a decision to record rather than to make inside an adapter.
   UNIT-027 is claimed by `mazwy/claude` and in progress; UNIT-025 and UNIT-026
   depend on it and stay unclaimable until it merges. UNIT-029 is specified and
   waits on UNIT-030.

Every intake now exists. `specs/000-INTAKE.md` has no backlog row without a
file, so the next unit of work is a claim rather than an authoring step.

## Read first next session

1. `AGENTS.md`, including the parallel work protocol
2. `specs/000-INTAKE.md`
3. `project-state/DECISIONS.md`, D-009 through D-025
4. `RESEARCH-LANE.md`, then the handoff notes in the five merged research
   unit intakes, which carry the findings and the open questions
5. `options-alpha-agent-design.md` sections 0 to 5 and 14
