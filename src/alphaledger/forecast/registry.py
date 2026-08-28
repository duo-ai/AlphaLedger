"""Append-only trial registry.

`.claude/rules/20-research-integrity.md` requires every attempted
configuration to be registered before anyone examines its result, and requires
a failed or abandoned trial to stay in the registry. That ordering is the
entire mechanism. A registry that could accept a result without a prior
registration would, in practice, hold only the variants that worked, and the
multiple-testing warning design section 7 asks for would be computed from a
number that had already been filtered by its own outcome.

So two operations are refused rather than accommodated: recording a result for
a trial nobody registered, and recording a second result over the first. The
second matters as much as the first, because overwriting is how a
disappointing result quietly becomes a better one.

The log is append-only and reuses `alphaledger.data.storage.AppendOnlyStore`,
which UNIT-020 built and tested, including its corruption behaviour. That is a
read-only import of another unit's module, not a shared write path: this
registry owns its own file. See the handoff notes for why this deviates from
the intake's stated scope.

Nothing here reads a clock. The registration instant is supplied by the caller,
so a registry can be rebuilt from a recorded run and still say the same thing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, NewType

from alphaledger.data.storage import AppendOnlyStore, StoreCorruptionError
from alphaledger.domain.contracts import require_utc

__all__ = [
    "ResultAlreadyRecordedError",
    "Trial",
    "TrialId",
    "TrialRegistry",
    "UnregisteredTrialError",
]

TrialId = NewType("TrialId", str)

_REGISTERED = "registered"
_RESULT = "result"


class UnregisteredTrialError(ValueError):
    """A result was offered for a trial that was never registered."""


class ResultAlreadyRecordedError(ValueError):
    """A second result was offered for a trial that already has one."""


@dataclass(frozen=True, slots=True)
class Trial:
    """One registered attempt, with its result if it ever got one."""

    trial_id: TrialId
    configuration_hash: str
    purpose: str
    registered_at: datetime
    result: Mapping[str, str] | None


class TrialRegistry:
    """Append-only record of every attempt, including the abandoned ones."""

    def __init__(self, store: AppendOnlyStore) -> None:
        self._store = store

    def register(
        self, configuration: Mapping[str, object], purpose: str, registered_at: datetime
    ) -> TrialId:
        """Record an attempt before its result exists, returning its address.

        Registering the same configuration, purpose, and instant twice records
        one trial. The same configuration registered at a later instant is a
        second trial, because rerunning a variant is another look and the
        multiple-testing count has to see both.
        """
        if not purpose.strip():
            raise ValueError(
                "purpose must say what this trial was testing; an unstated trial cannot be "
                "weighed against the others later"
            )
        moment = require_utc(registered_at, "registered_at")
        configuration_hash = _address(_texts(configuration, "configuration"))
        trial_id = TrialId(
            _address(
                {
                    "configuration_hash": configuration_hash,
                    "purpose": purpose,
                    "registered_at": moment.isoformat(),
                }
            )
        )
        if any(trial.trial_id == trial_id for trial in self.trials()):
            return trial_id
        self._store.append(
            {
                "kind": _REGISTERED,
                "trial_id": trial_id,
                "configuration_hash": configuration_hash,
                "configuration": dict(_texts(configuration, "configuration")),
                "purpose": purpose,
                "registered_at": moment.isoformat(),
            }
        )
        return trial_id

    def record_result(
        self, trial_id: str, result: Mapping[str, object], recorded_at: datetime
    ) -> None:
        """Attach a result to a trial that was registered first."""
        moment = require_utc(recorded_at, "recorded_at")
        known = {trial.trial_id: trial for trial in self.trials()}
        trial = known.get(TrialId(trial_id))
        if trial is None:
            raise UnregisteredTrialError(
                f"{trial_id!r} was never registered. A result must follow a registration, "
                "or the registry holds only the trials that happened to work"
            )
        if trial.result is not None:
            raise ResultAlreadyRecordedError(
                f"{trial_id!r} already has a result. Overwriting one is how a disappointing "
                "result quietly becomes a better one; register a new trial instead"
            )
        self._store.append(
            {
                "kind": _RESULT,
                "trial_id": trial_id,
                "result": dict(_texts(result, "result")),
                "recorded_at": moment.isoformat(),
            }
        )

    def trials(self) -> tuple[Trial, ...]:
        """Every trial ever registered, in registration order."""
        registered: dict[str, Trial] = {}
        results: dict[str, Mapping[str, str]] = {}
        for record in self._store.read_all():
            kind = record.get("kind")
            trial_id = _text(record, "trial_id")
            if kind == _REGISTERED:
                registered[trial_id] = Trial(
                    trial_id=TrialId(trial_id),
                    configuration_hash=_text(record, "configuration_hash"),
                    purpose=_text(record, "purpose"),
                    registered_at=require_utc(
                        datetime.fromisoformat(_text(record, "registered_at")), "registered_at"
                    ),
                    result=None,
                )
            elif kind == _RESULT:
                payload = record.get("result")
                if not isinstance(payload, dict):
                    raise StoreCorruptionError(f"{trial_id}: a result record has no result")
                results[trial_id] = MappingProxyType(
                    {str(key): str(value) for key, value in payload.items()}
                )
            else:
                raise StoreCorruptionError(f"a stored record has an unknown kind {kind!r}")
        return tuple(
            Trial(
                trial_id=trial.trial_id,
                configuration_hash=trial.configuration_hash,
                purpose=trial.purpose,
                registered_at=trial.registered_at,
                result=results.get(trial.trial_id),
            )
            for trial in registered.values()
        )

    def count(self) -> int:
        """How many trials have been registered, worked or not."""
        return len(self.trials())


def _texts(value: Mapping[str, object], field: str) -> Mapping[str, str]:
    """Copy a mapping, allowing only strings and whole numbers.

    A float is refused for the same reason money refuses one: a metric that
    round-trips through binary floating point is not the number that was
    reported, and a registry exists to be quoted from later.
    """
    out: dict[str, str] = {}
    for key, item in dict(value).items():
        if isinstance(item, float):
            raise TypeError(
                f"{field}[{key}] must not be float; record the value as it was reported, "
                f"as a string; got {item!r}"
            )
        if isinstance(item, bool) or not isinstance(item, str | int):
            raise TypeError(
                f"{field}[{key}] must be a string or a whole number; got {type(item).__name__}"
            )
        out[str(key)] = str(item)
    return MappingProxyType(out)


def _address(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(body), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise StoreCorruptionError(f"a stored trial record is missing {field}")
    return value
