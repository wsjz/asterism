"""The project card: ``project.md`` and its YAML front matter.

Unlike the notes mirror, a project card is edited by hand in Obsidian, so its
front matter is idiomatic YAML that Obsidian's Properties panel understands
rather than the JSON-scalar form ``rendering`` writes for collected notes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..config import PROJECT_STATUSES


FRONT_MATTER_KEYS: tuple[str, ...] = (
    "id",
    "title",
    "pillar",
    "type",
    "status",
    "promise",
    "primary",
    "platforms",
    "scheduled",
    "created",
    "sources",
    "published",
    "notion",
)
PROJECT_FILE = "project.md"
BRIEF_FILE = "brief.md"

# What the person has to do next for a project in each status. The machine
# advances nothing on its own in this phase; these are the prompts shown by
# `status` and `week`.
NEXT_ACTION: dict[str, str] = {
    "candidate": "decide whether to make it",
    "making": "gather the material and write the draft",
    "ready": "confirm and publish it",
    "published": "wait for the retrospective",
    "retrospected": "nothing, it is done",
    "dropped": "restore it if you change your mind",
}


class ProjectError(ValueError):
    """A project card is missing, malformed, or holds an unusable value."""


def split_front_matter(text: str) -> tuple[str, str]:
    """Split ``---`` delimited YAML front matter from the body.

    Raises ``ProjectError`` when the document does not start with front
    matter or the block is not terminated.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        raise ProjectError("a project card must start with YAML front matter")
    end = normalized.find("\n---", 3)
    if end == -1:
        raise ProjectError("the front matter block is not terminated by ---")
    body_start = normalized.find("\n", end + 1)
    body = "" if body_start == -1 else normalized[body_start + 1 :].lstrip("\n")
    return normalized[4:end], body


@dataclass(frozen=True, slots=True)
class ContentProject:
    id: str
    title: str
    status: str = "candidate"
    pillar: str | None = None
    type: str | None = None
    promise: str | None = None
    primary: str | None = None
    platforms: tuple[str, ...] = ()
    scheduled: date | None = None
    created: date | None = None
    sources: tuple[str, ...] = ()
    published: Mapping[str, Any] = field(default_factory=dict)
    notion: str | None = None
    body: str = ""
    directory: Path | None = None  # where the card was loaded from; not front matter

    def __post_init__(self) -> None:
        _short(self.id, "id", required=True)
        _short(self.title, "title", required=True, limit=300)
        if self.status not in PROJECT_STATUSES:
            raise ProjectError(
                f"status {self.status!r} is not one of {', '.join(PROJECT_STATUSES)}"
            )
        for name in ("pillar", "type", "primary", "notion"):
            _short(getattr(self, name), name)
        _short(self.promise, "promise", limit=1000)
        for name in ("platforms", "sources"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(v, str) or not v for v in values):
                raise ProjectError(f"{name} must be a list of non-empty strings")
        for name in ("scheduled", "created"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, date):
                raise ProjectError(f"{name} must be a date such as 2026-09-22")
        if not isinstance(self.published, Mapping):
            raise ProjectError("published must be a mapping of platform to record")

    # --- reading -------------------------------------------------------------

    @classmethod
    def from_markdown(cls, text: str, *, directory: Path | None = None) -> ContentProject:
        raw, body = split_front_matter(text)
        try:
            loaded = yaml.safe_load(raw) or {}
        except yaml.YAMLError as error:
            raise ProjectError(f"the front matter is not valid YAML: {error}") from error
        if not isinstance(loaded, Mapping):
            raise ProjectError("the front matter must be a mapping")
        unknown = sorted(key for key in loaded if key not in FRONT_MATTER_KEYS)
        if unknown:
            raise ProjectError(
                f"unknown front matter keys: {', '.join(unknown)}; "
                f"known keys are {', '.join(FRONT_MATTER_KEYS)}"
            )
        return cls(
            id=str(loaded.get("id") or "").strip(),
            title=str(loaded.get("title") or "").strip(),
            status=str(loaded.get("status") or "candidate").strip(),
            pillar=_optional_str(loaded.get("pillar")),
            type=_optional_str(loaded.get("type")),
            promise=_optional_str(loaded.get("promise")),
            primary=_optional_str(loaded.get("primary")),
            platforms=_str_tuple(loaded.get("platforms"), "platforms"),
            scheduled=_optional_date(loaded.get("scheduled"), "scheduled"),
            created=_optional_date(loaded.get("created"), "created"),
            sources=_str_tuple(loaded.get("sources"), "sources"),
            published=dict(loaded.get("published") or {}),
            notion=_optional_str(loaded.get("notion")),
            body=body,
            directory=directory,
        )

    @classmethod
    def load(cls, directory: Path) -> ContentProject:
        card = directory / PROJECT_FILE
        try:
            text = card.read_text(encoding="utf-8")
        except OSError as error:
            raise ProjectError(f"{card} could not be read") from error
        except UnicodeDecodeError as error:
            raise ProjectError(f"{card} is not UTF-8") from error
        return cls.from_markdown(text, directory=directory)

    # --- writing -------------------------------------------------------------

    def front_matter(self) -> dict[str, Any]:
        values: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "pillar": self.pillar,
            "type": self.type,
            "status": self.status,
            "promise": self.promise,
            "primary": self.primary,
            "platforms": list(self.platforms),
            "scheduled": self.scheduled,
            "created": self.created,
            "sources": list(self.sources),
            "published": dict(self.published),
            "notion": self.notion,
        }
        return {key: values[key] for key in FRONT_MATTER_KEYS}

    def to_markdown(self) -> str:
        rendered = yaml.safe_dump(
            self.front_matter(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=1000,
        )
        body = self.body.strip()
        return f"---\n{rendered}---\n\n{body}\n" if body else f"---\n{rendered}---\n"

    def with_body(self, body: str) -> ContentProject:
        return replace(self, body=body)

    @property
    def is_dropped(self) -> bool:
        return self.status == "dropped"

    @property
    def is_published(self) -> bool:
        return self.status in ("published", "retrospected")

    def published_on(self, platform: str) -> bool:
        record = self.published.get(platform)
        return isinstance(record, Mapping) and bool(record.get("url") or record.get("at"))


def _short(value: Any, name: str, *, required: bool = False, limit: int = 200) -> None:
    if required and (not isinstance(value, str) or not value.strip()):
        raise ProjectError(f"{name} is required")
    if value is None:
        return
    if not isinstance(value, str) or len(value) > limit:
        raise ProjectError(f"{name} must be a string of at most {limit} characters")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_date(value: Any, name: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as error:
        raise ProjectError(f"{name} must be a date such as 2026-09-22") from error


def _str_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ProjectError(f"{name} must be a list")
    return tuple(str(item).strip() for item in value if str(item).strip())
