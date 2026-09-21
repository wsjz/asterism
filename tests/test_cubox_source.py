import json
import unittest

from asterism.sources.cubox import CuboxCLISource


class CuboxCLISourceTest(unittest.TestCase):
    def test_collects_card_detail_folder_tags_and_annotations(self) -> None:
        calls: list[list[str]] = []

        def runner(arguments: list[str], timeout_seconds: int) -> str:
            calls.append(arguments)
            if arguments[:2] == ["card", "list"]:
                if "--archived" in arguments:
                    return "[]"
                return json.dumps([{"id": "card-1", "title": "Listed title"}])
            return json.dumps(
                {
                    "id": "card-1",
                    "title": "An article",
                    "description": "Description",
                    "domain": "example.com",
                    "read": True,
                    "starred": False,
                    "tags": ["Research/AI", "ToRead"],
                    "folder": {"id": "folder-1", "nested_name": "Research/Agents"},
                    "url": "https://example.com/article",
                    "create_time": "2026-09-20T10:00:00:000+08:00",
                    "update_time": "2026-09-21T11:00:00:000+08:00",
                    "content": "# Article\n\nBody",
                    "author": "Example Author",
                    "annotations": [
                        {"text": "Important quote", "note": "My note"}
                    ],
                }
            )

        items = CuboxCLISource(runner=runner).collect()

        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual("card-1", item.source_id)
        self.assertEqual("Research/Agents", item.parent)
        self.assertEqual(("Research/AI", "ToRead"), item.tags)
        self.assertIn("## Annotations", item.content_text)
        self.assertIn("> Important quote", item.content_text)
        self.assertEqual("https://example.com/article", item.url)
        self.assertNotIn("url", item.source_meta)
        self.assertEqual(
            ["card", "list", "--all", "-o", "json"], calls[0]
        )
        self.assertEqual(
            ["card", "list", "--archived", "--all", "-o", "json"], calls[1]
        )
        self.assertEqual(
            ["card", "detail", "--id", "card-1", "-o", "json"], calls[2]
        )

    def test_treats_null_card_lists_as_empty(self) -> None:
        def runner(arguments: list[str], timeout_seconds: int) -> str:
            return "null"

        self.assertEqual([], CuboxCLISource(runner=runner).collect())

class CuboxFolderTest(unittest.TestCase):
    def _item(self, folder):
        card = {"id": "c1", "title": "T", "content": "body", "folder": folder, "tags": []}
        runner = lambda args, timeout: json.dumps([card] if args[1] == "list" and "--archived" not in args else ([] if args[1] == "list" else card))
        return CuboxCLISource(runner=runner).collect()[0]

    def test_folder_names_including_uncategorized(self) -> None:
        self.assertEqual("效率 | 工具", self._item({"id": "1", "name": "效率 | 工具", "nested_name": "", "parent_id": ""}).parent)
        self.assertEqual("Research/Agents", self._item({"id": "2", "name": "Agents", "nested_name": "Research/Agents"}).parent)
        self.assertEqual("Uncategorized", self._item({"id": "3", "name": "Uncategorized", "nested_name": "", "uncategorized": True}).parent)
        self.assertIsNone(self._item(None).parent)


if __name__ == "__main__":
    unittest.main()
