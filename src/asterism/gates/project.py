"""Gates 2 and 3: the person's two answers about a finished piece.

Preparing either gate is reading: whether the draft keeps the card's promise,
whether each export reads right where it will appear. That is judgment, so it
belongs to whoever writes, a person or an agent following
``skills/asterism/SKILL.md``. What the machine keeps is the answer: one status
move per gate, made only when the person says so.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from ..config import Config
from ..projects import PROJECT_FILE, Project, ProjectError, find_artifact
from ..vault import atomic_write


def accept_project(config: Config, project: Project) -> Project:
    """Gate 2: the draft is good enough, so the piece is ``ready``."""
    _require(project, "making", "accept")
    return _save(project, replace(project, status="ready"))


def publish_project(
    config: Config, project: Project, *, urls: dict[str, str], today: date | None = None
) -> Project:
    """Gate 3: the piece went out; record where and when, and mark it ``published``.

    A piece with no platform still finishes: a report goes to one person and a
    note goes into a wiki, and neither is posted anywhere.
    """
    _require(project, "ready", "publish")
    unknown = sorted(platform for platform in urls if platform not in project.platforms)
    if unknown:
        raise ProjectError(
            f"{project.id} is not planned for {', '.join(unknown)}; "
            f"its platforms are {', '.join(project.platforms) or 'none'}"
        )
    published = record_publication(project, urls=urls, today=today)
    return _save(project, replace(project, status="published", published=published))


def record_publication(
    project: Project, *, urls: dict[str, str], today: date | None = None
) -> dict[str, dict[str, str]]:
    """The `published` mapping after this run: one record per platform."""
    stamp = (today or date.today()).isoformat()
    published = {key: dict(value) for key, value in project.published.items() if isinstance(value, dict)}
    for platform in project.platforms:
        record = {"at": stamp}
        if urls.get(platform):
            record["url"] = urls[platform]
        published.setdefault(platform, record)
    return published


def _require(project: Project, status: str, command: str) -> None:
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    if project.status != status:
        raise ProjectError(
            f"{project.id} is {project.status!r}; `{command}` is for a project that is {status!r}"
        )


def _save(project: Project, moved: Project) -> Project:
    atomic_write(find_artifact(project.directory, PROJECT_FILE), moved.to_markdown())
    return moved
