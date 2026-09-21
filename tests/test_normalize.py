from datetime import datetime, timezone
import unittest

from asterism.normalize import canonical_url, derive_title, html_to_markdown, parse_datetime


class DatetimeTest(unittest.TestCase):
    def test_parses_iso_unix_and_empty(self) -> None:
        self.assertIsNone(parse_datetime(None))
        self.assertIsNone(parse_datetime(""))
        self.assertEqual(datetime(2026, 9, 21, tzinfo=timezone.utc), parse_datetime(1789948800))
        self.assertEqual(
            datetime(2026, 9, 21, 10, 30, tzinfo=timezone.utc),
            parse_datetime("2026-09-21T10:30:00Z"),
        )
        self.assertEqual(datetime(2026, 9, 21, 16, 56, 30), parse_datetime("2026-09-21 16:56:30"))

    def test_rejects_garbage(self) -> None:
        for value in ("yesterday", "2019", True, [1]):
            with self.assertRaises(ValueError, msg=repr(value)):
                parse_datetime(value)


class UrlTest(unittest.TestCase):
    def test_canonical_form_drops_tracking_and_fragment(self) -> None:
        self.assertEqual(
            "https://example.com/a?b=2&x=1",
            canonical_url("HTTPS://Example.com/a/?x=1&utm_source=t&b=2#top"),
        )
        self.assertEqual("https://example.com/", canonical_url("https://example.com"))

    def test_rejects_relative_and_other_schemes(self) -> None:
        for value in ("/relative", "ftp://x.y/z", "javascript:alert(1)"):
            with self.assertRaises(ValueError, msg=value):
                canonical_url(value)


class TitleTest(unittest.TestCase):
    def test_native_title_wins(self) -> None:
        self.assertEqual("Native  title".replace("  ", " "), derive_title("Native  title", "# other"))

    def test_first_heading(self) -> None:
        self.assertEqual("Heading here", derive_title(None, "intro\n\n## Heading here ##\nbody"))

    def test_first_line_cleaned_and_cut(self) -> None:
        self.assertEqual(
            "AI 生成代码最大的成本可能不是生成，而是验证",
            derive_title(None, "- 09:20 AI 生成代码最大的成本可能不是生成，而是验证。后面还有话。"),
        )
        self.assertEqual("see this", derive_title(None, "see [this](https://x.y/z) https://a.b/c"))
        self.assertEqual("x" * 60, derive_title(None, "x" * 80))

    def test_url_fallback_and_none(self) -> None:
        self.assertEqual("github.com/opencli", derive_title(None, "", "https://github.com/jackwener/opencli/"))
        self.assertEqual("example.com", derive_title(None, "", "https://example.com"))
        self.assertIsNone(derive_title(None, "   \n", None))
        self.assertIsNone(derive_title("", "https://only.a/url"))


class MarkdownTest(unittest.TestCase):
    def test_converts_common_inline_and_block_markup(self) -> None:
        html = "<p>A <strong>bold</strong> and <em>soft</em> <a href='https://x.y/'>link</a></p><ul><li>one</li><li>two<br>lines</li></ul>"
        self.assertEqual(
            "A **bold** and *soft* [link](https://x.y/)\n- one\n- two\nlines",
            html_to_markdown(html),
        )


if __name__ == "__main__":
    unittest.main()
