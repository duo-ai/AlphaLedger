#!/usr/bin/env bash
# Dispatch one claimed unit to Codex in its own worktree.
#
#   scripts/dispatch.sh UNIT-010 pablo/codex
#   scripts/dispatch.sh UNIT-010 pablo/codex --dry-run
#
# Claims the unit, pushes the claim, cuts a worktree off develop, builds the
# prompt from the unit's own intake, and launches `codex exec` in the
# background. Prints how to watch it.
#
# Codex carries the larger budget, so implementation-heavy units belong here.
# See the parallel work protocol in AGENTS.md.
set -euo pipefail

die() { echo "dispatch: $*" >&2; exit 1; }

[ $# -ge 2 ] || die "usage: scripts/dispatch.sh <UNIT-ID> <handle>/codex [--dry-run]"
UNIT="$1"
OWNER="$2"
DRY_RUN=false
[ "${3:-}" = "--dry-run" ] && DRY_RUN=true

case "$OWNER" in
    */codex) ;;
    */claude) die "$OWNER is a Claude owner. Dispatch a Claude session with the Agent tool and worktree isolation, not this script." ;;
    *) die "owner must look like handle/codex" ;;
esac

command -v codex >/dev/null || die "codex CLI not on PATH"
ROOT=$(git rev-parse --show-toplevel) || die "not a git repository"
cd "$ROOT"

SLUG=$(python3 - "$UNIT" <<'PY'
import sys, pathlib
unit = sys.argv[1]
for p in sorted(pathlib.Path("specs/units").glob("*.md")):
    if f"id: {unit}\n" in p.read_text():
        print(p.stem)
        break
else:
    sys.exit(1)
PY
) || die "no intake file declares $UNIT"

BRANCH="feature/$SLUG"
WORKTREE="$ROOT/../AlphaLedger-wt/$SLUG"
LOGDIR="$ROOT/.dispatch"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$SLUG.jsonl"
RESULT="$LOGDIR/$SLUG.result.md"
PROMPT="$LOGDIR/$SLUG.prompt.txt"

cat > "$PROMPT" <<EOF
You are implementing $UNIT in the AlphaLedger repository, as owner $OWNER.

You are already inside an isolated git worktree on branch $BRANCH, cut from
develop. The unit is already claimed for you. Do not claim anything, do not
switch branches, and do not merge or push. Your job ends with a green quality
gate and a summary.

Read these first, in order:
  1. ONBOARDING.md
  2. AGENTS.md, especially the safety boundary and the definition of done
  3. specs/units/$SLUG.md, which is your specification
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

Hard constraints. These are enforced by a PreToolUse hook, so violating one
fails loudly rather than silently:
  - Write only inside the path globs named in your unit's frontmatter. Never
    touch another lane's files.
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

echo "unit      $UNIT"
echo "owner     $OWNER"
echo "branch    $BRANCH"
echo "worktree  $WORKTREE"
echo "log       $LOG"

if [ "$DRY_RUN" = true ]; then
    echo
    echo "dry run: nothing claimed, no worktree, no dispatch."
    echo "prompt written to $PROMPT"
    exit 0
fi

[ "$(git branch --show-current)" = "develop" ] \
    || die "claim from develop, not $(git branch --show-current). Git refuses to check one branch out twice, so the primary clone stays on develop as the claiming station."
git diff --quiet && git diff --cached --quiet \
    || die "working tree is dirty. Commit or stash before dispatching."

python3 scripts/coord.py claim "$UNIT" --owner "$OWNER" >/dev/null \
    || die "claim refused. Run 'python3 scripts/coord.py list' and pick another unit."

UNIT_FILE=$(git status --porcelain specs/units | awk '{print $2}' | head -1)
git add "$UNIT_FILE"
git commit -q -m "chore(registry): claim $UNIT for $OWNER"
git push -q origin develop || die "claim push rejected. Someone claimed first. Run: git pull --rebase origin develop"

git worktree add "$WORKTREE" -b "$BRANCH" develop >/dev/null
[ -f .claude/settings.local.json ] && cp .claude/settings.local.json "$WORKTREE/.claude/" || true

# git metadata for a worktree lives in the primary clone, so it must be writable
GIT_COMMON=$(git rev-parse --git-common-dir)
GIT_COMMON=$(cd "$GIT_COMMON" && pwd)

nohup codex exec \
    -C "$WORKTREE" \
    -s workspace-write \
    --add-dir "$GIT_COMMON" \
    --json \
    -o "$RESULT" \
    - < "$PROMPT" > "$LOG" 2>&1 &

echo "pid       $!"
echo
echo "watch:    tail -f $LOG"
echo "result:   cat $RESULT"
echo "finish:   cd $WORKTREE && bash scripts/verify_harness.sh"
