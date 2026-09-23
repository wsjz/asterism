"""Pulling already-filed material into a project that was thought of later."""
import contextlib
from datetime import date, datetime
import io
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from asterism.cli import main
from asterism.config import CONFIG_NAME, initialize_vault, load_config
from asterism.models import SourceItem
from asterism.pipeline import Pipeline
from asterism.projects import BRIEF_FILE, ProjectError, create_project, gather_into, load_projects
from asterism.sources.base import Source
from asterism.state import FileStateBackend


SH = ZoneInfo("Asia/Shanghai")
CONFIG = "state:\n  backend: file\ndigest:\n  timezone: Asia/Shanghai\n"
TODAY = date(2026, 9, 26)

ITEMS = [
    SourceItem("flomo", "d1", "Week1 26-08-11", "Shipped the SQL API",
               created_at=datetime(2026, 8, 11, 9, 0, tzinfo=SH), parent="Everyday"),
    SourceItem("flomo", "d2", "Week2 26-09-08", "Chased a dry-run bug",
               created_at=datetime(2026, 9, 8, 9, 0, tzinfo=SH), parent="Everyday"),
    SourceItem("flomo", "d3", "Week3 26-09-22", "Rewrote the skill",
               created_at=datetime(2026, 9, 22, 9, 0, tzinfo=SH), parent="Everyday"),
    SourceItem("flomo", "x1", "Desk lighting", "A lamp that does not glare",
               created_at=datetime(2026, 9, 15, 9, 0, tzinfo=SH)),
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
    return config.vault


def _project(vault: Path):
    create_project(load_config(vault), title="September report", status="candidate", today=TODAY)
    return load_projects(load_config(vault)).projects[0]


def _gather(vault: Path, project, **kwargs):
    config = load_config(vault)
    with FileStateBackend(config.state_dir / "manifest.json") as state:
        return gather_into(config, state, project, **kwargs)


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class GatherTest(unittest.TestCase):
    def test_a_folder_of_material_lands_on_the_card_oldest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            result = _gather(vault, _project(vault), prefix="notes/flomo/origin/Everyday")
            self.assertEqual(3, len(result.added))
            self.assertEqual(
                ["Week1 26-08-11.md", "Week2 26-09-08.md", "Week3 26-09-22.md"],
                [Path(source).name for source in result.project.sources],
            )
            self.assertNotIn("Desk lighting.md", [Path(s).name for s in result.project.sources])

    def test_the_window_narrows_what_is_taken(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            result = _gather(
                vault, _project(vault), prefix="notes/flomo/origin/Everyday",
                since=date(2026, 9, 1), until=date(2026, 9, 30),
            )
            self.assertEqual(2, len(result.added))

    def test_the_brief_quotes_everything_that_was_gathered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            result = _gather(vault, _project(vault), prefix="notes/flomo/origin/Everyday")
            brief = (result.project.directory / "02-brief.md").read_text(encoding="utf-8")
            self.assertIn("Shipped the SQL API", brief)
            self.assertIn("Rewrote the skill", brief)
            self.assertIn("## Candidate angles", brief)  # the rest of the brief survives

    def test_gathering_twice_adds_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            first = _gather(vault, _project(vault), prefix="notes/flomo/origin/Everyday")
            again = _gather(vault, first.project, prefix="notes/flomo/origin/Everyday")
            self.assertEqual((), again.added)
            self.assertEqual(3, len(again.already))
            self.assertEqual(3, len(again.project.sources))

    def test_a_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _project(vault)
            result = _gather(vault, project, prefix="notes/flomo/origin/Everyday", dry_run=True)
            self.assertEqual(3, len(result.added))
            self.assertEqual((), load_projects(load_config(vault)).projects[0].sources)

    def test_an_empty_match_says_so_instead_of_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            with self.assertRaises(ProjectError) as raised:
                _gather(vault, _project(vault), prefix="notes/flomo/origin/Nothing")
            self.assertIn("no collected item", str(raised.exception))

    def test_gathering_leaves_the_material_outcome_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _gather(vault, _project(vault), prefix="notes/flomo/origin/Everyday")
            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                self.assertIsNone(state.get_assignment("flomo", "d1"))


class GatherCommandTest(unittest.TestCase):
    def test_the_command_reports_what_it_added(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _project(vault)
            code, out, _ = _run(
                "gather", project.id, "--vault", str(vault),
                "--from", "notes/flomo/origin/Everyday",
            )
            self.assertEqual(0, code)
            self.assertIn("added 3 item(s)", out)
            self.assertEqual(3, len(load_projects(load_config(vault)).projects[0].sources))


if __name__ == "__main__":
    unittest.main()
