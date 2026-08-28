#!/usr/bin/env python3
"""Emit only the dispatch events a human would act on.

`watch.sh` renders everything, which is right when you are reading along.
This is the opposite: it stays silent while an agent is working and speaks when
something needs a decision. It is meant to feed a monitor, so every line it
prints becomes a notification.

Silence has to mean "still working", so the filter covers every way a run can
end, not just the good one:

  - a stop message, which is the agent refusing to guess. This is the event
    worth interrupting for, because it usually means a specification is wrong
    and a human can fix it in a minute.
  - a turn completing, which means the run is over either way.
  - the process going away without a completed turn, which is a crash and would
    otherwise look exactly like an agent thinking.

New dispatch logs are picked up while running, so a batch dispatched later is
covered without restarting the watch.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

STOP_WORDS = re.compile(
    r"\b(blocked|blocking|stopped|stopping|cannot|conflict|refus|contradict|halt)",
    re.I,
)
LOGDIR = Path(".dispatch")
POLL_SECONDS = 2.0


def say(unit: str, kind: str, detail: str) -> None:
    flat = " ".join(detail.split())
    print(f"{kind} [{unit}] {flat[:600]}", flush=True)
    # a desktop nudge too, when the box has one; never fatal if it does not
    if shutil.which("notify-send"):
        urgency = "critical" if kind == "STOPPED" else "normal"
        subprocess.run(
            ["notify-send", "-u", urgency, f"{kind}: {unit}", flat[:200]],
            check=False,
            capture_output=True,
        )


def codex_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "codex exec"], capture_output=True, text=True, check=False
    )
    return bool(result.stdout.strip())


def main() -> int:
    if not LOGDIR.is_dir():
        print("no .dispatch directory", flush=True)
        return 1

    handles: dict[Path, object] = {}
    inodes: dict[Path, int] = {}
    finished: set[str] = set()
    graded: set[str] = set()
    seen_activity = False

    def adopt(path: Path, *, from_end: bool) -> None:
        handle = path.open(encoding="utf-8", errors="replace")
        if from_end:
            handle.seek(0, 2)
        handles[path] = handle
        inodes[path] = path.stat().st_ino

    def already_finished(path: Path) -> bool:
        """A run that completed before this watch started is not missing.

        Without this, every pre-existing log looks unfinished and is reported
        GONE the moment no codex process is running, which is exactly what
        happened to a run that had ended cleanly hours earlier.
        """
        try:
            return '"type":"turn.completed"' in path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False

    while True:
        # pick up logs from a batch dispatched after this started
        for path in sorted(LOGDIR.glob("*.jsonl")):
            if path not in handles:
                if already_finished(path):
                    finished.add(path.stem)
                adopt(path, from_end=True)
                continue
            # A second dispatch of the same unit rotates the old stream aside
            # and writes a new one at this same path. Reading on through the
            # moved file would stay silent for the whole run, which is the one
            # thing this watch exists to prevent.
            try:
                if path.stat().st_ino == inodes[path]:
                    continue
            except OSError:
                continue
            handles[path].close()
            finished.discard(path.stem)
            adopt(path, from_end=False)

        for path, handle in handles.items():
            unit = path.stem
            for line in handle:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                seen_activity = True
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                kind = event.get("type", "")
                if kind == "turn.completed":
                    usage = event.get("usage", {})
                    total = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                    finished.add(unit)
                    say(unit, "FINISHED", f"run ended, {total:,} tokens")
                    # A review that ends without stating a verdict in either
                    # shape is the one outcome this watch must not pass over in
                    # silence: the findings are there, nothing announces them,
                    # and a review nobody grades is a review that did not happen.
                    if unit.endswith(".review") and unit not in graded:
                        say(unit, "VERDICT", "none stated; grade it from the findings")
                    continue

                if kind != "item.completed":
                    continue
                item = event.get("item", {})
                if item.get("type") != "agent_message":
                    continue
                text = item.get("text", "")
                # A review exists to produce a verdict, so say it the moment it
                # appears rather than waiting for the run to end. It arrives in
                # one of two shapes: the prose line the prompt asks for, or, when
                # `codex exec review --json` answers with a structured payload,
                # an `overall_correctness` field and no prose line at all. Both
                # are the verdict, and a monitor that knew only the first was
                # silent on half the reviews.
                if unit.endswith(".review"):
                    stated = re.search(r"VERDICT:\s*(clear|conditional|block)", text, re.I)
                    if stated:
                        graded.add(unit)
                        say(unit, "VERDICT", stated.group(1).lower())
                        continue
                    scored = re.search(r'"overall_correctness"\s*:\s*"([^"]+)"', text)
                    if scored:
                        graded.add(unit)
                        say(unit, "VERDICT", f"{scored.group(1)} (no VERDICT line; grade it)")
                        continue
                # only the opening matters: a summary often mentions what it did
                # not do, and that is not the agent stopping
                if STOP_WORDS.search(text[:200]):
                    say(unit, "STOPPED", text)

        # a run that vanishes without completing a turn has crashed, and that
        # looks identical to thinking unless someone says so
        if seen_activity and handles and not codex_running():
            pending = sorted({p.stem for p in handles} - finished)
            for unit in pending:
                say(unit, "GONE", "process exited with no completed turn; check the log")
            if pending:
                return 0
            return 0

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
