from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any
import unicodedata

from .models import SourceItem


SCHEMA_VERSION = 1

_WHITESPACE = re.compile(r"\s+")
MAX_FILENAME_CHARS = 80
UNTITLED = "Untitled"
_UNSAFE_FILENAME_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f\x7f]+")
_SUFFIX = re.compile(r" \((\d+)\)$")
_FRONT_MATTER_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*): (.*)$")


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def content_hash(rendered: str) -> str:
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


MAX_HIERARCHY_DEPTH = 12


def note_relative_dir(item: SourceItem) -> str:
    """Mirror the item's ``parent`` hierarchy as safe directory segments.

    ``parent`` is split on ``/``; each segment keeps its case and Unicode
    letters, replaces unsafe characters with ``-``, and is capped at 80
    characters. Empty or dot-only segments are dropped, so no segment can be
    ``.`` or ``..``. Returns ``""`` when the item has no hierarchy.
    """
    if not item.parent:
        return ""
    segments: list[str] = []
    for raw in item.parent.split("/"):
        cleaned = unicodedata.normalize("NFKC", raw).strip()
        cleaned = _WHITESPACE.sub(" ", cleaned)
        cleaned = _UNSAFE_FILENAME_CHARS.sub("-", cleaned).strip("-._ ")[:80]
        if cleaned:
            segments.append(cleaned)
        if len(segments) == MAX_HIERARCHY_DEPTH:
            break
    return "/".join(segments)




def note_filename(item: SourceItem) -> str:
    """The file name a new item would get: its cleaned title plus ``.md``.

    The title keeps its case and spaces; only characters that file systems
    reject are replaced. Collisions inside one directory are resolved by the
    pipeline with ``unique_filename``, and a name is fixed once recorded in
    state, so later title changes do not rename files.
    """
    return f"{clean_title_for_filename(item.title)}.md"


def clean_title_for_filename(title: str | None) -> str:
    text = unicodedata.normalize("NFKC", title or "")
    text = _UNSAFE_FILENAME_CHARS.sub("-", text)
    text = _WHITESPACE.sub(" ", text).strip(" .-")
    if len(text) > MAX_FILENAME_CHARS:
        text = text[:MAX_FILENAME_CHARS].rstrip(" .-")
    return text or UNTITLED


def unique_filename(filename: str, taken: set[str]) -> str:
    """Return ``filename`` or the first ``name (n).md`` not present in ``taken``."""
    if filename not in taken:
        return filename
    stem, suffix = (filename[:-3], ".md") if filename.endswith(".md") else (filename, "")
    stem = _SUFFIX.sub("", stem)
    counter = 2
    while f"{stem} ({counter}){suffix}" in taken:
        counter += 1
    return f"{stem} ({counter}){suffix}"


def front_matter_fields(item: SourceItem) -> list[tuple[str, object]]:
    """The front matter keys in their fixed rendering order."""
    origin = item.origin.as_dict() if item.origin is not None else {"adapter": item.source}
    return [
        ("schema", SCHEMA_VERSION),
        ("source", item.source),
        ("source_id", item.source_id),
        ("origin", origin),
        ("title", item.title),
        ("url", item.url),
        ("author", item.author),
        ("parent", item.parent),
        ("tags", list(item.tags)),
        ("created_at", _isoformat(item.created_at)),
        ("updated_at", _isoformat(item.updated_at)),
        ("source_meta", dict(sorted(item.source_meta.items()))),
    ]


def render_markdown(item: SourceItem) -> str:
    # JSON syntax is valid YAML for these values and safely quotes untrusted
    # titles, parent paths, and identifiers without another dependency.
    front_matter = ["---"]
    for key, value in front_matter_fields(item):
        encoded = json.dumps(value, ensure_ascii=False)
        front_matter.append(f"{key}: {encoded}")
    front_matter.extend(("---", ""))

    body = item.content_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return "\n".join(front_matter) + body + "\n"


def parse_front_matter(rendered: str) -> tuple[dict[str, Any], str]:
    """Read back a document written by ``render_markdown``.

    Only the format Asterism writes is accepted: one ``key: <json>`` per line
    between ``---`` markers. Raises ``ValueError`` for anything else.
    """
    if not rendered.startswith("---\n"):
        raise ValueError("document does not start with front matter")
    end = rendered.find("\n---\n", 4)
    if end == -1:
        raise ValueError("front matter is not terminated")
    fields: dict[str, Any] = {}
    for line in rendered[4:end].splitlines():
        match = _FRONT_MATTER_LINE.match(line)
        if match is None:
            raise ValueError(f"unreadable front matter line: {line[:40]!r}")
        key, raw_value = match.groups()
        try:
            fields[key] = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ValueError(f"front matter value for {key} is not JSON") from error
    body = rendered[end + len("\n---\n"):]
    return fields, body
