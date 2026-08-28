#!/usr/bin/env bash
# Resolve a Python interpreter the AlphaLedger tooling can actually run on,
# then exec it with the given arguments.
#
# Why this exists: the guards and scripts/coord.py require 3.11 or newer, but
# on macOS a bare `python3` resolves to /usr/bin/python3, which is 3.9. A hook
# invoked that way dies with a SyntaxError and exits 1. Claude Code and Codex
# treat any exit code other than 2 as a non-blocking error, so the safety guard
# would fail open and silently stop enforcing.
#
# This resolver fails closed instead: with no usable interpreter it exits 2,
# which both runtimes read as a block, per .claude/rules/01-safety.md.
set -uo pipefail

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

for candidate in \
    "$root/.venv/bin/python" \
    python3.14 python3.13 python3.12 python3.11 \
    python3
do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
        >/dev/null 2>&1 || continue
    exec "$candidate" "$@"
done

echo "[AlphaLedger guard] no Python 3.11 or newer found; refusing to run unguarded." >&2
echo "[AlphaLedger guard] install uv and run 'uv sync --frozen', or put a newer python3 on PATH." >&2
exit 2
