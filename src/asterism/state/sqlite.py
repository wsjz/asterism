from __future__ import annotations

from pathlib import Path
import sqlite3

from ..models import DigestState, ItemState
from .base import StateBackend


_ITEM_COLUMNS = (
    "source, source_id, relative_path, content_hash, source_updated_at, "
    "last_seen_at, first_seen_at, source_created_at, title"
)
_DIGEST_COLUMNS = "level, period_start, period_end, relative_path, state, generated_at"


class SQLiteStateBackend(StateBackend):
    SCHEMA_VERSION = 2

    def __init__(self, path: Path) -> None:
        resolved = path.resolve(strict=False)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(resolved)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cursor = self.connection
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS item_state (
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                source_updated_at TEXT,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (source, source_id)
            )
            """
        )
        cursor.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = cursor.execute("SELECT version FROM schema_version").fetchone()
        version = int(row[0]) if row else 1
        if version == 1:
            existing = {info[1] for info in cursor.execute("PRAGMA table_info(item_state)")}
            for column in ("first_seen_at TEXT", "source_created_at TEXT", "title TEXT"):
                if column.split()[0] not in existing:
                    cursor.execute(f"ALTER TABLE item_state ADD COLUMN {column}")
            cursor.execute("UPDATE item_state SET first_seen_at = last_seen_at WHERE first_seen_at IS NULL")
            cursor.execute("DELETE FROM schema_version")
            cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (self.SCHEMA_VERSION,))
        elif version != self.SCHEMA_VERSION:
            raise ValueError("unsupported SQLite state schema version")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS digest_state (
                level TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                state TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                PRIMARY KEY (level, period_start)
            )
            """
        )
        cursor.commit()

    # --- items ---------------------------------------------------------------

    def get(self, source: str, source_id: str) -> ItemState | None:
        row = self.connection.execute(
            f"SELECT {_ITEM_COLUMNS} FROM item_state WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        return ItemState(**dict(row)) if row else None

    def save(self, state: ItemState) -> None:
        self.connection.execute(
            f"""
            INSERT INTO item_state ({_ITEM_COLUMNS})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_id) DO UPDATE SET
                relative_path = excluded.relative_path,
                content_hash = excluded.content_hash,
                source_updated_at = excluded.source_updated_at,
                last_seen_at = excluded.last_seen_at,
                first_seen_at = COALESCE(item_state.first_seen_at, excluded.first_seen_at),
                source_created_at = excluded.source_created_at,
                title = excluded.title
            """,
            (
                state.source,
                state.source_id,
                state.relative_path,
                state.content_hash,
                state.source_updated_at,
                state.last_seen_at,
                state.first_seen_at,
                state.source_created_at,
                state.title,
            ),
        )
        self.connection.commit()

    def source_ids(self, source: str) -> set[str]:
        rows = self.connection.execute(
            "SELECT source_id FROM item_state WHERE source = ?", (source,)
        )
        return {str(row[0]) for row in rows}

    def sources(self) -> set[str]:
        return {str(row[0]) for row in self.connection.execute("SELECT DISTINCT source FROM item_state")}

    def items(self, source: str) -> list[ItemState]:
        rows = self.connection.execute(
            f"SELECT {_ITEM_COLUMNS} FROM item_state WHERE source = ? "
            "ORDER BY COALESCE(source_created_at, first_seen_at), source, source_id",
            (source,),
        )
        return [ItemState(**dict(row)) for row in rows]

    def items_between(self, start: str, end: str) -> list[ItemState]:
        rows = self.connection.execute(
            f"SELECT {_ITEM_COLUMNS} FROM item_state "
            "WHERE COALESCE(source_created_at, first_seen_at) >= ? "
            "AND COALESCE(source_created_at, first_seen_at) < ? "
            "ORDER BY COALESCE(source_created_at, first_seen_at), source, source_id",
            (start, end),
        )
        return [ItemState(**dict(row)) for row in rows]

    # --- digests -------------------------------------------------------------

    def get_digest(self, level: str, period_start: str) -> DigestState | None:
        row = self.connection.execute(
            f"SELECT {_DIGEST_COLUMNS} FROM digest_state WHERE level = ? AND period_start = ?",
            (level, period_start),
        ).fetchone()
        return DigestState(**dict(row)) if row else None

    def save_digest(self, digest: DigestState) -> None:
        self.connection.execute(
            f"""
            INSERT INTO digest_state ({_DIGEST_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(level, period_start) DO UPDATE SET
                period_end = excluded.period_end,
                relative_path = excluded.relative_path,
                state = excluded.state,
                generated_at = excluded.generated_at
            """,
            (
                digest.level,
                digest.period_start,
                digest.period_end,
                digest.relative_path,
                digest.state,
                digest.generated_at,
            ),
        )
        self.connection.commit()

    def digests(self, level: str | None = None) -> list[DigestState]:
        if level is None:
            rows = self.connection.execute(
                f"SELECT {_DIGEST_COLUMNS} FROM digest_state ORDER BY level, period_start"
            )
        else:
            rows = self.connection.execute(
                f"SELECT {_DIGEST_COLUMNS} FROM digest_state WHERE level = ? ORDER BY period_start",
                (level,),
            )
        return [DigestState(**dict(row)) for row in rows]

    def close(self) -> None:
        self.connection.close()
