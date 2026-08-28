#!/usr/bin/env bash
# Verify the AlphaLedger development harness.
#
# Read-only apart from a throwaway probe worktree, which is removed on exit.
# Run this after changing a guard, a hook, the coordination tool, or the
# branching setup. It does not verify application code; that is what the unit
# verification commands in specs/units/ are for.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

fail=0
check() {
    if [ "$1" -eq 0 ]; then
        echo "  PASS  $2"
    else
        echo "  FAIL  $2"
        fail=1
    fi
}

echo "== self-tests =="
out=$(python3 .claude/hooks/guard.py --self-test 2>&1); check $? "claude guard: $out"
out=$(python3 .codex/hooks/guard.py --self-test 2>&1); check $? "codex guard: $out"
out=$(python3 scripts/coord.py --self-test 2>&1 | tail -1); check $? "coord: $out"

echo "== configuration parses =="
python3 -c "import json;json.load(open('.claude/settings.json'))" 2>/dev/null
check $? ".claude/settings.json"
python3 -c "import json;json.load(open('.codex/hooks.json'))" 2>/dev/null
check $? ".codex/hooks.json"
python3 -c "import json;json.load(open('.mcp.json'))" 2>/dev/null
check $? ".mcp.json"

echo "== unit registry =="
python3 scripts/coord.py list >/dev/null 2>&1
check $? "coord list runs"
python3 scripts/coord.py claim UNIT-010 --owner probe/codex >/dev/null 2>&1
[ $? -ne 0 ]; check $? "dependency gate refuses a unit whose dependency is unmerged"
git diff --quiet specs/
check $? "a refused claim leaves specs/ untouched"

echo "== git flow =="
git show-ref --verify --quiet refs/heads/develop; check $? "develop exists"
git show-ref --verify --quiet refs/heads/main; check $? "main exists"
[ -n "$(git config --get gitflow.branch.develop)" ]
check $? "gitflow config present (run scripts/gitflow-init.sh if absent)"
branch=$(git branch --show-current)
case "$branch" in
    main|develop|feature/*|bugfix/*|release/*|hotfix/*|support/*) true ;;
    *) false ;;
esac
check $? "current branch '$branch' follows the model"

echo "== prose =="
c=$(grep -rln $'[—–]' --include="*.md" . 2>/dev/null | grep -v "^./.idea" | wc -l)
[ "$c" -eq 0 ]; check $? "no em or en dashes in markdown ($c files)"

echo "== hooks fire inside a worktree =="
probe=$(mktemp -d)
trap 'git worktree remove --force "$probe" >/dev/null 2>&1; git branch -D feature/harness-probe >/dev/null 2>&1; rmdir "$probe" 2>/dev/null' EXIT
git worktree remove --force "$probe" >/dev/null 2>&1
git branch -D feature/harness-probe >/dev/null 2>&1
git worktree add "$probe" -b feature/harness-probe >/dev/null 2>&1
check $? "probe worktree created"
( cd "$probe" && python3 .claude/hooks/guard.py --self-test >/dev/null 2>&1 )
check $? "claude guard self-test inside the worktree"
( cd "$probe" && python3 .codex/hooks/guard.py --self-test >/dev/null 2>&1 )
check $? "codex guard self-test inside the worktree"
( cd "$probe" && python3 scripts/coord.py list >/dev/null 2>&1 )
check $? "coord runs inside the worktree"
[ ! -f "$probe/.claude/settings.local.json" ]
check $? "settings.local.json absent in the worktree, as documented"

echo
if [ "$fail" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "SOME CHECKS FAILED"
fi
exit "$fail"
