"""Finding a phrase again: the two questions that come up while writing."""
import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from asterism.cli import main
from asterism.config import CONFIG_NAME, initialize_vault, load_config
from asterism.digest import DigestBuilder
from asterism.models import SourceItem
from asterism.pipeline import Pipeline
from asterism.search import search, search_notes
from asterism.sources.base import Source
from asterism.state import FileStateBackend


SH = ZoneInfo("Asia/Shanghai")
CONFIG = "state:\n  backend: file\ndigest:\n  timezone: Asia/Shanghai\n"

ITEMS = [
    SourceItem("flomo", "m1", "Desk lighting", "A lamp that does not glare",
               created_at=datetime(2026, 9, 14, 9, 20, tzinfo=SH)),
    SourceItem("flomo", "m2", "Cable routing", "Every cable behind the desk",
               created_at=datetime(2026, 9, 15, 12, 40, tzinfo=SH)),
]


class FakeSource(Source):
    name = "flomo"
    output_name = "flomo"

    def collect(self):
        return ITEMS


def _vault(temporary: str) -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    config = load_config(vault)
    with FileStateBackend(config.state_dir / "manifest.json") as state:
        Pipeline(FakeSource(), state, config.vault).sync()
        DigestBuilder(config, state, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH)).run()
    return config.vault


def _project(vault: Path, *, draft: str, brief: str = "") -> Path:
    folder = vault / "content" / "2026" / "2026-09-22-A piece"
    folder.mkdir(parents=True)
    (folder / "01-project.md").write_text(
        "---\nid: 2026-001\ntitle: A piece\nstatus: making\n---\n", encoding="utf-8"
    )
    (folder / "02-brief.md").write_text(f"# A piece\n\n## Source fragments\n\n> {brief}\n", encoding="utf-8")
    (folder / "03-draft.md").write_text(f"# A piece\n\n{draft}\n", encoding="utf-8")
    return folder


def _json(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main([*argv, "--json"])
    return code, json.loads(out.getvalue())


class SearchTest(unittest.TestCase):
    def test_a_phrase_is_found_in_the_collected_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            hits = search(load_config(vault), "does not glare")
            self.assertEqual(1, len(hits))
            self.assertTrue(hits[0].path.startswith("notes/flomo/origin/"))

    def test_digests_do_not_repeat_every_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            self.assertEqual(1, len(search(config, "does not glare")))
            # the same line is in the rollups, which are their own scope
            self.assertGreaterEqual(len(search(config, "does not glare", scope="digest")), 1)

    def test_content_means_what_was_written_not_the_material_it_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _project(vault, draft="I wrote about glare myself.", brief="A lamp that does not glare")
            hits = search(load_config(vault), "glare", scope="content")
            self.assertEqual(["content/2026/2026-09-22-A piece/03-draft.md"], [h.path for h in hits])

    def test_the_search_is_case_insensitive_and_reports_the_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            hits = search(load_config(vault), "CABLE")
            self.assertTrue(any("cable" in hit.text.lower() for hit in hits))
            self.assertTrue(all(hit.line > 0 for hit in hits))

    def test_an_empty_search_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            with self.assertRaises(ValueError):
                search(load_config(vault), "   ")


class SearchNotesTest(unittest.TestCase):
    def test_front_matter_is_not_searched_unless_asked(self) -> None:
        """A tag or a source name is in every header; the prose that uses it is the answer."""
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            self.assertEqual([], search_notes(config, "flomo"))  # only in `source: "flomo"`
            with_meta = search_notes(config, "flomo", meta=True)
            self.assertEqual(2, len(with_meta))

    def test_one_note_is_one_entry_with_its_date_and_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            notes = search_notes(load_config(vault), "desk")
            self.assertEqual(1, len(notes))  # "behind the desk" once; the other note says lamp
            note = notes[0]
            self.assertEqual("2026-09-15", note.day)
            self.assertEqual("Cable routing", note.title)
            self.assertEqual(1, len(note.lines))
            self.assertTrue(all(hit.path == note.path for hit in note.lines))

    def test_the_limit_counts_notes_not_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            self.assertEqual(1, len(search_notes(config, "e", limit=1)))
            self.assertEqual(2, len(search_notes(config, "e", limit=2)))


class FindCommandTest(unittest.TestCase):
    def test_the_command_lists_notes_with_their_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            from asterism.models import Assignment
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                state.save_assignment(Assignment("flomo", "m1", "used", "2026-09-20T09:00:00+08:00", "2026-001"))
            code, payload = _json("find", "glare", "--vault", str(vault))
            self.assertEqual(0, code)
            self.assertEqual(1, len(payload["notes"]))
            note = payload["notes"][0]
            self.assertEqual("used", note["outcome"])
            self.assertEqual("2026-001", note["project"])
            self.assertEqual("2026-09-14", note["day"])
            self.assertEqual(1, len(note["lines"]))


    def test_the_command_reports_every_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = str(_vault(temporary))
            code, payload = _json("find", "glare", "--vault", vault)
            self.assertEqual(0, code)
            self.assertEqual(1, len(payload["hits"]))
            self.assertEqual("all", payload["scope"])

    def test_a_missing_phrase_is_not_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = str(_vault(temporary))
            code, payload = _json("find", "nothing here", "--vault", vault)
            self.assertEqual(0, code)
            self.assertEqual([], payload["hits"])


if __name__ == "__main__":
    unittest.main()
