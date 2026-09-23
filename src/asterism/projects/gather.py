"""Bringing already-collected material into a project.

Sorting offers each item once; a piece assembled later — a monthly report, a
retrospective, anything whose material was filed long before the piece was
thought of — needs a way to pull that material in afterwards.

Gathering never changes what was decided about an item. A note filed as
``reference`` stays ``reference`` when a piece quotes it: ``sources`` on the
card is what carries many fragments into one piece, and the assignment is only
the record that the note was seen and decided.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import re

from ..config import Config
from ..models import ItemState
from ..state.base import StateBackend
from ..vault import atomic_write
from .model import BRIEF_FILE, PROJECT_FILE, Project, ProjectError
from .scaffold import quote_sources
from .stages import find_artifact


MATERIAL_HEADING = "## Source fragments"
_HEADING = re.compile(r"^##\s+")


@dataclass(frozen=True, slots=True)
class Gathered:
    project: Project
    added: tuple[str, ...]
    already: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added)


def matching_items(
    state: StateBackend,
    *,
    prefix: str,
    since: date | None = None,
    until: date | None = None,
) -> list[ItemState]:
    """Collected items under ``prefix``, oldest first, inside the window."""
    found: list[tuple[date | None, str, ItemState]] = []
    for source in sorted(state.sources()):
        for item in state.items(source):
            if not _under(item.relative_path, prefix):
                continue
            day = _day(item)
            if since is not None and (day is None or day < since):
                continue
            if until is not None and (day is None or day > until):
                continue
            found.append((day, item.relative_path, item))
    found.sort(key=lambda entry: (entry[0] or date.min, entry[1]))
    return [item for _day, _path, item in found]


def _under(relative_path: str, prefix: str) -> bool:
    cleaned = prefix.strip("/")
    return relative_path == cleaned or relative_path.startswith(cleaned + "/")


def _day(item: ItemState) -> date | None:
    moment = item.digest_time
    if not moment:
        return None
    try:
        return date.fromisoformat(moment[:10])
    except ValueError:
        return None


def gather_into(
    config: Config,
    state: StateBackend,
    project: Project,
    *,
    prefix: str,
    since: date | None = None,
    until: date | None = None,
    dry_run: bool = False,
) -> Gathered:
    """Append the matching material to the project and rewrite the brief's quotes.

    Material already on the card is reported and left where it is, so running
    this twice adds nothing and never reorders what is there.
    """
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    items = matching_items(state, prefix=prefix, since=since, until=until)
    if not items:
        raise ProjectError(
            f"no collected item under {prefix!r}"
            + (f" since {since.isoformat()}" if since else "")
            + (f" until {until.isoformat()}" if until else "")
        )
    known = set(project.sources)
    added = tuple(item.relative_path for item in items if item.relative_path not in known)
    already = tuple(item.relative_path for item in items if item.relative_path in known)
    if dry_run or not added:
        return Gathered(project=project, added=added, already=already)

    gathered = replace(project, sources=project.sources + added)
    card = find_artifact(config.project, project.directory, PROJECT_FILE)
    atomic_write(card, gathered.to_markdown())
    _rewrite_material(config, gathered, card)
    return Gathered(project=gathered, added=added, already=already)


def _rewrite_material(config: Config, project: Project, card) -> None:
    """Replace the brief's material section, leaving everything written above it.

    The section is the brief's last one by convention, so it is replaced from
    its heading to the next heading or the end of the file; prose the person
    wrote elsewhere is never touched.
    """
    brief = find_artifact(config.project, project.directory, BRIEF_FILE)
    try:
        text = brief.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    quoted = quote_sources(config, project.sources, card)
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == MATERIAL_HEADING)
    except StopIteration:
        body = text.rstrip() + f"\n\n{MATERIAL_HEADING}\n\n{quoted}\n"
        atomic_write(brief, body)
        return
    end = next((i for i in range(start + 1, len(lines)) if _HEADING.match(lines[i])), len(lines))
    replaced = lines[:start] + [MATERIAL_HEADING, "", quoted, ""] + lines[end:]
    atomic_write(brief, "\n".join(replaced).rstrip() + "\n")
