"""Content ids and project directories, both derived from configuration."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from string import Formatter

from ..config import Config
from ..rendering import clean_title_for_filename, unique_filename
from .model import Project, ProjectError, find_cards


def id_pattern(id_format: str, year: int) -> re.Pattern[str]:
    """A pattern matching ids of ``year``, capturing the sequence number."""
    parts: list[str] = []
    for literal, field, _spec, _conversion in Formatter().parse(id_format):
        parts.append(re.escape(literal))
        if field == "seq":
            parts.append(r"(?P<seq>\d+)")
        elif field == "year":
            parts.append(re.escape(str(year)))
        elif field is not None:
            parts.append(r"[^\s/]*")
    return re.compile("^" + "".join(parts) + "$")


def next_id(config: Config, *, today: date, pillar: str | None = None, type_: str | None = None) -> str:
    """The next free content id, read from the ids already in ``content/``."""
    pattern = id_pattern(config.project.id_format, today.year)
    highest = 0
    for existing in existing_ids(config):
        match = pattern.match(existing)
        if match:
            highest = max(highest, int(match.group("seq")))
    return config.project.id_format.format(
        year=today.year, seq=highest + 1, pillar=pillar or "", type=type_ or ""
    )


def existing_ids(config: Config) -> list[str]:
    ids: list[str] = []
    for card in find_cards(config.projects_root):
        try:
            ids.append(Project.load(card.parent).id)
        except ProjectError:
            continue  # a broken card must not block creating new projects
    return ids


def render_path(config: Config, *, project_id: str, title: str, created: date, pillar: str | None, type_: str | None) -> str:
    """The project's directory relative to ``content/``, each segment cleaned."""
    rendered = config.project.path.format(
        year=created.year,
        date=created.isoformat(),
        title=title,
        id=project_id,
        pillar=pillar or "unsorted",
        type=type_ or "unsorted",
    )
    segments = [clean_title_for_filename(segment) for segment in rendered.split("/") if segment.strip()]
    if not segments:
        raise ProjectError("project.path produced an empty directory name")
    return "/".join(segments)


def unique_directory(config: Config, relative: str, root: Path | None = None) -> str:
    """``relative`` or the first ``name (n)`` free inside ``root`` (``content/`` by default)."""
    base = root if root is not None else config.projects_root
    parent, _, name = relative.rpartition("/")
    folder = base / parent if parent else base
    taken = {entry.name for entry in folder.iterdir()} if folder.is_dir() else set()
    chosen = unique_filename(name, taken)
    return f"{parent}/{chosen}" if parent else chosen


def project_directory(config: Config, project: Project) -> Path:
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    return project.directory


def vault_relative(config: Config, path: Path) -> str:
    return path.resolve(strict=False).relative_to(config.vault).as_posix()
