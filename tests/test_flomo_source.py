from pathlib import Path
import tempfile
import unittest
import zipfile

from asterism.sources.flomo import FlomoExportSource


FLOMO_HTML = """<!doctype html>
<html><body>
  <div class="memo" data-memo-id="memo-1">
    <div class="time">2026-09-21 10:30:00</div>
    <div class="content">
      <p>A <strong>small</strong> thought</p>
      <p>#Writing/Ideas #draft</p>
    </div>
  </div>
</body></html>
"""


class FlomoExportSourceTest(unittest.TestCase):
    def test_collects_memos_tags_and_markup_from_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            export = Path(temporary) / "index.html"
            export.write_text(FLOMO_HTML, encoding="utf-8")

            items = FlomoExportSource(export).collect()

            self.assertEqual(1, len(items))
            item = items[0]
            self.assertEqual("memo-1", item.source_id)
            self.assertEqual(("Writing/Ideas", "draft"), item.tags)
            self.assertEqual("A small thought", item.title)
            self.assertIn("**small**", item.content_text)
            self.assertIsNone(item.parent)

    def test_reads_official_style_zip_without_extracting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            export = Path(temporary) / "flomo.zip"
            with zipfile.ZipFile(export, "w") as archive:
                archive.writestr("flomo/index.html", FLOMO_HTML)

            items = FlomoExportSource(export).collect()

            self.assertEqual("memo-1", items[0].source_id)


if __name__ == "__main__":
    unittest.main()

