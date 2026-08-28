# Claude Code development harness

This package includes a project-scoped Claude Code harness so implementation
can start with the architecture, safety boundaries, review roles, and session
state already loaded. It is intentionally useful before application code
exists and does not count any competition gate as passed.

## Layout

| Path | Purpose |
|---|---|
| `AGENTS.md` | Canonical, tool-neutral project contract |
| `.claude/CLAUDE.md` | Claude Code imports plus runtime-specific guidance |
| `.claude/settings.json` | Shared permissions and the fail-closed tool hook |
| `.claude/settings.local.json.example` | Empty personal override template; never commit the copy |
| `.claude/agents/` | Six bounded, read-only research/review specialists |
| `.claude/rules/` | Global and path-specific implementation invariants |
| `.claude/skills/` | Explicit bootstrap, gate, smoke-test, handoff, and submission workflows |
| `.claude/hooks/guard.py` | Blocks secrets, destructive commands, live endpoints, and mutating Alpaca MCP calls |
| `project-state/` | Tool-neutral committed checkpoint and decision log loaded each session |
| `.mcp.json` | Pinned, environment-based, market-data-only Alpaca MCP server |
| `run_manifest.example.yaml` | Secret-free Day-0 facts and frozen run configuration template |

## Why this hierarchy

`AGENTS.md` is the canonical contract, while `.claude/CLAUDE.md` imports it and
adds only Claude-specific operation. Status and decisions live in the shared
`project-state/` directory so the Claude and Codex harnesses resume from the
same verified checkpoint.

Specialist agents can inspect, research, and run already-approved checks, but
cannot edit files. The main interactive session remains the sole writer. This
is deliberate: Anthropic's maintained examples distinguish autonomous agents
from user-invoked workflows, and a one-week trading build benefits more from
independent reviews than from several processes modifying one checkout.

Skills with lifecycle effects are manual-only via
`disable-model-invocation: true`. Claude cannot decide on its own to run a
paper smoke test, freeze research, update handoff state, or perform the final
submission audit.

## First use

1. Install a current Claude Code release. Version 2.1.233 or later is required
   for `claude plugin validate .claude/agents`.
2. Install Python 3.14 and `uv`/`uvx`.
3. Start from the repository root. Project settings are read from the directory
   where Claude Code starts:

   ```bash
   cd options-alpha-agent-hackathon
   claude
   ```

4. Review and trust the repository files. Inspect hooks with `/hooks` before
   accepting them.
5. If personal overrides are needed, copy
   `.claude/settings.local.json.example` to
   `.claude/settings.local.json`. Keep model preferences and personal approvals
   there; do not weaken committed deny rules.
6. Put paper API credentials in the process environment or an OS secret
   manager. Do not create a repository `.env` file and never paste values into
   chat:

   ```text
   ALPACA_API_KEY
   ALPACA_SECRET_KEY
   ```

7. Run `claude mcp list`, approve the project server after reviewing
   `.mcp.json`, and confirm the `alpaca` server connects. Its committed
   `ALPACA_TOOLSETS` excludes both account management and trading.
8. Invoke `/bootstrap`. Resolve every failed safety or version check before
   scaffolding application code.

Missing variables do not make `.mcp.json` invalid; Claude Code reports them and
leaves the reference unexpanded. That is preferable to putting credentials in
the file.

## Daily development loop

1. Read the imported status and verify it against the tree.
2. Implement one bounded vertical change in the main session.
3. Run narrow tests and the repository quality gate.
4. Invoke the specialist whose independent coverage matches the risk:
   - research hypothesis: `quant-researcher`;
   - research implementation: `backtest-auditor`;
   - broker/risk/state code: `execution-safety-reviewer`;
   - current Alpaca contract: `alpaca-docs-researcher`;
   - ordinary implementation diff: `code-reviewer`;
   - frozen competition package: `submission-reviewer`.
5. Address or explicitly record material findings.
6. Invoke `/handoff` before ending a meaningful session.

No custom agent is configured as the project-wide default. Launch behavior and
personal model choice therefore remain explicit and are not dependent on host
support for the `agent` setting.

## Permissions and enforcement

The shared settings file auto-allows only read-only git inspection and the
future locked Python quality commands. Dependency changes, the application
paper-smoke command, and git mutations still ask. Known secret reads,
destructive shell actions, and Alpaca mutation tools are denied.

The PreToolUse hook adds contextual enforcement that prompt instructions cannot
provide. It exits with code 2 to block:

- reads or edits of environment, secret, credential, and private-key paths;
- destructive filesystem, system, and git commands;
- shell use of the live Alpaca host or disabled paper mode;
- shell expansion of Alpaca credential variables; and
- mutating Alpaca MCP operations even if someone broadens local MCP scope.

Test it without Claude:

```bash
python3 .claude/hooks/guard.py --self-test
```

The hook is defense in depth, not a complete operating-system sandbox. Review
permissions and commands, run with a low-privilege development account, and
keep real capital credentials out of this project.

## Alpaca separation of duties

The official MCP server supports both data and direct order execution. This
harness intentionally uses only:

```text
assets,stock-data,options-data,corporate-actions,news
```

Do not add `trading` to committed `.mcp.json` or a project agent. G0 account
checks and G1 paper execution go through the application's typed adapter, where
endpoint assertions, risk tokens, idempotency, reconciliation, and ledger
records can be tested deterministically. The version pin is a starting point;
Day-0 schema checks may update it only with a recorded decision and contract
test.

## Manual skills

| Skill | When | Side-effect boundary |
|---|---|---|
| `/bootstrap` | clone or toolchain change | validation/setup only |
| `/research-gate` | before Gate G3 freeze | audit only; cannot arm trading |
| `/paper-smoke dry-run` | before G1 | constructs evidence, no submit |
| `/paper-smoke submit` | one-contract G1 test | exact human acknowledgement plus app-only order path |
| `/handoff` | useful session checkpoint | edits committed state files, no git mutation |
| `/submission-readiness` | G5/G6 | audit only; no submission or broker mutation without a separate request |
| `/social-update` | daily progress post | writes a draft to `social/`; never posts |

Two further skills are model-invocable because they touch no trading state:
`/tdd-workflow` drives a claimed unit from its test list, and
`/verification-loop` runs the quality gate and reports. Every skill above
them stays manual-only.


## Official references used

- Claude Code directory structure: <https://code.claude.com/docs/en/claude-directory>
- Settings and project scope: <https://code.claude.com/docs/en/settings>
- Permissions: <https://code.claude.com/docs/en/permissions>
- Custom subagents: <https://code.claude.com/docs/en/sub-agents>
- Skills: <https://code.claude.com/docs/en/skills>
- Hooks: <https://code.claude.com/docs/en/hooks>
- Project MCP configuration: <https://code.claude.com/docs/en/mcp>
- Project memory and path rules: <https://code.claude.com/docs/en/memory>
- Anthropic agent examples: <https://github.com/anthropics/claude-code/tree/main/plugins>
- Anthropic skill examples: <https://github.com/anthropics/skills>
- Alpaca MCP server: <https://docs.alpaca.markets/us/docs/alpaca-mcp-server>
- Official Alpaca MCP repository: <https://github.com/alpacahq/alpaca-mcp-server>

The harness reflects those sources as reviewed on 2026-08-27. Recheck
version-sensitive fields before the event rather than assuming the files stay
current indefinitely.
