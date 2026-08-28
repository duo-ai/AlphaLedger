from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import NoReturn

import pytest

from alphaledger.data.universe import UniverseFloors
from alphaledger.evidence.price_volume import FeatureConfig as ResearchFeatureConfig

COMMITTED_CONFIG = Path(__file__).parents[2] / "config"
CONFIG_FILENAMES = ("universe.toml", "feature.toml", "risk.toml", "session.toml")


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


def test_full_load_preserves_every_value_in_immutable_records_and_hashes_content(
    tmp_path: Path,
) -> None:
    config_api = _config_api()
    directory = _copy_config(tmp_path)

    loaded = config_api.load(directory)

    assert loaded.universe == config_api.UniverseConfig(
        min_prior_close=Decimal("10"),
        min_median_dollar_volume=Decimal("10000000"),
        max_symbols=30,
    )
    assert loaded.feature == config_api.FeatureConfig(
        lookback_sessions=60,
        residual_volatility_sessions=20,
        abnormal_volume_sessions=20,
        atr_sessions=14,
        extreme_sessions=20,
        min_sector_peers=2,
        winsor_lower=-5.0,
        winsor_upper=5.0,
        sector_by_symbol={},
    )
    assert loaded.risk == config_api.RiskConfig(
        maximum_loss_fraction_per_new_trade=Decimal("0.00375"),
        maximum_concurrent_positions=2,
        max_contracts_per_structure=3,
        smoke_test_max_contracts=1,
        require_defined_risk=True,
        require_risk_token=True,
        require_human_paper_arm=True,
        start_at_half_risk=True,
    )
    assert loaded.session == config_api.SessionConfig(
        timezone="America/New_York",
        scheduled_scans=("10:00", "12:30", "15:00"),
        no_new_entry_first_minutes=10,
        no_new_entry_final_minutes=45,
        strategy_allowlist=("bull_call_debit_vertical", "bear_put_debit_vertical"),
        dte_min=7,
        dte_max=21,
    )
    assert len(loaded.frozen_config_hash) == 64
    assert loaded.frozen_config_hash == config_api.config_hash(loaded)
    with pytest.raises(FrozenInstanceError):
        loaded.risk = loaded.risk  # type: ignore[misc]
    with pytest.raises(TypeError):
        loaded.feature.sector_by_symbol["AAPL"] = "technology"  # type: ignore[index]

    changed_directory = _copy_config(tmp_path, "changed-config")
    _replace(changed_directory, "session.toml", "dte_max = 21", "dte_max = 20")
    assert config_api.load(changed_directory).frozen_config_hash != loaded.frozen_config_hash


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


def test_value_outside_its_range_is_rejected_by_the_section_record(tmp_path: Path) -> None:
    config_api = _config_api()
    directory = _copy_config(tmp_path)
    _replace(directory, "universe.toml", "max_symbols = 30", "max_symbols = 31")

    with pytest.raises(ValueError, match="design cap of 30"):
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

    class EnvironmentReadFails(dict[str, str]):
        def __getitem__(self, key: str) -> str:
            pytest.fail(f"loader read environment key {key!r}")

        def get(self, key: str, default: str | None = None) -> str | None:
            pytest.fail(f"loader read environment key {key!r}")

        def __iter__(self):  # type: ignore[no-untyped-def]
            pytest.fail("loader iterated over the process environment")

    def getenv_fails(key: str, default: str | None = None) -> NoReturn:
        pytest.fail(f"loader called getenv for {key!r}")

    monkeypatch.setattr(os, "environ", EnvironmentReadFails())
    monkeypatch.setattr(os, "getenv", getenv_fails)
    monkeypatch.delitem(sys.modules, "alphaledger.config", raising=False)

    config_api = importlib.import_module("alphaledger.config")

    loaded = config_api.load(directory)

    assert loaded.frozen_config_hash == config_api.config_hash(loaded)
