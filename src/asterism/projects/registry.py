"""Reading every project card in the vault.

The cards are the source of truth: an edit made in Obsidian is visible to the
next command without a synchronization step, so there is no project table in
state to drift from them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config
from .model import PROJECT_FILE, ContentProject, ProjectError


@dataclass(frozen=True, slots=True)
class Registry:
    projects: tuple[ContentProject, ...] = ()
    problems: tuple[str, ...] = ()  # cards that could not be read, reported not raised

    def by_status(self, status: str) -> tuple[ContentProject, ...]:
        return tuple(project for project in self.projects if project.status == status)

    def in_flight(self) -> tuple[ContentProject, ...]:
        return tuple(
            project
            for project in self.projects
            if not project.is_published and not project.is_dropped
        )

    def find(self, project_id: str) -> ContentProject | None:
        return next((project for project in self.projects if project.id == project_id), None)

    def filtered(
        self, *, pillar: str | None = None, status: str | None = None, year: int | None = None
    ) -> Registry:
        selected = [
            project
            for project in self.projects
            if (pillar is None or project.pillar == pillar)
            and (status is None or project.status == status)
            and (year is None or (project.created is not None and project.created.year == year))
        ]
        return Registry(tuple(selected), self.problems)


def load_projects(config: Config, *, include_dropped: bool = False) -> Registry:
    """Every readable project card, newest first; unreadable ones are reported.

    Only live work under ``content/`` is read by default. Dropped projects
    wait under ``trash/`` and are included on request.
    """
    projects: list[ContentProject] = []
    problems: list[str] = []
    roots = [config.content_root] + ([config.trash_root] if include_dropped else [])
    for root in roots:
        if not root.is_dir():
            continue
        for card in sorted(root.rglob(PROJECT_FILE)):
            try:
                projects.append(ContentProject.load(card.parent))
            except ProjectError as error:
                problems.append(f"{card.relative_to(config.vault).as_posix()}: {error}")
    projects.sort(key=_sort_key, reverse=True)
    return Registry(tuple(projects), tuple(problems))


def _sort_key(project: ContentProject) -> tuple[str, str]:
    return (project.created.isoformat() if project.created else "", project.id)
