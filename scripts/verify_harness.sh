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

# Every interpreter call goes through the resolver so a stale system python3
# cannot make a check pass or fail for the wrong reason. See
# scripts/hook_python.sh for why a bare system interpreter is not safe here.
py() { bash scripts/hook_python.sh "$@"; }

check() {
    if [ "$1" -eq 0 ]; then
        echo "  PASS  $2"
    else
        echo "  FAIL  $2"
        fail=1
    fi
}

echo "== self-tests =="
out=$(py .claude/hooks/guard.py --self-test 2>&1); check $? "claude guard: $out"
out=$(py .codex/hooks/guard.py --self-test 2>&1); check $? "codex guard: $out"
out=$(py scripts/coord.py --self-test 2>&1 | tail -1); check $? "coord: $out"

echo "== configuration parses =="
py -c "import json;json.load(open('.claude/settings.json'))" 2>/dev/null
check $? ".claude/settings.json"
py -c "import json;json.load(open('.codex/hooks.json'))" 2>/dev/null
check $? ".codex/hooks.json"
py -c "import json;json.load(open('.mcp.json'))" 2>/dev/null
check $? ".mcp.json"

# Portable in-place edit. GNU sed and BSD sed disagree about `sed -i`, and
# the BSD reading silently left the probe fixture untouched.
rewrite_state() {
    _file=$1; _from=$2; _to=$3
    sed "s/^state: ${_from}\$/state: ${_to}/" "$_file" > "${_file}.new" \
        && mv "${_file}.new" "$_file"
}

echo "== unit registry =="
py scripts/coord.py list >/dev/null 2>&1
check $? "coord list runs"

# Probe a throwaway copy. A verification script must never mutate the registry.
probe_units=$(mktemp -d)
cp specs/units/*.md "$probe_units/"
rewrite_state "$probe_units"/001-*.md 'merged' 'available'
py scripts/coord.py --units-dir "$probe_units" claim UNIT-010 --owner probe/codex \
    >/dev/null 2>&1
[ $? -ne 0 ]; check $? "dependency gate refuses a unit whose dependency is unmerged"

rewrite_state "$probe_units"/001-*.md 'available' 'merged'
py scripts/coord.py --units-dir "$probe_units" claim UNIT-010 --owner probe/codex \
    >/dev/null 2>&1
check $? "the same unit is claimable once its dependency is merged"

py scripts/coord.py --units-dir "$probe_units" claim UNIT-010 --owner other/claude \
    >/dev/null 2>&1
[ $? -ne 0 ]; check $? "a second owner cannot claim a held unit"

rm -r "$probe_units"
git diff --quiet specs/
check $? "the probe never touched the real registry"

# These harness checks do not replace the application quality gate in AGENTS.md.
# Run it here too, or a formatting regression in the tooling passes this script
# while the repository gate is red.
if [ -f pyproject.toml ]; then
    echo "== application quality gate =="
    uv run ruff check . >/dev/null 2>&1; check $? "ruff check"
    uv run ruff format --check . >/dev/null 2>&1; check $? "ruff format --check"
    uv run mypy src >/dev/null 2>&1; check $? "mypy strict"
    uv run pytest -q >/dev/null 2>&1; check $? "pytest"
fi

echo "== skill conventions =="
c=0
for f in .claude/skills/*/SKILL.md .agents/skills/*/SKILL.md; do
    grep -q "^origin:" "$f" || c=$((c + 1))
done
[ "$c" -eq 0 ]; check $? "every skill declares origin ($c missing)"

c=0
for d in .agents/skills/*/; do
    [ -f "$d/agents/openai.yaml" ] || c=$((c + 1))
done
[ "$c" -eq 0 ]; check $? "every codex skill has an interface binding ($c missing)"

# Lifecycle skills must never be implicitly invocable. A model must not be able
# to decide on its own to run a paper smoke test or freeze research.
c=0
for s in bootstrap handoff paper-smoke research-gate submission-readiness social-update; do
    f=".agents/skills/$s/agents/openai.yaml"
    [ -f "$f" ] && grep -q "allow_implicit_invocation: false" "$f" || c=$((c + 1))
done
[ "$c" -eq 0 ]; check $? "lifecycle skills stay manual-only ($c wrong)"

echo "== codex dispatch =="
command -v codex >/dev/null 2>&1; check $? "codex CLI on PATH"
bash scripts/dispatch.sh UNIT-010 pablo/codex --dry-run >/dev/null 2>&1
check $? "dispatch dry run builds a prompt"
bash scripts/dispatch.sh UNIT-010 pablo/claude --dry-run >/dev/null 2>&1
[ $? -ne 0 ]; check $? "dispatch refuses a claude owner"
git diff --quiet specs/; check $? "a dry run claims nothing"

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
( cd "$probe" && py .claude/hooks/guard.py --self-test >/dev/null 2>&1 )
check $? "claude guard self-test inside the worktree"
( cd "$probe" && py .codex/hooks/guard.py --self-test >/dev/null 2>&1 )
check $? "codex guard self-test inside the worktree"
( cd "$probe" && py scripts/coord.py list >/dev/null 2>&1 )
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
