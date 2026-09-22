import dataclasses
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from asterism.models import Assignment, DigestState, ItemState
from asterism.state import FileStateBackend, SQLiteStateBackend


def _item(source_id: str, seen: str, created: str | None = None, source: str = "apple_notes") -> ItemState:
    return ItemState(
        source, source_id, f"notes/{source}/{source_id}.md", "sha256:abc", None, seen,
        first_seen_at=seen, source_created_at=created, title=f"Title {source_id}",
    )


class StateBackendContract:
    backend_type: type
    filename: str

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            backend = self.backend_type(Path(temporary) / self.filename)
            value = _item("note-1", "2026-01-01T00:00:00+00:00")
            backend.save(value)
            self.assertEqual(value, backend.get("apple_notes", "note-1"))
            self.assertEqual({"note-1"}, backend.source_ids("apple_notes"))
            self.assertEqual({"apple_notes"}, backend.sources())
            backend.close()

    def test_first_seen_is_preserved_across_saves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            backend = self.backend_type(Path(temporary) / self.filename)
            backend.save(_item("n", "2026-01-01T00:00:00+00:00"))
            later = dataclasses.replace(_item("n", "2026-01-02T00:00:00+00:00"), first_seen_at=None)
            backend.save(later)
            stored = backend.get("apple_notes", "n")
            self.assertEqual("2026-01-02T00:00:00+00:00", stored.last_seen_at)
            self.assertEqual("2026-01-01T00:00:00+00:00", stored.first_seen_at)
            backend.close()

    def test_items_between_uses_created_then_first_seen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            backend = self.backend_type(Path(temporary) / self.filename)
            backend.save(_item("a", "2026-09-25T00:00:00+00:00", "2026-09-21T09:20:00+08:00"))
            backend.save(_item("b", "2026-09-22T00:00:00+00:00"))
            backend.save(_item("c", "2026-09-30T00:00:00+00:00", "2026-09-30T00:00:00+00:00", source="flomo"))
            inside = backend.items_between("2026-09-21", "2026-09-23")
            self.assertEqual(["a", "b"], [item.source_id for item in inside])
            self.assertEqual(["a", "b"], [item.source_id for item in backend.items("apple_notes")])
            backend.close()

    def test_digest_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            backend = self.backend_type(Path(temporary) / self.filename)
            digest = DigestState("flomo", "day", "2026-09-21", "2026-09-21", "notes/flomo/digest/daily/2026/2026-09-21.md", "open", "2026-09-21T10:00:00+08:00")
            backend.save_digest(digest)
            self.assertEqual(digest, backend.get_digest("flomo", "day", "2026-09-21"))
            backend.save_digest(dataclasses.replace(digest, state="closed", generated_at="2026-09-22T00:00:00+08:00"))
            self.assertEqual("closed", backend.get_digest("flomo", "day", "2026-09-21").state)
            backend.save_digest(DigestState("flomo", "week", "2026-09-18", "2026-09-24", "notes/flomo/digest/weekly/2026/2026-W39.md", "open", "x"))
            backend.save_digest(dataclasses.replace(digest, source="cubox"))
            self.assertEqual(["cubox", "flomo", "flomo"], [d.source for d in backend.digests()])
            self.assertEqual(1, len(backend.digests("flomo", "week")))
            self.assertEqual(1, len(backend.digests("cubox")))
            self.assertIsNone(backend.get_digest("cubox", "week", "2026-09-18"))
            backend.close()

    def test_assignments_are_recorded_and_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            backend = self.backend_type(Path(temporary) / self.filename)
            self.assertIsNone(backend.get_assignment("flomo", "m1"))
            backend.save_assignment(Assignment("flomo", "m1", "used", "2026-09-22T10:00:00+08:00", "2026-001"))
            backend.save_assignment(Assignment("flomo", "m2", "later", "2026-09-22T10:01:00+08:00"))
            stored = backend.get_assignment("flomo", "m1")
            self.assertEqual(("used", "2026-001"), (stored.decision, stored.project_id))
            self.assertTrue(stored.is_dealt_with)
            self.assertFalse(backend.get_assignment("flomo", "m2").is_dealt_with)
            self.assertEqual(["m1", "m2"], [a.source_id for a in backend.assignments()])
            self.assertEqual(["m2"], [a.source_id for a in backend.assignments("later")])
            backend.save_assignment(Assignment("flomo", "m2", "used", "2026-09-23T00:00:00+08:00", "2026-002"))
            self.assertEqual("used", backend.get_assignment("flomo", "m2").decision)
            self.assertEqual([], backend.assignments("later"))
            backend.close()

    def test_rejects_an_unusable_decision(self) -> None:
        with self.assertRaises(ValueError):
            Assignment("flomo", "m", "maybe", "2026-09-22T10:00:00+08:00")
        with self.assertRaises(ValueError):
            Assignment("flomo", "m", "used", "2026-09-22T10:00:00+08:00")


class FileStateTest(StateBackendContract, unittest.TestCase):
    backend_type = FileStateBackend
    filename = "manifest.json"

    def test_migrates_schema_1(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / self.filename
            path.write_text(json.dumps({
                "schema_version": 1,
                "sources": {"flomo": {"m1": {
                    "source": "flomo", "source_id": "m1", "relative_path": "notes/flomo/origin/m1.md",
                    "content_hash": "sha256:x", "source_updated_at": None,
                    "last_seen_at": "2026-09-01T00:00:00+00:00",
                }}},
            }))
            backend = FileStateBackend(path)
            item = backend.get("flomo", "m1")
            self.assertEqual("2026-09-01T00:00:00+00:00", item.first_seen_at)
            self.assertIsNone(item.title)
            self.assertEqual(4, json.loads(path.read_text())["schema_version"])
            backend.close()


class SQLiteStateTest(StateBackendContract, unittest.TestCase):
    backend_type = SQLiteStateBackend
    filename = "state.sqlite"

    def test_migrates_schema_1(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / self.filename
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE item_state (source TEXT NOT NULL, source_id TEXT NOT NULL, "
                "relative_path TEXT NOT NULL, content_hash TEXT NOT NULL, source_updated_at TEXT, "
                "last_seen_at TEXT NOT NULL, PRIMARY KEY (source, source_id))"
            )
            connection.execute(
                "INSERT INTO item_state VALUES ('flomo', 'm1', 'notes/flomo/origin/m1.md', 'sha256:x', NULL, '2026-09-01T00:00:00+00:00')"
            )
            connection.commit()
            connection.close()
            backend = SQLiteStateBackend(path)
            item = backend.get("flomo", "m1")
            self.assertEqual("2026-09-01T00:00:00+00:00", item.first_seen_at)
            self.assertIsNone(item.source_created_at)
            self.assertEqual([], backend.assignments())
            backend.close()
            # reopening must not migrate twice or fail
            SQLiteStateBackend(path).close()

    def test_migrates_schema_2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / self.filename
            first = SQLiteStateBackend(path)
            first.save(_item("n", "2026-09-01T00:00:00+00:00"))
            first.connection.execute("DELETE FROM schema_version")
            first.connection.execute("INSERT INTO schema_version (version) VALUES (2)")
            first.connection.execute("DROP TABLE assignment")
            first.connection.execute("DROP TABLE digest_state")
            first.connection.commit()
            first.close()

            backend = SQLiteStateBackend(path)
            self.assertEqual([], backend.assignments())
            self.assertEqual("n", backend.get("apple_notes", "n").source_id)
            backend.close()


if __name__ == "__main__":
    unittest.main()
