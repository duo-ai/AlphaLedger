#!/usr/bin/env python3
"""Fail-closed PreToolUse guard for secrets, destructive actions, and live trading."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

MUTATING_ALPACA_PREFIXES = (
    "place_",
    "replace_",
    "cancel_",
    "close_",
    "exercise_",
    "do_not_exercise_",
    "update_",
    "create_",
    "delete_",
    "add_",
    "remove_",
)

SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")

DESTRUCTIVE_COMMANDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brm\s+-(?:[^\s]*r[^\s]*f|[^\s]*f[^\s]*r)\b", re.I), "recursive forced deletion"),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.I), "destructive git reset"),
    (re.compile(r"\bgit\s+clean\s+-[^\s]*f", re.I), "destructive git clean"),
    (re.compile(r"\bfind\b[^\n;&|]*\s-delete\b", re.I), "recursive find deletion"),
    (
        re.compile(r"\b(?:mkfs(?:\.[a-z0-9]+)?|shutdown|reboot)\b", re.I),
        "system-destructive command",
    ),
    (re.compile(r"\bdd\s+[^\n;&|]*\bif=", re.I), "raw device copy"),
    (re.compile(r"\bchmod\s+-R\s+777\b", re.I), "unsafe recursive permissions"),
)


def _normalized_path(value: str) -> str:
    return value.replace("\\", "/").lower()


def _sensitive_path(path: str) -> str | None:
    normalized = _normalized_path(path)
    parts = [part for part in normalized.split("/") if part]
    basename = parts[-1] if parts else ""

    if basename == ".env" or basename.startswith(".env."):
        return "environment file"
    if any(part in {"secret", "secrets", "credentials"} for part in parts):
        return "secret or credentials directory"
    if basename in {"id_rsa", "id_ed25519"} or basename.endswith(SENSITIVE_SUFFIXES):
        return "private key or credential file"
    if "credential" in basename or "secret_key" in basename:
        return "credential-like filename"
    return None


GIT_FLOW_PREFIXES = ("feature/", "bugfix/", "release/", "hotfix/", "support/")
GIT_FLOW_BASE_BRANCHES = ("main", "develop")

BRANCH_CREATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgit\s+checkout\s+(?:-[^\s]+\s+)*-b\s+([^\s]+)"),
    re.compile(r"\bgit\s+switch\s+(?:-[^\s]+\s+)*-c\s+([^\s]+)"),
    re.compile(r"\bgit\s+worktree\s+add\s+[^\s]+\s+-b\s+([^\s]+)"),
)

CONVENTIONAL_TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)

# git writes these itself, and the conventional commits spec does not cover them
MERGE_SUBJECT = re.compile(r"^(?:Merge|Revert) ")

CONVENTIONAL_SUBJECT = re.compile(
    r"^(?:" + "|".join(CONVENTIONAL_TYPES) + r")(?:\([a-z0-9._/-]+\))?!?: .+"
)

COMMIT_MESSAGE_ARGUMENT = re.compile(
    r"-m\s+(?:\"((?:[^\"\\]|\\.)*)\"|'((?:[^']|'\\'')*)'|([^\s]+))"
)


def _message_text(match: tuple[str, ...]) -> str:
    return next((group for group in match if group), "")


COMMIT_TELLS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"co-authored-by\s*:[^\n]*(claude|codex|gpt|copilot|anthropic|openai)", re.I),
        "an AI attribution trailer",
    ),
    (re.compile(r"generated with\s*\[?(claude|codex|copilot)", re.I), "an AI generation marker"),
    (re.compile("\U0001f916"), "a robot emoji"),
    (re.compile(r"[\u2014\u2013]"), "an em or en dash"),
)


def _current_branch() -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_violation(command: str) -> str | None:
    if not re.search(r"\bgit\b", command):
        return None

    if re.search(r"\bgit\s+commit\b", command, re.I):
        messages = [_message_text(m) for m in COMMIT_MESSAGE_ARGUMENT.findall(command)]
        message = " ".join(messages)
        for pattern, reason in COMMIT_TELLS:
            if pattern.search(message):
                return f"{reason} in a commit message"
        if (
            messages
            and not MERGE_SUBJECT.match(messages[0])
            and not CONVENTIONAL_SUBJECT.match(messages[0])
        ):
            allowed = ", ".join(CONVENTIONAL_TYPES)
            return (
                f"a commit subject outside conventional commits: {messages[0]!r}. "
                f"Use 'type(scope): subject' with one of: {allowed}"
            )
        if _current_branch() == "main":
            return (
                "a direct commit to main; main takes only --no-ff merges from release/ or hotfix/"
            )

    for pattern in BRANCH_CREATION_PATTERNS:
        for name in pattern.findall(command):
            if name not in GIT_FLOW_BASE_BRANCHES and not name.startswith(GIT_FLOW_PREFIXES):
                allowed = ", ".join(GIT_FLOW_PREFIXES)
                return f"branch name {name!r} outside the git flow prefixes ({allowed})"

    for name in re.findall(r"\bgit\s+branch\s+-[mM]\s+(?:[^\s]+\s+)?([^\s]+)", command):
        if name not in GIT_FLOW_BASE_BRANCHES and not name.startswith(GIT_FLOW_PREFIXES):
            return f"branch rename to {name!r} outside the git flow prefixes"

    if re.search(r"\bgit\s+push\b", command, re.I) and re.search(
        r"(?:--force(?!-with-lease)|\s-f\b)", command
    ):
        return "a force push; use --force-with-lease on your own branch only"

    if (
        re.search(r"\bgit\s+merge\b", command, re.I)
        and "--no-ff" not in command
        and "--squash" not in command
        and _current_branch() in GIT_FLOW_BASE_BRANCHES
    ):
        return "a fast-forward merge into a shared branch; git flow requires --no-ff"

    return None


def _bash_violation(command: str) -> str | None:
    reason = _git_violation(command)
    if reason:
        return reason

    for pattern, reason in DESTRUCTIVE_COMMANDS:
        if pattern.search(command):
            return reason

    if re.search(r"https?://api\.alpaca\.markets\b", command, re.I):
        return "live Alpaca trading endpoint"
    if re.search(r"\bALPACA_PAPER_TRADE\s*=\s*(?:false|0|no|off)\b", command, re.I):
        return "paper-trading mode disabled"
    if re.search(r"\balphaledger\b[^\n;&|]*\s--live\b", command, re.I):
        return "live application mode"
    if re.search(r"\$\{?ALPACA_(?:API_KEY|SECRET_KEY)\}?", command, re.I):
        return "credential expansion in a shell command"
    if re.search(r"(?:^|[\s/])\.env(?:[.\s/]|$)", command, re.I):
        return "shell access to an environment file"
    return None


def violation(payload: dict[str, Any]) -> str | None:
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool_name in {"Read", "Edit", "Write"}:
        path = tool_input.get("file_path")
        if isinstance(path, str):
            reason = _sensitive_path(path)
            if reason:
                return f"{tool_name} of {reason} is forbidden"

    if tool_name in {"Bash", "PowerShell"}:
        command = tool_input.get("command")
        if isinstance(command, str):
            reason = _bash_violation(command)
            if reason:
                return f"{reason} is forbidden"

    if tool_name.startswith("mcp__alpaca__"):
        operation = tool_name.rsplit("__", maxsplit=1)[-1].lower()
        if operation.startswith(MUTATING_ALPACA_PREFIXES):
            return f"mutating Alpaca MCP operation '{operation}' is forbidden"

    return None


def _self_test() -> int:
    cases = (
        ({"tool_name": "Read", "tool_input": {"file_path": "/repo/.env"}}, True),
        ({"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}, True),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "curl https://api.alpaca.markets/v2/account"},
            },
            True,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "curl https://paper-api.alpaca.markets/v2/account"},
            },
            False,
        ),
        ({"tool_name": "mcp__alpaca__place_option_order", "tool_input": {}}, True),
        ({"tool_name": "mcp__alpaca__get_option_chain", "tool_input": {}}, False),
        ({"tool_name": "Read", "tool_input": {"file_path": "/repo/src/app.py"}}, False),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'chore: x' -m 'Co-Authored-By: Claude <a@b>'"},
            },
            True,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'fix(hooks): guard \u2014 tighten regex'"},
            },
            True,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'fix(hooks): tighten the guard regex'"},
            },
            False,
        ),
        ({"tool_name": "Bash", "tool_input": {"command": "git checkout -b wip-thing"}}, True),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git checkout -b feature/010-order-adapter"},
            },
            False,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree add ../wt/x -b feature/020-recorder"},
            },
            False,
        ),
        ({"tool_name": "Bash", "tool_input": {"command": "git push --force origin develop"}}, True),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "grep -b pattern file.py && git status"},
            },
            False,
        ),
        (
            {"tool_name": "Bash", "tool_input": {"command": "git worktree add ../wt/x -b nope"}},
            True,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "cat > f.md <<'X'\nprose \u2014 with a dash\nX\ngit commit -m 'docs: add prose'"
                },
            },
            False,
        ),
        (
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'tidy the guard'"}},
            True,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'fix(hooks): tidy the guard'"},
            },
            False,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'chore(registry): claim UNIT-010'"},
            },
            False,
        ),
        (
            {"tool_name": "Bash", "tool_input": {"command": "git commit --amend --no-edit"}},
            False,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git merge --no-ff feature/x -m 'Merge feature x'"},
            },
            False,
        ),
        (
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'Merge branch develop into feature/x'"},
            },
            False,
        ),
    )
    failures = [
        index
        for index, (payload, expected_block) in enumerate(cases, start=1)
        if bool(violation(payload)) is not expected_block
    ]
    if failures:
        print(f"guard self-test failed: cases {failures}", file=sys.stderr)
        return 1
    print(f"guard self-test passed: {len(cases)} cases")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return _self_test()

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[AlphaLedger guard] blocked: invalid hook input ({exc})", file=sys.stderr)
        return 2

    if not isinstance(payload, dict):
        print("[AlphaLedger guard] blocked: hook input must be an object", file=sys.stderr)
        return 2

    reason = violation(payload)
    if reason:
        print(f"[AlphaLedger guard] blocked: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
