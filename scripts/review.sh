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

# A second review round would otherwise truncate the artifact the round before
# it wrote, which is the evidence a merge gate depends on. Move it aside first,
# matching the rotation scripts/dispatch.sh already does for its own log.
rotate_aside() {
    local f="$1"
    if [ -s "$f" ]; then
        local n=1
        while [ -e "$f.$n" ]; do n=$((n + 1)); done
        mv "$f" "$f.$n"
    fi
}

# codex exec review states its conclusion in one of two shapes and sometimes in
# neither: a prose VERDICT line, or a JSON overall_correctness field. Three
# reviews so far ended with a confident summary and no verdict at all, which
# reads exactly like a finished result and leaves the reader to notice an
# absence. Say so in the artifact rather than making absence the signal. This
# grades nothing: D-018 puts that on the session on purpose.
note_missing_verdict() {
    local f="$1"
    if ! grep -q "VERDICT:" "$f" && ! grep -q "overall_correctness" "$f"; then
        {
            echo
            echo "NO VERDICT STATED. This review ended without a VERDICT line and without"
            echo "an overall_correctness field. Grade it from its findings and record the"
            echo "grade yourself, per D-018. Do not read the absence as a clearance."
        } >> "$f"
    fi
}

if [ "${1:-}" = "--self-test" ]; then
    dir=$(mktemp -d)
    trap 'rm -rf "$dir"' EXIT
    f="$dir/probe.review.md"

    echo "round one" > "$f"
    rotate_aside "$f"
    got=$(cat "$f.1" 2>/dev/null || true)
    [ "$got" = "round one" ] || die "self-test: the first round was not moved aside as $f.1"

    echo "round two" > "$f"
    rotate_aside "$f"
    got=$(cat "$f.2" 2>/dev/null || true)
    [ "$got" = "round two" ] || die "self-test: the second round did not take the next free number"
    got=$(cat "$f.1" 2>/dev/null || true)
    [ "$got" = "round one" ] || die "self-test: the second round overwrote the first"

    prose="$dir/prose.md"
    echo "looks fine to me. VERDICT: clear" > "$prose"
    note_missing_verdict "$prose"
    grep -q "NO VERDICT STATED" "$prose" && die "self-test: a stated prose verdict was wrongly flagged"

    js="$dir/json.md"
    echo '{"overall_correctness": "patch is incorrect"}' > "$js"
    note_missing_verdict "$js"
    grep -q "NO VERDICT STATED" "$js" && die "self-test: a json verdict was wrongly flagged"

    silent="$dir/silent.md"
    echo "All findings are fixed and the suite passes." > "$silent"
    note_missing_verdict "$silent"
    grep -q "NO VERDICT STATED" "$silent" || die "self-test: a review with no verdict was not flagged"

    echo "review self-test passed: 5 cases"
    exit 0
fi

[ $# -ge 1 ] || die "usage: scripts/review.sh <UNIT-ID> [--base <branch>] [--dry-run] [--self-test]"
UNIT="$1"
BASE="develop"
DRY_RUN=false
shift
while [ $# -gt 0 ]; do
    case "$1" in
        --base) BASE="${2:?--base needs a branch}"; shift ;;
        --dry-run) DRY_RUN=true ;;
        *) die "unknown argument $1" ;;
    esac
    shift
done

ROOT=$(git rev-parse --show-toplevel) || die "not a git repository"
cd "$ROOT"

read -r SLUG REVIEWER OWNER BRANCH ROUNDS <<EOF
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
    log = fields.get("review_log", "")
    rounds = len([v for v in log.strip("[]").split(",") if v.strip()])
    print(
        path.stem,
        fields.get("reviewer", "-"),
        fields.get("owner", "-"),
        fields.get("branch", "-"),
        rounds,
    )
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
echo "round     $((ROUNDS + 1))"
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

A finding carries severity only if it is actionable inside this unit's declared
path globs and bears on one of its numbered acceptance criteria. Work that
belongs to a later unit is not a finding against this one. Put anything like
that under a heading "Out of scope", with no severity, and do not let it move
the verdict. A reviewer with an unbounded mandate always finds something, and a
unit held open for work it was never asked to do never closes.

If a finding restates one an earlier round already addressed, say so and say
what is still wrong with the fix, rather than raising it again as new.

End with a verdict on its own line, exactly one of:
  VERDICT: clear
  VERDICT: conditional
  VERDICT: block

Then state which commands you actually ran, and what remains unverified. Never
call a path verified when it was only inspected.
EOF
} > "$PROMPT"

# A unit that has been reviewed before does not need its whole diff read again.
# Rereading it is how a unit stays open forever: every full pass is a fresh
# chance to find something new in code two earlier passes already cleared, so
# the rounds have no natural end. A follow-up round asks a narrower question,
# which is the one that actually decides whether the unit is done.
if [ "${ROUNDS:-0}" -gt 0 ]; then
    cat >> "$PROMPT" <<FOLLOWUP

THIS IS REVIEW ROUND $((ROUNDS + 1)). The $ROUNDS round(s) before it already read
this unit's full diff, and every finding they produced is recorded in the intake
under "Handoff notes". Answer these, and only these:

  1. For each recorded finding, is it fixed? Name the code that fixes it and the
     test that would fail if it regressed. A finding that is not fixed is still
     a finding, and saying so is the most useful thing you can do here.
  2. Read the commits this round added, the most recent ones on the branch. Two
     of this project's past findings were defects introduced by the previous
     round's own fix, so a new defect is likeliest here.
  3. Is the unit's own verification green.

Code that neither changed this round nor relates to a recorded finding has been
read twice already. Do not raise it again. You may raise something new only if
you can name the numbered acceptance criterion it breaks and show the failure.
A preference, a style, or work that belongs to a later unit is not that.

If every recorded finding is fixed and this round introduced nothing, the
verdict is clear, and saying so is the correct outcome. A reviewer that never
clears anything is not a stricter reviewer, it is a gate that does not open.
FOLLOWUP
fi

if [ "$DRY_RUN" = true ]; then
    echo
    echo "dry run: prompt built, nothing dispatched."
    echo "  $PROMPT"
    exit 0
fi

echo
echo "reviewing with the Codex specialist $(basename "$AGENT_FILE" .toml)"
# --json so the run is watchable like any dispatch. scripts/watch.sh picks
# up *.review.jsonl and marks it a review rather than an implementation.
STREAM="$ROOT/.dispatch/$SLUG.review.jsonl"
rotate_aside "$STREAM"
( cd "$WORKTREE" && codex exec review --json -c model_reasoning_effort=xhigh \
    - < "$PROMPT" ) > "$STREAM" 2>&1 || true

# Lift the review out of the stream into a readable artifact. Keep every
# message, not the last one: the UNIT-011 review carried its summary and its
# findings, and an extractor that overwrote on each message would have kept
# whichever came last and silently dropped the other.
rotate_aside "$OUT"
bash scripts/hook_python.sh - "$STREAM" > "$OUT" <<'EXTRACT'
import json
import sys
from pathlib import Path

said = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    item = event.get("item", {})
    if event.get("type") == "item.completed" and item.get("type") == "agent_message":
        text = item.get("text", "").strip()
        if text:
            said.append(text)
print("\n\n".join(said))
EXTRACT

# An empty artifact reads exactly like a review that found nothing, which is the
# most dangerous thing this script could say. Refuse instead, and point at the
# stream so the reason is one command away.
if [ ! -s "$OUT" ]; then
    rm -f "$OUT"
    die "the review produced no readable output. The raw stream is $STREAM; its first lines are:
$(head -3 "$STREAM")"
fi

# `codex exec review` states its conclusion in one of two shapes and sometimes
# in neither: a prose VERDICT line, or a JSON overall_correctness field. Three
# reviews so far have ended with a confident summary and no verdict at all,
# which reads exactly like a finished result and leaves the reader to notice an
# absence. Say so in the artifact rather than making absence the signal. This
# does not grade anything: D-018 puts that on the session on purpose.
note_missing_verdict "$OUT"
tail -40 "$OUT"

echo
echo "full review: $OUT"
echo "record it:   scripts/coord.py review $UNIT --by $REVIEWER --verdict <clear|conditional|block>"
