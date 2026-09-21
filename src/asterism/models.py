from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Mapping, TypeAlias


MetadataScalar: TypeAlias = str | int | float | bool | None

_SLUG = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


@dataclass(frozen=True, slots=True)
class Origin:
    """Where an item came from: which adapter and which upstream producer.

    ``adapter`` names the Asterism adapter (``apple_notes``, ``cubox``,
    ``opencli`` …). ``producer`` names the upstream program or channel the
    adapter read from (``osascript``, ``cubox-cli``, ``twitter/bookmarks``),
    and ``producer_version`` its version when known. Readers use these to
    judge who guarantees the item's semantics.
    """

    adapter: str
    producer: str | None = None
    producer_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, str) or _SLUG.fullmatch(self.adapter) is None:
            raise ValueError("origin.adapter must be a short lowercase slug")
        for name in ("producer", "producer_version"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip() or len(value) > 255 or "\n" in value
            ):
                raise ValueError(f"origin.{name} must be a short single-line string")

    def as_dict(self) -> dict[str, str]:
        result = {"adapter": self.adapter}
        if self.producer is not None:
            result["producer"] = self.producer
        if self.producer_version is not None:
            result["producer_version"] = self.producer_version
        return result


@dataclass(frozen=True, slots=True)
class SourceItem:
    source: str
    source_id: str
    title: str | None
    content_text: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    parent: str | None = None
    tags: tuple[str, ...] = ()
    source_meta: Mapping[str, MetadataScalar] = field(default_factory=dict)
    url: str | None = None
    author: str | None = None
    origin: Origin | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source or len(self.source) > 64:
            raise ValueError("source must contain 1 to 64 characters")
        if (
            not isinstance(self.source_id, str)
            or not self.source_id
            or len(self.source_id) > 4096
        ):
            raise ValueError("source_id must contain 1 to 4096 characters")
        if self.title is not None and (
            not isinstance(self.title, str) or len(self.title) > 10_000
        ):
            raise ValueError("title is unexpectedly long")
        if not isinstance(self.content_text, str) or len(self.content_text) > 50_000_000:
            raise ValueError("note body exceeds the 50 MB safety limit")
        if self.parent is not None and (
            not isinstance(self.parent, str) or len(self.parent) > 4096
        ):
            raise ValueError("parent is unexpectedly long")
        if len(self.tags) > 1000:
            raise ValueError("an item cannot contain more than 1000 tags")
        if any(
            not isinstance(tag, str) or not tag or len(tag) > 255
            for tag in self.tags
        ):
            raise ValueError("tags must be non-empty strings up to 255 characters")
        if len(self.source_meta) > 100:
            raise ValueError("source_meta cannot contain more than 100 fields")
        for key, value in self.source_meta.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError("source_meta keys must be short non-empty strings")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError("source_meta values must be JSON scalar values")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("source_meta numeric values must be finite")
            if isinstance(value, str) and len(value) > 10_000:
                raise ValueError("source_meta string value is unexpectedly long")
        if self.url is not None and (
            not isinstance(self.url, str)
            or not self.url.strip()
            or len(self.url) > 4096
            or any(character in self.url for character in "\r\n\t ")
        ):
            raise ValueError("url must be a single-line string without whitespace")
        if self.author is not None and (
            not isinstance(self.author, str) or not self.author.strip() or len(self.author) > 1000
        ):
            raise ValueError("author must be a short non-empty string")
        if self.origin is None:
            object.__setattr__(self, "origin", Origin(adapter=self.source))
        elif not isinstance(self.origin, Origin):
            raise ValueError("origin must be an Origin")


@dataclass(frozen=True, slots=True)
class ItemState:
    source: str
    source_id: str
    relative_path: str
    content_hash: str
    source_updated_at: str | None
    last_seen_at: str
    first_seen_at: str | None = None
    source_created_at: str | None = None
    title: str | None = None

    @property
    def digest_time(self) -> str | None:
        """The instant used to place the item in a digest period."""
        return self.source_created_at or self.first_seen_at


# A decision is recorded only once it is made; an item nobody has judged yet
# simply has no assignment.
ASSIGNMENT_DECISIONS: tuple[str, ...] = ("ignored", "promoted")


@dataclass(frozen=True, slots=True)
class Assignment:
    """What the person decided about one collected item."""

    source: str
    source_id: str
    decision: str
    decided_at: str
    project_id: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in ASSIGNMENT_DECISIONS:
            raise ValueError(f"decision must be one of {', '.join(ASSIGNMENT_DECISIONS)}")
        if self.decision == "promoted" and not self.project_id:
            raise ValueError("a promoted item must name the project it became")


DIGEST_LEVELS: tuple[str, ...] = ("day", "week", "month", "year")
DIGEST_STATES: tuple[str, ...] = ("open", "closed", "rolled", "archived")


@dataclass(frozen=True, slots=True)
class DigestState:
    level: str
    period_start: str  # ISO date, inclusive
    period_end: str  # ISO date, inclusive
    relative_path: str
    state: str
    generated_at: str

    def __post_init__(self) -> None:
        if self.level not in DIGEST_LEVELS:
            raise ValueError("unknown digest level")
        if self.state not in DIGEST_STATES:
            raise ValueError("unknown digest state")


@dataclass(frozen=True, slots=True)
class SyncResult:
    discovered: int
    created: int
    updated: int
    unchanged: int
    missing: int
    dry_run: bool
