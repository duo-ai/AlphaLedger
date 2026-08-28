"""Trial registry tests.

The registry's only job is to make it impossible to report the variant that
worked without also reporting the ones that did not. Every test here is about
that asymmetry: registering is cheap and required, and a result cannot exist
without one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alphaledger.data.storage import AppendOnlyStore, StoreCorruptionError
from alphaledger.forecast.registry import (
    ResultAlreadyRecordedError,
    TrialRegistry,
    UnregisteredTrialError,
)

T0 = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def registry(tmp_path: Path, name: str = "trials.jsonl") -> TrialRegistry:
    return TrialRegistry(AppendOnlyStore(tmp_path / name))


def a_config(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {"lookback": 60, "winsor": "0.05"}
    fields.update(overrides)
    return fields


# --- success ------------------------------------------------------------


def test_registering_records_the_configuration_before_any_result_exists(tmp_path: Path) -> None:
    trials = registry(tmp_path)

    trial_id = trials.register(a_config(), "widen the lookback", T0)

    [trial] = trials.trials()
    assert trial.trial_id == trial_id
    assert trial.purpose == "widen the lookback"
    assert trial.registered_at == T0
    assert trial.result is None


def test_a_result_attaches_to_the_trial_that_was_registered_first(tmp_path: Path) -> None:
    trials = registry(tmp_path)
    trial_id = trials.register(a_config(), "widen the lookback", T0)

    trials.record_result(trial_id, {"brier": "0.21"}, T0 + timedelta(hours=1))

    [trial] = trials.trials()
    assert trial.result == {"brier": "0.21"}


def test_two_configurations_get_two_trials_and_the_count_says_two(tmp_path: Path) -> None:
    trials = registry(tmp_path)
    trials.register(a_config(lookback=60), "a", T0)
    trials.register(a_config(lookback=90), "b", T0)

    assert trials.count() == 2


def test_registering_the_same_trial_twice_records_one_fact(tmp_path: Path) -> None:
    """The address is the content, so a retry after an ambiguous write records
    the same trial rather than inventing a second one to answer for."""
    trials = registry(tmp_path)

    path = tmp_path / "trials.jsonl"

    first = trials.register(a_config(), "widen the lookback", T0)
    second = trials.register(a_config(), "widen the lookback", T0)

    assert first == second
    assert trials.count() == 1
    # on disk too: reading collapses duplicates by id, so counting trials alone
    # would pass even while the log grew a line per retry
    assert len(path.read_text().splitlines()) == 1


def test_the_same_configuration_registered_at_two_instants_is_two_trials(tmp_path: Path) -> None:
    """Rerunning a variant later is a second trial, and the multiple testing
    count has to see both."""
    trials = registry(tmp_path)
    trials.register(a_config(), "rerun", T0)
    trials.register(a_config(), "rerun", T0 + timedelta(days=1))

    assert trials.count() == 2


# --- failure ------------------------------------------------------------


def test_a_result_for_an_unregistered_trial_is_refused_naming_the_id(tmp_path: Path) -> None:
    """This is the whole point. If a result could be recorded without a prior
    registration, the registry would only ever hold the variants that worked."""
    trials = registry(tmp_path)

    with pytest.raises(UnregisteredTrialError) as raised:
        trials.record_result("never-registered", {"brier": "0.21"}, T0)

    assert "never-registered" in str(raised.value)
    assert trials.count() == 0


def test_a_second_result_for_one_trial_is_refused_rather_than_overwriting(tmp_path: Path) -> None:
    """Overwriting is how a disappointing first result quietly becomes a better
    second one."""
    trials = registry(tmp_path)
    trial_id = trials.register(a_config(), "widen the lookback", T0)
    trials.record_result(trial_id, {"brier": "0.31"}, T0)

    with pytest.raises(ResultAlreadyRecordedError):
        trials.record_result(trial_id, {"brier": "0.19"}, T0)

    [trial] = trials.trials()
    assert trial.result == {"brier": "0.31"}


def test_an_empty_purpose_is_refused_because_an_unstated_trial_is_not_a_trial(
    tmp_path: Path,
) -> None:
    trials = registry(tmp_path)

    with pytest.raises(ValueError, match="purpose"):
        trials.register(a_config(), "   ", T0)


def test_a_naive_registration_instant_is_refused(tmp_path: Path) -> None:
    trials = registry(tmp_path)

    with pytest.raises(ValueError, match="registered_at"):
        trials.register(a_config(), "widen the lookback", datetime(2026, 8, 28, 12, 0))


def test_a_float_in_a_result_is_refused_because_a_metric_is_recorded_verbatim(
    tmp_path: Path,
) -> None:
    trials = registry(tmp_path)
    trial_id = trials.register(a_config(), "widen the lookback", T0)

    with pytest.raises(TypeError) as raised:
        trials.record_result(trial_id, {"brier": 0.21}, T0)  # type: ignore[dict-item]

    # the field alone is not enough: a generic type check names the same field.
    # The refusal has to say a float is the problem, or the float specific
    # branch could be deleted with nothing noticing
    assert "float" in str(raised.value)
    assert "0.21" in str(raised.value)


def test_a_float_in_a_configuration_is_refused_the_same_way_a_metric_is() -> None:
    """One validator serves both arguments. Testing only the result path would
    let a change that bypassed validation on the configuration path pass."""
    with pytest.raises(TypeError) as raised:
        TrialRegistry(AppendOnlyStore(Path("unused.jsonl"))).register(
            {"winsor": 0.05},  # type: ignore[dict-item]
            "widen the winsor",
            T0,
        )

    assert "float" in str(raised.value)
    assert "0.05" in str(raised.value)


def test_two_results_for_one_trial_on_disk_are_refused_on_read(tmp_path: Path) -> None:
    """`record_result` refuses the second, but two processes can both pass that
    check before either appends. Taking the last one on read would be the same
    overwrite arriving by another route."""
    path = tmp_path / "trials.jsonl"
    store = AppendOnlyStore(path)
    trials = TrialRegistry(store)
    trial_id = trials.register(a_config(), "widen the lookback", T0)
    for brier in ("0.31", "0.05"):
        store.append(
            {
                "kind": "result",
                "trial_id": trial_id,
                "result": {"brier": brier},
                "recorded_at": T0.isoformat(),
            }
        )

    with pytest.raises(StoreCorruptionError, match="two recorded results"):
        TrialRegistry(AppendOnlyStore(path)).trials()


def test_a_result_with_no_registration_on_disk_is_refused_rather_than_hidden(
    tmp_path: Path,
) -> None:
    """An orphan result would otherwise vanish from every count, which reports
    a shorter history than the file holds."""
    path = tmp_path / "trials.jsonl"
    store = AppendOnlyStore(path)
    store.append(
        {
            "kind": "result",
            "trial_id": "never-registered",
            "result": {"brier": "0.05"},
            "recorded_at": T0.isoformat(),
        }
    )

    with pytest.raises(StoreCorruptionError, match="never-registered"):
        TrialRegistry(store).trials()


# --- restart ------------------------------------------------------------


RESTART_SCRIPT = """
import sys
from datetime import UTC, datetime

from alphaledger.data.storage import AppendOnlyStore
from alphaledger.forecast.registry import TrialRegistry

path, purpose = sys.argv[1], sys.argv[2]
trials = TrialRegistry(AppendOnlyStore(path))
print("count_at_start=%d" % trials.count())
moment = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
trial_id = trials.register({"purpose": purpose}, purpose, moment)
if purpose == "abandoned":
    print("registered_without_result")
else:
    trials.record_result(trial_id, {"brier": "0.21"}, moment)
"""


def run_restart(path: Path, purpose: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", RESTART_SCRIPT, str(path), purpose],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_a_registry_reopened_in_another_process_reports_every_earlier_trial(
    tmp_path: Path,
) -> None:
    """A real process boundary. An abandoned trial is the one that must survive,
    because it is the one a dishonest report would leave out."""
    path = tmp_path / "trials.jsonl"

    assert "count_at_start=0" in run_restart(path, "first")
    before = path.read_bytes()
    assert "count_at_start=1" in run_restart(path, "abandoned")
    assert "count_at_start=2" in run_restart(path, "third")

    trials = TrialRegistry(AppendOnlyStore(path)).trials()
    assert [trial.purpose for trial in trials] == ["first", "abandoned", "third"]
    assert [trial.result is None for trial in trials] == [False, True, False]
    assert path.read_bytes().startswith(before)


def test_appending_after_a_restart_does_not_rewrite_the_earlier_lines(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    run_restart(path, "first")
    first_lines = path.read_text().splitlines()

    run_restart(path, "second")

    assert path.read_text().splitlines()[: len(first_lines)] == first_lines
    assert all(json.loads(line) for line in path.read_text().splitlines())


# --- no trade -----------------------------------------------------------


def test_an_empty_registry_reports_zero_trials_rather_than_failing(tmp_path: Path) -> None:
    trials = registry(tmp_path)

    assert trials.trials() == ()
    assert trials.count() == 0


def test_a_registry_whose_file_was_never_written_is_still_readable(tmp_path: Path) -> None:
    trials = registry(tmp_path, name="never-written.jsonl")

    assert trials.count() == 0
    assert not (tmp_path / "never-written.jsonl").exists()
