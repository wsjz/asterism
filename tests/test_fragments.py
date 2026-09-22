from datetime import date, datetime
import unittest
from zoneinfo import ZoneInfo

from asterism.sources.apple_notes import AppleNotesSource
from asterism.sources.fragments import note_date, split_daily_log


SH = ZoneInfo("Asia/Shanghai")

DAILY_HTML = (
    "2026-09-21 随手记\n"
    "开头没有时间戳的一段。\n"
    "\n"
    "09:20 AI 生成代码最大的成本可能不是生成，而是验证。\n"
    "12:40 桌面灯光不应该只讲参数，\n"
    "应该讲长时间写代码时眼睛是否疲劳。\n"
    "12:40 同一分钟的第二条\n"
    "22:10 想试试让 Claude 读取 Home Assistant 状态。\n"
    "25:99 这不是时间戳\n"
)
DAILY = DAILY_HTML  # the splitter works on Markdown, which is what the adapter passes it


def as_html(text: str) -> str:
    """The shape Apple Notes hands over: one div per line."""
    return "".join(f"<div>{line or '<br>'}</div>" for line in text.splitlines())


class FragmentSplitTest(unittest.TestCase):
    def test_note_date_prefers_title_then_creation(self) -> None:
        created = datetime(2026, 9, 22, 8, 0)
        self.assertEqual(date(2026, 9, 21), note_date("2026-09-21 随手记", created))
        self.assertEqual(date(2026, 9, 22), note_date("no date here", created))
        self.assertIsNone(note_date("no date", None))

    def test_splits_into_anchored_fragments(self) -> None:
        fragments = split_daily_log(
            DAILY, title="2026-09-21 随手记", day=date(2026, 9, 21),
            note_created_at=datetime(2026, 9, 21, 8, 0), zone=SH,
        )
        anchors = [fragment.anchor for fragment in fragments]
        self.assertEqual(["preamble", "09:20", "12:40", "12:40-2", "22:10"], anchors)
        self.assertEqual("开头没有时间戳的一段。", fragments[0].text)
        self.assertEqual(datetime(2026, 9, 21, 8, 0, tzinfo=SH), fragments[0].created_at)
        self.assertEqual(datetime(2026, 9, 21, 12, 40, tzinfo=SH), fragments[2].created_at)
        self.assertEqual("桌面灯光不应该只讲参数，\n应该讲长时间写代码时眼睛是否疲劳。", fragments[2].text)
        self.assertTrue(fragments[4].text.endswith("25:99 这不是时间戳"))

    def test_appending_a_line_adds_exactly_one_fragment(self) -> None:
        before = split_daily_log(DAILY, title="2026-09-21 随手记", day=date(2026, 9, 21), note_created_at=None, zone=SH)
        after = split_daily_log(DAILY + "23:00 新的一条\n", title="2026-09-21 随手记", day=date(2026, 9, 21), note_created_at=None, zone=SH)
        self.assertEqual([f.anchor for f in before], [f.anchor for f in after[:-1]])
        self.assertEqual(before[1:], after[1:-1])
        self.assertEqual("23:00", after[-1].anchor)


class AppleNotesFragmentTest(unittest.TestCase):
    def test_daily_log_folder_yields_fragment_items(self) -> None:
        source = AppleNotesSource(daily_log_folders=("00 随手记",), timezone="Asia/Shanghai")
        record = {
            "source_id": "x-coredata://ABC/ICNote/p42",
            "account": "iCloud",
            "folder": "Notes/00 随手记",
            "title": "2026-09-21 随手记",
            "content_text": as_html(DAILY),
            "created_at": "2026-09-21T08:00:00",
            "updated_at": "2026-09-21T22:11:00",
        }
        items = source._parse_record(record)
        self.assertEqual(5, len(items))
        first = items[1]
        self.assertEqual("x-coredata://ABC/ICNote/p42#09:20", first.source_id)
        self.assertEqual("Notes/00 随手记/2026-09-21 随手记", first.parent)
        self.assertEqual("AI 生成代码最大的成本可能不是生成，而是验证", first.title)
        self.assertEqual(datetime(2026, 9, 21, 9, 20, tzinfo=SH), first.created_at)
        self.assertEqual("09:20", first.source_meta["fragment"])

    def test_other_folders_stay_whole(self) -> None:
        source = AppleNotesSource(daily_log_folders=("00 随手记",), timezone="Asia/Shanghai")
        record = {
            "source_id": "n1", "account": "iCloud", "folder": "Ideas",
            "title": "Whole", "content_text": as_html("Whole\n09:20 still one note"),
            "created_at": None, "updated_at": None,
        }
        items = source._parse_record(record)
        self.assertEqual(1, len(items))
        self.assertEqual("n1", items[0].source_id)

    def test_the_html_body_becomes_markdown_and_the_title_heading_is_dropped(self) -> None:
        source = AppleNotesSource()
        record = {
            "source_id": "n1", "account": "iCloud", "folder": "Notes", "title": "Week6",
            "content_text": '<div><h1>Week6</h1></div><ul class="Checklist"><li class="checked">shipped</li>'
                            '<li class="unchecked">todo</li></ul><div><b>bold</b></div>',
            "created_at": None, "updated_at": None,
        }
        item = source._parse_record(record)[0]
        self.assertNotIn("# Week6", item.content_text)  # the title is already a field
        self.assertIn("- [x] shipped", item.content_text)
        self.assertIn("- [ ] todo", item.content_text)
        self.assertIn("**bold**", item.content_text)

    def test_recently_deleted_is_skipped_by_default(self) -> None:
        source = AppleNotesSource()
        record = {"source_id": "d1", "account": "iCloud", "folder": "Recently Deleted", "title": "Gone",
                  "content_text": as_html("Gone"), "created_at": None, "updated_at": None}
        self.assertEqual([], source._parse_record(record))
        record["folder"] = "Recently Deleted/Sub"
        self.assertEqual([], source._parse_record(record))
        kept = AppleNotesSource(exclude_folders=())._parse_record(record)
        self.assertEqual(1, len(kept))

    def test_rejects_unknown_timezone(self) -> None:
        with self.assertRaises(ValueError):
            AppleNotesSource(timezone="Mars/Olympus")


if __name__ == "__main__":
    unittest.main()
