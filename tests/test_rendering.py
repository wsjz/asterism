from datetime import datetime, timezone
import unittest

from asterism.models import Origin, SourceItem
from asterism.rendering import note_filename, parse_front_matter, render_markdown, unique_filename


class RenderingTest(unittest.TestCase):
    def test_front_matter_quotes_untrusted_scalars(self) -> None:
        item = SourceItem(
            source="apple_notes",
            source_id="x: 1\n---",
            title='A "title"',
            content_text="hello\r\nworld",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            parent="Ideas",
            tags=("writing/ideas", "draft"),
            source_meta={"account": "iCloud"},
        )
        rendered = render_markdown(item)
        self.assertIn('source_id: "x: 1\\n---"', rendered)
        self.assertIn('parent: "Ideas"', rendered)
        self.assertIn('tags: ["writing/ideas", "draft"]', rendered)
        self.assertIn('source_meta: {"account": "iCloud"}', rendered)
        self.assertNotIn("\nfolder:", rendered)
        self.assertTrue(rendered.endswith("hello\nworld\n"))
        self.assertTrue(rendered.startswith("---\nschema: 1\nsource: \"apple_notes\"\n"))
        self.assertIn('origin: {"adapter": "apple_notes"}', rendered)
        self.assertIn("url: null", rendered)

    def test_fixed_key_order_and_round_trip(self) -> None:
        item = SourceItem(
            "cubox", "card-1", "Read me", "body",
            url="https://example.com/a", author="Someone",
            origin=Origin("cubox", "cubox-cli", "1.2.3"),
            source_meta={"domain": "example.com"},
        )
        rendered = render_markdown(item)
        keys = [line.split(":", 1)[0] for line in rendered.split("\n---\n", 1)[0].splitlines()[1:]]
        self.assertEqual(
            ["schema", "source", "source_id", "origin", "title", "url", "author",
             "parent", "tags", "created_at", "updated_at", "source_meta"],
            keys,
        )
        fields, body = parse_front_matter(rendered)
        self.assertEqual("body\n", body)
        self.assertEqual(1, fields["schema"])
        self.assertEqual({"adapter": "cubox", "producer": "cubox-cli", "producer_version": "1.2.3"}, fields["origin"])
        self.assertEqual("https://example.com/a", fields["url"])
        with self.assertRaises(ValueError):
            parse_front_matter("no front matter")

    def test_filename_is_the_cleaned_title(self) -> None:
        item = SourceItem("apple_notes", "id/../1", "../ My Note: v2 / draft?", "body")
        filename = note_filename(item)
        self.assertNotIn("/", filename)
        self.assertNotIn("..", filename)
        self.assertEqual("My Note- v2 - draft-.md".replace("-.md", ".md"), filename)
        self.assertEqual("Untitled.md", note_filename(SourceItem("flomo", "m", None, "body")))
        self.assertEqual("Week6 26.09.15.md", note_filename(SourceItem("apple_notes", "1", "Week6 26.09.15", "b")))
        long = note_filename(SourceItem("apple_notes", "1", "标题" * 60, "b"))
        self.assertLessEqual(len(long), 83)

    def test_unique_filename_adds_finder_style_suffixes(self) -> None:
        taken = {"Idea.md", "Idea (2).md"}
        self.assertEqual("Idea (3).md", unique_filename("Idea.md", taken))
        self.assertEqual("Other.md", unique_filename("Other.md", taken))
        self.assertEqual("Idea (3).md", unique_filename("Idea (2).md", taken))


if __name__ == "__main__":
    unittest.main()
