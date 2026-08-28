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
reviewed_by: execution-safety-reviewer
review_verdict: block
reviewed_at: 2026-08-28T23:42:34Z
review_log: [block, block]
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

- 2026-08-29 code review round one, `execution-safety-reviewer` via `codex exec review`.
  Three P1 findings and one P2, every one of them a test that can stay green
  while the invariant it names is broken. The reviewer states AC-1 through AC-6
  are implemented, so this round is about proving the code, not changing it.
  Do not rewrite the loader. Change production code only where a strengthened
  test demonstrates a real defect, and say so in the commit when you do.
  1. P1, `tests/config/test_frozen_config.py` around line 110. The hash-change
     test mutates only `dte_max`, so it cannot tell the full content hash from
     one that omits a universe, feature, or risk field. If a risk cap were left
     out of the hash, the cap could change while the old hash, and an arm bound
     to it, stayed valid. Parameterise a valid mutation of every field and
     assert an invariant-only change fails closed.
  2. P1, same file around line 105. The freeze test assigns to the outer
     `FrozenConfig.risk` attribute only, so it proves nothing about the nested
     records. If `RiskConfig` became mutable a process could load and arm under
     hash H, mutate `max_contracts_per_structure`, and trade the changed cap
     still calling it H. Attempt assignment on the fields of each nested
     section record.
  3. P1, same file around line 227. The environment guard fake subclasses
     `dict`, so inherited `items`, `keys`, `copy`, and `in` read its empty
     storage without ever reaching the overridden methods, and `os.environb` is
     not guarded at all. A loader could take an override through any of those
     and the test would still pass, which means AC-5 is currently unasserted.
     Use a proxy that refuses every mapping operation, and cover the
     byte-oriented API.
  4. P2, same file around line 153. Matching the error text cannot tell
     `UniverseConfig.__post_init__` from a duplicate check in the loader.
     Moving the check into `_load_universe` while letting the public record
     accept 31 would leave the test green. Exercise the invalid public record
     directly, or otherwise assert where the exception came from.
- 2026-08-29 pablo/claude on two things the reviewer raised that are not
  findings to fix here. It named Pydantic v2 as the established alternative to
  the hand-rolled validation, correctly applying the package rule in
  `AGENTS.md`; that is one decision for the whole boundary rather than a change
  to make inside this unit, and the same note is on UNIT-011. It also listed
  the whole pre-gate execution matrix as unverified, which is true and is the
  scope of UNIT-012 onward, not of this unit.
- 2026-08-29 pablo/claude, recorded so it is not rediscovered: this review
  emitted no `VERDICT:` line, although the prompt asks for one and the UNIT-011
  review produced one. The verdict was graded from the findings by the session,
  which is what D-018 puts on the session anyway. `scripts/notable.py` only
  announces a verdict it can see, so a review that omits the line is silent on
  the monitor.

- 2026-08-29 code review round two, `execution-safety-reviewer`, verdict block.
  Two P1 findings. Unlike round one, the first is a defect in production code.
  1. P1, `src/alphaledger/config/__init__.py` around line 391. Canonicalisation
     calls `Decimal.normalize()`, which rounds to the active decimal context
     precision before hashing. Two values of
     `maximum_loss_fraction_per_new_trade` that differ beyond that precision
     load as unequal and hash identically, so a session could keep an arm hash
     while its sizing fraction changed. That is AC-2 and the frozen config hash
     requirement in `AGENTS.md`. Canonicalise every digit without context
     rounding, and add a collision test that fails before the fix.
  2. P1, `tests/config/test_frozen_config.py` around line 232. The assertion
     builds its expected value through the same production class it is
     checking, so if `RiskConfig.__post_init__` turned a cap of 3 into 4, both
     sides would become 4 and the suite would stay green while the runtime cap
     exceeded the committed one. Compare loaded primitive fields against
     independent literals.
- 2026-08-29 pablo/claude, on spending a third round. `coord.py` refused to
  reopen without `--another-pass`, per D-022. The round is justified: both
  findings sit inside the declared globs, and the first is a real hash collision
  on the value the whole config hash exists to pin. Round one produced no
  production change; this one does, and it is a two line change with a test that
  fails without it.
- 2026-08-29 pablo/claude, scope for round three. These two findings are the
  whole of it. The reviewer's pre-gate execution matrix, paper host isolation,
  arm and risk binding, sizing caps, idempotent retries, reconciliation,
  staleness, flattening, and ledger transitions, belongs to UNIT-010 and
  UNIT-012 onward and must not be implemented here.

