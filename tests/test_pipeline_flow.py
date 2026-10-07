"""The whole flow, one piece from collected notes to a recorded publication."""
import contextlib
from datetime import date, datetime
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
from asterism.projects import BRIEF_FILE, load_projects
from asterism.sources.base import Source
from asterism.state import FileStateBackend


SH = ZoneInfo("Asia/Shanghai")
CONFIG = (
    "state:\n  backend: file\n"
    "digest:\n  timezone: Asia/Shanghai\n  week: { run_on: 3 }\n"
    "content:\n"
    "  pillars: [{ key: desk-setup, tags: [desk] }]\n"
    "  platforms: [blog, zhihu]\n"
)

ITEMS = [
    SourceItem("flomo", "m1", "Desk lighting", "A lamp that does not glare",
               created_at=datetime(2026, 9, 14, 9, 20, tzinfo=SH), tags=("desk",)),
    SourceItem("flomo", "m2", "Cable routing", "Every cable behind the desk",
               created_at=datetime(2026, 9, 15, 12, 40, tzinfo=SH), tags=("desk",)),
]


class FakeSource(Source):
    name = "flomo"
    output_name = "flomo"

    def collect(self):
        return ITEMS


def _json(*argv: str) -> tuple[int, dict]:
    """Run a command in JSON mode and parse stdout.

    stderr is captured separately on purpose: warnings from unrelated tests are
    written there and would otherwise be parsed as part of the object.
    """
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main([*argv, "--json"])
    return code, json.loads(out.getvalue())


class FlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        vault = Path(self.temporary.name) / "vault"
        initialize_vault(vault, "file")
        (vault / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
        config = load_config(vault)
        with FileStateBackend(config.state_dir / "manifest.json") as state:
            Pipeline(FakeSource(), state, config.vault).sync()
            DigestBuilder(config, state, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH)).run()
        self.vault = config.vault
        self.v = str(config.vault)

    def _project(self):
        return load_projects(load_config(self.vault)).projects[0]

    def test_a_topic_travels_from_sorting_to_a_recorded_publication(self) -> None:
        # sort: both fragments become one topic
        _code, sheet = _json("propose", "--vault", self.v)
        path = self.vault / sheet["sheet"]
        lines = path.read_text(encoding="utf-8").splitlines()
        moved = [line for line in lines if "[[notes/" in line]
        for line in moved:
            lines.remove(line)
        index = next(i for i, line in enumerate(lines) if line.endswith(" used"))
        lines[index + 4 : index + 4] = ["### A tidy desk", ""] + [m.lstrip() for m in moved] + [""]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        code, applied = _json("apply", "--vault", self.v)
        self.assertEqual(0, code)
        self.assertEqual(1, len(applied["created"]))

        project = self._project()
        self.assertEqual("candidate", project.status)
        self.assertEqual(2, len(project.sources))

        # gate 1: asking does not pass it
        code, offered = _json("confirm", project.id, "--vault", self.v)
        self.assertEqual(1, code)
        self.assertFalse(offered["confirmed"])
        self.assertEqual("candidate", self._project().status)

        code, _ = _json("confirm", project.id, "--vault", self.v, "--angle", "1",
                        "--promise", "tidy the desk in one afternoon")
        self.assertEqual(0, code)
        self.assertEqual("making", self._project().status)

        # more material, filed earlier, pulled in afterwards
        code, gathered = _json("gather", project.id, "--vault", self.v,
                               "--from", "notes/flomo/origin")
        self.assertEqual(0, code)
        self.assertEqual([], gathered["added"])  # both are already on the card

        # the writing is the writer's: nothing here generates it
        (project.directory / "03-draft.md").write_text("# A tidy desk\n\nProse.\n", encoding="utf-8")

        # gate 2
        code, accepted = _json("accept", project.id, "--vault", self.v)
        self.assertEqual(0, code)
        self.assertEqual("ready", accepted["status"])

        # platforms, then gate 3
        code, _ = _json("set", project.id, "--vault", self.v, "--platform", "blog", "--platform", "zhihu")
        self.assertEqual(0, code)
        code, published = _json("publish", project.id, "--vault", self.v,
                                "--url", "blog=https://example.test/desk")
        self.assertEqual(0, code)
        self.assertEqual("published", published["status"])
        self.assertEqual("https://example.test/desk", published["published"]["blog"]["url"])
        self.assertIn("at", published["published"]["zhihu"])  # posted, link not given
        self.assertEqual("published", self._project().status)
        self.assertTrue((project.directory / "03-draft.md").is_file())

    def test_a_piece_with_no_platform_still_finishes(self) -> None:
        # a report goes to one person, not to a platform, and used to be stuck
        _json("new", "September report", "--vault", self.v, "--status", "making")
        project = self._project()
        code, _ = _json("accept", project.id, "--vault", self.v)
        self.assertEqual(0, code)

        code, published = _json("publish", project.id, "--vault", self.v)
        self.assertEqual(0, code)
        self.assertEqual("published", published["status"])
        self.assertEqual({}, published["published"])
        self.assertEqual("published", self._project().status)

    def test_each_gate_answers_only_its_own_question(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup")
        project = self._project()

        code, refused = _json("accept", project.id, "--vault", self.v)
        self.assertEqual(1, code)
        self.assertIn("'candidate'", refused["error"])  # gate 1 comes first

        _json("confirm", project.id, "--vault", self.v, "--title", "Desk lighting")
        code, refused = _json("publish", project.id, "--vault", self.v)
        self.assertEqual(1, code)
        self.assertIn("'making'", refused["error"])  # and gate 2 before gate 3
        self.assertEqual("making", self._project().status)

    def test_a_link_for_a_platform_the_card_does_not_plan_is_refused(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--status", "making", "--platform", "blog")
        project = self._project()
        _json("accept", project.id, "--vault", self.v)

        code, refused = _json("publish", project.id, "--vault", self.v,
                              "--url", "blgo=https://example.test/desk")
        self.assertEqual(1, code)
        self.assertIn("blgo", refused["error"])
        self.assertEqual("ready", self._project().status)  # a typo loses nothing


if __name__ == "__main__":
    unittest.main()
