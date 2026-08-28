#!/usr/bin/env python3
"""Follow dispatched Codex runs as readable events.

The dispatcher writes a JSONL event stream per unit. Raw, it is unreadable;
formatted, it is a live view of what each agent is doing.

    scripts/watch.sh                 all agents, one colour each
    scripts/watch.sh UNIT-011        one agent alone
    scripts/watch.sh --split         one tmux pane per agent
    scripts/watch.sh --replay        what already happened, then stop

Two agents interleaved in one stream is hard to read no matter how it is
formatted, so there are two answers. Merged view gives every agent a stable
colour and a short tag, so the eye can follow one thread down the page. Split
view gives each its own pane and stops the interleaving entirely.

Reading the stream is the point. An agent about to stop on a source-of-truth
conflict says so several turns before it exits, which is exactly when a human
can decide whether the specification is wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"

# 256-colour picks that stay distinct on both dark and light terminals
PALETTE = (39, 208, 141, 42, 199, 220, 51, 166)

EVENT_COLOUR = {
    "$": 33,  # command, blue
    "edit": 214,  # file change, amber
    "says": 252,  # message, near-white
    "find": 87,  # search, pale cyan
    "run": 245,
    "end": 245,
}


def tty() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(text: str, code: int | None = None, style: str = "") -> str:
    if not tty():
        return text
    prefix = style
    if code is not None:
        prefix += f"\033[38;5;{code}m"
    return f"{prefix}{text}{RESET}" if prefix else text


def width() -> int:
    return max(60, shutil.get_terminal_size((110, 24)).columns)


def clip(text: str, room: int) -> str:
    flat = " ".join(text.split())
    if room < 8:
        return flat[:room]
    return flat if len(flat) <= room else flat[: room - 1] + "…"


def short(stem: str) -> str:
    """004-frozen-config -> 004"""
    head = stem.split("-", 1)[0]
    return head if head.isdigit() else stem[:4]


class Agent:
    """One dispatched unit: its log, its colour, its short tag."""

    def __init__(self, path: Path, index: int) -> None:
        self.path = path
        self.stem = path.stem
        self.tag = short(self.stem)
        self.colour = PALETTE[index % len(PALETTE)]
        self.handle: object | None = None

    def label(self) -> str:
        return paint(f"● {self.tag:<4}", self.colour, BOLD)


def render(event: dict, agent: Agent, *, clock: bool = True) -> str | None:
    kind = event.get("type", "")
    # The stream carries no event time, so this is when the line was read. That
    # is true while following and false while replaying, so replay omits it
    # rather than printing the same fake instant against every past event.
    stamp = paint(datetime.now().astimezone().strftime("%H:%M:%S"), None, DIM) if clock else ""
    lead = f"{stamp} {agent.label()} " if clock else f"{agent.label()} "
    room = width() - (20 if clock else 11)

    def line(word: str, body: str, tail: str = "") -> str:
        painted = paint(f"{word:<4}", EVENT_COLOUR.get(word, 245))
        pad = room - len(word) - (len(tail) + 2 if tail else 0)
        return f"{lead}{painted} {clip(body, pad)}" + (f"  {tail}" if tail else "")

    if kind == "thread.started":
        return line("run", "run began")
    if kind == "turn.completed":
        usage = event.get("usage", {})
        total = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return line("end", f"run ended, {total:,} tokens")
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
        tail = paint("ok", 42) if code in (0, None) else paint(f"exit {code}", 196)
        return line("$", command, tail)

    if itype == "file_change":
        names = ", ".join(Path(c.get("path", "?")).name for c in item.get("changes") or []) or "?"
        return line("edit", names)

    if itype == "web_search":
        return line("find", str(item.get("query", "")))

    if itype == "agent_message":
        text = " ".join(item.get("text", "").split())
        if not text:
            return None
        head = line("says", text)
        lowered = text.lower()[:160]
        if any(w in lowered for w in ("blocked", "stopping", "conflict", "cannot", "refus")):
            # a stop is what a human most needs to read, so give it the room
            body = clip(text, width() * 3)
            return head + "\n" + paint(f"    {body}", 220)
        return head

    return None


def discover(logdir: Path, unit: str | None) -> list[Agent]:
    logs = sorted(logdir.glob("*.jsonl"))
    if unit:
        number = unit.upper().removeprefix("UNIT-")
        logs = [p for p in logs if p.name.startswith(number)]
    return [Agent(p, i) for i, p in enumerate(logs)]


def split(logdir: Path) -> int:
    """One tmux pane per agent, each following a single unit."""
    agents = discover(logdir, None)
    if not agents:
        print("no dispatch logs to split")
        return 1
    if not shutil.which("tmux"):
        print("tmux is not installed; use scripts/watch.sh <UNIT-ID> in separate terminals")
        return 1

    here = Path(__file__).resolve().parent / "watch.sh"
    inside = bool(os.environ.get("TMUX"))
    session = "alphaledger"

    first, *rest = agents
    if inside:
        subprocess.run(
            ["tmux", "new-window", "-n", "agents", f"bash {here} {first.tag}"], check=False
        )
    else:
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, f"bash {here} {first.tag}"], check=False
        )
    for agent in rest:
        subprocess.run(
            ["tmux", "split-window", "-t", session, f"bash {here} {agent.tag}"], check=False
        )
    subprocess.run(["tmux", "select-layout", "-t", session, "even-vertical"], check=False)
    if not inside:
        os.execvp("tmux", ["tmux", "attach", "-t", session])
    return 0


def follow(agents: list[Agent], replay: bool) -> int:
    for agent in agents:
        agent.handle = agent.path.open(encoding="utf-8", errors="replace")
        if not replay:
            agent.handle.seek(0, 2)
        print(f"{agent.label()} {paint(agent.stem, None, DIM)}")
    if agents:
        print(paint("─" * min(width(), 100), None, DIM))

    try:
        while True:
            idle = True
            for agent in agents:
                for raw in agent.handle:  # type: ignore[union-attr]
                    raw = raw.strip()
                    if not raw.startswith("{"):
                        continue
                    idle = False
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    out = render(event, agent, clock=not replay)
                    if out:
                        print(out, flush=True)
            if replay:
                return 0
            if idle:
                time.sleep(0.4)
    except KeyboardInterrupt:
        print(paint("\nstopped watching; the runs continue", None, DIM))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Follow dispatched Codex runs")
    parser.add_argument("unit", nargs="?", help="UNIT-011, or omit for all")
    parser.add_argument("--replay", action="store_true", help="print history and exit")
    parser.add_argument("--split", action="store_true", help="one tmux pane per agent")
    args = parser.parse_args()

    logdir = Path(".dispatch")
    if not logdir.is_dir():
        print("no .dispatch directory; nothing has been dispatched here")
        return 1
    if args.split:
        return split(logdir)

    agents = discover(logdir, args.unit)
    if not agents:
        print(f"no dispatch log for {args.unit}" if args.unit else "no dispatch logs yet")
        return 1
    return follow(agents, args.replay)


if __name__ == "__main__":
    sys.exit(main())
