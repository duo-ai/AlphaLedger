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
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

STATES = ("available", "claimed", "in_review", "merged", "blocked")

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "available": ("claimed", "blocked"),
    "claimed": ("in_review", "available", "blocked"),
    "in_review": ("merged", "claimed", "blocked"),
    "merged": (),
    "blocked": ("available",),
}

LIST_KEYS = ("depends_on",)
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


def cmd_claim(units: dict, unit_id: str, owner: str, branch: str | None) -> int:
    meta, order, body, path = get(units, unit_id)
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
    slug = path.stem
    meta["state"] = "claimed"
    meta["owner"] = owner
    meta["branch"] = branch or f"feature/{slug}"
    meta["claimed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for key in ("branch", "claimed_at"):
        if key not in order:
            order.append(key)
    write_unit(path, meta, order, body)
    worktree = f"../AlphaLedger-wt/{slug}"
    print(f"claimed {unit_id} for {owner} on branch {meta['branch']}")
    print("\nCommit and push the claim to develop before you start work:")
    print(
        f"  git add {path.as_posix()} && git commit -m 'claim: {unit_id} ({owner})' && git push origin develop"
    )
    print("\nThen create the isolated worktree:")
    print(f"  git worktree add {worktree} -b {meta['branch']} develop")
    if str(meta.get("preferred_runtime", "")) == "claude":
        print(
            f"  cp .claude/settings.local.json {worktree}/.claude/   # untracked: does NOT carry into a worktree"
        )
    return 0


def cmd_state(units: dict, unit_id: str, new_state: str) -> int:
    meta, order, body, path = get(units, unit_id)
    current = str(meta["state"])
    if new_state not in STATES:
        raise UnitError(f"unknown state {new_state!r}; one of {', '.join(STATES)}")
    if new_state not in ALLOWED_TRANSITIONS[current]:
        allowed = ", ".join(ALLOWED_TRANSITIONS[current]) or "nothing (terminal)"
        raise UnitError(f"{unit_id}: {current} -> {new_state} is not allowed; allowed: {allowed}")
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
        cmd_state(load_all(directory), "UNIT-001", "merged")
        assert cmd_claim(load_all(directory), "UNIT-010", "ada/claude", None) == 0
        assert load_all(directory)["UNIT-010"][0]["owner"] == "ada/claude", (
            "dependency gate must open"
        )
        cases += 1

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

    p_state = sub.add_parser("state", help="transition a unit")
    p_state.add_argument("unit_id")
    p_state.add_argument("new_state", choices=STATES)

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
        if args.command == "state":
            return cmd_state(units, args.unit_id, args.new_state)
    except UnitError as exc:
        print(f"[coord] {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
