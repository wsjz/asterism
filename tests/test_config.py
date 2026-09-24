from pathlib import Path
import shutil
import tempfile
import unittest

from asterism.config import (
    CONFIG_NAME,
    ConfigError,
    initialize_vault,
    load_config,
)


class ConfigTest(unittest.TestCase):
    def test_initializes_separate_private_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            created = initialize_vault(vault, "sqlite")
            loaded = load_config(vault)

            self.assertEqual(created, loaded)
            self.assertTrue((vault / CONFIG_NAME).is_file())
            self.assertTrue((vault / "notes").is_dir())
            self.assertTrue((vault / ".asterism" / "state").is_dir())
            self.assertFalse((vault / "logs").exists())  # nothing ever wrote there
            self.assertIn(".asterism/", (vault / ".gitignore").read_text())

    def test_settings_a_person_writes_stay_visible_and_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "file")
            config = load_config(vault)
            self.assertEqual(config.vault / "settings" / "templates", config.templates_root)
            self.assertEqual(config.vault / "settings" / "platforms", config.platforms_root)

    def test_a_new_vault_explains_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "file")
            readme = (vault / "README.md").read_text(encoding="utf-8")
            self.assertIn("sources ──► notes/ ──► picks/ ──► projects/", readme)

    def test_rejects_root_as_vault(self) -> None:
        with self.assertRaises(ValueError):
            initialize_vault(Path("/"), "file")

    def test_loads_markdown_roots_and_scoped_notion_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "file")
            (vault / CONFIG_NAME).write_text(
                "state:\n  backend: file\n"
                "sources:\n"
                "  markdown:\n    roots: ['../Obsidian']\n"
                "  notion:\n"
                "    root_page_ids: ['11111111-1111-1111-1111-111111111111']\n"
                "    data_source_ids: ['22222222-2222-2222-2222-222222222222']\n"
                "    discover_all: false\n",
                encoding="utf-8",
            )

            loaded = load_config(vault)

            self.assertEqual(
                ((Path(temporary) / "Obsidian").resolve(),), loaded.markdown_roots
            )
            self.assertEqual(
                ("11111111-1111-1111-1111-111111111111",),
                loaded.notion_root_page_ids,
            )

    def test_rejects_wrong_types(self) -> None:
        cases = {
            "state:\n  backend: postgres\n": "state.backend",
            "state:\n  backend: file\nsources:\n  apple_notes:\n    account: 42\n": "account",
            "state:\n  backend: file\nsources:\n  markdown:\n    roots: /not/a/list\n": "roots",
            "state:\n  backend: file\nsources:\n  notion:\n    discover_all: yes please\n": "discover_all",
            "- just\n- a list\n": "mapping",
        }
        for text, needle in cases.items():
            with tempfile.TemporaryDirectory() as temporary:
                vault = Path(temporary) / "vault"
                initialize_vault(vault, "file")
                (vault / CONFIG_NAME).write_text(text, encoding="utf-8")
                with self.assertRaises(ConfigError, msg=text) as raised:
                    load_config(vault)
                self.assertIn(needle, str(raised.exception))

    def test_parses_digest_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "file")
            (vault / CONFIG_NAME).write_text(
                "state:\n  backend: file\n"
                "links: markdown\n"
                "digest:\n"
                "  timezone: Asia/Shanghai\n"
                "  excerpt_chars: 120\n"
                "  week: { run_on: 3, include_days: false, archive_days: true }\n"
                "  month:\n"
                "    run_on: ['01-31','02-28','03-31','04-30','05-31','06-30','07-31','08-31','09-30','10-31','11-30','12-31']\n"
                "  year: { enabled: true, run_on: 6 }\n",
                encoding="utf-8",
            )
            loaded = load_config(vault)
            self.assertEqual("markdown", loaded.links)
            self.assertEqual("Asia/Shanghai", loaded.digest.timezone)
            self.assertEqual(120, loaded.digest.excerpt_chars)
            self.assertEqual((3, False, True), (loaded.digest.week.run_on, loaded.digest.week.include_lower, loaded.digest.week.archive_lower))
            self.assertEqual("12-31", loaded.digest.month.run_on[11])
            self.assertEqual(6, loaded.digest.year.run_on)

    def test_parses_storage_archive_and_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "sqlite")
            (vault / CONFIG_NAME).write_text(
                "state:\n  backend: sqlite\n  state_dir: ../local-state\n"
                "storage:\n  media_root: /Volumes/Content\n  inbox: [inbox, /Volumes/Drop]\n"
                "archive:\n  enabled: true\n  root: /Volumes/Archive\n  mode: move\n",
                encoding="utf-8",
            )
            loaded = load_config(vault)
            self.assertEqual((Path(temporary) / "local-state").resolve(), loaded.state_dir)
            self.assertEqual(Path("/Volumes/Content"), loaded.storage.media_root)
            self.assertEqual(((vault / "inbox").resolve(), Path("/Volumes/Drop")), loaded.storage.inbox)
            self.assertTrue(loaded.archive.enabled)
            self.assertEqual(Path("/Volumes/Archive"), loaded.archive_root)
            self.assertEqual("move", loaded.archive.mode)
            plain = initialize_vault(Path(temporary) / "plain", "file")
            self.assertEqual((Path(temporary) / "plain" / "archive").resolve(), plain.archive_root)
            with tempfile.TemporaryDirectory() as other:
                bad = Path(other) / "vault"
                initialize_vault(bad, "file")
                (bad / CONFIG_NAME).write_text("state:\n  backend: file\narchive:\n  mode: delete\n", encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(bad)

    def test_rejects_bad_digest_values(self) -> None:
        cases = [
            ("digest:\n  week: { run_on: 8 }\n", "ISO weekday"),
            ("digest:\n  month: { run_on: [2026-01-31, '02-28', '03-31', '04-30', '05-31', '06-30', '07-31', '08-31', '09-30', '10-31', '11-30', '12-31'] }\n", "quoted"),
            ("digest:\n  month: { run_on: 6 }\n", "week index"),
            ("digest:\n  timezone: Mars/Olympus\n", "timezone"),
            ("links: html\n", "links"),
        ]
        for text, needle in cases:
            with tempfile.TemporaryDirectory() as temporary:
                vault = Path(temporary) / "vault"
                initialize_vault(vault, "file")
                (vault / CONFIG_NAME).write_text("state:\n  backend: file\n" + text, encoding="utf-8")
                with self.assertRaises(ConfigError, msg=text) as raised:
                    load_config(vault)
                self.assertIn(needle, str(raised.exception))

    def test_a_missing_configuration_says_where_it_looked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            vault.mkdir()
            with self.assertRaises(FileNotFoundError) as raised:
                load_config(vault)
            self.assertIn(CONFIG_NAME, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
