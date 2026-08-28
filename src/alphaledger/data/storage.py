"""Append-only storage for point-in-time observations.

The store is a JSON Lines file opened only in append mode. Nothing here can
rewrite or reorder a prior record, which is what makes the recorder's claim
auditable after the fact: the bytes written during a session are still the
bytes on disk at the end of it.

The file is deliberately dumb. It holds no index, no cache, and no notion of
what a record means, so a restart cannot resume from anything but the file
itself. Meaning lives in `alphaledger.data.recorder`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["AppendOnlyStore", "StoreCorruptionError"]

_ENCODING = "utf-8"


class StoreCorruptionError(RuntimeError):
    """A stored line is not a record.

    Raised rather than skipped. A store that silently drops what it cannot
    parse would report a smaller history than it holds, and no later audit
    could tell that from a session that simply recorded less.
    """


class AppendOnlyStore:
    """A JSON Lines file that only ever grows."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def __repr__(self) -> str:
        return f"AppendOnlyStore({str(self._path)!r})"

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: Mapping[str, object]) -> None:
        """Write one record as the last line of the file.

        The file is opened with mode "a" on every call, so a concurrent
        process cannot have its records truncated by this one, and a restart
        reopens rather than recreates. The write is flushed and fsynced
        because a record that exists only in a page cache cannot be produced
        as evidence after a crash.
        """
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding=_ENCODING) as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read_all(self) -> tuple[Mapping[str, Any], ...]:
        """Every record in the order it was appended.

        A missing file is an empty history, not an error: nothing has been
        recorded yet is a legitimate state, and the caller distinguishes it by
        the empty result rather than by an exception.
        """
        if not self._path.exists():
            return ()
        records: list[Mapping[str, Any]] = []
        with self._path.open("r", encoding=_ENCODING) as handle:
            for number, raw in enumerate(handle, start=1):
                line = raw.rstrip("\n")
                if not line:
                    raise StoreCorruptionError(
                        f"{self._path}:{number} is empty; an append-only store never "
                        "writes a blank line, so the file was truncated or edited"
                    )
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise StoreCorruptionError(
                        f"{self._path}:{number} is not a JSON record: {exc}"
                    ) from exc
                if not isinstance(record, dict):
                    raise StoreCorruptionError(
                        f"{self._path}:{number} is a {type(record).__name__}, not a record"
                    )
                records.append(record)
        return tuple(records)
