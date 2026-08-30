# AlphaLedger SDD intake

This is the front door for spec-driven development on AlphaLedger. It says how
work is specified, split, claimed, and verified by two people running three
coding-agent runtimes against one repository.

It does not restate the architecture or the safety boundary. Those live in
`options-alpha-agent-design.md` and `AGENTS.md`, and this document defers to
them everywhere.

## Why this exists

The repository already had most of a spec-driven process without naming it:

| SDD layer | Where it already lives |
|---|---|
| Constitution, the invariants no unit may violate | `AGENTS.md`, `.claude/rules/*.md` |
| Milestones and acceptance gates | G0 to G6 in `hackathon-build-plan.md` |
| Independent review | six read-only specialists per runtime |
| Restart checkpoint | `project-state/STATUS.md` |

What was missing was per-unit metadata: who owns a piece of work, on which
branch, in what state, and which reviewer gates it. That gap is why parallel
work was previously unsafe, and it is the only thing this intake adds.

## Two entry points

Work smaller than a unit is a bugfix branch. Work that is one unit starts at
the intake below. Work larger than one unit starts with a spec, so the
decomposition is decided once and several units become dispatchable together
rather than one at a time:

```
spec-plot -> spec-analyze -> spec-clarify -> spec-plan -> spec-analyze again
          -> spec-tasks -> dispatch.sh -> review.sh -> coord.py review -> merge
```

Each step is a skill. `spec-tasks` writes unit intakes into `specs/units/`, at
which point everything below applies unchanged: the registry claims them, the
dispatcher sends them, the reviewer gates them. See `specs/features/README.md`.

The pipeline exists to plot ahead. Its value is not ceremony per unit, it is
that a decomposition decided in advance can be dispatched in parallel, and
`coord.py` will refuse the batch if the boundaries were not real.

## How a unit moves

```text
backlog row -> intake written -> claimable -> claimed -> in_review -> merged
```

A backlog row below becomes a real unit when someone writes its intake file
from `specs/TEMPLATE.md` into `specs/units/`. An intake is claimable only when
its `## Contract`, `## Acceptance criteria`, and `## Test list` sections are
filled in. Writing the test list before the implementation is the point: it is
where TDD enters, and `coord.py` treats an unwritten one as a spec that is not
finished rather than work that is ready.

## Lanes

Two lanes with disjoint path globs, so two people's agents never write the same
file. The globs already exist as the path scopes of the rules files, which is
how we know the split is real and not invented for this document.

| Lane | Owns | Paths | Reviewer |
|---|---|---|---|
| shared | frozen domain contracts | `src/alphaledger/domain/**` | code-reviewer |
| execution | endpoint assertion, broker adapter, order state machine, risk, structure, reconciliation, ledger, kill switch | `src/alphaledger/{broker,execution,risk,structure,ledger}/**` | execution-safety-reviewer |
| research | data recorder, universe, evidence, news labels, forecast, baselines | `src/alphaledger/{data,evidence,forecast}/**`, `research/**` | backtest-auditor |

The execution lane is the never-cut spine in the descope ladder, so it carries
the stricter reviewer.

## The sequencing constraint

`UNIT-001` freezes the domain contracts from design section 14. Every other
unit declares `depends_on: [UNIT-001]`, and `coord.py claim` refuses a unit
whose dependencies are not `merged`. This is mechanical, not advisory. Without
it two lanes redefine the same dataclasses and every merge conflicts.

## Roster

Three writers across two people:

| Owner | Runtime | Lane | Typical work |
|---|---|---|---|
| `pablo/codex` | Codex | execution | implementation-heavy units |
| `pablo/claude` | Claude Code | execution and shared | intake authoring, review, integration |
| `mazwy/claude` | Claude Code | research | research and evidence units |

Codex has the larger budget, so implementation-heavy units carry
`preferred_runtime: codex`. Claude sessions are better spent writing intakes,
running the specialist reviews, and integrating. The field is a hint a human
reads, not routing logic.

## Claiming work

```bash
git switch develop && git pull --rebase origin develop
python3 scripts/coord.py list --state available
python3 scripts/coord.py claim UNIT-010 --owner pablo/codex
```

`claim` refuses a unit that is already owned or whose dependencies are
unmerged, then prints the exact commit and worktree commands. Push the claim to
`develop` before starting work: it is a single-file change, so two people
claiming different units never touch the same file and never conflict. If the
push is rejected, rebase, re-read the row, and pick another unit.

Each unit is one worktree, cut from `develop`, on a `feature/` branch. See
`.claude/rules/50-git.md` for the branching model.

One thing the worktree does not carry: `.claude/settings.local.json` is
untracked, so a fresh worktree has no MCP server enabled. Copy it in. The
tracked parts of `.claude/` and `.codex/`, including both guard hooks, are
present and verified to fire inside a worktree.

## Backlog

`depends_on` is `[UNIT-001]` for everything except UNIT-001 itself.

| Id | Lane | Title | Gate |
|---|---|---|---|
| UNIT-001 | shared | Freeze the domain contracts | G1 |
| UNIT-002 | shared | Amend the news label contract to hold what the labeler emits | G1 |
| UNIT-003 | shared | Enumerate the news category on the label | G1 |
| UNIT-004 | shared | Load the frozen configuration and hash it | G1 |
| UNIT-005 | shared | Commit the risk thresholds design section 10 requires | G2 |
| UNIT-010 | execution | Assert the paper endpoint and make live impossible | G1 |
| UNIT-011 | execution | Map Alpaca order schemas behind a typed adapter | G1 |
| UNIT-012 | execution | Implement the order state machine and idempotent client ids | G1 |
| UNIT-013 | execution | Produce a risk approval token bound to the order payload | G2 |
| UNIT-014 | execution | Enumerate real chains and compute exact payoffs | G2 |
| UNIT-015 | execution | Reconcile broker truth and recover after restart | G2 |
| UNIT-016 | execution | Append-only decision and trade ledger | G2 |
| UNIT-017 | execution | Kill switch and emergency flatten | G2 |
| UNIT-018 | execution | Step the bounded entry price ladder | G2 |
| UNIT-019 | execution | Derive the bounded entry rung price sequence from live quotes | G2 |
| UNIT-020 | research | Record point-in-time observations with the timestamp contract | G3 |
| UNIT-021 | research | Generate the lagged frozen universe | G3 |
| UNIT-022 | research | Build residual price and volume features | G3 |
| UNIT-023 | research | Encode point-in-time news into features | G3 |
| UNIT-024 | research | Split chronologically and register every trial | G3 |
| UNIT-025 | research | Fit the pooled forecast and emit the Forecast record | G3 |
| UNIT-026 | research | Run the required baselines and ablations | G3 |
| UNIT-027 | research | Construct forward residual return labels | G3 |
| UNIT-028 | research | Fetch Alpaca bars and news into point-in-time records | G3 |
| UNIT-029 | research | Label news through a cached LLM adapter | G3 |
| UNIT-030 | research | Carry the article summary on the news record | G3 |

Every row above has an intake file in `specs/units/`. There is no backlog row
without one, so the next piece of work is a claim rather than an authoring
step. Promoting a future row means writing its intake from
`specs/TEMPLATE.md`. This paragraph named UNIT-016, UNIT-017, UNIT-018, and
UNIT-029 as intake-less backlog rows until 2026-08-30, by which point all four
had intakes and the first three had merged, so it had been describing a state
the repository left days earlier. Run
`uv run python scripts/coord.py list` for current state rather than reading it
here; this table records the decomposition, not progress. Use `uv run python`
rather than a bare `python3`: `coord.py` needs `datetime.UTC`, which the system
interpreter on at least one development machine is too old to provide.

The ladder row, UNIT-018, was added on 2026-08-29 to close a gap the
decomposition had left open. Design section 11 step 4 requires a bounded limit
price ladder on entry, and no row owned it: UNIT-011 and UNIT-012 each pushed
it to UNIT-013, which this table assigns to the risk approval token, so the
reference was wrong in both and is corrected in place.

It earns its own row rather than joining UNIT-013 because of D-023. The client
order id is derived from `(plan_id, quantity, limit_price)`, so a ladder step
at a new price produces a new id, a new payload, and therefore a new approval.
The ladder is a bounded loop that calls the approval unit repeatedly, which
puts it above UNIT-013 rather than inside it. It depends on UNIT-012 and
UNIT-013, and it must not be implemented inside any unit that disclaims it.

UNIT-005 and UNIT-019 were added on 2026-08-30, and both close gaps this
table had left open rather than introducing new work. The mitigation D-026
prescribes was applied first: the rows were read against each other and against
the merged code, looking for a unit two rows claim, a capability no row claims,
and a record a consumer needs that no producer fills.

UNIT-019 is the second kind. UNIT-018 consumes an ordered sequence of candidate
limit prices and its own intake records that no row produces one; UNIT-014
carries the quotes in `ChainContract` and disclaims the pricing. So the ladder
and the chain enumeration both merged with the function between them owned by
nobody, which is exactly the shape UNIT-018 itself was created to fix and is
recorded here rather than left for a third discovery.

UNIT-005 is the third kind. Design section 10 requires a daily loss stop, a
peak-to-valley kill switch bound, and a staleness bound. `config/risk.toml`
commits none of the three, verified against the file, so UNIT-013 and UNIT-017
each take them as required explicit parameters and each recorded that as a gap.
D-017 makes a threshold that explains a decision something that has to be
committed and hashed, so leaving them as arguments means a halted session
cannot prove which threshold halted it.

Neither row overlaps anything claimed. UNIT-019 declares
`src/alphaledger/structure/pricing.py`, a file that does not exist, and
UNIT-005 declares `config/risk.toml` and the config package, which no other
unmerged unit touches.

UNIT-025 and UNIT-026 were corrected on 2026-08-29, and the correction runs
the same way the UNIT-018 one did. Three stale rows sat below this prose,
detached from the table, holding a decomposition that had already moved: they
duplicated UNIT-023 and UNIT-024 with superseded titles, and they assigned the
baselines to UNIT-025. Two merged, reviewed intakes disagree with that.
`024-splits-and-trial-registry.md` disclaims the pooled forecast model and the
`Forecast` record it emits to UNIT-025, and both it and
`023-news-features.md` disclaim the baselines to UNIT-026.

The merged units win, for the reason D-023 gives: an acceptance criterion that
survived review describes work someone actually reasoned about, and a table row
nobody has implemented against does not. Rewriting the two merged intakes to
match the table would have edited files belonging to closed units in order to
preserve a row that was wrong. The forecast model was consequently owned by no
row at all, which is exactly the gap UNIT-018 was created to close, so it gets
a row rather than an assumption.

UNIT-027 was added on 2026-08-29 for the third time this decomposition has
had to close a hole of the same shape. Writing the UNIT-025 intake surfaced
that nothing owned forward residual label construction. UNIT-022 emits features
and no outcome, UNIT-023 the same, and UNIT-024 consumes a label's identity,
its prediction instant, and its outcome instant, but never its value. A model
cannot be fitted without labelled outcomes, so the work was required by a unit
and owned by none.

It earns its own row rather than joining UNIT-025 because a label is
point-in-time evidence, not modelling. Folding it into the fit would put the
definition of the correct answer inside the thing being judged, and UNIT-026
compares models against exactly these labels, so a label built by one of the
things it discriminates between could not be trusted by the other. It is placed
before UNIT-025 in dependency order and after it in numbering, the same way
UNIT-018 sits above UNIT-013.

UNIT-028 and UNIT-029 were added on 2026-08-29, and they close the same class
of hole as UNIT-018 and UNIT-027 did. Nothing in the decomposition fetched
anything. UNIT-020 records an observation once it exists and UNIT-011 maps
order schemas in the execution lane, so the path from Alpaca into a
point-in-time record was required by every research unit and owned by none.
That is why `project-state/STATUS.md` can say that no real feed is connected
anywhere while eight research units are merged.

UNIT-029 is the labeler adapter UNIT-023 disclaims by name: the LLM client, its
caching by article and prompt hash, and the validation of Prompt B's
consistency rules. UNIT-023 shipped a `NewsLabeler` protocol precisely so this
unit could be written later without touching it.

The two are separate because one needs Alpaca credentials and the other needs
model credentials, and because the failure modes share nothing. D-024 records
what the Alpaca schemas actually say and is the reason UNIT-028 is specified
the way it is.

Specified is not the same as claimable. The execution lane is a chain:
UNIT-011 waits on UNIT-010 and UNIT-012 waits on UNIT-011, because each
consumes the previous one's public surface. `coord.py` enforces that.

`UNIT-022` additionally depends on `UNIT-021`, since features are built over a
frozen universe.
## Definition of ready and done

Ready to claim: contract, acceptance criteria, and test list written; the
dependency is merged; the reviewer is named.

Done: the acceptance criteria hold, the verification commands pass, the named
reviewer has reported, paper and live isolation still holds, and the failure
and restart behaviour is explicit. Inspection is not verification.
