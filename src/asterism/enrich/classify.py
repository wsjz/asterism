"""Assigning a collected item to a content pillar by rule.

Only the aliases configured under ``content.pillars`` decide this. An item
that matches nothing stays unclassified and is shown that way, because a
guessed pillar is worse than an empty one the person fills in.
"""
from __future__ import annotations

from pathlib import Path
import re

from ..config import Config, Pillar
from ..models import ItemState
from ..rendering import parse_front_matter


def item_facets(vault: Path, relative_path: str) -> tuple[tuple[str, ...], str | None]:
    """The tags and parent of a collected note, read from its front matter."""
    try:
        fields, _ = parse_front_matter((vault / relative_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return (), None
    raw_tags = fields.get("tags")
    tags = tuple(str(tag) for tag in raw_tags if str(tag).strip()) if isinstance(raw_tags, list) else ()
    parent = fields.get("parent")
    return tags, parent if isinstance(parent, str) and parent.strip() else None


def classify(pillars: tuple[Pillar, ...], tags: tuple[str, ...], parent: str | None) -> str | None:
    """The first pillar whose aliases match a tag or folder segment."""
    segments = {segment.strip().casefold() for tag in tags for segment in tag.split("/") if segment.strip()}
    if parent:
        segments.update(segment.strip().casefold() for segment in parent.split("/") if segment.strip())
    for pillar in pillars:
        if any(alias.casefold() in segments for alias in pillar.tags):
            return pillar.key
    return None


def classify_item(config: Config, item: ItemState) -> str | None:
    tags, parent = item_facets(config.vault, item.relative_path)
    return classify(config.content.pillars, tags, parent)


def classify_text(pillars: tuple[Pillar, ...], text: str) -> str | None:
    """The first pillar whose alias appears in a line the person wrote.

    This is for a topic heading — "CLI 设计" — where the aliases cannot be whole
    segments of anything. It is still not a guess: the alias is one the person
    configured, and it has to be there in full. An alias written in ASCII must
    match a whole word, so ``cli`` does not claim ``client``; one with other
    scripts matches anywhere, because they are written without word breaks.
    """
    if not text.strip():
        return None
    for pillar in pillars:
        for alias in pillar.tags:
            if not alias.strip():
                continue
            if alias.isascii():
                if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
                    return pillar.key
            elif alias in text:
                return pillar.key
    return None
