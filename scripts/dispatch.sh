#!/usr/bin/env bash
# Dispatch one or more claimed units to Codex, each in its own worktree.
#
#   scripts/dispatch.sh UNIT-010 pablo/codex
#   scripts/dispatch.sh UNIT-010 UNIT-020 UNIT-021 pablo/codex
#   scripts/dispatch.sh UNIT-010 UNIT-020 pablo/codex --dry-run
#   scripts/dispatch.sh UNIT-010 pablo/codex --continue   (after a review)
#
# For each unit: claims it, cuts a worktree off develop, builds the prompt from
# the unit's own intake, and launches `codex exec` in the background. Claims are
# pushed together once every unit has been taken.
#
# Units dispatched together must declare disjoint path globs. That is checked
# before anything is claimed, because two agents writing one file is discovered
# at merge time otherwise. See D-010.
#
# Codex is the standing default runtime for implementation work. See the
# parallel work protocol in AGENTS.md.
set -euo pipefail

die() { echo "dispatch: $*" >&2; exit 1; }

# A second pass only happens through the registry, so the review round count and
# the escalation after two rounds that did not clear sit on the path rather than
# beside it. Without this the dispatcher is a way around that gate, and the gate
# is a convention again.
require_claimed() {
    local unit="$1" state
    state=$(bash scripts/hook_python.sh - "$unit" <<'STATE'
import pathlib
import sys

unit = sys.argv[1]
for path in sorted(pathlib.Path("specs/units").glob("*.md")):
    text = path.read_text()
    if f"id: {unit}\n" not in text:
        continue
    for line in text.split("---", 2)[1].splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "state":
            print(value.strip())
    break
STATE
)
    [ "$state" = "claimed" ] || die "$unit is '$state', not 'claimed'. A second pass goes through the registry:
  python3 scripts/coord.py state $unit claimed
which is where the review round count lives, and the refusal after two rounds that did not clear."
}

UNITS=()
OWNER=""
DRY_RUN=false
CONTINUE=false
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --continue) CONTINUE=true ;;
        */codex|*/claude) OWNER="$arg" ;;
        UNIT-*) UNITS+=("$arg") ;;
        *) die "unrecognised argument '$arg'. Usage: scripts/dispatch.sh <UNIT-ID>... <handle>/codex [--dry-run]" ;;
    esac
done

[ ${#UNITS[@]} -gt 0 ] || die "name at least one unit"
[ -n "$OWNER" ] || die "name an owner, for example pablo/codex"
case "$OWNER" in
    */claude) die "$OWNER is a Claude owner. Dispatch a Claude session with the Agent tool and worktree isolation, not this script." ;;
esac

command -v codex >/dev/null || die "codex CLI not on PATH"
ROOT=$(git rev-parse --show-toplevel) || die "not a git repository"
cd "$ROOT"

# resolve each unit to its intake file
SLUGS=()
for unit in "${UNITS[@]}"; do
    slug=$(bash scripts/hook_python.sh - "$unit" <<'PY'
import sys, pathlib
unit = sys.argv[1]
for p in sorted(pathlib.Path("specs/units").glob("*.md")):
    if f"id: {unit}\n" in p.read_text():
        print(p.stem)
        break
else:
    sys.exit(1)
PY
    ) || die "no intake file declares $unit"
    SLUGS+=("$slug")
done

# refuse a batch that would put two agents in the same files
if [ ${#UNITS[@]} -gt 1 ]; then
    bash scripts/hook_python.sh - "${UNITS[@]}" <<'PY' || exit 1
import sys
sys.path.insert(0, "scripts")
import coord

wanted = sys.argv[1:]
units = coord.load_all(coord.units_dir())
bad = []
for i, a in enumerate(wanted):
    for b in wanted[i + 1 :]:
        pa = str(units[a][0].get("paths", ""))
        pb = str(units[b][0].get("paths", ""))
        if coord.paths_overlap(pa, pb):
            bad.append(f"{a} and {b} both reach {pa} / {pb}")
if bad:
    print("dispatch: these units cannot run in parallel:", file=sys.stderr)
    for line in bad:
        print(f"  {line}", file=sys.stderr)
    print("  Narrow the globs or dispatch them one after another.", file=sys.stderr)
    sys.exit(1)
PY
fi

LOGDIR="$ROOT/.dispatch"
mkdir -p "$LOGDIR"

build_prompt() {
    local unit="$1" slug="$2" branch="$3" out="$4"
    cat > "$out" <<EOF
You are implementing $unit in the AlphaLedger repository, as owner $OWNER.

You are already inside an isolated git worktree on branch $branch, cut from
develop. The unit is already claimed for you.

Commit your work on this branch as you go, with conventional commit subjects.
Uncommitted work is lost work: the branch is how your output reaches anyone.
Do not claim anything, do not switch branches, do not merge, and do not push.
Do not change the unit's state in the registry. Your job ends when the gate is
green, your work is committed, and you have written a summary.

The environment is already prepared. `uv sync --frozen` has been run here, so
the virtualenv exists. If a uv command reports the cache is read-only, set
UV_CACHE_DIR to a path inside this worktree rather than working around it some
other way.

Other agents are working other units in parallel worktrees right now. Stay
strictly inside the path globs named in your unit's frontmatter. Touching
another unit's files is the one thing that breaks parallel work.

Read these first, in order:
  1. ONBOARDING.md
  2. AGENTS.md, especially the safety boundary and the definition of done
  3. specs/units/$slug.md, which is your specification
  4. the file in .claude/rules/ whose path globs match the code you will touch

The unit intake contains a "## Test list" written before the unit became
claimable. That list is the specification. Work strictly test-first:

  1. Write the tests from that list. It covers four paths and so must you:
     success, failure, restart, and no-trade.
  2. Run them and confirm they fail for the reason you expect.
  3. Implement the minimum that makes them pass.
  4. Refactor with the tests green.

Then run the gate and do not stop until it is clean:

  uv sync --frozen
  uv run ruff check . && uv run ruff format --check .
  uv run mypy src
  uv run pytest

Hard constraints, enforced by a PreToolUse hook so violating one fails loudly:
  - Write only inside your unit's declared path globs.
  - Paper trading only. Never introduce the live Alpaca host, a --live path, or
    a way to disable paper mode.
  - Never read, print, log, or commit credentials, .env files, or keys.
  - Conventional commit subjects, for example "feat(data): record bars".
  - No em dashes, no AI attribution trailers.
  - Never weaken a test, loosen a gate, or delete a case to reach green. If a
    test in the list is wrong, say so and fix the intake first.

Stop and report instead of guessing if: two sources of truth disagree, the unit
needs a file outside its lane, or the only way to pass a gate is to lower it.
Stopping is a correct outcome and is preferred over a guess. Say exactly what
blocked you and what you did and did not change.

If the gate or the harness is already failing when you arrive, before you have
changed anything, that is an environment or tooling problem rather than a
verdict on your unit. Report it with the exact failing commands and stop.

When done, summarise: what you implemented, the exact commands you ran and
their output, which acceptance criteria you believe are met, and what remains
unverified. Never call a path verified when it was only inspected.
EOF
}

echo "owner     $OWNER"
echo "units     ${UNITS[*]}"
echo

if [ "$DRY_RUN" = true ]; then
    for i in "${!UNITS[@]}"; do
        slug="${SLUGS[$i]}"
        [ "$CONTINUE" = true ] && require_claimed "${UNITS[$i]}"
        build_prompt "${UNITS[$i]}" "$slug" "feature/$slug" "$LOGDIR/$slug.prompt.txt"
        echo "  ${UNITS[$i]}  ->  feature/$slug  ($LOGDIR/$slug.prompt.txt)"
    done
    echo
    echo "dry run: nothing claimed, no worktrees, no dispatch."
    exit 0
fi

[ "$(git branch --show-current)" = "develop" ] \
    || die "claim from develop, not $(git branch --show-current). Git refuses to check one branch out twice, so the primary clone stays on develop as the claiming station."
git diff --quiet && git diff --cached --quiet \
    || die "working tree is dirty. Commit or stash before dispatching."

# A leftover branch or worktree means a previous run died midway. Say so before
# claiming anything, so a retry cannot deepen the mess.
for i in "${!SLUGS[@]}"; do
    slug="${SLUGS[$i]}"
    unit="${UNITS[$i]}"
    if [ "$CONTINUE" = true ]; then
        require_claimed "$unit"
        wt="$ROOT/../AlphaLedger-wt/$slug"
        [ -d "$wt" ] \
            || die "--continue needs an existing worktree at ../AlphaLedger-wt/$slug. Dispatch without it to start fresh."
        # A second pass is told to read the intake again, because the review
        # findings are recorded there. Those land on develop, and the agent runs
        # with -C on this worktree, so without this the brief points at an
        # amended specification the checkout does not have and the agent
        # re-reads the one it already implemented. Git Flow rebases a feature
        # branch onto develop and never merges develop into one; see
        # .claude/rules/50-git.md.
        git -C "$wt" diff --quiet && git -C "$wt" diff --cached --quiet \
            || die "worktree $wt has uncommitted work. Commit it there before continuing, or the rebase loses it."
        # A conflict stops the whole batch. Dispatching an agent into a
        # half-rebased worktree is worse than not dispatching it at all.
        if ! git -C "$wt" rebase develop >/dev/null 2>&1; then
            git -C "$wt" rebase --abort >/dev/null 2>&1 || true
            die "rebasing feature/$slug onto develop conflicts. Resolve it in $wt, then dispatch again."
        fi
        continue
    fi
    if git show-ref --verify --quiet "refs/heads/feature/$slug"; then
        die "branch feature/$slug already exists, so a previous run did not finish. Clean up with:
  git worktree remove --force ../AlphaLedger-wt/$slug
  git branch -D feature/$slug"
    fi
    if [ -e "$ROOT/../AlphaLedger-wt/$slug" ]; then
        die "worktree ../AlphaLedger-wt/$slug already exists. Remove it with: git worktree remove --force ../AlphaLedger-wt/$slug"
    fi
done

# take every unit first, so a refusal midway does not leave a half-dispatched batch
claimed_any=false
[ "$CONTINUE" = true ] && echo "  continuing existing work, not re-claiming"
for i in "${!UNITS[@]}"; do
    [ "$CONTINUE" = true ] && continue
    unit="${UNITS[$i]}"
    held_by=$(bash scripts/hook_python.sh scripts/coord.py show "$unit" \
        | sed -n 's/^owner: //p' | head -1)
    if [ "$held_by" = "$OWNER" ]; then
        echo "  $unit already held by $OWNER, resuming without re-claiming"
    else
        bash scripts/hook_python.sh scripts/coord.py claim "$unit" --owner "$OWNER" >/dev/null \
            || die "claim refused for $unit. Nothing after it was claimed. Run 'scripts/coord.py list'."
        git add "specs/units/${SLUGS[$i]}.md"
        git commit -q -m "chore(registry): claim $unit for $OWNER"
        claimed_any=true
    fi
done
if [ "$claimed_any" = true ]; then
    git push -q origin develop \
        || die "claim push rejected. Run: git pull --rebase origin develop, then re-check the registry."
fi

GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" && pwd)

for i in "${!UNITS[@]}"; do
    unit="${UNITS[$i]}"
    slug="${SLUGS[$i]}"
    branch="feature/$slug"
    worktree="$ROOT/../AlphaLedger-wt/$slug"
    log="$LOGDIR/$slug.jsonl"
    result="$LOGDIR/$slug.result.md"

    build_prompt "$unit" "$slug" "$branch" "$LOGDIR/$slug.prompt.txt"
    if [ "$CONTINUE" = true ]; then
        # A branch with no non-merge commits was never implemented, so this is a
        # retry after something blocked the first run, not a post-review pass.
        prior=$(git -C "$worktree" log --no-merges --oneline develop..HEAD 2>/dev/null | wc -l)
        if [ "$prior" -eq 0 ]; then
            cat >> "$LOGDIR/$slug.prompt.txt" <<'RETRY'

THIS IS A RETRY, NOT A SECOND PASS. An earlier run of this unit stopped before
writing anything, because the harness was failing for a reason that had nothing
to do with the unit. That cause is fixed. The branch is deliberately empty and
the intake carries no review findings, so do not go looking for either.

Treat this as a first implementation, exactly as the instructions above
describe. You were right to stop last time; nothing about that stop should
change how you approach the work now.
RETRY
        else
            cat >> "$LOGDIR/$slug.prompt.txt" <<'FOLLOWUP'

THIS IS A SECOND PASS. Your earlier implementation of this unit is already on
this branch and has been through an independent review. The review returned
findings, and the unit intake has been updated: read it again in full,
including the acceptance criteria you have not seen and the section recording
the review findings.

Reconcile the existing code with the updated specification. Where a test is
named as theatre, replace it rather than adding another beside it. Where an
acceptance criterion was corrected because the original was unachievable,
implement the corrected one and do not try to satisfy the old wording.

Not every finding is yours to fix. If one asks for work outside this unit's
declared path globs, or for behaviour no acceptance criterion of this unit
names, do not implement it. Say so plainly in your summary and leave it. A unit
that grows to absorb the next three units never finishes, and the reviewer is
not the source of truth about scope; the intake is.

Keep the existing commits. Add new ones on top.
FOLLOWUP
        fi
    fi
    if [ "$CONTINUE" = false ]; then
        git worktree add "$worktree" -b "$branch" develop >/dev/null
    fi
    [ -f .claude/settings.local.json ] && cp .claude/settings.local.json "$worktree/.claude/" || true

    # Prepare the environment here, outside the agent's sandbox. A fresh
    # worktree has no .venv, so the agent's first `uv run` would need network
    # access the sandbox may deny, and the quality gate would fail before any
    # work began. ONBOARDING tells the agent to stop on that, correctly.
    echo "  $unit preparing environment"
    ( cd "$worktree" && uv sync --frozen >/dev/null 2>&1 ) \
        || die "uv sync failed in $worktree. Fix the environment before dispatching."

    # the default uv cache sits outside the sandbox and is not writable there
    # Reasoning effort is pinned here rather than inherited from whoever's
    # personal config happens to be loaded, so a dispatch is reproducible.
    # A second pass would otherwise truncate the stream of the pass it follows,
    # which is the evidence of what the agent did and what the reviewer read.
    if [ -s "$log" ]; then
        n=1
        while [ -e "$log.$n" ]; do n=$((n + 1)); done
        mv "$log" "$log.$n"
    fi
    # The result summary is what a later session actually reads to learn what a
    # pass concluded, so it needs the same rotation the stream gets.
    if [ -s "$result" ]; then
        n=1
        while [ -e "$result.$n" ]; do n=$((n + 1)); done
        mv "$result" "$result.$n"
    fi

    # --approve-for-me already runs under the workspace-write sandbox and, as of
    # codex-cli 0.150.1, refuses to be given -s as well. Do not add it back.
    nohup env UV_CACHE_DIR="$worktree/.uv-cache" codex exec \
        -c model_reasoning_effort=xhigh \
        --approve-for-me \
        -C "$worktree" \
        --add-dir "$GIT_COMMON" \
        --json \
        -o "$result" \
        - < "$LOGDIR/$slug.prompt.txt" > "$log" 2>&1 &
    pid=$!

    # A launch that dies on an argument error used to be indistinguishable from
    # one that started: the pid was printed, the log held a usage message, and
    # the failure surfaced only when someone wondered why nothing had happened.
    # Wait for the first event, or for the process to be gone, whichever is
    # first, and refuse to report a dispatch that never began.
    for _ in $(seq 20); do
        grep -q "^{" "$log" 2>/dev/null && break
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    if ! grep -q "^{" "$log" 2>/dev/null; then
        die "$unit emitted no events, so it never started. codex said:
$(head -5 "$log")
Units already dispatched in this batch are still running."
    fi

    echo "  $unit  pid $pid  $log"
done

echo
echo "watch all:  tail -f $LOGDIR/*.jsonl"
echo "results:    cat $LOGDIR/*.result.md"
echo "status:     bash scripts/hook_python.sh scripts/coord.py list"
