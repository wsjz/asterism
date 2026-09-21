"""Apply a collection's field mapping to one opencli row."""
from __future__ import annotations

import json
from typing import Any

from ...config import OpencliCollection
from ...models import MetadataScalar, Origin, SourceItem
from ...normalize import canonical_url, derive_title, html_to_markdown, parse_datetime
from ..base import SourceError


def map_row(row: dict[str, Any], collection: OpencliCollection, source_name: str, origin: Origin) -> SourceItem:
    mapping = collection.map
    url = _text(row, mapping.url)
    if url is not None:
        try:
            url = canonical_url(url)
        except ValueError:
            url = None if not url.strip() else url.strip()

    raw_id = _text(row, mapping.id)
    if raw_id:
        source_id = raw_id
    elif url:
        source_id = url
    else:
        raise SourceError(
            f"opencli {collection.producer} row has no {mapping.id or mapping.url or 'id'}; "
            "every row needs an id or url to be collected"
        )

    parts = [text for field in mapping.content if (text := _text(row, field))]
    content = "\n\n".join(parts)
    if mapping.content_format == "html" and content:
        try:
            content = html_to_markdown(content)
        except ValueError:
            pass

    tags: tuple[str, ...] = ()
    raw_tags = row.get(mapping.tags) if mapping.tags else None
    if isinstance(raw_tags, list):
        tags = tuple(dict.fromkeys(str(tag).strip() for tag in raw_tags if str(tag).strip()))
    elif isinstance(raw_tags, str):
        tags = tuple(dict.fromkeys(part.strip() for part in raw_tags.split(mapping.tag_separator) if part.strip()))

    used = set(mapping.mapped_fields()) | set(mapping.exclude)
    metadata: dict[str, MetadataScalar] = {"opencli_command": collection.producer}
    for key, value in row.items():
        if key in used or not isinstance(key, str) or not key:
            continue
        if len(metadata) >= 100:
            break
        metadata[key[:128]] = _scalar(value)

    return SourceItem(
        source=source_name,
        source_id=source_id[:4096],
        title=derive_title(_text(row, mapping.title), content, url),
        content_text=content,
        created_at=_moment(row.get(mapping.created_at) if mapping.created_at else None),
        updated_at=_moment(row.get(mapping.updated_at) if mapping.updated_at else None),
        parent=_text(row, mapping.parent),
        tags=tags[:1000],
        source_meta=metadata,
        url=url,
        author=_text(row, mapping.author),
        origin=origin,
    )


def _text(row: dict[str, Any], field: str | None) -> str | None:
    if not field:
        return None
    value = row.get(field)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:50_000_000] or None


def _moment(value: Any):
    """Tolerant timestamp parsing: anything unreadable becomes None."""
    try:
        return parse_datetime(value)
    except ValueError:
        return None


def _scalar(value: Any) -> MetadataScalar:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        return value[:10_000]
    try:
        return json.dumps(value, ensure_ascii=False)[:10_000]
    except (TypeError, ValueError):
        return str(value)[:10_000]
