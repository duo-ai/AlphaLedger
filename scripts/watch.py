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
    "plan": 111,  # the agent's todo list, soft violet
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
    """004-frozen-config -> 004, and 004-frozen-config.review -> 004R"""
    base = stem.removesuffix(".review")
    head = base.split("-", 1)[0]
    tag = head if head.isdigit() else base[:4]
    return f"{tag}R" if stem.endswith(".review") else tag


class Agent:
    """One dispatched unit: its log, its colour, its short tag."""

    def __init__(self, path: Path, index: int) -> None:
        self.path = path
        self.stem = path.stem
        self.tag = short(self.stem)
        self.colour = PALETTE[index % len(PALETTE)]
        self.handle = None
        self.inode = -1

    def open(self, *, from_start: bool) -> None:
        self.handle = self.path.open(encoding="utf-8", errors="replace")
        self.inode = self.path.stat().st_ino
        if not from_start:
            self.handle.seek(0, 2)

    def replaced(self) -> bool:
        """True once this log is a different file, or a shorter one.

        A second dispatch of the same unit rotates the previous stream aside and
        writes a new one at the same path. Without this the watcher keeps
        reading the file that was moved away, which never grows again, and goes
        quiet for the rest of the run while looking exactly like an agent that
        is thinking.
        """
        if self.handle is None:
            return False
        try:
            status = self.path.stat()
        except OSError:
            return False
        return status.st_ino != self.inode or status.st_size < self.handle.tell()

    @property
    def is_review(self) -> bool:
        return self.stem.endswith(".review")

    def label(self) -> str:
        # a diamond for a review, a circle for the implementation, so a glance
        # separates the agent doing the work from the one judging it
        mark = "◆" if self.is_review else "●"
        return paint(f"{mark} {self.tag:<4}", self.colour, BOLD)


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
    item = event.get("item", {})
    itype = item.get("type", "")
    # Every other item is rendered when it completes, so its exit code or its
    # result is known. A todo list has no completion event at all, so it is read
    # from the events that do carry it or it is never seen.
    if kind in ("item.started", "item.updated"):
        if itype != "todo_list":
            return None
    elif kind != "item.completed":
        return None

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

    if itype == "todo_list":
        # what the agent thinks it is doing, which is the one signal a reader
        # cannot reconstruct from the commands going past
        steps = item.get("items") or []
        done = sum(1 for s in steps if s.get("completed"))
        current = next((s.get("text", "") for s in steps if not s.get("completed")), "all done")
        return line("plan", f"{done}/{len(steps)}  {current}")

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


def discover(logdir: Path, unit: str | None) -> list[Path]:
    logs = sorted(logdir.glob("*.jsonl"))
    if unit:
        number = unit.upper().removeprefix("UNIT-")
        logs = [p for p in logs if p.name.startswith(number)]
    return logs


def split(logdir: Path) -> int:
    """One tmux pane per agent, each following a single unit."""
    agents = [Agent(p, i) for i, p in enumerate(discover(logdir, None))]
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


def drain(agent: Agent, replay: bool) -> bool:
    """Render whatever the log has gained. True if it had anything at all."""
    moved = False
    while True:
        position = agent.handle.tell()
        raw = agent.handle.readline()
        if not raw:
            return moved
        if not raw.endswith("\n"):
            # the writer is mid-line. Rewind and read it whole next time, rather
            # than parsing half an event and dropping it for good.
            agent.handle.seek(position)
            return moved
        moved = True
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        rendered = render(event, agent, clock=not replay)
        if rendered:
            print(rendered, flush=True)


def follow(logdir: Path, unit: str | None, replay: bool) -> int:
    agents: dict[Path, Agent] = {}

    def adopt(path: Path, from_start: bool) -> None:
        agent = Agent(path, len(agents))
        agent.open(from_start=from_start)
        agents[path] = agent
        print(f"{agent.label()} {paint(agent.stem, None, DIM)}", flush=True)

    for path in discover(logdir, unit):
        adopt(path, replay)
    if agents:
        print(paint("─" * min(width(), 100), None, DIM))

    try:
        while True:
            idle = True
            if not replay:
                # a unit dispatched after this started is worth following too
                for path in discover(logdir, unit):
                    if path not in agents:
                        adopt(path, True)
                for agent in agents.values():
                    if agent.replaced():
                        agent.handle.close()
                        agent.open(from_start=True)
                        print(
                            f"{agent.label()} "
                            f"{paint('log rotated, following the new run', None, DIM)}",
                            flush=True,
                        )
            for agent in list(agents.values()):
                if drain(agent, replay):
                    idle = False
            if replay:
                return 0
            if idle:
                time.sleep(0.4)
    except KeyboardInterrupt:
        print(paint("\nstopped watching; the runs continue", None, DIM))
        return 0


def self_test() -> int:
    """Follow a log across the rotation a second dispatch performs.

    This is a live test rather than a unit one because the failure it guards
    against is entirely about file identity: the watcher kept reading a handle
    on a file that had been moved aside, which never grows again and therefore
    looks exactly like an agent that is still thinking.
    """
    import shutil
    import subprocess
    import tempfile

    cases = 0
    root = Path(tempfile.mkdtemp(prefix="watch-selftest-"))
    try:
        logdir = root / ".dispatch"
        logdir.mkdir()
        log = logdir / "099-probe.jsonl"

        def emit(path: Path, command: str) -> None:
            payload = {
                "type": "item.completed",
                "item": {"type": "command_execution", "command": command, "exit_code": 0},
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\n")

        emit(log, "before rotation")
        out = root / "out.txt"
        with out.open("w", encoding="utf-8") as sink:
            watcher = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve())],
                cwd=root,
                stdout=sink,
                stderr=subprocess.STDOUT,
                env={**os.environ, "NO_COLOR": "1"},
            )
        try:
            time.sleep(1.5)
            emit(log, "still the first file")
            time.sleep(1.0)
            # exactly what scripts/dispatch.sh does when it starts a second pass
            log.rename(logdir / (log.name + ".1"))
            emit(log, "after rotation")
            emit(logdir / "100-late.jsonl", "a later dispatch")
            time.sleep(2.5)
        finally:
            watcher.terminate()
            watcher.wait(timeout=10)

        text = out.read_text(encoding="utf-8", errors="replace")
        assert "still the first file" in text, "must follow the log it opened"
        cases += 1
        assert "after rotation" in text, "must reopen a log that a second dispatch rotated aside"
        cases += 1
        assert "a later dispatch" in text, "must adopt a log created after the watch started"
        cases += 1
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"watch self-test passed: {cases} cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Follow dispatched Codex runs")
    parser.add_argument("unit", nargs="?", help="UNIT-011, or omit for all")
    parser.add_argument("--replay", action="store_true", help="print history and exit")
    parser.add_argument("--split", action="store_true", help="one tmux pane per agent")
    parser.add_argument("--self-test", action="store_true", help="prove the follower works")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    logdir = Path(".dispatch")
    if not logdir.is_dir():
        print("no .dispatch directory; nothing has been dispatched here")
        return 1
    if args.split:
        return split(logdir)

    if not discover(logdir, args.unit):
        print(f"no dispatch log for {args.unit}" if args.unit else "no dispatch logs yet")
        return 1
    return follow(logdir, args.unit, args.replay)


if __name__ == "__main__":
    sys.exit(main())
