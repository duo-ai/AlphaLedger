#!/usr/bin/env python3
"""Follow a dispatched Codex run as readable events.

The dispatcher writes a JSONL event stream per unit. Raw, it is unreadable;
formatted, it is a live view of what the agent is doing: every command it runs
with its exit status, every message it writes, and every file it changes.

    scripts/watch.sh                 follow every active dispatch
    scripts/watch.sh UNIT-011        follow one
    scripts/watch.sh --replay        print what already happened, then stop

Reading the stream is the point. An agent that is about to stop on a
source-of-truth conflict says so in a message several turns before it exits,
and that is exactly when a human can decide whether the spec is wrong.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"


def colour(text: str, code: str) -> str:
    return text if not sys.stdout.isatty() else f"{code}{text}{RESET}"


def width() -> int:
    return max(60, shutil.get_terminal_size((100, 24)).columns)


def clip(text: str, room: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= room else flat[: room - 1] + "…"


def render(event: dict, label: str) -> str | None:
    """One line per event, or a short block for a message. None to skip."""
    kind = event.get("type", "")
    tag = colour(f"{label[:24]:<25}", DIM)
    room = width() - 29

    if kind == "thread.started":
        return f"{tag}{colour('started', CYAN)}"
    if kind == "turn.completed":
        usage = event.get("usage", {})
        total = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return f"{tag}{colour('turn complete', CYAN)} {colour(f'{total:,} tokens', DIM)}"
    if kind != "item.completed":
        return None

    item = event.get("item", {})
    itype = item.get("type", "")

    if itype == "command_execution":
        command = item.get("command", "")
        for prefix in ("/usr/bin/bash -lc ", "bash -lc "):
            if command.startswith(prefix):
                command = command[len(prefix) :].strip("'\"")
        code = item.get("exit_code")
        mark = colour("ok", GREEN) if code in (0, None) else colour(f"exit {code}", RED)
        return f"{tag}{colour('$', BLUE)} {clip(command, room - 6)}  {mark}"

    if itype == "file_change":
        changes = item.get("changes") or []
        names = ", ".join(Path(c.get("path", "?")).name for c in changes) or "?"
        return f"{tag}{colour('edit', YELLOW)} {clip(names, room)}"

    if itype == "web_search":
        return f"{tag}{colour('search', CYAN)} {clip(str(item.get('query', '')), room)}"

    if itype == "agent_message":
        text = " ".join(item.get("text", "").split())
        if not text:
            return None
        head = f"{tag}{colour('says', BOLD)} {clip(text, room)}"
        # a stop is the thing a human most needs to see, so give it room
        if any(w in text.lower()[:120] for w in ("blocked", "stopping", "conflict", "cannot")):
            return head + "\n" + colour("  " + clip(text, width() * 3), YELLOW)
        return head

    return None


def follow(paths: list[Path], replay: bool) -> int:
    handles: dict[Path, object] = {}
    for path in paths:
        handle = path.open(encoding="utf-8", errors="replace")
        if not replay:
            handle.seek(0, 2)
        handles[path] = handle
        print(colour(f"following {path.name}", DIM))

    try:
        while True:
            idle = True
            for path, handle in handles.items():
                for line in handle:
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    idle = False
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    out = render(event, path.stem.replace(".jsonl", ""))
                    if out:
                        print(out, flush=True)
            if replay:
                return 0
            if idle:
                time.sleep(0.4)
    except KeyboardInterrupt:
        print(colour("\nstopped watching; the run continues", DIM))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Follow dispatched Codex runs")
    parser.add_argument("unit", nargs="?", help="UNIT-011, or omit for all")
    parser.add_argument("--replay", action="store_true", help="print history and exit")
    args = parser.parse_args()

    logdir = Path(".dispatch")
    if not logdir.is_dir():
        print("no .dispatch directory; nothing has been dispatched here")
        return 1

    logs = sorted(logdir.glob("*.jsonl"))
    if args.unit:
        number = args.unit.upper().removeprefix("UNIT-")
        logs = [p for p in logs if p.name.startswith(number)]
    if not logs:
        print(f"no dispatch log for {args.unit}" if args.unit else "no dispatch logs yet")
        return 1

    return follow(logs, args.replay)


if __name__ == "__main__":
    sys.exit(main())
