"""The agent contract: every flow command can report itself as one JSON object."""
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
from asterism.sources.base import Source
from asterism.state import FileStateBackend


SH = ZoneInfo("Asia/Shanghai")
CONFIG = (
    "state:\n  backend: file\n"
    "digest:\n  timezone: Asia/Shanghai\n  week: { run_on: 3 }\n"
    "content:\n  pillars: [{ key: desk-setup, tags: [desk] }]\n"
)

ITEMS = [
    SourceItem("flomo", "m1", "Desk lighting", "Body one",
               created_at=datetime(2026, 9, 14, 9, 20, tzinfo=SH), tags=("desk",)),
    SourceItem("flomo", "m2", "A loose thought", "Body two",
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


def _json(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main([*argv, "--json"])
    return code, json.loads(out.getvalue())


class JsonOutputTest(unittest.TestCase):
    def test_every_object_names_its_command_and_whether_it_worked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = str(_vault(temporary))
            for argv in (
                ("status", "--vault", vault),
                ("week", "--vault", vault),
                ("material", "--vault", vault),
                ("review", "--vault", vault),
            ):
                code, payload = _json(*argv)
                self.assertEqual(0, code, argv[0])
                self.assertEqual(argv[0], payload["command"])
                self.assertTrue(payload["ok"], argv[0])

    def test_the_reporting_commands_all_speak_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = str(_vault(temporary))
            code, payload = _json("doctor", "--vault", vault, "--source", "flomo")
            self.assertEqual("doctor", payload["command"])
            self.assertIn("vault", payload["storage"])
            self.assertTrue(any(check["label"] == "notes directory" for check in payload["checks"]))

            code, payload = _json("digest", "--vault", vault)
            self.assertEqual(0, code)
            self.assertIsInstance(payload["written"], list)

            code, payload = _json("missing", "--vault", vault)
            self.assertEqual(0, code)
            self.assertEqual(0, payload["count"])

    def test_a_failing_doctor_carries_its_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = str(_vault(temporary))
            code, payload = _json("doctor", "--vault", vault, "--source", "markdown")
            self.assertEqual(1, code)
            self.assertFalse(payload["ok"])
            self.assertTrue(any("sources.markdown.roots" in hint for hint in payload["hints"]))

    def test_review_reports_the_sheet_and_its_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = str(_vault(temporary))
            _code, payload = _json("review", "--vault", vault)
            self.assertTrue(payload["sheet"].startswith("review/"))
            self.assertEqual(2, payload["listed"])
            self.assertEqual({"undecided"}, {line["section"] for line in payload["lines"]})
            self.assertIsNone(payload["lines"][0]["topic"])

    def test_a_failure_carries_the_message_in_the_same_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = str(_vault(temporary))
            code, payload = _json("confirm", "9999-999", "--vault", vault)
            self.assertEqual(1, code)
            self.assertFalse(payload["ok"])
            self.assertIn("9999-999", payload["error"])

    def test_a_candidate_reports_its_angles_without_passing_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = str(_vault(temporary))
            _json("new", "Desk lighting", "--vault", vault, "--pillar", "desk-setup")
            _code, listed = _json("status", "--vault", vault)
            project_id = listed["projects"][0]["id"]

            code, payload = _json("confirm", project_id, "--vault", vault)
            self.assertEqual(1, code)  # the gate is not passed by asking
            self.assertFalse(payload["confirmed"])
            self.assertEqual([1], [angle["number"] for angle in payload["angles"]])

            code, payload = _json("confirm", project_id, "--vault", vault, "--angle", "1")
            self.assertEqual(0, code)
            self.assertTrue(payload["confirmed"])
            self.assertEqual("making", payload["status"])


if __name__ == "__main__":
    unittest.main()
