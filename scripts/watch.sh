#!/usr/bin/env bash
# Follow dispatched Codex runs as readable events.
#
#   scripts/watch.sh                 every active dispatch
#   scripts/watch.sh UNIT-011        one of them
#   scripts/watch.sh --replay        what already happened, then stop
#
# Ctrl-C stops watching. It does not stop the run.
exec bash "$(dirname "$0")/hook_python.sh" "$(dirname "$0")/watch.py" "$@"
