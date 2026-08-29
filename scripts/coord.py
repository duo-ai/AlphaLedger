#!/usr/bin/env python3
"""AlphaLedger unit coordination CLI, the Claude and Codex work channel.

The registry is the directory ``specs/units/``: one Markdown intake file per
unit, carrying ``---`` frontmatter. One file per unit is deliberate. Two people
claiming two different units never touch the same file, so concurrent claims
merge cleanly instead of conflicting on adjacent lines of a shared registry.

Standard library only: this must run before ``uv sync`` and inside a fresh
worktree. ``--self-test`` mirrors the convention in ``.claude/hooks/guard.py``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

VERDICTS = ("clear", "conditional", "block")

STATES = ("available", "claimed", "in_review", "merged", "blocked")

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "available": ("claimed", "blocked"),
    "claimed": ("in_review", "available", "blocked"),
    "in_review": ("merged", "claimed", "blocked"),
    "merged": (),
    "blocked": ("available",),
}

LIST_KEYS = ("depends_on", "review_log")
OWNER_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]*/(claude|codex)")
UNCLAIMED = "-"


class UnitError(Exception):
    """A coordination precondition failed."""


def units_dir(override: str | None = None) -> Path:
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "specs" / "units"


def parse_unit(path: Path) -> tuple[dict[str, object], list[str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise UnitError(f"{path.name}: missing frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise UnitError(f"{path.name}: unterminated frontmatter")
    _, front, body = parts
    meta: dict[str, object] = {}
    order: list[str] = []
    for line in front.splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise UnitError(f"{path.name}: malformed frontmatter line {line!r}")
        key, value = key.strip(), value.strip()
        if key in LIST_KEYS:
            meta[key] = [v.strip() for v in value.strip("[]").split(",") if v.strip()]
        else:
            meta[key] = value
        order.append(key)
    for required in ("id", "lane", "state", "owner"):
        if required not in meta:
            raise UnitError(f"{path.name}: frontmatter missing {required!r}")
    if meta["state"] not in STATES:
        raise UnitError(f"{path.name}: unknown state {meta['state']!r}")
    return meta, order, body


def write_unit(path: Path, meta: dict[str, object], order: list[str], body: str) -> None:
    lines = ["---"]
    for key in order:
        value = meta[key]
        if isinstance(value, list):
            value = "[" + ", ".join(value) + "]"
        lines.append(f"{key}: {value}")
    lines.append("---")
    payload = "\n".join(lines) + "\n" + body
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(payload)
    os.replace(tmp, path)


def load_all(directory: Path) -> dict[str, tuple[dict[str, object], list[str], str, Path]]:
    if not directory.is_dir():
        raise UnitError(f"no unit directory at {directory}")
    units = {}
    for path in sorted(directory.glob("*.md")):
        meta, order, body = parse_unit(path)
        unit_id = str(meta["id"])
        if unit_id in units:
            raise UnitError(f"duplicate unit id {unit_id} in {path.name}")
        units[unit_id] = (meta, order, body, path)
    return units


def get(units: dict, unit_id: str) -> tuple[dict[str, object], list[str], str, Path]:
    if unit_id not in units:
        raise UnitError(f"unknown unit {unit_id}; run 'coord.py list'")
    return units[unit_id]


OWNED_SECTIONS = ("## Contract", "## Test list", "## Verification")
CLARIFICATION = re.compile(r"\[NEEDS CLARIFICATION:[^\]]*\]")
PATH_TOKEN = re.compile(r"`((?:src|tests|research|config)/[A-Za-z0-9_./*-]+)`")
COMMAND_TOKEN = re.compile(r"(?:pytest|mypy|ruff check)\s+((?:src|tests|research|config)/[^\s]+)")


def _section(body: str, heading: str) -> str:
    if heading not in body:
        return ""
    return body.split(heading, 1)[1].split("\n## ", 1)[0]


def _covered(candidate: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if candidate == pattern:
            return True
        if pattern.endswith("**"):
            root = pattern[:-2].rstrip("/")
            if candidate == root or candidate.startswith(root + "/"):
                return True
    return False


def undeclared_paths(meta: dict, body: str) -> list[str]:
    """Files the unit's own body names that its declared globs do not permit.

    The globs are authored before the test list is elaborated, so they drift.
    The body is the later, more considered statement of what the unit touches.
    """
    patterns = [p.strip() for p in str(meta.get("paths", "")).split(",") if p.strip()]
    if not patterns:
        return ["<no paths declared>"]
    named: set[str] = set()
    for heading in OWNED_SECTIONS:
        chunk = _section(body, heading)
        named.update(PATH_TOKEN.findall(chunk))
        named.update(COMMAND_TOKEN.findall(chunk))
    return sorted(c for c in named if not _covered(c, patterns))


def open_clarifications(body: str) -> list[str]:
    """Questions the author deliberately left open rather than guessing."""
    return CLARIFICATION.findall(body)


def _glob_root(glob: str) -> str:
    """The fixed directory prefix of a path glob, before any wildcard."""
    return glob.split("*", 1)[0].rstrip("/")


def _covers(outer: str, inner: str) -> bool:
    return inner == outer or inner.startswith(outer + "/")


def paths_overlap(left: str, right: str) -> bool:
    """Do two units' declared path globs reach the same file?

    D-010 permits parallel writers only while their globs are disjoint. A
    directory glob swallows anything beneath it, which is how two agents end up
    editing one file and discovering it at merge time.
    """
    for a in (item.strip() for item in left.split(",") if item.strip()):
        for b in (item.strip() for item in right.split(",") if item.strip()):
            if a == b:
                return True
            root_a, root_b = _glob_root(a), _glob_root(b)
            if a.endswith("**") and _covers(root_a, root_b):
                return True
            if b.endswith("**") and _covers(root_b, root_a):
                return True
    return False


def conflicting_units(units: dict, unit_id: str) -> list[str]:
    """In-progress units whose globs reach the same files as this one."""
    mine = str(units[unit_id][0].get("paths", ""))
    if not mine:
        return []
    clashes = []
    for other_id, (meta, _, _, _) in units.items():
        if other_id == unit_id or meta["state"] not in ("claimed", "in_review"):
            continue
        if paths_overlap(mine, str(meta.get("paths", ""))):
            clashes.append(f"{other_id} ({meta['owner']})")
    return sorted(clashes)


def cmd_list(units: dict, lane: str | None, state: str | None, owner: str | None) -> int:
    rows = []
    for unit_id in sorted(units):
        meta = units[unit_id][0]
        if lane and meta["lane"] != lane:
            continue
        if state and meta["state"] != state:
            continue
        if owner and meta["owner"] != owner:
            continue
        rows.append(
            (
                unit_id,
                str(meta["lane"]),
                str(meta["state"]),
                str(meta["owner"]),
                str(meta.get("preferred_runtime", "-")),
                str(meta.get("title", "")),
            )
        )
    if not rows:
        print("no units match")
        return 0
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    header = ("ID", "LANE", "STATE", "OWNER", "PREFER", "TITLE")
    widths = [max(widths[i], len(header[i])) for i in range(5)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths) + "  {}"
    print(fmt.format(*header))
    for row in rows:
        print(fmt.format(*row))
    return 0


def cmd_show(units: dict, unit_id: str) -> int:
    meta, order, body, path = get(units, unit_id)
    print(f"# {path}")
    for key in order:
        value = meta[key]
        if isinstance(value, list):
            value = "[" + ", ".join(value) + "]"
        print(f"{key}: {value}")
    print(body.rstrip())
    return 0


def check_claimable(units: dict, unit_id: str, owner: str) -> None:
    """Every precondition a claim must satisfy, reading only, raising on the first failure.

    `cmd_claim` and the `check` subcommand both call this, so asking whether a
    claim would succeed and actually making it can never drift apart. Nothing
    here writes a unit file.
    """
    meta, _order, body, _path = get(units, unit_id)
    if not OWNER_PATTERN.fullmatch(owner):
        raise UnitError("owner must look like handle/claude or handle/codex")
    if meta["state"] != "available":
        raise UnitError(
            f"{unit_id} is {meta['state']} (owner {meta['owner']}); pull --rebase and pick another unit"
        )
    unmet = [
        dep for dep in meta.get("depends_on", []) if str(get(units, dep)[0]["state"]) != "merged"
    ]
    if unmet:
        raise UnitError(f"{unit_id} depends on unmerged units: {', '.join(unmet)}")
    open_questions = open_clarifications(body)
    if open_questions:
        raise UnitError(
            f"{unit_id} still carries {len(open_questions)} open clarification(s): "
            f"{'; '.join(q[:70] for q in open_questions)}. Resolve them in the intake "
            "before claiming. A unit is claimable only when it is not knowingly hollow."
        )
    missing = undeclared_paths(meta, body)
    if missing:
        raise UnitError(
            f"{unit_id} names files its declared paths forbid: {', '.join(missing)}. "
            "Either widen paths or stop naming them. An agent that hits this mid-unit "
            "has to stop, which is correct and expensive."
        )
    clashes = conflicting_units(units, unit_id)
    if clashes:
        raise UnitError(
            f"{unit_id} declares paths that overlap work already in progress: "
            f"{', '.join(clashes)}. Parallel writers are only safe while their "
            "globs are disjoint, per D-010."
        )


def cmd_check(units: dict, unit_id: str, owner: str) -> int:
    """Ask whether a unit would be claimable, without claiming it."""
    check_claimable(units, unit_id, owner)
    return 0


def cmd_claim(units: dict, unit_id: str, owner: str, branch: str | None) -> int:
    check_claimable(units, unit_id, owner)
    meta, order, body, path = get(units, unit_id)
    slug = path.stem
    meta["state"] = "claimed"
    meta["owner"] = owner
    meta["branch"] = branch or f"feature/{slug}"
    meta["claimed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # a re-claim reopens the work, so a verdict from the previous round no
    # longer describes what is on the branch
    meta.pop("review_verdict", None)
    order[:] = [k for k in order if k != "review_verdict"]
    for key in ("branch", "claimed_at"):
        if key not in order:
            order.append(key)
    write_unit(path, meta, order, body)
    worktree = f"../AlphaLedger-wt/{slug}"
    print(f"claimed {unit_id} for {owner} on branch {meta['branch']}")
    print("\nCommit and push the claim to develop before you start work:")
    print(
        f"  git add {path.as_posix()} && git commit -m 'chore(registry): claim {unit_id} for {owner}' && git push origin develop"
    )
    print("\nThen create the isolated worktree:")
    print(f"  git worktree add {worktree} -b {meta['branch']} develop")
    if str(meta.get("preferred_runtime", "")) == "claude":
        print(
            f"  cp .claude/settings.local.json {worktree}/.claude/   # untracked: does NOT carry into a worktree"
        )
    return 0


def cmd_review(units: dict, unit_id: str, reviewer: str, verdict: str) -> int:
    """Record that a review happened and what it concluded."""
    meta, order, body, path = get(units, unit_id)
    if verdict not in VERDICTS:
        raise UnitError(f"verdict must be one of {', '.join(VERDICTS)}; got {verdict!r}")
    if meta["state"] not in ("claimed", "in_review"):
        raise UnitError(f"{unit_id} is {meta['state']}; review applies to work in progress")
    # The merge gate only asks whether the last verdict was clear, so it cannot
    # tell a verdict from the declared reviewer apart from one recorded under any
    # other name. Without this the routing in D-018, execution work to the
    # execution reviewer, is prose rather than a rule, and a typo silently
    # attributes a clearance to a specialist that never ran.
    declared = str(meta.get("reviewer", ""))
    if not declared or declared == "-":
        raise UnitError(f"{unit_id} declares no reviewer, so no review of it can be recorded")
    if reviewer != declared:
        raise UnitError(
            f"{unit_id} names {declared} as its reviewer; refusing to record a verdict "
            f"from {reviewer!r}. If the reviewer really did change, change the "
            f"frontmatter first so the record and the routing agree."
        )
    log = meta.get("review_log")
    if not isinstance(log, list):
        # A unit reviewed before the log existed carries one verdict and no
        # history. Seed from it rather than starting the count at zero, or the
        # round that follows looks like the first and the escalation below
        # fires a whole round late.
        previous = str(meta.get("review_verdict", ""))
        log = [previous] if previous in VERDICTS else []
    meta["review_log"] = [*log, verdict]
    meta["reviewed_by"] = reviewer
    meta["review_verdict"] = verdict
    meta["reviewed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for key in ("reviewed_by", "review_verdict", "reviewed_at", "review_log"):
        if key not in order:
            order.append(key)
    write_unit(path, meta, order, body)
    rounds = len(meta["review_log"])
    print(f"{unit_id}: reviewed by {reviewer}, verdict {verdict}, round {rounds}")
    if verdict != "clear":
        print("  not mergeable until the findings are addressed and it is reviewed again")
    if verdict != "clear" and rounds >= 2 and str(meta["review_log"][-2]) != "clear":
        print(f"  {rounds} rounds have not cleared this unit. Reopening it now needs")
        print("  --another-pass, so that the decision to spend another round is a")
        print("  human one. See the message that refusal prints.")
    return 0


def cmd_state(units: dict, unit_id: str, new_state: str, another_pass: bool = False) -> int:
    meta, order, body, path = get(units, unit_id)
    current = str(meta["state"])
    if new_state not in STATES:
        raise UnitError(f"unknown state {new_state!r}; one of {', '.join(STATES)}")
    if new_state not in ALLOWED_TRANSITIONS[current]:
        allowed = ", ".join(ALLOWED_TRANSITIONS[current]) or "nothing (terminal)"
        raise UnitError(f"{unit_id}: {current} -> {new_state} is not allowed; allowed: {allowed}")
    if current == "in_review" and new_state == "claimed" and not another_pass:
        log = meta.get("review_log")
        log = [str(v) for v in log] if isinstance(log, list) else []
        if len(log) >= 2 and log[-1] != "clear" and log[-2] != "clear":
            raise UnitError(
                f"{unit_id} has been through {len(log)} review rounds without clearing "
                f"({', '.join(log)}). Another pass is not automatically the answer. "
                f"Decide first: if the outstanding findings are actionable inside this "
                f"unit's own path globs and bear on its numbered acceptance criteria, "
                f"reopen it with --another-pass. If they belong to a later unit, they "
                f"are not findings against this one; record that and narrow the intake, "
                f"or split the work into a new unit. This refusal exists so a reviewer "
                f"with an unbounded mandate cannot keep a unit open forever."
            )
    if new_state == "merged":
        verdict = str(meta.get("review_verdict", ""))
        if not verdict:
            raise UnitError(
                f"{unit_id} has no recorded review. A unit merges only after the reviewer "
                f"named in its frontmatter reports. Record it with: "
                f"coord.py review {unit_id} --by <reviewer> --verdict clear"
            )
        if verdict != "clear":
            raise UnitError(
                f"{unit_id} last review returned {verdict!r}. Address the findings and "
                "record a new review before merging."
            )
    meta["state"] = new_state
    if new_state == "available":
        meta["owner"] = UNCLAIMED
        meta["branch"] = UNCLAIMED
    write_unit(path, meta, order, body)
    print(f"{unit_id}: {current} -> {new_state}")
    return 0


def _sample(unit_id: str, lane: str, state: str, owner: str, depends: str = "[]") -> str:
    return (
        "---\n"
        f"id: {unit_id}\n"
        f"title: sample {unit_id}\n"
        f"lane: {lane}\n"
        f"state: {state}\n"
        f"owner: {owner}\n"
        "branch: -\n"
        f"paths: src/alphaledger/{unit_id.lower()}.py\n"
        "reviewer: code-reviewer\n"
        "preferred_runtime: codex\n"
        f"depends_on: {depends}\n"
        "---\n"
        "\n## Problem\n\nBody text must survive a rewrite.\n"
    )


def self_test() -> int:
    import shutil

    cases = 0
    root = Path(tempfile.mkdtemp(prefix="coord-selftest-"))
    try:
        directory = root / "units"
        directory.mkdir()
        (directory / "001-domain.md").write_text(
            _sample("UNIT-001", "shared", "available", UNCLAIMED)
        )
        (directory / "010-adapter.md").write_text(
            _sample("UNIT-010", "execution", "available", UNCLAIMED, "[UNIT-001]")
        )
        (directory / "020-recorder.md").write_text(
            _sample("UNIT-020", "research", "claimed", "ada/claude")
        )

        units = load_all(directory)
        assert set(units) == {"UNIT-001", "UNIT-010", "UNIT-020"}, "load_all must find every unit"
        cases += 1

        # 2. body survives a frontmatter rewrite
        meta, order, body, path = units["UNIT-001"]
        write_unit(path, meta, order, body)
        assert "Body text must survive a rewrite." in path.read_text(), "rewrite must preserve body"
        cases += 1

        # 3. claiming an available unit sets owner, state, branch
        assert cmd_claim(load_all(directory), "UNIT-001", "pablo/codex", None) == 0
        meta = load_all(directory)["UNIT-001"][0]
        assert meta["state"] == "claimed" and meta["owner"] == "pablo/codex", (
            "claim must record owner"
        )
        assert meta["branch"] == "feature/001-domain", "claim must derive a branch"
        cases += 1

        # 4. a second claim on the same unit is refused
        try:
            cmd_claim(load_all(directory), "UNIT-001", "ada/claude", None)
            raise AssertionError("double claim must be refused")
        except UnitError as exc:
            assert "claimed" in str(exc), "refusal must name the current state"
        cases += 1

        # 5. a unit whose dependency is unmerged cannot be claimed
        try:
            cmd_claim(load_all(directory), "UNIT-010", "ada/claude", None)
            raise AssertionError("claim over an unmerged dependency must be refused")
        except UnitError as exc:
            assert "UNIT-001" in str(exc), "refusal must name the blocking dependency"
        cases += 1

        # 6. the same unit is claimable once its dependency reaches merged
        cmd_state(load_all(directory), "UNIT-001", "in_review")
        try:
            cmd_state(load_all(directory), "UNIT-001", "merged")
            raise AssertionError("merging without a review must be refused")
        except UnitError as exc:
            assert "no recorded review" in str(exc), "refusal must name the missing review"
        cmd_review(load_all(directory), "UNIT-001", "code-reviewer", "conditional")
        try:
            cmd_state(load_all(directory), "UNIT-001", "merged")
            raise AssertionError("a conditional verdict must not merge")
        except UnitError as exc:
            assert "conditional" in str(exc), "refusal must name the verdict"
        cmd_review(load_all(directory), "UNIT-001", "code-reviewer", "clear")
        # a verdict recorded under a name the unit did not declare is refused,
        # because the merge gate cannot tell one reviewer's clearance from
        # another's and would accept a specialist that never ran
        try:
            cmd_review(load_all(directory), "UNIT-001", "backtest-auditor", "clear")
        except UnitError as exc:
            assert "code-reviewer" in str(exc), "refusal must name the declared reviewer"
        else:
            raise AssertionError("a review by an undeclared reviewer must be refused")
        cases += 1
        cmd_state(load_all(directory), "UNIT-001", "merged")
        assert cmd_claim(load_all(directory), "UNIT-010", "ada/claude", None) == 0
        assert load_all(directory)["UNIT-010"][0]["owner"] == "ada/claude", (
            "dependency gate must open"
        )
        cases += 3

        # 7. a merged unit is terminal
        try:
            cmd_state(load_all(directory), "UNIT-001", "claimed")
            raise AssertionError("merged must be terminal")
        except UnitError as exc:
            assert "terminal" in str(exc), "refusal must say the state is terminal"
        cases += 1

        # 8. releasing a claim clears the owner and branch
        cmd_state(load_all(directory), "UNIT-020", "available")
        released = load_all(directory)["UNIT-020"][0]
        assert released["owner"] == UNCLAIMED and released["branch"] == UNCLAIMED, (
            "release must clear owner"
        )
        cases += 1

        # 9. owner strings must identify both a person and a runtime
        for bad in ("pablo", "pablo/gpt", "/claude", "PABLO/claude"):
            try:
                cmd_claim(load_all(directory), "UNIT-020", bad, None)
                raise AssertionError(f"owner {bad!r} must be refused")
            except UnitError:
                pass
        cases += 1

        # 10. an unknown unit id is an error, never a silent no-op
        try:
            cmd_claim(load_all(directory), "UNIT-999", "pablo/codex", None)
            raise AssertionError("unknown unit must be refused")
        except UnitError as exc:
            assert "unknown unit" in str(exc), "refusal must say the unit is unknown"
        cases += 1

        # 11. two files declaring one id is a registry corruption, not a merge

        # 12. overlapping globs cannot be held at the same time
        (directory / "030-wide.md").write_text(
            _sample("UNIT-030", "research", "available", UNCLAIMED, "[]").replace(
                "reviewer: code-reviewer", "paths: src/alphaledger/data/**\nreviewer: code-reviewer"
            )
        )
        (directory / "031-narrow.md").write_text(
            _sample("UNIT-031", "research", "available", UNCLAIMED, "[]").replace(
                "reviewer: code-reviewer",
                "paths: src/alphaledger/data/universe.py\nreviewer: code-reviewer",
            )
        )
        cmd_claim(load_all(directory), "UNIT-030", "ada/claude", None)
        try:
            cmd_claim(load_all(directory), "UNIT-031", "pablo/codex", None)
            raise AssertionError("overlapping globs must be refused")
        except UnitError as exc:
            assert "overlap" in str(exc), "refusal must name the overlap"
        cases += 1

        # 13. disjoint globs in the same lane are fine
        assert paths_overlap("src/a/**", "src/b/**") is False, "siblings must not overlap"
        assert paths_overlap("src/data/**", "src/database/**") is False, "prefix is not containment"
        assert paths_overlap("src/a/x.py", "src/a/x.py") is True, "same file overlaps"
        cases += 1

        # 14. a unit may not be claimed while it names a file its paths forbid
        (directory / "040-drift.md").write_text(
            _sample("UNIT-040", "shared", "available", UNCLAIMED, "[]").replace(
                "reviewer: code-reviewer",
                "paths: src/alphaledger/thing.py\nreviewer: code-reviewer",
            )
            + "\n## Verification\n\n```bash\nuv run pytest tests/thing/test_thing.py\n```\n"
        )
        try:
            cmd_claim(load_all(directory), "UNIT-040", "ada/claude", None)
            raise AssertionError("undeclared paths must refuse the claim")
        except UnitError as exc:
            assert "forbid" in str(exc), "refusal must name the problem"
        cases += 1

        # 15. an open clarification blocks the claim
        (directory / "041-open.md").write_text(
            _sample("UNIT-041", "shared", "available", UNCLAIMED, "[]").replace(
                "reviewer: code-reviewer",
                "paths: src/alphaledger/other.py\nreviewer: code-reviewer",
            )
            + "\n## Contract\n\n[NEEDS CLARIFICATION: which feed supplies this]\n"
        )
        try:
            cmd_claim(load_all(directory), "UNIT-041", "ada/claude", None)
            raise AssertionError("an open clarification must refuse the claim")
        except UnitError as exc:
            assert "clarification" in str(exc), "refusal must name the clarification"
        cases += 1
        # every verdict survives the file, and two that do not clear refuse a
        # reflexive third pass. Counting matters more than the count: a reviewer
        # with an unbounded mandate always finds something, so the loop has to
        # reach a human rather than spend rounds on its own.
        if load_all(directory)["UNIT-020"][0]["state"] == "available":
            cmd_claim(load_all(directory), "UNIT-020", "ada/claude", None)
        cmd_state(load_all(directory), "UNIT-020", "in_review")
        cmd_review(load_all(directory), "UNIT-020", "code-reviewer", "block")
        cmd_state(load_all(directory), "UNIT-020", "claimed")
        cmd_state(load_all(directory), "UNIT-020", "in_review")
        cmd_review(load_all(directory), "UNIT-020", "code-reviewer", "block")
        log = load_all(directory)["UNIT-020"][0]["review_log"]
        assert log == ["block", "block"], f"every verdict must survive the file, got {log!r}"
        cases += 1
        try:
            cmd_state(load_all(directory), "UNIT-020", "claimed")
            raise AssertionError("a third pass after two failed rounds must not be automatic")
        except UnitError as exc:
            assert "--another-pass" in str(exc), "refusal must name the way through it"
        cases += 1
        cmd_state(load_all(directory), "UNIT-020", "claimed", another_pass=True)
        cmd_state(load_all(directory), "UNIT-020", "in_review")
        cmd_review(load_all(directory), "UNIT-020", "code-reviewer", "conditional")
        log = load_all(directory)["UNIT-020"][0]["review_log"]
        assert log == ["block", "block", "conditional"], (
            f"three rounds must round-trip, got {log!r}"
        )
        cases += 1

        # a unit reviewed before the log existed carries a verdict and no
        # history, and must still count that round
        meta, order, body, path = load_all(directory)["UNIT-010"]
        meta["state"] = "in_review"
        meta["reviewed_by"] = "code-reviewer"
        meta["review_verdict"] = "block"
        for key in ("reviewed_by", "review_verdict"):
            if key not in order:
                order.append(key)
        write_unit(path, meta, order, body)
        cmd_review(load_all(directory), "UNIT-010", "code-reviewer", "block")
        assert load_all(directory)["UNIT-010"][0]["review_log"] == ["block", "block"], (
            "a verdict recorded before the log existed must seed it"
        )
        cases += 1
        try:
            cmd_state(load_all(directory), "UNIT-010", "claimed")
            raise AssertionError("a seeded history must gate the next pass too")
        except UnitError as exc:
            assert "--another-pass" in str(exc), "refusal must name the way through it"
        cases += 1

        # 16. check succeeds, silently, for a unit claim would accept, and
        # touches nothing
        (directory / "050-first.md").write_text(
            _sample("UNIT-050", "shared", "available", UNCLAIMED)
        )
        before = (directory / "050-first.md").read_bytes()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert cmd_check(load_all(directory), "UNIT-050", "ada/claude") == 0
        assert buf.getvalue() == "", "check must print nothing on success"
        assert (directory / "050-first.md").read_bytes() == before, (
            "a successful check must not write the file it inspected"
        )
        cases += 1

        # 17. check refuses exactly what claim refuses: an unmet dependency
        # (UNIT-030 is still claimed, not merged, from case 12) and an
        # undeclared path (UNIT-040, from case 14)
        (directory / "051-second.md").write_text(
            _sample("UNIT-051", "shared", "available", UNCLAIMED, "[UNIT-030]")
        )
        before = (directory / "051-second.md").read_bytes()
        try:
            cmd_check(load_all(directory), "UNIT-051", "ada/claude")
            raise AssertionError("check must refuse an unmet dependency")
        except UnitError as exc:
            assert "UNIT-030" in str(exc), "refusal must name the blocking dependency"
        assert (directory / "051-second.md").read_bytes() == before, (
            "a refused check must not write the file it inspected"
        )
        cases += 1

        before = (directory / "040-drift.md").read_bytes()
        try:
            cmd_check(load_all(directory), "UNIT-040", "ada/claude")
            raise AssertionError("check must refuse an undeclared path the same as claim")
        except UnitError as exc:
            assert "forbid" in str(exc), "refusal must name the problem"
        assert (directory / "040-drift.md").read_bytes() == before, (
            "a refused check must not write the file it inspected"
        )
        cases += 1

        # 18. check and claim must fail on the identical fixture with the
        # identical message; a check that could drift from claim would make a
        # dispatch dry run trustworthy in appearance only
        try:
            cmd_check(load_all(directory), "UNIT-051", "ada/claude")
            raise AssertionError("check must still refuse UNIT-051")
        except UnitError as check_exc:
            check_message = str(check_exc)
        try:
            cmd_claim(load_all(directory), "UNIT-051", "ada/claude", None)
            raise AssertionError("claim must still refuse UNIT-051")
        except UnitError as claim_exc:
            claim_message = str(claim_exc)
        assert check_message == claim_message, (
            "check and claim must refuse the same unit with the same message"
        )
        cases += 1

        # 19. defect B, reproduced then fixed. Dispatching a batch one unit at
        # a time claims the first before discovering the second is bad, which
        # is exactly what left UNIT-013 claimed with no worktree and no agent
        # when a real batch dispatch died on its second unit. Checking every
        # unit before claiming any of them is the fix; this proves it against
        # the same two-unit shape rather than asserting it from the code.
        assert cmd_claim(load_all(directory), "UNIT-050", "ada/claude", None) == 0
        try:
            cmd_claim(load_all(directory), "UNIT-051", "ada/claude", None)
            raise AssertionError("the second unit in the batch must still be refused")
        except UnitError:
            pass
        assert load_all(directory)["UNIT-050"][0]["state"] == "claimed", (
            "reproduction: claiming one unit at a time leaves the first claimed "
            "even though the batch as a whole cannot proceed"
        )
        cmd_state(load_all(directory), "UNIT-050", "available")
        before = (directory / "050-first.md").read_bytes()
        try:
            check_claimable(load_all(directory), "UNIT-050", "ada/claude")
            check_claimable(load_all(directory), "UNIT-051", "ada/claude")
            raise AssertionError("the batch check must still refuse UNIT-051")
        except UnitError as exc:
            assert "UNIT-030" in str(exc), "refusal must name the blocking dependency"
        assert load_all(directory)["UNIT-050"][0]["state"] == "available", (
            "fix: checking the whole batch first must leave the first unit "
            "untouched when a later unit in the same batch is invalid"
        )
        assert (directory / "050-first.md").read_bytes() == before, (
            "the batch check must not have written the first unit's file at all"
        )
        cases += 1

        (directory / "099-dupe.md").write_text(
            _sample("UNIT-001", "shared", "available", UNCLAIMED)
        )
        try:
            load_all(directory)
            raise AssertionError("duplicate unit id must be refused")
        except UnitError as exc:
            assert "duplicate" in str(exc), "refusal must name the duplication"
        cases += 1
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"coord self-test passed: {cases} cases")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AlphaLedger unit coordination")
    parser.add_argument("--self-test", action="store_true", help="run built-in checks and exit")
    parser.add_argument("--units-dir", help="override the specs/units directory")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="show the unit registry")
    p_list.add_argument("--lane")
    p_list.add_argument("--state", choices=STATES)
    p_list.add_argument("--owner")

    p_show = sub.add_parser("show", help="print one unit intake")
    p_show.add_argument("unit_id")

    p_claim = sub.add_parser("claim", help="take ownership of an available unit")
    p_claim.add_argument("unit_id")
    p_claim.add_argument("--owner", required=True, help="handle/claude or handle/codex")
    p_claim.add_argument("--branch")

    p_check = sub.add_parser(
        "check", help="ask whether a unit would be claimable, without claiming it"
    )
    p_check.add_argument("unit_id")
    p_check.add_argument("--owner", required=True, help="handle/claude or handle/codex")

    p_review = sub.add_parser("review", help="record a review and its verdict")
    p_review.add_argument("unit_id")
    p_review.add_argument("--by", required=True, help="the reviewer that reported")
    p_review.add_argument("--verdict", required=True, choices=VERDICTS)

    p_state = sub.add_parser("state", help="transition a unit")
    p_state.add_argument("unit_id")
    p_state.add_argument("new_state", choices=STATES)
    p_state.add_argument(
        "--another-pass",
        action="store_true",
        help="reopen a unit that two review rounds have not cleared",
    )

    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.command:
        parser.print_help()
        return 2

    try:
        units = load_all(units_dir(args.units_dir))
        if args.command == "list":
            return cmd_list(units, args.lane, args.state, args.owner)
        if args.command == "show":
            return cmd_show(units, args.unit_id)
        if args.command == "claim":
            return cmd_claim(units, args.unit_id, args.owner, args.branch)
        if args.command == "check":
            return cmd_check(units, args.unit_id, args.owner)
        if args.command == "review":
            return cmd_review(units, args.unit_id, args.by, args.verdict)
        if args.command == "state":
            return cmd_state(units, args.unit_id, args.new_state, args.another_pass)
    except UnitError as exc:
        print(f"[coord] {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
