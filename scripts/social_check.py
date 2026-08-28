#!/usr/bin/env python3
"""SessionStart reminder: has today's social progress draft been written yet?

Prints one line of context and always exits 0. This never blocks a session and
never writes anything. Drafting is `/social-update` in Claude Code or
`$social-update` in Codex, and posting stays with the human.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    today = date.today().isoformat()
    draft = root / "social" / f"{today}.md"
    if draft.exists():
        return 0

    existing = sorted(
        path.stem for path in (root / "social").glob("*.md") if path.stem != "README"
    )
    if existing:
        print(
            f"No social progress draft for {today} yet (last one: {existing[-1]}). "
            "Run /social-update when there is something real to report."
        )
    else:
        print(
            f"No social progress draft for {today} yet. "
            "Run /social-update when there is something real to report."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
