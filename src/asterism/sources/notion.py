from __future__ import annotations

import json
import os
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

from ..models import Origin, SourceItem
from ..normalize import derive_title
from .base import Source, SourceError
from .utils import parse_datetime


NOTION_API_VERSION = "2026-03-11"
_MAX_RESPONSE_BYTES = 50 * 1024 * 1024
APITransport = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


class NotionSource(Source):
    name = "notion"
    output_name = "notion"
    origin = Origin(adapter="notion", producer="api")

    def __init__(
        self,
        *,
        root_page_ids: tuple[str, ...] = (),
        data_source_ids: tuple[str, ...] = (),
        discover_all: bool = False,
        transport: APITransport | None = None,
    ) -> None:
        self.root_page_ids = tuple(_normalize_id(value, "root page") for value in root_page_ids)
        self.data_source_ids = tuple(
            _normalize_id(value, "data source") for value in data_source_ids
        )
        self.discover_all = discover_all
        if not self.root_page_ids and not self.data_source_ids and not discover_all:
            raise ValueError(
                "configure Notion root_page_ids or data_source_ids, or explicitly set discover_all = true"
            )
        if transport is None:
            api_token = os.environ.get("ASTERISM_NOTION_TOKEN")
            if not api_token:
                raise SourceError("ASTERISM_NOTION_TOKEN is not set")
            if len(api_token) > 4096 or "\n" in api_token or "\r" in api_token:
                raise SourceError("ASTERISM_NOTION_TOKEN has an invalid format")
            self._transport = _NotionHTTPTransport(api_token)
        else:
            self._transport = transport

    def collect(self) -> list[SourceItem]:
        parents: dict[str, str | None] = {
            page_id: None for page_id in self.root_page_ids
        }
        pending_pages = list(self.root_page_ids)
        pending_data_sources = list(self.data_source_ids)
        seen_data_sources: set[str] = set()

        if self.discover_all:
            for page in self._paginate(
                "POST",
                "/v1/search",
                {"filter": {"property": "object", "value": "page"}},
            ):
                page_id = _object_id(page, "Notion search")
                if page_id not in parents:
                    parents[page_id] = _parent_label(page.get("parent"))
                    pending_pages.append(page_id)

        while pending_data_sources:
            data_source_id = pending_data_sources.pop(0)
            if data_source_id in seen_data_sources:
                continue
            seen_data_sources.add(data_source_id)
            for page in self._paginate(
                "POST", f"/v1/data_sources/{data_source_id}/query", {}
            ):
                page_id = _object_id(page, "Notion data source query")
                if page_id not in parents:
                    parents[page_id] = f"data-source:{data_source_id}"
                    pending_pages.append(page_id)

        items: list[SourceItem] = []
        collected: set[str] = set()
        while pending_pages:
            page_id = pending_pages.pop(0)
            if page_id in collected:
                continue
            page = self._request("GET", f"/v1/pages/{page_id}")
            title = _page_title(page)
            markdown = self._request("GET", f"/v1/pages/{page_id}/markdown")
            items.append(_page_item(page_id, page, markdown, title, parents[page_id]))
            collected.add(page_id)

            current_name = title or page_id
            current_parent = parents[page_id]
            current_path = (
                f"{current_parent}/{current_name}" if current_parent else current_name
            )
            resources = self._child_resources(page_id)
            for resource_type, child_id, child_title in resources:
                if resource_type == "page" and child_id not in parents:
                    parents[child_id] = current_path
                    pending_pages.append(child_id)
            for resource_type, database_id, _ in resources:
                if resource_type != "database":
                    continue
                database = self._request("GET", f"/v1/databases/{database_id}")
                raw_sources = database.get("data_sources", [])
                if not isinstance(raw_sources, list):
                    raise SourceError("Notion database returned invalid data_sources")
                for raw_source in raw_sources:
                    source_id = _object_id(raw_source, "Notion database")
                    if source_id not in seen_data_sources:
                        pending_data_sources.append(source_id)

            while pending_data_sources:
                data_source_id = pending_data_sources.pop(0)
                if data_source_id in seen_data_sources:
                    continue
                seen_data_sources.add(data_source_id)
                for child in self._paginate(
                    "POST", f"/v1/data_sources/{data_source_id}/query", {}
                ):
                    child_id = _object_id(child, "Notion data source query")
                    if child_id not in parents:
                        parents[child_id] = f"data-source:{data_source_id}"
                        pending_pages.append(child_id)
        return items

    def _child_resources(self, page_id: str) -> list[tuple[str, str, str | None]]:
        resources: list[tuple[str, str, str | None]] = []
        pending_blocks = [page_id]
        visited: set[str] = set()
        while pending_blocks:
            block_id = pending_blocks.pop()
            if block_id in visited:
                continue
            visited.add(block_id)
            for block in self._paginate("GET", f"/v1/blocks/{block_id}/children", None):
                block_type = block.get("type")
                resource_id = _object_id(block, "Notion block")
                if block_type == "child_page":
                    child = block.get("child_page", {})
                    title = child.get("title") if isinstance(child, dict) else None
                    resources.append(
                        ("page", resource_id, title if isinstance(title, str) else None)
                    )
                elif block_type == "child_database":
                    resources.append(("database", resource_id, None))
                elif block.get("has_children") is True:
                    pending_blocks.append(resource_id)
        return resources

    def _paginate(
        self, method: str, path: str, payload: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body = dict(payload or {})
            request_path = path
            if method == "GET":
                query: dict[str, str | int] = {"page_size": 100}
                if cursor:
                    query["start_cursor"] = cursor
                request_path = f"{path}?{urlencode(query)}"
                response = self._request(method, request_path)
            else:
                body["page_size"] = 100
                if cursor:
                    body["start_cursor"] = cursor
                response = self._request(method, request_path, body)
            page_results = response.get("results")
            if not isinstance(page_results, list) or any(
                not isinstance(item, dict) for item in page_results
            ):
                raise SourceError("Notion returned an invalid paginated response")
            results.extend(page_results)
            if response.get("has_more") is not True:
                break
            cursor_value = response.get("next_cursor")
            if not isinstance(cursor_value, str) or not cursor_value or len(cursor_value) > 4096:
                raise SourceError("Notion returned an invalid pagination cursor")
            cursor = cursor_value
        return results

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._transport(method, path, payload)
        if not isinstance(response, dict):
            raise SourceError("Notion returned a non-object response")
        return response


class _NotionHTTPTransport:
    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(
        self, method: str, path: str, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not path.startswith("/v1/") or "\\" in path or " " in path:
            raise SourceError("refusing an unsafe Notion API path")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        raw: bytes | None = None
        for attempt in range(3):
            request = Request(
                "https://api.notion.com" + path,
                data=body,
                method=method,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Notion-Version": NOTION_API_VERSION,
                    "Content-Type": "application/json",
                },
            )
            try:
                with urlopen(request, timeout=60) as response:
                    raw = response.read(_MAX_RESPONSE_BYTES + 1)
                break
            except HTTPError as error:
                if error.code == 429 and attempt < 2:
                    retry_after = error.headers.get("Retry-After", "1")
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = 1.0
                    time.sleep(min(max(delay, 0.0), 10.0))
                    continue
                raise SourceError(
                    f"Notion API request failed with HTTP {error.code}"
                ) from error
            except (URLError, TimeoutError, OSError) as error:
                raise SourceError("Notion API request failed") from error
        if raw is None:
            raise SourceError("Notion API request failed after rate-limit retries")
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise SourceError("Notion API response exceeds the 50 MB safety limit")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceError("Notion API returned malformed JSON") from error
        if not isinstance(decoded, dict):
            raise SourceError("Notion API returned a non-object response")
        return decoded


def _normalize_id(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError(f"Notion {label} IDs must be UUIDs") from error


def _object_id(value: Any, label: str) -> str:
    if not isinstance(value, dict):
        raise SourceError(f"{label} returned an invalid object")
    identifier = value.get("id")
    if not isinstance(identifier, str):
        raise SourceError(f"{label} returned an invalid identifier")
    try:
        return _normalize_id(identifier, label)
    except ValueError as error:
        raise SourceError(f"{label} returned an invalid identifier") from error


def _page_title(page: dict[str, Any]) -> str | None:
    properties = page.get("properties", {})
    if not isinstance(properties, dict):
        raise SourceError("Notion page returned invalid properties")
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _rich_text(prop.get("title")) or None
    return None


def _page_tags(page: dict[str, Any]) -> tuple[str, ...]:
    properties = page.get("properties", {})
    tags: list[str] = []
    if not isinstance(properties, dict):
        return ()
    for prop in properties.values():
        if not isinstance(prop, dict) or prop.get("type") != "multi_select":
            continue
        values = prop.get("multi_select", [])
        if not isinstance(values, list):
            raise SourceError("Notion page returned invalid multi-select tags")
        for value in values:
            name = value.get("name") if isinstance(value, dict) else None
            if not isinstance(name, str) or not name or len(name) > 255:
                raise SourceError("Notion page returned an invalid tag")
            tags.append(name)
    return tuple(dict.fromkeys(tags))


def _rich_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for segment in value:
        text = segment.get("plain_text") if isinstance(segment, dict) else None
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)[:10_000]


def _page_item(
    page_id: str,
    page: dict[str, Any],
    markdown: dict[str, Any],
    title: str | None,
    parent: str | None,
) -> SourceItem:
    if markdown.get("object") != "page_markdown":
        raise SourceError("Notion returned an invalid page Markdown object")
    content = markdown.get("markdown")
    if not isinstance(content, str):
        raise SourceError("Notion returned invalid page Markdown")
    raw_parent = page.get("parent")
    parent_type = raw_parent.get("type") if isinstance(raw_parent, dict) else None
    metadata: dict[str, str | bool] = {}
    for key, value in {
        "parent_type": parent_type,
        "archived": page.get("archived"),
        "in_trash": page.get("in_trash"),
        "truncated": markdown.get("truncated"),
    }.items():
        if isinstance(value, (str, bool)):
            metadata[key] = value
    page_url = page.get("url") if isinstance(page.get("url"), str) else None
    return SourceItem(
        source="notion",
        source_id=page_id,
        title=derive_title(title, content, page_url),
        content_text=content,
        created_at=parse_datetime(page.get("created_time"), "Notion"),
        updated_at=parse_datetime(page.get("last_edited_time"), "Notion"),
        parent=parent,
        tags=_page_tags(page),
        source_meta=metadata,
        url=page_url,
        origin=NotionSource.origin,
    )


def _parent_label(parent: Any) -> str | None:
    if not isinstance(parent, dict):
        return None
    parent_type = parent.get("type")
    identifier = parent.get(parent_type) if isinstance(parent_type, str) else None
    if isinstance(identifier, str):
        try:
            identifier = _normalize_id(identifier, "parent")
        except ValueError:
            return None
        return f"{parent_type}:{identifier}"
    return None
