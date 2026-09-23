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


def _tick(path: Path) -> None:
    """Answer every question on a gate sheet, the way a person would."""
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")


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

        # draft
        code, drafted = _json("draft", project.id, "--vault", self.v)
        self.assertEqual(0, code)
        self.assertTrue(drafted["created"])
        draft = self.vault / drafted["draft"]
        self.assertIn("## Material", draft.read_text(encoding="utf-8"))
        self.assertIn("Desk lighting", draft.read_text(encoding="utf-8"))

        # gate 2 reports what is missing and refuses to move on unanswered
        code, checked = _json("check", project.id, "--vault", self.v)
        kinds = {finding["kind"] for finding in checked["findings"]}
        self.assertIn("no-platform", kinds)
        self.assertEqual(2, checked["gathered"])
        self.assertEqual(0, checked["cited"])

        code, refused = _json("accept", project.id, "--vault", self.v)
        self.assertEqual(1, code)
        self.assertIn("unticked", refused["error"])
        self.assertEqual("making", self._project().status)

        _tick(self.vault / checked["sheet"])
        code, accepted = _json("accept", project.id, "--vault", self.v)
        self.assertEqual(0, code)
        self.assertEqual("ready", accepted["status"])

        # platforms, then the exports
        card = self._project()
        text = (card.directory / "01-project.md").read_text(encoding="utf-8")
        (card.directory / "01-project.md").write_text(
            text.replace("platforms: []", "platforms:\n- blog\n- zhihu"), encoding="utf-8"
        )
        code, adapted = _json("adapt", card.id, "--vault", self.v)
        self.assertEqual(["blog", "zhihu"], adapted["written"])
        self.assertTrue((self.vault / adapted["exports"]["blog"]).is_file())
        self.assertTrue((self.vault / "settings/platforms/blog.md").is_file())

        # gate 3
        code, released = _json("release", card.id, "--vault", self.v)
        self.assertEqual(0, code)
        self.assertEqual([], released["missing"])
        _tick(self.vault / released["sheet"])

        code, published = _json("publish", card.id, "--vault", self.v,
                                "--url", "blog=https://example.test/desk")
        self.assertEqual(0, code)
        self.assertEqual("published", published["status"])
        self.assertEqual("https://example.test/desk", published["published"]["blog"]["url"])
        self.assertEqual("published", self._project().status)

    def test_naming_a_note_is_not_citing_it(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup",
              "--status", "making", "--platform", "blog",
              "--source", "notes/flomo/origin/Desk lighting.md")
        project = self._project()
        _json("draft", project.id, "--vault", self.v)
        draft = project.directory / "03-draft.md"
        head = draft.read_text(encoding="utf-8")

        # the piece is named after its own material, which used to count as a citation
        draft.write_text(head.replace("## Material", "## Body\n\nWhat makes Desk lighting hard?\n\n## Material"),
                         encoding="utf-8")
        _code, checked = _json("check", project.id, "--vault", self.v)
        self.assertEqual(0, checked["cited"])
        self.assertIn("uncited", {f["kind"] for f in checked["findings"]})

        # a real link to it settles the check
        draft.write_text(
            draft.read_text(encoding="utf-8").replace(
                "What makes Desk lighting hard?",
                "What makes [[notes/flomo/origin/Desk lighting|this]] hard?",
            ),
            encoding="utf-8",
        )
        _code, checked = _json("check", project.id, "--vault", self.v)
        self.assertEqual(1, checked["cited"])
        self.assertEqual([], [f for f in checked["findings"] if f["kind"] == "uncited"])

    def test_composing_again_never_touches_the_prose(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup",
              "--status", "making")
        project = self._project()
        _json("draft", project.id, "--vault", self.v)
        draft = project.directory / "03-draft.md"
        written = "# Desk lighting\n\n## A heading the brief never had\n\nReal prose.\n\n## Material\n\n- old\n"
        draft.write_text(written, encoding="utf-8")

        _code, again = _json("draft", project.id, "--vault", self.v)
        self.assertFalse(again["created"])
        text = draft.read_text(encoding="utf-8")
        self.assertIn("## A heading the brief never had", text)
        self.assertIn("Real prose.", text)  # restructuring a draft must never lose it
        self.assertNotIn("- old", text)  # only the material list is refreshed

    def test_a_piece_with_no_platform_still_finishes(self) -> None:
        # a report goes to one person, not to a platform, and used to be stuck
        _json("new", "September report", "--vault", self.v, "--status", "making")
        project = self._project()
        _json("draft", project.id, "--vault", self.v)
        _code, checked = _json("check", project.id, "--vault", self.v)
        self.assertIn("no-platform", {f["kind"] for f in checked["findings"]})

        _tick(self.vault / checked["sheet"])
        _json("accept", project.id, "--vault", self.v)

        code, released = _json("release", project.id, "--vault", self.v)
        self.assertEqual(0, code)
        self.assertEqual([], released["missing"])
        sheet = self.vault / released["sheet"]
        self.assertIn("names no platform", sheet.read_text(encoding="utf-8"))

        _tick(sheet)
        code, published = _json("publish", project.id, "--vault", self.v)
        self.assertEqual(0, code)
        self.assertEqual("published", published["status"])
        self.assertEqual({}, published["published"])
        self.assertEqual("published", self._project().status)

    def test_a_candidate_cannot_be_drafted(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup")
        project = self._project()
        code, payload = _json("draft", project.id, "--vault", self.v)
        self.assertEqual(1, code)
        self.assertIn("confirm it first", payload["error"])

    def test_an_edited_export_is_never_overwritten(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup",
              "--platform", "blog", "--status", "making")
        project = self._project()
        _json("draft", project.id, "--vault", self.v)
        _code, first = _json("adapt", project.id, "--vault", self.v)
        export = self.vault / first["exports"]["blog"]
        export.write_text("# Rewritten by hand\n", encoding="utf-8")

        _code, again = _json("adapt", project.id, "--vault", self.v)
        self.assertEqual(["blog"], again["kept"])
        self.assertEqual("# Rewritten by hand\n", export.read_text(encoding="utf-8"))

    def test_editing_only_the_prose_is_enough_to_keep_an_export(self) -> None:
        """A person who rewrites the body and never touches the header is protected too."""
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup",
              "--platform", "blog", "--status", "making")
        project = self._project()
        _json("draft", project.id, "--vault", self.v)
        _code, first = _json("adapt", project.id, "--vault", self.v)
        export = self.vault / first["exports"]["blog"]
        generated = export.read_text(encoding="utf-8")
        self.assertIn("fingerprint: ", generated)
        edited = generated.rstrip() + "\n\nOne sentence added at the end, header untouched.\n"
        export.write_text(edited, encoding="utf-8")

        _code, again = _json("adapt", project.id, "--vault", self.v)
        self.assertEqual(["blog"], again["kept"])
        self.assertEqual(edited, export.read_text(encoding="utf-8"))

    def test_an_untouched_export_follows_the_draft(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup",
              "--platform", "blog", "--status", "making")
        project = self._project()
        _json("draft", project.id, "--vault", self.v)
        _code, first = _json("adapt", project.id, "--vault", self.v)
        export = self.vault / first["exports"]["blog"]
        draft = project.directory / "03-draft.md"
        draft.write_text(
            draft.read_text(encoding="utf-8").replace("# Desk lighting\n", "# Desk lighting\n\nA new opening.\n"),
            encoding="utf-8",
        )

        _code, again = _json("adapt", project.id, "--vault", self.v)
        self.assertEqual(["blog"], again["written"])
        self.assertIn("A new opening.", export.read_text(encoding="utf-8"))

    def test_an_export_from_before_fingerprints_is_judged_by_its_marker(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup",
              "--platform", "blog", "--status", "making")
        project = self._project()
        _json("draft", project.id, "--vault", self.v)
        _code, first = _json("adapt", project.id, "--vault", self.v)
        export = self.vault / first["exports"]["blog"]
        legacy = "---\nproject: x\nplatform: blog\n---\n\n<!-- asterism:generated -->\n\nOld body\n"
        export.write_text(legacy, encoding="utf-8")
        _code, again = _json("adapt", project.id, "--vault", self.v)
        self.assertEqual(["blog"], again["written"])  # still marked as the machine's

        export.write_text("---\nproject: x\nplatform: blog\n---\n\nMine now\n", encoding="utf-8")
        _code, third = _json("adapt", project.id, "--vault", self.v)
        self.assertEqual(["blog"], third["kept"])

    def test_the_draft_takes_its_sections_from_the_briefs_outline(self) -> None:
        _json("new", "Desk lighting", "--vault", self.v, "--pillar", "desk-setup",
              "--status", "making")
        project = self._project()
        brief = project.directory / "02-brief.md"
        brief.write_text(
            brief.read_text(encoding="utf-8").replace(
                "## Outline\n", "## Outline\n\n- Why the desk feels loud\n- What to change first\n"
            ),
            encoding="utf-8",
        )
        _code, drafted = _json("draft", project.id, "--vault", self.v)
        self.assertEqual(["Why the desk feels loud", "What to change first"], drafted["headings"])
        text = (project.directory / "03-draft.md").read_text(encoding="utf-8")
        self.assertIn("## Why the desk feels loud", text)
        self.assertNotIn("## Audience", text)  # planning prompts stay in the brief


if __name__ == "__main__":
    unittest.main()
