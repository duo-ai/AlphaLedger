#!/usr/bin/env bash
# Dispatch one or more claimed units to Codex, each in its own worktree.
#
#   scripts/dispatch.sh UNIT-010 pablo/codex
#   scripts/dispatch.sh UNIT-010 UNIT-020 UNIT-021 pablo/codex
#   scripts/dispatch.sh UNIT-010 UNIT-020 pablo/codex --dry-run
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

UNITS=()
OWNER=""
DRY_RUN=false
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
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
develop. The unit is already claimed for you. Do not claim anything, do not
switch branches, and do not merge or push. Your job ends with a green quality
gate and a summary.

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
for slug in "${SLUGS[@]}"; do
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
for i in "${!UNITS[@]}"; do
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
    git worktree add "$worktree" -b "$branch" develop >/dev/null
    [ -f .claude/settings.local.json ] && cp .claude/settings.local.json "$worktree/.claude/" || true

    # Prepare the environment here, outside the agent's sandbox. A fresh
    # worktree has no .venv, so the agent's first `uv run` would need network
    # access the sandbox may deny, and the quality gate would fail before any
    # work began. ONBOARDING tells the agent to stop on that, correctly.
    echo "  $unit preparing environment"
    ( cd "$worktree" && uv sync --frozen >/dev/null 2>&1 ) \
        || die "uv sync failed in $worktree. Fix the environment before dispatching."

    nohup codex exec \
        -C "$worktree" \
        -s workspace-write \
        --add-dir "$GIT_COMMON" \
        --json \
        -o "$result" \
        - < "$LOGDIR/$slug.prompt.txt" > "$log" 2>&1 &

    echo "  $unit  pid $!  $log"
done

echo
echo "watch all:  tail -f $LOGDIR/*.jsonl"
echo "results:    cat $LOGDIR/*.result.md"
echo "status:     bash scripts/hook_python.sh scripts/coord.py list"
