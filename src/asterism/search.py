"""Plain text search across everything the vault holds.

Two questions come up constantly while writing and neither had an answer: *when
did I first write this down?* and *have I already published something about it?*
Both are the same lookup over different directories, and neither needs anything
cleverer than a substring — the vault is Markdown, and the writer knows the word
they are looking for.

The answer is a list of notes, not of lines. A trial run that searched for a
tag got seven lines back, six of them front matter, and the one line of prose
was buried; one long article matching five times filled a quarter of the list
on its own. Front matter is left out unless asked for, and the lines of one
note travel together under its date.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .rendering import parse_front_matter


SCOPES: tuple[str, ...] = ("notes", "content", "digest", "all")
MAX_SNIPPET = 120
ORIGIN = "origin"  # what was collected, as opposed to the rollups over it
WRITING = ("draft.md",)  # what the person wrote, as opposed to the material it quotes
EXPORTS = "exports"


@dataclass(frozen=True, slots=True)
class Hit:
    path: str  # vault-relative
    line: int  # 1-based
    text: str


@dataclass(frozen=True, slots=True)
class Match:
    """One note and every line of it that matched."""

    path: str  # vault-relative
    day: str  # the note's created_at, as a date, or ""
    lines: tuple[Hit, ...]

    @property
    def title(self) -> str:
        return Path(self.path).stem


def search(
    config: Config, needle: str, *, scope: str = "all", limit: int = 50, meta: bool = False
) -> list[Hit]:
    """Every line containing ``needle``, case-insensitive, oldest path first.

    Front matter is skipped unless ``meta`` is set: a tag or a folder name is
    in every note's header, and a search for it should find the prose that
    uses it, not the header that files it.
    """
    return [hit for match in search_notes(config, needle, scope=scope, limit=limit, meta=meta) for hit in match.lines]


def search_notes(
    config: Config, needle: str, *, scope: str = "all", limit: int = 50, meta: bool = False
) -> list[Match]:
    """The notes containing ``needle``, each with its matching lines; ``limit`` counts notes."""
    if not needle.strip():
        raise ValueError("search for something: `asterism find <text>`")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    wanted = needle.lower()
    found: list[Match] = []
    for root in _roots(config, scope):
        for path in sorted(root.rglob("*.md")):
            if len(found) >= limit:
                return found
            if root == config.projects_root and not _is_writing(path):
                continue
            match = _match_in(config, path, wanted, meta)
            if match is not None:
                found.append(match)
    return found


def _is_writing(path: Path) -> bool:
    """A draft or an export, not a brief.

    A brief holds the quoted material, so searching it returns the collected
    notes a second time. "Have I written about this before" is a question about
    the prose, and the prose is the draft and what was adapted from it.
    """
    return path.name.endswith(WRITING) or EXPORTS in path.parts


def _roots(config: Config, scope: str) -> list[Path]:
    """Where to look.

    Digests are rollups of the notes beneath them, so searching both returns
    the same line three or four times and buries the one copy that has a date
    on it. They are their own scope, asked for on purpose.
    """
    notes = sorted(config.notes_root.glob(f"*/{ORIGIN}")) if config.notes_root.is_dir() else []
    digests = sorted(config.notes_root.glob("*/digest")) if config.notes_root.is_dir() else []
    roots = {
        "notes": notes,
        "content": [config.projects_root],
        "digest": digests,
        "all": [*notes, config.projects_root],
    }[scope]
    return [root for root in roots if root.is_dir()]


def _match_in(config: Config, path: Path, wanted: str, meta: bool) -> Match | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    day = ""
    skip_until = 0  # the last line number of the front matter, when there is one
    try:
        fields, body = parse_front_matter(text)
    except ValueError:
        pass
    else:
        day = str(fields.get("created_at") or "")[:10]
        if not meta:
            skip_until = text[: len(text) - len(body)].count("\n")
    relative = path.relative_to(config.vault).as_posix()
    found = [
        Hit(path=relative, line=number, text=_snippet(line))
        for number, line in enumerate(text.splitlines(), 1)
        if number > skip_until and wanted in line.lower()
    ]
    return Match(path=relative, day=day, lines=tuple(found)) if found else None


def _snippet(line: str) -> str:
    stripped = line.strip().lstrip("> ").strip()
    return stripped if len(stripped) <= MAX_SNIPPET else stripped[:MAX_SNIPPET].rstrip() + "..."
