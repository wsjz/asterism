from pathlib import Path
import tempfile
import unittest

from asterism.models import SourceItem
from asterism.pipeline import Pipeline
from asterism.sources.base import Source
from asterism.state import FileStateBackend


class FakeSource(Source):
    name = "apple_notes"
    output_name = "apple-notes"

    def __init__(self, items: list[SourceItem]) -> None:
        self.items = items

    def collect(self) -> list[SourceItem]:
        return self.items


class PipelineTest(unittest.TestCase):
    def test_incremental_sync_and_missing_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            state = FileStateBackend(vault / "state" / "manifest.json")
            item = SourceItem(
                "apple_notes", "1", "First", "Body",
                parent="Ideas", source_meta={"account": "iCloud"}
            )
            pipeline = Pipeline(FakeSource([item]), state, vault)

            first = pipeline.sync()
            self.assertEqual((1, 0, 0), (first.created, first.updated, first.unchanged))
            self.assertEqual(1, len(list((vault / "notes").rglob("*.md"))))

            second = pipeline.sync()
            self.assertEqual((0, 0, 1), (second.created, second.updated, second.unchanged))

            missing = Pipeline(FakeSource([]), state, vault).sync()
            self.assertEqual(1, missing.missing)
            self.assertEqual(1, len(list((vault / "notes").rglob("*.md"))))

    def test_output_mirrors_parent_hierarchy_and_follows_moves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            state = FileStateBackend(vault / "state" / "manifest.json")
            item = SourceItem("apple_notes", "1", "Desk", "Body", parent="Effeciency/Everyday/Month-2608/Week2")
            Pipeline(FakeSource([item]), state, vault).sync()
            files = list((vault / "notes" / "apple-notes").rglob("*.md"))
            self.assertEqual(1, len(files))
            self.assertEqual(
                ("Effeciency", "Everyday", "Month-2608", "Week2"),
                files[0].relative_to(vault / "notes" / "apple-notes").parts[:-1],
            )
            # moving the note in its source moves the file and keeps the file name
            moved = SourceItem("apple_notes", "1", "Desk", "Body", parent="Archive/2026")
            result = Pipeline(FakeSource([moved]), state, vault).sync()
            self.assertEqual(1, result.updated)
            after = list((vault / "notes" / "apple-notes").rglob("*.md"))
            self.assertEqual(1, len(after))
            self.assertEqual(("Archive", "2026"), after[0].relative_to(vault / "notes" / "apple-notes").parts[:-1])
            self.assertEqual(files[0].name, after[0].name)
            self.assertEqual("notes/apple-notes/Archive/2026/" + after[0].name, state.get("apple_notes", "1").relative_path)

    def test_same_titles_in_one_folder_get_numbered_and_names_stay_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            state = FileStateBackend(vault / "state" / "manifest.json")
            items = [
                SourceItem("apple_notes", "1", "Weekly", "a", parent="Everyday"),
                SourceItem("apple_notes", "2", "Weekly", "b", parent="Everyday"),
                SourceItem("apple_notes", "3", "Weekly", "c", parent="Other"),
            ]
            Pipeline(FakeSource(items), state, vault).sync()
            everyday = sorted(p.name for p in (vault / "notes" / "apple-notes" / "Everyday").glob("*.md"))
            self.assertEqual(["Weekly (2).md", "Weekly.md"], everyday)
            self.assertEqual(["Weekly.md"], [p.name for p in (vault / "notes" / "apple-notes" / "Other").glob("*.md")])
            # a later sync with a new same-titled note and a renamed old one keeps existing names
            later = [
                SourceItem("apple_notes", "1", "Weekly renamed", "a", parent="Everyday"),
                SourceItem("apple_notes", "2", "Weekly", "b", parent="Everyday"),
                SourceItem("apple_notes", "4", "Weekly", "d", parent="Everyday"),
            ]
            Pipeline(FakeSource(later), state, vault).sync()
            everyday = sorted(p.name for p in (vault / "notes" / "apple-notes" / "Everyday").glob("*.md"))
            self.assertEqual(["Weekly (2).md", "Weekly (3).md", "Weekly.md"], everyday)
            self.assertEqual("notes/apple-notes/Everyday/Weekly.md", state.get("apple_notes", "1").relative_path)

    def test_unsafe_parent_segments_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            state = FileStateBackend(vault / "state" / "manifest.json")
            item = SourceItem("apple_notes", "1", "T", "B", parent="../..//etc/passwd/. /weird:name|x")
            Pipeline(FakeSource([item]), state, vault).sync()
            files = list((vault / "notes" / "apple-notes").rglob("*.md"))
            self.assertEqual(1, len(files))
            parts = files[0].relative_to(vault / "notes" / "apple-notes").parts[:-1]
            self.assertEqual(("etc", "passwd", "weird-name-x"), parts)

    def test_dry_run_does_not_write_files_or_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            state = FileStateBackend(vault / "state" / "manifest.json")
            item = SourceItem("apple_notes", "1", "First", "Body", parent="Ideas")
            result = Pipeline(FakeSource([item]), state, vault).sync(dry_run=True)
            self.assertEqual(1, result.created)
            self.assertFalse((vault / "notes").exists())
            self.assertEqual(set(), state.source_ids("apple_notes"))

    def test_source_controls_output_directory_and_tags(self) -> None:
        class FakeFlomoSource(FakeSource):
            name = "flomo"
            output_name = "flomo"

        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            state = FileStateBackend(vault / "state" / "manifest.json")
            item = SourceItem(
                source="flomo",
                source_id="memo-1",
                title=None,
                content_text="A small thought.",
                tags=("product/ideas", "draft"),
            )

            result = Pipeline(FakeFlomoSource([item]), state, vault).sync()

            self.assertEqual(1, result.created)
            files = list((vault / "notes" / "flomo").glob("*.md"))
            self.assertEqual(1, len(files))
            rendered = files[0].read_text(encoding="utf-8")
            self.assertIn('tags: ["product/ideas", "draft"]', rendered)
            self.assertIn("parent: null", rendered)


if __name__ == "__main__":
    unittest.main()
