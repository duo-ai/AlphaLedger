#!/usr/bin/env python3
"""One line per dispatch that a session resuming here should know about.

Runs at SessionStart. Silent when nothing has been dispatched, because a hook
that speaks every time trains people to ignore it.

A dispatch survives the session that started it: `codex exec` is a detached
process writing to a log. So a session picking the repository back up needs to
know whether an agent is mid-flight, finished and unread, or died.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def codex_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "codex exec"], capture_output=True, text=True, check=False
    )
    return bool(result.stdout.strip())


def last_event(path: Path) -> tuple[str, str]:
    """The final event kind and the last thing the agent said."""
    kind, said = "", ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            event = json.loads(line)
            kind = event.get("type", kind)
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                said = " ".join(item.get("text", "").split())
    except OSError, json.JSONDecodeError:
        pass
    return kind, said


def main() -> int:
    logdir = Path(".dispatch")
    logs = sorted(logdir.glob("*.jsonl")) if logdir.is_dir() else []
    if not logs:
        return 0

    running = codex_running()
    lines = []
    for path in logs:
        kind, said = last_event(path)
        unit = path.stem
        if kind == "turn.completed":
            state = "finished"
        elif running:
            state = "in flight"
        else:
            state = "ended without completing, check the log"
        detail = f", last said: {said[:90]}" if said and state != "in flight" else ""
        lines.append(f"  {unit}: {state}{detail}")

    if lines:
        print("Codex dispatches in this repository:")
        print("\n".join(lines))
        print("  follow one with: scripts/watch.sh <UNIT-ID>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
