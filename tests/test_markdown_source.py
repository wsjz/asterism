from pathlib import Path
import os
import tempfile
import unittest

from asterism.sources.base import SourceError
from asterism.sources.markdown import MarkdownDirectorySource


class MarkdownDirectorySourceTest(unittest.TestCase):
    def test_collects_obisidian_style_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Obsidian"
            vault = base / "Asterism"
            (root / "Projects").mkdir(parents=True)
            (root / ".obsidian").mkdir()
            (root / "Projects" / "idea.md").write_text(
                "---\ntitle: My idea\ntags: [writing, project/asterism]\ncustom: kept\n---\n"
                "Body with #inline-tag.\n",
                encoding="utf-8",
            )
            (root / ".obsidian" / "ignored.md").write_text("ignored", encoding="utf-8")

            items = MarkdownDirectorySource((root,), vault=vault).collect()

            self.assertEqual(1, len(items))
            item = items[0]
            self.assertEqual("My idea", item.title)
            self.assertEqual("Projects", item.parent)
            self.assertEqual(
                ("writing", "project/asterism", "inline-tag"), item.tags
            )
            self.assertNotIn("title: My idea", item.content_text)
            self.assertIn("custom: kept", item.source_meta["front_matter"])

    def test_skips_symlinks_and_dot_directories_and_reads_author(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "Notes"
            outside = base / "Outside"
            vault = base / "Asterism"
            (root / "Sub" / ".hidden").mkdir(parents=True)
            outside.mkdir()
            (outside / "secret.md").write_text("secret", encoding="utf-8")
            (root / "Sub" / "kept.md").write_text("---\nauthor: 'Me'\n---\n# Kept\nbody", encoding="utf-8")
            (root / "Sub" / ".hidden" / "no.md").write_text("no", encoding="utf-8")
            os.symlink(outside / "secret.md", root / "link.md")
            os.symlink(outside, root / "linked-dir")

            items = MarkdownDirectorySource((root,), vault=vault).collect()

            self.assertEqual(["kept"], [item.title for item in items])  # file name, not the first heading
            self.assertEqual("Me", items[0].author)
            self.assertEqual("Sub", items[0].parent)
            self.assertEqual("Sub/kept.md", items[0].source_meta["path"])

    def test_symlinked_root_resolves_and_non_utf8_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "Real"
            real.mkdir()
            (real / "ok.md").write_text("# Ok", encoding="utf-8")
            os.symlink(real, base / "Link")
            items = MarkdownDirectorySource((base / "Link",), vault=base / "Asterism").collect()
            self.assertEqual("Real", items[0].source_meta["root"])  # the real directory is what gets scanned
            (real / "bad.md").write_bytes(b"\xff\xfe not utf-8")
            with self.assertRaises(SourceError):
                MarkdownDirectorySource((real,), vault=base / "Asterism").collect()

    def test_rejects_input_that_overlaps_output_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            source = vault / "other-notes"
            with self.assertRaises(ValueError):
                MarkdownDirectorySource((source,), vault=vault)
            with self.assertRaises(ValueError):
                MarkdownDirectorySource((Path(temporary),), vault=vault)


if __name__ == "__main__":
    unittest.main()
