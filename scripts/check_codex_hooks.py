#!/usr/bin/env python3
"""Is the Codex PreToolUse guard both trusted and enabled for this project?

Codex records hook trust per project in ~/.codex/config.toml. Two things can go
wrong independently, and only one of them shows up as a stale timestamp:

  1. the hook definition changed, so the recorded hash no longer matches and
     Codex skips the hook;
  2. the entry is present and current but carries `enabled = false`, so Codex
     skips it just as completely.

Verified on 2026-08-28: with an entry present, hash fresh, and enabled false, a
command carrying the live trading host ran at exit 0 inside `codex exec` while
the same string was blocked under Claude Code.

The trust key names the primary clone, so this resolves that path rather than
the current directory. Dispatched agents run inside worktrees, and matching on
the working directory reported "no trust recorded" in exactly the place the
answer matters most.

Exit 0 when the guard will run, 1 when it will not, 2 when it cannot be told.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


def primary_clone() -> Path:
    """The main working copy, even when called from inside a worktree.

    `--git-common-dir` points at the primary clone's .git for every worktree of
    a repository, so its parent is the path Codex recorded trust against.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return Path.cwd().resolve()
    if result.returncode != 0 or not result.stdout.strip():
        return Path.cwd().resolve()
    return Path(result.stdout.strip()).resolve().parent


def main() -> int:
    config = Path.home() / ".codex" / "config.toml"
    if not config.is_file():
        print("no codex config on this machine")
        return 2
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"codex config unreadable: {exc}")
        return 2

    root = primary_clone()
    state = data.get("hooks", {}).get("state", {})
    entries = {k: v for k, v in state.items() if k.startswith(f"{root}/") and "pre_tool_use" in k}
    if not entries:
        print(f"no PreToolUse trust recorded for {root}; run codex there, then /hooks")
        return 1

    for key, entry in sorted(entries.items()):
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            print("PreToolUse hook is trusted but DISABLED")
            print("the guard will not run for dispatched Codex agents")
            print(f"re-enable it: run codex in {root}, then /hooks")
            return 1
        if not entry.get("trusted_hash"):
            print(f"PreToolUse entry carries no trusted hash: {key}")
            return 1
    print("codex PreToolUse guard is trusted and enabled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
