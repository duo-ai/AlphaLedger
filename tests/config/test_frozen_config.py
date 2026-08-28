from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from dataclasses import fields as dataclass_fields
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import NoReturn

import pytest

from alphaledger.data.universe import UniverseFloors
from alphaledger.evidence.price_volume import FeatureConfig as ResearchFeatureConfig

COMMITTED_CONFIG = Path(__file__).parents[2] / "config"
CONFIG_FILENAMES = ("universe.toml", "feature.toml", "risk.toml", "session.toml")
HASH_FIELD_MUTATIONS = (
    ("min_prior_close", "universe.toml", 'min_prior_close = "10"', 'min_prior_close = "11"'),
    (
        "min_median_dollar_volume",
        "universe.toml",
        'min_median_dollar_volume = "10000000"',
        'min_median_dollar_volume = "11000000"',
    ),
    ("max_symbols", "universe.toml", "max_symbols = 30", "max_symbols = 29"),
    (
        "lookback_sessions",
        "feature.toml",
        "lookback_sessions = 60",
        "lookback_sessions = 61",
    ),
    (
        "residual_volatility_sessions",
        "feature.toml",
        "residual_volatility_sessions = 20",
        "residual_volatility_sessions = 21",
    ),
    (
        "abnormal_volume_sessions",
        "feature.toml",
        "abnormal_volume_sessions = 20",
        "abnormal_volume_sessions = 21",
    ),
    ("atr_sessions", "feature.toml", "atr_sessions = 14", "atr_sessions = 15"),
    (
        "extreme_sessions",
        "feature.toml",
        "extreme_sessions = 20",
        "extreme_sessions = 21",
    ),
    (
        "min_sector_peers",
        "feature.toml",
        "min_sector_peers = 2",
        "min_sector_peers = 3",
    ),
    ("winsor_lower", "feature.toml", "winsor_lower = -5.0", "winsor_lower = -4.5"),
    ("winsor_upper", "feature.toml", "winsor_upper = 5.0", "winsor_upper = 4.5"),
    (
        "sector_by_symbol",
        "feature.toml",
        "[sector_by_symbol]",
        '[sector_by_symbol]\nAAPL = "technology"',
    ),
    (
        "maximum_loss_fraction_per_new_trade",
        "risk.toml",
        'maximum_loss_fraction_per_new_trade = "0.00375"',
        'maximum_loss_fraction_per_new_trade = "0.004"',
    ),
    (
        "maximum_concurrent_positions",
        "risk.toml",
        "maximum_concurrent_positions = 2",
        "maximum_concurrent_positions = 3",
    ),
    (
        "max_contracts_per_structure",
        "risk.toml",
        "max_contracts_per_structure = 3",
        "max_contracts_per_structure = 4",
    ),
    (
        "start_at_half_risk",
        "risk.toml",
        "start_at_half_risk = true",
        "start_at_half_risk = false",
    ),
    (
        "timezone",
        "session.toml",
        'timezone = "America/New_York"',
        'timezone = "UTC"',
    ),
    (
        "scheduled_scans",
        "session.toml",
        'scheduled_scans = ["10:00", "12:30", "15:00"]',
        'scheduled_scans = ["10:01", "12:30", "15:00"]',
    ),
    (
        "no_new_entry_first_minutes",
        "session.toml",
        "no_new_entry_first_minutes = 10",
        "no_new_entry_first_minutes = 11",
    ),
    (
        "no_new_entry_final_minutes",
        "session.toml",
        "no_new_entry_final_minutes = 45",
        "no_new_entry_final_minutes = 46",
    ),
    (
        "strategy_allowlist",
        "session.toml",
        'strategy_allowlist = ["bull_call_debit_vertical", "bear_put_debit_vertical"]',
        'strategy_allowlist = ["bull_call_debit_vertical"]',
    ),
    ("dte_min", "session.toml", "dte_min = 7", "dte_min = 8"),
    ("dte_max", "session.toml", "dte_max = 21", "dte_max = 22"),
)
INVARIANT_FIELD_MUTATIONS = (
    (
        "smoke_test_max_contracts",
        "smoke_test_max_contracts = 1",
        "smoke_test_max_contracts = 2",
    ),
    ("require_defined_risk", "require_defined_risk = true", "require_defined_risk = false"),
    ("require_risk_token", "require_risk_token = true", "require_risk_token = false"),
    (
        "require_human_paper_arm",
        "require_human_paper_arm = true",
        "require_human_paper_arm = false",
    ),
)
SECTION_FIELDS = (
    ("universe", "min_prior_close"),
    ("universe", "min_median_dollar_volume"),
    ("universe", "max_symbols"),
    ("feature", "lookback_sessions"),
    ("feature", "residual_volatility_sessions"),
    ("feature", "abnormal_volume_sessions"),
    ("feature", "atr_sessions"),
    ("feature", "extreme_sessions"),
    ("feature", "min_sector_peers"),
    ("feature", "winsor_lower"),
    ("feature", "winsor_upper"),
    ("feature", "sector_by_symbol"),
    ("risk", "maximum_loss_fraction_per_new_trade"),
    ("risk", "maximum_concurrent_positions"),
    ("risk", "max_contracts_per_structure"),
    ("risk", "smoke_test_max_contracts"),
    ("risk", "require_defined_risk"),
    ("risk", "require_risk_token"),
    ("risk", "require_human_paper_arm"),
    ("risk", "start_at_half_risk"),
    ("session", "timezone"),
    ("session", "scheduled_scans"),
    ("session", "no_new_entry_first_minutes"),
    ("session", "no_new_entry_final_minutes"),
    ("session", "strategy_allowlist"),
    ("session", "dte_min"),
    ("session", "dte_max"),
)


def _config_api() -> ModuleType:
    try:
        import alphaledger.config as config_api
    except ImportError as exc:
        pytest.fail(f"alphaledger.config is not implemented: {exc}")
    return config_api


def _copy_config(tmp_path: Path, name: str = "config") -> Path:
    destination = tmp_path / name
    shutil.copytree(COMMITTED_CONFIG, destination)
    return destination


def _replace(directory: Path, filename: str, before: str, after: str) -> None:
    path = directory / filename
    original = path.read_text(encoding="utf-8")
    changed = original.replace(before, after, 1)
    assert changed != original, f"fixture replacement did not find {before!r}"
    path.write_text(changed, encoding="utf-8")


def _hash_in_subprocess(directory: Path) -> str:
    script = (
        "import sys; from pathlib import Path; "
        "from alphaledger.config import load; "
        "print(load(Path(sys.argv[1])).frozen_config_hash)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(directory)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_full_load_preserves_every_value_and_hashes_content(tmp_path: Path) -> None:
    config_api = _config_api()
    directory = _copy_config(tmp_path)

    loaded = config_api.load(directory)

    assert (
        loaded.universe.min_prior_close,
        loaded.universe.min_median_dollar_volume,
        loaded.universe.max_symbols,
    ) == (
        Decimal("10"),
        Decimal("10000000"),
        30,
    )
    assert (
        loaded.feature.lookback_sessions,
        loaded.feature.residual_volatility_sessions,
        loaded.feature.abnormal_volume_sessions,
        loaded.feature.atr_sessions,
        loaded.feature.extreme_sessions,
        loaded.feature.min_sector_peers,
        loaded.feature.winsor_lower,
        loaded.feature.winsor_upper,
        dict(loaded.feature.sector_by_symbol),
    ) == (
        60,
        20,
        20,
        14,
        20,
        2,
        -5.0,
        5.0,
        {},
    )
    assert (
        loaded.risk.maximum_loss_fraction_per_new_trade,
        loaded.risk.maximum_concurrent_positions,
        loaded.risk.max_contracts_per_structure,
        loaded.risk.smoke_test_max_contracts,
        loaded.risk.require_defined_risk,
        loaded.risk.require_risk_token,
        loaded.risk.require_human_paper_arm,
        loaded.risk.start_at_half_risk,
    ) == (
        Decimal("0.00375"),
        2,
        3,
        1,
        True,
        True,
        True,
        True,
    )
    assert (
        loaded.session.timezone,
        loaded.session.scheduled_scans,
        loaded.session.no_new_entry_first_minutes,
        loaded.session.no_new_entry_final_minutes,
        loaded.session.strategy_allowlist,
        loaded.session.dte_min,
        loaded.session.dte_max,
    ) == (
        "America/New_York",
        ("10:00", "12:30", "15:00"),
        10,
        45,
        ("bull_call_debit_vertical", "bear_put_debit_vertical"),
        7,
        21,
    )
    assert len(loaded.frozen_config_hash) == 64
    assert loaded.frozen_config_hash == config_api.config_hash(loaded)


def test_regression_cases_cover_every_section_field(tmp_path: Path) -> None:
    config_api = _config_api()
    loaded = config_api.load(_copy_config(tmp_path))
    expected_fields = {
        filename: {field.name for field in dataclass_fields(getattr(loaded, section))}
        for filename, section in (
            ("universe.toml", "universe"),
            ("feature.toml", "feature"),
            ("risk.toml", "risk"),
            ("session.toml", "session"),
        )
    }
    hash_fields = {filename: set() for filename in CONFIG_FILENAMES}
    for field, filename, _, _ in HASH_FIELD_MUTATIONS:
        hash_fields[filename].add(field)
    hash_fields["risk.toml"].update(field for field, _, _ in INVARIANT_FIELD_MUTATIONS)
    immutable_fields = {
        section: {field.name for field in dataclass_fields(getattr(loaded, section))}
        for section in ("universe", "feature", "risk", "session")
    }
    covered_immutable_fields = {
        section: {field for candidate, field in SECTION_FIELDS if candidate == section}
        for section in immutable_fields
    }

    assert hash_fields == expected_fields
    assert covered_immutable_fields == immutable_fields


@pytest.mark.parametrize(
    ("field", "filename", "before", "after"),
    HASH_FIELD_MUTATIONS,
    ids=[case[0] for case in HASH_FIELD_MUTATIONS],
)
def test_every_valid_field_change_changes_the_frozen_hash(
    tmp_path: Path,
    field: str,
    filename: str,
    before: str,
    after: str,
) -> None:
    config_api = _config_api()
    baseline = config_api.load(_copy_config(tmp_path, "baseline"))
    changed_directory = _copy_config(tmp_path, field)
    _replace(changed_directory, filename, before, after)

    changed = config_api.load(changed_directory)

    assert changed.frozen_config_hash != baseline.frozen_config_hash


def test_distinct_high_precision_decimal_values_produce_distinct_frozen_hashes(
    tmp_path: Path,
) -> None:
    config_api = _config_api()
    first_directory = _copy_config(tmp_path, "first")
    second_directory = _copy_config(tmp_path, "second")
    original = 'maximum_loss_fraction_per_new_trade = "0.00375"'
    _replace(
        first_directory,
        "risk.toml",
        original,
        'maximum_loss_fraction_per_new_trade = "0.1234567890123456789012345678901"',
    )
    _replace(
        second_directory,
        "risk.toml",
        original,
        'maximum_loss_fraction_per_new_trade = "0.1234567890123456789012345678902"',
    )

    first = config_api.load(first_directory)
    second = config_api.load(second_directory)

    assert (
        first.risk.maximum_loss_fraction_per_new_trade
        != second.risk.maximum_loss_fraction_per_new_trade
    )
    assert first.frozen_config_hash != second.frozen_config_hash


@pytest.mark.parametrize(
    ("section", "field"),
    SECTION_FIELDS,
    ids=[f"{section}.{field}" for section, field in SECTION_FIELDS],
)
def test_every_nested_section_field_rejects_assignment(
    tmp_path: Path, section: str, field: str
) -> None:
    config_api = _config_api()
    loaded = config_api.load(_copy_config(tmp_path))
    record = getattr(loaded, section)

    with pytest.raises(FrozenInstanceError):
        setattr(record, field, getattr(record, field))


def test_frozen_config_rejects_section_assignment(tmp_path: Path) -> None:
    config_api = _config_api()
    loaded = config_api.load(_copy_config(tmp_path))

    with pytest.raises(FrozenInstanceError):
        loaded.risk = loaded.risk  # type: ignore[misc]


def test_nested_sector_mapping_rejects_item_assignment(tmp_path: Path) -> None:
    config_api = _config_api()
    loaded = config_api.load(_copy_config(tmp_path))

    with pytest.raises(TypeError):
        loaded.feature.sector_by_symbol["AAPL"] = "technology"  # type: ignore[index]


def test_same_directory_hashed_in_a_subprocess_produces_the_same_string(tmp_path: Path) -> None:
    config_api = _config_api()
    directory = _copy_config(tmp_path)

    local_hash = config_api.load(directory).frozen_config_hash

    assert _hash_in_subprocess(directory) == local_hash


def test_money_written_as_a_toml_float_is_rejected_and_names_the_field(tmp_path: Path) -> None:
    config_api = _config_api()
    directory = _copy_config(tmp_path)
    _replace(directory, "universe.toml", 'min_prior_close = "10"', "min_prior_close = 10.0")

    with pytest.raises(TypeError, match="min_prior_close") as raised:
        config_api.load(directory)

    assert "never float" in str(raised.value)


@pytest.mark.parametrize("filename", CONFIG_FILENAMES)
def test_unknown_key_in_any_config_file_is_rejected_and_names_the_key(
    tmp_path: Path, filename: str
) -> None:
    config_api = _config_api()
    directory = _copy_config(tmp_path)
    path = directory / filename
    path.write_text("unexpected_setting = 1\n" + path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected_setting"):
        config_api.load(directory)


def test_public_section_record_rejects_value_above_its_validated_range() -> None:
    config_api = _config_api()

    with pytest.raises(ValueError, match="design cap of 30"):
        config_api.UniverseConfig(
            min_prior_close=Decimal("10"),
            min_median_dollar_volume=Decimal("10000000"),
            max_symbols=31,
        )


@pytest.mark.parametrize(
    ("field", "before", "after"),
    INVARIANT_FIELD_MUTATIONS,
    ids=[case[0] for case in INVARIANT_FIELD_MUTATIONS],
)
def test_invariant_only_field_change_fails_closed_and_names_the_field(
    tmp_path: Path, field: str, before: str, after: str
) -> None:
    config_api = _config_api()
    directory = _copy_config(tmp_path)
    _replace(directory, "risk.toml", before, after)

    with pytest.raises(ValueError, match=field):
        config_api.load(directory)


def test_hash_before_and_after_process_restart_is_identical(tmp_path: Path) -> None:
    _config_api()
    directory = _copy_config(tmp_path)

    before_restart = _hash_in_subprocess(directory)
    after_restart = _hash_in_subprocess(directory)

    assert after_restart == before_restart


@pytest.mark.parametrize("filename", CONFIG_FILENAMES)
@pytest.mark.parametrize("failure", ("missing", "unreadable"))
def test_missing_or_unreadable_file_halts_without_falling_back_to_defaults(
    tmp_path: Path, filename: str, failure: str
) -> None:
    config_api = _config_api()
    directory = _copy_config(tmp_path)
    path = directory / filename
    path.unlink()
    if failure == "unreadable":
        path.mkdir()

    expected = FileNotFoundError if failure == "missing" else OSError
    with pytest.raises(expected):
        config_api.load(directory)


def test_committed_universe_and_feature_values_match_merged_defaults() -> None:
    config_api = _config_api()
    loaded = config_api.load(COMMITTED_CONFIG)
    universe_defaults = UniverseFloors()
    feature_defaults = ResearchFeatureConfig()

    assert loaded.universe.min_prior_close == universe_defaults.min_prior_close
    assert loaded.universe.min_median_dollar_volume == universe_defaults.min_median_dollar_volume
    assert loaded.universe.max_symbols == universe_defaults.max_symbols
    for field in (
        "lookback_sessions",
        "residual_volatility_sessions",
        "abnormal_volume_sessions",
        "atr_sessions",
        "extreme_sessions",
        "min_sector_peers",
        "winsor_lower",
        "winsor_upper",
    ):
        assert getattr(loaded.feature, field) == getattr(feature_defaults, field)
    assert dict(loaded.feature.sector_by_symbol) == dict(feature_defaults.sector_by_symbol)


def test_loading_config_never_reads_the_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _copy_config(tmp_path)

    class EnvironmentReadFails(Mapping[object, object]):
        def __getitem__(self, key: object) -> NoReturn:
            pytest.fail(f"loader read the environment with key {key!r}")

        def __iter__(self) -> NoReturn:
            pytest.fail("loader iterated over the process environment")

        def __len__(self) -> NoReturn:
            pytest.fail("loader measured the process environment")

        def __contains__(self, key: object) -> NoReturn:
            pytest.fail(f"loader checked the environment for key {key!r}")

        def get(self, key: object, default: object = None) -> NoReturn:
            pytest.fail(f"loader read the environment with key {key!r}")

        def keys(self) -> NoReturn:
            pytest.fail("loader read environment keys")

        def items(self) -> NoReturn:
            pytest.fail("loader read environment items")

        def values(self) -> NoReturn:
            pytest.fail("loader read environment values")

        def copy(self) -> NoReturn:
            pytest.fail("loader copied the process environment")

    def getenv_fails(key: object, default: object = None) -> NoReturn:
        pytest.fail(f"loader called an environment getter for {key!r}")

    with monkeypatch.context() as environment_guard:
        environment_guard.setattr(os, "environ", EnvironmentReadFails())
        environment_guard.setattr(os, "environb", EnvironmentReadFails())
        environment_guard.setattr(os, "getenv", getenv_fails)
        environment_guard.setattr(os, "getenvb", getenv_fails)
        environment_guard.delitem(sys.modules, "alphaledger.config", raising=False)

        config_api = importlib.import_module("alphaledger.config")
        loaded = config_api.load(directory)

    assert loaded.frozen_config_hash == config_api.config_hash(loaded)
