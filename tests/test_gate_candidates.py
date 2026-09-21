import contextlib
from datetime import date, datetime
import io
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from asterism.cli import main
from asterism.cli import _week
from asterism.config import CONFIG_NAME, initialize_vault, load_config
from asterism.digest import DigestBuilder, parse_label
from asterism.models import SourceItem
from asterism.pipeline import Pipeline
from asterism.projects import ContentProject, load_projects
from asterism.sources.base import Source
from asterism.state import FileStateBackend


SH = ZoneInfo("Asia/Shanghai")
WEEK = "2026-W39"
DIGEST = Path("digest/weekly/2026/2026-W39.md")


class FakeSource(Source):
    name = "flomo"
    output_name = "flomo"

    def __init__(self, items):
        self.items = items

    def collect(self):
        return self.items


def _vault(temporary: str) -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text(
        "state:\n  backend: file\n"
        "digest:\n  timezone: Asia/Shanghai\n  week: { run_on: 3 }\n"
        "content:\n"
        "  pillars:\n"
        "    - { key: vibe-coding, tags: [coding] }\n"
        "    - { key: desk-setup, tags: [desk] }\n",
        encoding="utf-8",
    )
    return load_config(vault).vault


def _seed(vault: Path) -> None:
    items = [
        SourceItem("flomo", "m1", "Verify AI code", "Body one", created_at=datetime(2026, 9, 21, 9, 20, tzinfo=SH), tags=("coding",)),
        SourceItem("flomo", "m2", "Desk lighting", "Body two", created_at=datetime(2026, 9, 22, 12, 40, tzinfo=SH), tags=("desk",)),
        SourceItem("flomo", "m3", "Loose thought", "Body three", created_at=datetime(2026, 9, 22, 22, 10, tzinfo=SH)),
    ]
    config = load_config(vault)
    with FileStateBackend(config.state_dir / "manifest.json") as state:
        Pipeline(FakeSource(items), state, vault).sync()
        DigestBuilder(config, state, now=datetime(2026, 9, 24, 9, 0, tzinfo=SH)).run()


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _tick(vault: Path, needle: str) -> None:
    path = vault / DIGEST
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if needle in line and line.startswith("- [ ]"):
            lines[index] = "- [x]" + line[5:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ProposeTest(unittest.TestCase):
    def test_groups_by_pillar_with_unclassified_last(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault)
            code, out, _ = _run("propose", "--vault", str(vault), "--week", WEEK)
            self.assertEqual(0, code)
            self.assertIn("3 candidate(s) for 2026-W39", out)

            text = (vault / DIGEST).read_text(encoding="utf-8")
            self.assertIn("## Candidates", text)
            self.assertLess(text.index("### vibe-coding"), text.index("### desk-setup"))
            self.assertLess(text.index("### desk-setup"), text.index("### Unclassified"))
            self.assertIn("- [ ] 2026-09-21 [[notes/flomo/Verify AI code|Verify AI code]] <!-- asterism:flomo:m1 -->", text)
            self.assertIn("<!-- asterism:flomo:m3 -->", text)

    def test_refreshing_keeps_ticks_and_survives_a_digest_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault)
            _run("propose", "--vault", str(vault), "--week", WEEK)
            _tick(vault, "asterism:flomo:m2")

            _run("propose", "--vault", str(vault), "--week", WEEK)
            self.assertIn("- [x] 2026-09-22 [[notes/flomo/Desk lighting", (vault / DIGEST).read_text(encoding="utf-8"))

            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                DigestBuilder(config, state, now=datetime(2026, 9, 24, 9, 0, tzinfo=SH)).regenerate(
                    parse_label(WEEK, config.digest)
                )
            text = (vault / DIGEST).read_text(encoding="utf-8")
            self.assertIn("## Candidates", text)
            self.assertIn("- [x] 2026-09-22 [[notes/flomo/Desk lighting", text)
            self.assertEqual(1, text.count("## Candidates"))

    def test_reports_a_missing_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            code, _, err = _run("propose", "--vault", str(vault), "--week", WEEK)
            self.assertEqual(1, code)
            self.assertIn("does not exist yet", err)

    def test_rejects_a_label_that_is_not_a_week(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            code, _, err = _run("propose", "--vault", str(vault), "--week", "2026-09-21")
            self.assertEqual(1, code)
            self.assertIn("not a week", err)


class ApplyTest(unittest.TestCase):
    def test_ticked_candidates_become_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault)
            _run("propose", "--vault", str(vault), "--week", WEEK)
            _tick(vault, "asterism:flomo:m1")

            code, out, _ = _run("apply", "--vault", str(vault), "--week", WEEK)
            self.assertEqual(0, code)
            self.assertIn("Verify AI code", out)

            config = load_config(vault)
            projects = load_projects(config).projects
            self.assertEqual(1, len(projects))
            project = projects[0]
            self.assertEqual(("approved", "vibe-coding"), (project.status, project.pillar))
            self.assertEqual(("notes/flomo/Verify AI code.md",), project.sources)
            brief = (project.directory / "brief.md").read_text(encoding="utf-8")
            self.assertIn("### [[notes/flomo/Verify AI code|Verify AI code]]", brief)
            self.assertIn("2026-09-21 - flomo", brief)
            self.assertIn("> Body one", brief)

            text = (vault / DIGEST).read_text(encoding="utf-8")
            self.assertIn(f"-> [[content/2026/2026-09-", text)
            self.assertIn(f"|{project.id}]]", text)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                assignment = state.get_assignment("flomo", "m1")
            self.assertEqual(("promoted", project.id), (assignment.decision, assignment.project_id))
            self.assertIn(project.title, (config.content_root / "INDEX.md").read_text(encoding="utf-8"))

    def test_applying_twice_creates_nothing_new(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault)
            _run("propose", "--vault", str(vault), "--week", WEEK)
            _tick(vault, "asterism:flomo:m1")
            _run("apply", "--vault", str(vault), "--week", WEEK)

            code, out, _ = _run("apply", "--vault", str(vault), "--week", WEEK)
            self.assertEqual(0, code)
            self.assertIn("No ticked candidates", out)
            self.assertEqual(1, len(load_projects(load_config(vault)).projects))

    def test_a_decided_item_leaves_the_fresh_list_but_keeps_its_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault)
            _run("propose", "--vault", str(vault), "--week", WEEK)
            _tick(vault, "asterism:flomo:m1")
            _run("apply", "--vault", str(vault), "--week", WEEK)

            code, out, _ = _run("propose", "--vault", str(vault), "--week", WEEK)
            self.assertIn("2 candidate(s)", out)
            text = (vault / DIGEST).read_text(encoding="utf-8")
            self.assertIn("asterism:flomo:m1", text)
            self.assertIn("- [x]", text)

    def test_week_counts_what_is_waiting_then_what_is_in_flight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault)
            _run("propose", "--vault", str(vault), "--week", WEEK)
            config = load_config(vault)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                _week(config, date(2026, 9, 22))
            self.assertIn("Week 2026-W39", out.getvalue())
            self.assertIn("Candidates waiting in digest/weekly/2026/2026-W39.md: 3", out.getvalue())

            _tick(vault, "asterism:flomo:m1")
            _run("apply", "--vault", str(vault), "--week", WEEK)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                _week(config, date(2026, 9, 22))
            self.assertIn("In flight (1)", out.getvalue())
            self.assertIn("waiting: start gathering material", out.getvalue())
            self.assertIn("Candidates waiting in digest/weekly/2026/2026-W39.md: 2", out.getvalue())


if __name__ == "__main__":
    unittest.main()
