from email.message import Message
import io
from typing import Any
import unittest
from unittest import mock
from urllib.error import HTTPError

from asterism.sources.base import SourceError
from asterism.sources.notion import NotionSource, _NotionHTTPTransport


ROOT_ID = "11111111-1111-1111-1111-111111111111"
CHILD_ID = "22222222-2222-2222-2222-222222222222"


def page(page_id: str, title: str) -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "url": f"https://www.notion.so/{page_id}",
        "created_time": "2026-09-20T10:00:00Z",
        "last_edited_time": "2026-09-21T10:00:00Z",
        "archived": False,
        "in_trash": False,
        "parent": {"type": "workspace", "workspace": True},
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": title}],
            },
            "Tags": {
                "type": "multi_select",
                "multi_select": [{"name": "Research"}],
            },
        },
    }


class NotionSourceTest(unittest.TestCase):
    def test_collects_scoped_root_and_descendant_as_markdown(self) -> None:
        calls: list[tuple[str, str, dict[str, Any] | None]] = []

        def transport(
            method: str, path: str, payload: dict[str, Any] | None
        ) -> dict[str, Any]:
            calls.append((method, path, payload))
            if path == f"/v1/pages/{ROOT_ID}":
                return page(ROOT_ID, "Root")
            if path == f"/v1/pages/{CHILD_ID}":
                return page(CHILD_ID, "Child")
            if path.endswith("/markdown"):
                return {
                    "object": "page_markdown",
                    "markdown": "# Content\n",
                    "truncated": False,
                    "unknown_block_ids": [],
                }
            if path.startswith(f"/v1/blocks/{ROOT_ID}/children?"):
                return {
                    "results": [
                        {
                            "id": CHILD_ID,
                            "type": "child_page",
                            "child_page": {"title": "Child"},
                            "has_children": True,
                        }
                    ],
                    "has_more": False,
                    "next_cursor": None,
                }
            if path.startswith(f"/v1/blocks/{CHILD_ID}/children?"):
                return {"results": [], "has_more": False, "next_cursor": None}
            raise AssertionError(f"unexpected request: {method} {path}")

        items = NotionSource(root_page_ids=(ROOT_ID,), transport=transport).collect()

        self.assertEqual([ROOT_ID, CHILD_ID], [item.source_id for item in items])
        self.assertEqual("Root", items[1].parent)
        self.assertEqual(("Research",), items[0].tags)
        self.assertEqual("# Content\n", items[0].content_text)
        self.assertTrue(any("/markdown" in path for _, path, _ in calls))

    def test_requires_an_explicit_scope_by_default(self) -> None:
        with self.assertRaises(ValueError):
            NotionSource(transport=lambda method, path, payload: {})

class NotionHardeningTest(unittest.TestCase):
    def test_paginates_children_with_cursor(self) -> None:
        second = "33333333-3333-3333-3333-333333333333"
        seen_cursors: list[str] = []

        def transport(method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
            if path.endswith("/markdown"):
                return {"object": "page_markdown", "markdown": "x", "truncated": False, "unknown_block_ids": []}
            if path.startswith("/v1/pages/"):
                page_id = path.rsplit("/", 1)[1]
                return page(page_id, f"Page {page_id[:1]}")
            if path.startswith(f"/v1/blocks/{ROOT_ID}/children?"):
                if "start_cursor=" in path:
                    seen_cursors.append(path.split("start_cursor=", 1)[1].split("&", 1)[0])
                    return {"results": [{"id": second, "type": "child_page", "child_page": {"title": "Two"}, "has_children": False}], "has_more": False, "next_cursor": None}
                return {"results": [{"id": CHILD_ID, "type": "child_page", "child_page": {"title": "One"}, "has_children": False}], "has_more": True, "next_cursor": "cursor-2"}
            return {"results": [], "has_more": False, "next_cursor": None}

        items = NotionSource(root_page_ids=(ROOT_ID,), transport=transport).collect()
        self.assertEqual([ROOT_ID, CHILD_ID, second], [item.source_id for item in items])
        self.assertEqual(["cursor-2"], seen_cursors)

    def test_malformed_payloads_raise_source_error(self) -> None:
        def transport(method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
            if path.endswith("/markdown"):
                return {"object": "page_markdown", "markdown": 42}
            if path.startswith("/v1/pages/"):
                return page(ROOT_ID, "Root")
            return {"results": [], "has_more": False, "next_cursor": None}

        with self.assertRaises(SourceError):
            NotionSource(root_page_ids=(ROOT_ID,), transport=transport).collect()

    def test_http_transport_retries_on_429_then_succeeds(self) -> None:
        headers = Message()
        headers["Retry-After"] = "0"
        attempts: list[int] = []

        def fake_urlopen(request, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 429, "Too Many Requests", headers, io.BytesIO(b""))
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = b'{"ok": true}'
            return response

        with mock.patch("asterism.sources.notion.urlopen", fake_urlopen), mock.patch("asterism.sources.notion.time.sleep") as sleep:
            result = _NotionHTTPTransport("token")("GET", "/v1/pages/x", None)
        self.assertEqual({"ok": True}, result)
        self.assertEqual(2, len(attempts))
        sleep.assert_called_once()

    def test_http_transport_rejects_unsafe_paths_and_other_errors(self) -> None:
        transport = _NotionHTTPTransport("token")
        with self.assertRaises(SourceError):
            transport("GET", "/etc/passwd", None)
        headers = Message()

        def failing(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", headers, io.BytesIO(b""))

        with mock.patch("asterism.sources.notion.urlopen", failing):
            with self.assertRaises(SourceError) as raised:
                transport("GET", "/v1/pages/x", None)
        self.assertNotIn("token", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
