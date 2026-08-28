#!/usr/bin/env bash
# Dispatch the reviewer a unit names in its own frontmatter.
#
#   scripts/review.sh UNIT-011
#   scripts/review.sh UNIT-011 --base develop
#
# Review is mandatory. `coord.py state <unit> merged` refuses a unit with no
# recorded review, and refuses one whose last verdict was not clear. This
# script produces the review; recording it is a separate, deliberate step.
#
# Codex-dispatched work is reviewed by the Codex specialist of the same name,
# so a run does not mix model families. Claude-owned work is reviewed by the
# Claude specialist, which only the orchestrating session can spawn.
set -euo pipefail

die() { echo "review: $*" >&2; exit 1; }

[ $# -ge 1 ] || die "usage: scripts/review.sh <UNIT-ID> [--base <branch>]"
UNIT="$1"
BASE="develop"
[ "${2:-}" = "--base" ] && BASE="${3:?--base needs a branch}"

ROOT=$(git rev-parse --show-toplevel) || die "not a git repository"
cd "$ROOT"

read -r SLUG REVIEWER OWNER BRANCH <<EOF
$(bash scripts/hook_python.sh - "$UNIT" <<'PY'
import pathlib
import sys

unit = sys.argv[1]
for path in sorted(pathlib.Path("specs/units").glob("*.md")):
    text = path.read_text()
    if f"id: {unit}\n" not in text:
        continue
    fields = {}
    for line in text.split("---", 2)[1].splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    print(path.stem, fields.get("reviewer", "-"), fields.get("owner", "-"), fields.get("branch", "-"))
    break
else:
    sys.exit(1)
PY
)
EOF
[ -n "${SLUG:-}" ] || die "no intake file declares $UNIT"

WORKTREE="$ROOT/../AlphaLedger-wt/$SLUG"
[ -d "$WORKTREE" ] || die "no worktree at $WORKTREE. The unit's work has to exist before it can be reviewed."
OUT="$ROOT/.dispatch/$SLUG.review.md"
mkdir -p "$ROOT/.dispatch"

echo "unit      $UNIT"
echo "reviewer  $REVIEWER"
echo "owner     $OWNER"
echo "base      $BASE"

case "$OWNER" in
    */claude)
        echo
        echo "This unit is Claude-owned, so its reviewer is the Claude specialist"
        echo "'$REVIEWER', which only the orchestrating session can spawn. This script"
        echo "does not shell out to it. Ask the session to dispatch it against:"
        echo "  git diff $BASE $BRANCH"
        echo "Then record the outcome:"
        echo "  scripts/coord.py review $UNIT --by $REVIEWER --verdict <clear|conditional|block>"
        exit 0
        ;;
    */codex) ;;
    *) die "owner $OWNER names no runtime" ;;
esac

# the Codex specialist carrying the same role, hyphens become underscores
AGENT_FILE=".codex/agents/$(echo "$REVIEWER" | tr '-' '_').toml"
[ -f "$AGENT_FILE" ] || die "no Codex specialist at $AGENT_FILE for reviewer $REVIEWER"

PROMPT="$ROOT/.dispatch/$SLUG.review-prompt.txt"
{
    bash scripts/hook_python.sh - "$AGENT_FILE" <<'PY'
import pathlib
import sys
import tomllib

data = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
print(data.get("developer_instructions", "").strip())
PY
    cat <<EOF

You are reviewing $UNIT. Its specification is specs/units/$SLUG.md; read it in
full, including its acceptance criteria, its test list, and any handoff notes,
because those record decisions taken during implementation.

The bounded diff is:

    git diff $BASE...HEAD

Use the three-dot form. Two dots would also show everything $BASE gained since
this branch was cut, which here is substantial and none of it belongs to this
unit. Do not widen beyond that diff.

Answer these explicitly:
  - which acceptance criteria are met and which are not, by number;
  - for each test, whether it would still pass if the behaviour it names were
    broken. Name any test that asserts on a double it configured itself rather
    than on real behaviour;
  - whether all four required paths are genuinely covered: success, failure,
    restart, and no-trade;
  - whether the change stayed inside the unit's declared path globs;
  - whether anything the implementation added was not asked for.

The repository prefers a well established package to bespoke code. If this
change hand-rolls something a known library already does, say so and name the
library.

End with a verdict on its own line, exactly one of:
  VERDICT: clear
  VERDICT: conditional
  VERDICT: block

Then state which commands you actually ran, and what remains unverified. Never
call a path verified when it was only inspected.
EOF
} > "$PROMPT"

echo
echo "reviewing with the Codex specialist $(basename "$AGENT_FILE" .toml)"
( cd "$WORKTREE" && codex exec review -c model_reasoning_effort=xhigh - < "$PROMPT" ) \
    | tee "$OUT" | tail -40

echo
echo "full review: $OUT"
echo "record it:   scripts/coord.py review $UNIT --by $REVIEWER --verdict <clear|conditional|block>"
