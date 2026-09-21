from __future__ import annotations

import re
from urllib.parse import urlsplit

from .punctuation import EM_DASH, EN_DASH, FULLWIDTH_COLON, SENTENCE_ENDS


MAX_TITLE_CHARS = 60

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)]|>)+\s*")
_LEADING_TIME = re.compile(r"^\s*(?:\d{4}-\d{2}-\d{2}[ T])?\d{1,2}:\d{2}(?::\d{2})?\s*[-–—:]?\s*")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\((?:https?://|mailto:)[^)]*\)")
_BARE_URL = re.compile(r"https?://\S+")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)")
_SENTENCE_END = re.compile(f"[{re.escape(SENTENCE_ENDS)}]")
_WHITESPACE = re.compile(r"\s+")


def derive_title(native: str | None, body: str, url: str | None = None) -> str | None:
    """Apply the shared title rule.

    1. A non-empty native title wins unchanged (trimmed).
    2. Otherwise the first Markdown heading in ``body``.
    3. Otherwise the first non-empty line of ``body``, with list markers,
       a leading timestamp, and bare URLs removed, cut at the first sentence
       end or ``MAX_TITLE_CHARS`` characters.
    4. Otherwise the URL's host and last path segment.
    5. Otherwise ``None``.
    """
    if native is not None:
        cleaned = _WHITESPACE.sub(" ", native).strip()
        if cleaned:
            return cleaned

    for line in body.splitlines():
        heading = _HEADING.match(line)
        if heading:
            candidate = _clean(heading.group(1))
            if candidate:
                return candidate
            break

    for line in body.splitlines():
        if not line.strip():
            continue
        candidate = _clean(_LEADING_TIME.sub("", _LIST_MARKER.sub("", line), count=1))
        if candidate:
            return _cut(candidate)
        break

    if url:
        try:
            parts = urlsplit(url)
        except ValueError:
            parts = None
        if parts and parts.netloc:
            segment = parts.path.rstrip("/").rsplit("/", 1)[-1]
            return f"{parts.netloc}/{segment}" if segment else parts.netloc

    return None


def _clean(text: str) -> str:
    text = _MARKDOWN_LINK.sub(lambda match: match.group(1), text)
    text = _BARE_URL.sub("", text)
    text = _EMPHASIS.sub("", text)
    return _WHITESPACE.sub(" ", text).strip(" \t-:" + EN_DASH + EM_DASH + FULLWIDTH_COLON)


def _cut(text: str) -> str:
    match = _SENTENCE_END.search(text)
    if match and match.start() > 0:
        text = text[: match.start()]
    text = text.strip()
    if len(text) > MAX_TITLE_CHARS:
        text = text[:MAX_TITLE_CHARS].rstrip()
    return text
