from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from asterism.config import CONFIG_NAME, initialize_vault, load_config
from asterism.digest import DigestBuilder, parse_label
from asterism.models import SourceItem
from asterism.pipeline import Pipeline
from asterism.rendering import parse_front_matter
from asterism.sources.base import Source
from asterism.state import FileStateBackend


SH = ZoneInfo("Asia/Shanghai")


class FakeSource(Source):
    name = "flomo"
    output_name = "flomo"

    def __init__(self, items):
        self.items = items

    def collect(self):
        return self.items


def _vault(temporary: str, extra: str = "") -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text(
        "state:\n  backend: file\n"
        "digest:\n  timezone: Asia/Shanghai\n  week: { run_on: 3 }\n" + extra,
        encoding="utf-8",
    )
    return vault


class DigestBuilderTest(unittest.TestCase):
    def test_daily_and_weekly_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            items = [
                SourceItem("flomo", "m1", "Morning idea", "A short body.", created_at=datetime(2026, 9, 21, 9, 20, tzinfo=SH), tags=("idea",)),
                SourceItem("flomo", "m2", None, "x" * 400, created_at=datetime(2026, 9, 21, 12, 40, tzinfo=SH)),
                SourceItem("flomo", "m3", "Next day", "Body 3", created_at=datetime(2026, 9, 22, 8, 0, tzinfo=SH)),
            ]
            now = datetime(2026, 9, 25, 20, 0, tzinfo=SH)  # Friday; week run_on=3 → W39 (17..23) closed, W40 open
            with FileStateBackend(vault / "state" / "manifest.json") as state:
                Pipeline(FakeSource(items), state, vault).sync()
                messages = DigestBuilder(config, state, now=now).run()

                daily = (vault / "digest" / "daily" / "2026" / "2026-09-21.md").read_text(encoding="utf-8")
                fields, body = parse_front_matter(daily)
                self.assertEqual("day", fields["digest"])
                self.assertEqual("closed", fields["state"])
                self.assertEqual("unread", fields["review_status"])
                self.assertEqual({"flomo": 2}, fields["sources"])
                self.assertIn("- **09:20** [[notes/flomo/Morning idea|Morning idea]]", body)
                self.assertIn("  A short body.", body)
                self.assertIn(" ...", body)  # long body excerpted

                weekly = (vault / "digest" / "weekly" / "2026" / "2026-W39.md").read_text(encoding="utf-8")
                wfields, wbody = parse_front_matter(weekly)
                self.assertEqual(("2026-09-17", "2026-09-23"), (wfields["period_start"], wfields["period_end"]))
                self.assertEqual(3, wfields["items"])
                # the week holds the week's own content, not a pointer to the days
                self.assertIn("## 2026-09-21", wbody)
                self.assertIn("### New", wbody)
                self.assertIn("#### flomo", wbody)
                self.assertIn("A short body.", wbody)
                self.assertIn("## 2026-09-22", wbody)
                self.assertNotIn("![[", wbody)
                self.assertNotIn("no digest", wbody)

                self.assertEqual("rolled", state.get_digest("day", "2026-09-21").state)
                self.assertIsNone(state.get_digest("week", "2026-09-24"))  # open week without items: no document
                self.assertFalse((vault / "digest" / "weekly" / "2026" / "2026-W40.md").exists())
                self.assertTrue(any("week 2026-W39 generated" in m for m in messages))
                self.assertTrue((vault / "digest" / "monthly" / "2026" / "2026-09.md").exists())  # open month rebuilt
                self.assertFalse((vault / "digest" / "yearly").exists())

    def test_regenerate_preserves_review_status_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            item = SourceItem("flomo", "m1", "Idea", "Body", created_at=datetime(2026, 9, 21, 9, 0, tzinfo=SH))
            now = datetime(2026, 9, 22, 9, 0, tzinfo=SH)
            with FileStateBackend(vault / "state" / "manifest.json") as state:
                Pipeline(FakeSource([item]), state, vault).sync()
                builder = DigestBuilder(config, state, now=now)
                builder.run()
                path = vault / "digest" / "daily" / "2026" / "2026-09-21.md"
                text = path.read_text(encoding="utf-8").replace('review_status: "unread"', 'review_status: "reviewed"')
                path.write_text(text, encoding="utf-8")
                builder.regenerate(parse_label("2026-09-21", config.digest))
                fields, _ = parse_front_matter(path.read_text(encoding="utf-8"))
                self.assertEqual("reviewed", fields["review_status"])
                first = path.read_text(encoding="utf-8")
                builder.regenerate(parse_label("2026-09-21", config.digest))
                self.assertEqual(first, path.read_text(encoding="utf-8"))

    def test_markdown_links_and_disabled_week_falls_back_to_days(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary, "  week: { enabled: false }\nlinks: markdown\n")
            config = load_config(vault)
            item = SourceItem("flomo", "m1", "Idea", "Body", created_at=datetime(2026, 8, 5, 9, 0, tzinfo=SH))
            now = datetime(2026, 9, 2, 9, 0, tzinfo=SH)
            with FileStateBackend(vault / "state" / "manifest.json") as state:
                Pipeline(FakeSource([item]), state, vault).sync()
                DigestBuilder(config, state, now=now).run()
                daily = (vault / "digest" / "daily" / "2026" / "2026-08-05.md").read_text(encoding="utf-8")
                self.assertIn("[Idea](../../../notes/flomo/Idea.md)", daily)
                monthly = (vault / "digest" / "monthly" / "2026" / "2026-08.md").read_text(encoding="utf-8")
                # weeks are off, so the month aggregates the days directly
                self.assertIn("## 2026-08-05", monthly)
                self.assertIn("[Idea](../../../notes/flomo/Idea.md)", monthly)
                self.assertIn("Body", monthly)
                self.assertNotIn("2026-08-06", monthly)

    def test_archive_move_keeps_the_week_complete_after_moving_the_days(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_root = Path(temporary) / "archive-root"
            archive_root.mkdir()
            vault = _vault(
                temporary,
                "  week: { run_on: 3, archive_days: true }\n"
                f"archive:\n  enabled: true\n  root: {archive_root}\n  mode: move\n",
            )
            config = load_config(vault)
            item = SourceItem("flomo", "m1", "Idea", "Body text", created_at=datetime(2026, 9, 21, 9, 0, tzinfo=SH))
            now = datetime(2026, 9, 25, 9, 0, tzinfo=SH)
            with FileStateBackend(vault / "state" / "manifest.json") as state:
                Pipeline(FakeSource([item]), state, vault).sync()
                messages = DigestBuilder(config, state, now=now).run()
                day_file = vault / "digest" / "daily" / "2026" / "2026-09-21.md"
                self.assertFalse(day_file.exists())
                self.assertTrue((archive_root / "digest" / "daily" / "2026" / "2026-09-21.md").is_file())
                weekly = (vault / "digest" / "weekly" / "2026" / "2026-W39.md").read_text(encoding="utf-8")
                self.assertIn("## 2026-09-21", weekly)
                self.assertIn("Body text", weekly)  # the week keeps the content the archived day held
                self.assertNotIn("![[", weekly)
                self.assertEqual("archived", state.get_digest("day", "2026-09-21").state)
                self.assertTrue(any("moved to" in m for m in messages))
                # rebuilding the week after the day file is gone loses nothing:
                # every level is rendered from state, not from the level below
                DigestBuilder(config, state, now=now).regenerate(parse_label("2026-W39", config.digest))
                rebuilt = (vault / "digest" / "weekly" / "2026" / "2026-W39.md").read_text(encoding="utf-8")
                self.assertIn("## 2026-09-21", rebuilt)
                self.assertIn("Body text", rebuilt)

    def test_archive_disabled_leaves_files_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary, "  week: { run_on: 3, archive_days: true }\n")
            config = load_config(vault)
            item = SourceItem("flomo", "m1", "Idea", "Body", created_at=datetime(2026, 9, 21, 9, 0, tzinfo=SH))
            with FileStateBackend(vault / "state" / "manifest.json") as state:
                Pipeline(FakeSource([item]), state, vault).sync()
                DigestBuilder(config, state, now=datetime(2026, 9, 25, 9, 0, tzinfo=SH)).run()
                self.assertTrue((vault / "digest" / "daily" / "2026" / "2026-09-21.md").exists())
                self.assertFalse((vault / "archive").exists())
                self.assertEqual("rolled", state.get_digest("day", "2026-09-21").state)

    def test_no_items_reports_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            with FileStateBackend(vault / "state" / "manifest.json") as state:
                self.assertEqual(["no items collected yet"], DigestBuilder(config, state).run())
            self.assertFalse((vault / "digest").exists())


if __name__ == "__main__":
    unittest.main()
