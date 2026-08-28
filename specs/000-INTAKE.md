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
| UNIT-010 | execution | Assert the paper endpoint and make live impossible | G1 |
| UNIT-011 | execution | Map Alpaca order schemas behind a typed adapter | G1 |
| UNIT-012 | execution | Implement the order state machine and idempotent client ids | G1 |
| UNIT-013 | execution | Produce a risk approval token bound to the order payload | G2 |
| UNIT-014 | execution | Enumerate real chains and compute exact payoffs | G2 |
| UNIT-015 | execution | Reconcile broker truth and recover after restart | G2 |
| UNIT-016 | execution | Append-only decision and trade ledger | G2 |
| UNIT-017 | execution | Kill switch and emergency flatten | G2 |
| UNIT-020 | research | Record point-in-time observations with the timestamp contract | G3 |
| UNIT-021 | research | Generate the lagged frozen universe | G3 |
| UNIT-022 | research | Build residual price and volume features | G3 |

Rows with an intake file in `specs/units/` are specified: UNIT-001 (merged),
UNIT-010, UNIT-011, UNIT-012, UNIT-020, UNIT-021, and UNIT-022. The rest are
backlog rows; promoting one means writing its intake from `specs/TEMPLATE.md`.

Specified is not the same as claimable. The execution lane is a chain:
UNIT-011 waits on UNIT-010 and UNIT-012 waits on UNIT-011, because each
consumes the previous one's public surface. `coord.py` enforces that.

`UNIT-022` additionally depends on `UNIT-021`, since features are built over a
frozen universe.
| UNIT-023 | research | Label news against the fixed schema | G3 |
| UNIT-024 | research | Fit and calibrate the forecast on chronological folds | G3 |
| UNIT-025 | research | Run the required baselines and the trial registry | G3 |

## Definition of ready and done

Ready to claim: contract, acceptance criteria, and test list written; the
dependency is merged; the reviewer is named.

Done: the acceptance criteria hold, the verification commands pass, the named
reviewer has reported, paper and live isolation still holds, and the failure
and restart behaviour is explicit. Inspection is not verification.
