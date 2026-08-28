---
id: UNIT-004
title: Load the frozen configuration and hash it
lane: shared
state: claimed
owner: pablo/codex
branch: feature/004-frozen-config
reviewer: execution-safety-reviewer
preferred_runtime: codex
depends_on: [UNIT-001]
paths: src/alphaledger/config/**, tests/config/**, config/**
claimed_at: 2026-08-28T22:06:36Z
---

## Problem

`config/` now holds the operational constants, and already-merged code holds
the same values as dataclass defaults. That is two sources for one value, which
is exactly what `config/README.md` calls a design error. Nothing reads the
files, and nothing produces the hashes the run manifest reserves fields for, so
a frozen run cannot yet be proven frozen.

## Source of truth

- `project-state/DECISIONS.md` D-017 for the split and the test that decides it.
- `config/README.md` for what belongs where.
- `run_manifest.example.yaml` for the hash fields this must populate:
  `model_version`, `feature_version`, `risk_config_hash`, `run_manifest_hash`.
- `.claude/rules/01-safety.md` on not mutating frozen thresholds mid-session.

## Scope

In:

- A loader that reads `config/*.toml` into frozen records this unit defines in
  `alphaledger.config`, one per file. It does not import the research lane's
  `UniverseFloors` or `FeatureConfig`: those live in `data/universe.py` and
  `evidence/price_volume.py`, which are another lane's files, and importing
  across lanes from `src` would couple the config layer to the research one.
  Consumers adapt at their own boundary, in their own units.
- A stable content hash over the loaded configuration, reproducible in another
  process, which is what the arm state and the ledger bind to.
- Rejection of a money value expressed as a TOML float, with the same message
  shape `money()` uses. A float here is the same defect as a float anywhere
  else and must not be silently accepted because TOML permits it.
- A drift test: every value in `config/` equals the corresponding dataclass
  default in merged code. This is what stops the two sources disagreeing while
  both look right. The test imports `data.universe` and `evidence.price_volume`
  to compare, which is fine: a test may read across lanes, and only `src` is
  bound by the import rule.

Out:

- Reading any secret. This module never touches the environment, and a test
  asserts it. Credentials reach the broker adapter, never the config loader.
- Choosing values. Selection on development data is a research activity with a
  trial registry, not a loader concern.
- The arm state and what it binds to (UNIT-013).

## Contract

`alphaledger.config`, importing only from `alphaledger.domain`.

```python
def load(directory: Path = Path("config")) -> FrozenConfig: ...
def config_hash(config: FrozenConfig) -> str: ...
```

`FrozenConfig` is immutable and carries the four sections plus the hash. Two
loads of the same directory in different processes produce the same hash.

The four section records are defined here, not imported. `config/risk.toml` and
`config/session.toml` have no counterpart in merged code at all, so AC-4's
drift check applies only to the two that do, universe and feature. State that
rather than leaving a reader to infer it.

## Acceptance criteria

- AC-1: each file loads into its existing frozen dataclass with no value lost.
- AC-2: the hash is stable across processes and changes when any value changes.
- AC-3: a money field given a TOML float is rejected, naming the field.
- AC-4: every committed value in `universe.toml` and `feature.toml` equals its
  dataclass default in merged code. `risk.toml` and `session.toml` have no
  counterpart yet, so there is nothing to drift from and nothing to check.
- AC-5: the module reads no environment variable. Asserted, not assumed.
- AC-6: an unknown key in a config file is rejected rather than ignored. A
  silently ignored key is how a frozen run stops matching its manifest.

## Test list

- success: a full load produces the expected dataclasses and a stable hash.
- success: the same directory hashed in a subprocess yields the same string.
- failure: a money value written as a TOML float is rejected, naming the field.
- failure: an unknown key is rejected, naming the key.
- failure: a value outside its validated range is rejected by the dataclass
  that already validates it, not by a second check here.
- restart: a hash computed before and after a process restart is identical, so
  an arm bound to it survives a restart.
- no-trade: a missing or unreadable config file halts rather than falling back
  to defaults. Falling back would produce a run whose manifest is a lie.

## Verification

```bash
uv run pytest tests/config -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Notes

Once this lands, the dataclass defaults become redundant. Removing them is a
later narrowing and a separate change; while both exist, AC-4 is what keeps
them honest.

## Handoff notes

- 2026-08-29 pablo/claude: Codex refused this unit on its first real pass and
  was right. The contract said "load into the frozen dataclasses that already
  exist" and named `UniverseFloors` and `FeatureConfig`, which live in the
  research lane, plus risk and session records that do not exist anywhere. A
  spec cannot require importing across lanes from `src` and also forbid it.
  Repaired: the loader defines its own records, and only the drift test reads
  across lanes, which is allowed because the import rule binds `src` alone.
  `spec-analyze` exists to catch exactly this, and was written one step too
  late for this unit.
- 2026-08-29 pablo/claude: `config/**` added to paths. The unit reads those
  files rather than writing them, but it is the only unit that touches them and
  the claim-time path check cannot tell a read from a write. Ownership is the
  honest resolution.
