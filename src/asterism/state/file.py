from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from ..models import DigestState, ItemState
from .base import StateBackend, digest_time_in_range, iter_sorted


class FileStateBackend(StateBackend):
    SCHEMA_VERSION = 2

    def __init__(self, path: Path) -> None:
        self.path = path.resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": self.SCHEMA_VERSION, "sources": {}, "digests": {}}
        with self.path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        version = data.get("schema_version")
        if not isinstance(data.get("sources"), dict):
            raise ValueError("invalid file state: sources must be an object")
        if version == 1:
            data = self._migrate_v1(data)
            self._data = data
            self._flush()
        elif version != self.SCHEMA_VERSION:
            raise ValueError("unsupported file state schema version")
        data.setdefault("digests", {})
        if not isinstance(data["digests"], dict):
            raise ValueError("invalid file state: digests must be an object")
        return data

    @staticmethod
    def _migrate_v1(data: dict[str, Any]) -> dict[str, Any]:
        for rows in data["sources"].values():
            for raw in rows.values():
                raw.setdefault("first_seen_at", raw.get("last_seen_at"))
                raw.setdefault("source_created_at", None)
                raw.setdefault("title", None)
        data["schema_version"] = 2
        data.setdefault("digests", {})
        return data

    # --- items ---------------------------------------------------------------

    def get(self, source: str, source_id: str) -> ItemState | None:
        raw = self._data["sources"].get(source, {}).get(source_id)
        return ItemState(**raw) if raw else None

    def save(self, state: ItemState) -> None:
        sources = self._data["sources"]
        rows = sources.setdefault(state.source, {})
        record = asdict(state)
        previous = rows.get(state.source_id)
        if record["first_seen_at"] is None and previous is not None:
            record["first_seen_at"] = previous.get("first_seen_at")
        rows[state.source_id] = record
        self._flush()

    def source_ids(self, source: str) -> set[str]:
        return set(self._data["sources"].get(source, {}))

    def sources(self) -> set[str]:
        return {name for name, rows in self._data["sources"].items() if rows}

    def items(self, source: str) -> list[ItemState]:
        return iter_sorted(ItemState(**raw) for raw in self._data["sources"].get(source, {}).values())

    def items_between(self, start: str, end: str) -> list[ItemState]:
        return iter_sorted(
            item
            for rows in self._data["sources"].values()
            for item in (ItemState(**raw) for raw in rows.values())
            if digest_time_in_range(item, start, end)
        )

    # --- digests -------------------------------------------------------------

    @staticmethod
    def _digest_key(level: str, period_start: str) -> str:
        return f"{level}:{period_start}"

    def get_digest(self, level: str, period_start: str) -> DigestState | None:
        raw = self._data["digests"].get(self._digest_key(level, period_start))
        return DigestState(**raw) if raw else None

    def save_digest(self, digest: DigestState) -> None:
        self._data["digests"][self._digest_key(digest.level, digest.period_start)] = asdict(digest)
        self._flush()

    def digests(self, level: str | None = None) -> list[DigestState]:
        found = (DigestState(**raw) for raw in self._data["digests"].values())
        return sorted(
            (digest for digest in found if level is None or digest.level == level),
            key=lambda digest: (digest.level, digest.period_start),
        )

    # --- persistence ---------------------------------------------------------

    def _flush(self) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
