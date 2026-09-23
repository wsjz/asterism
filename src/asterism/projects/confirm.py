"""Gate 1: deciding which piece a candidate becomes.

A candidate already holds the material gathered for it and, in its brief, the
angles that material could support. Confirming one writes it into the card's
``title`` and ``promise`` and moves the status to ``making``.

This is the only place the machine advances that status. An agent may fill the
brief with angles; answering the gate's question is the person's move.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

from ..config import Config
from ..vault import atomic_write
from .model import BRIEF_FILE, PROJECT_FILE, ContentProject, ProjectError
from .stages import find_artifact


ANGLES_HEADING = "## Candidate angles"
# "1. **A title** — the promise it keeps", the promise optional
_ANGLE = re.compile(r"^\s*(?P<number>\d+)\.\s+\*\*(?P<title>.+?)\*\*\s*(?:[—:-]\s*(?P<promise>.*))?$")
_HEADING = re.compile(r"^##\s+")


@dataclass(frozen=True, slots=True)
class Angle:
    number: int
    title: str
    promise: str


def _brief_text(config: Config, project: ContentProject) -> str:
    if project.directory is None:
        return ""
    brief = find_artifact(config.project, project.directory, BRIEF_FILE)
    try:
        return brief.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def offers_angles(config: Config, project: ContentProject) -> bool:
    """Whether the brief has the section at all, empty or not.

    A vault seeds its templates once and the machine never rewrites them, so a
    vault older than this section keeps a brief without it. That is a different
    problem from a brief that offers no angle yet, and the person needs to be
    told which one they have.
    """
    return any(line.strip() == ANGLES_HEADING for line in _brief_text(config, project).splitlines())


def angles(config: Config, project: ContentProject) -> list[Angle]:
    """The angles the project's brief offers, in the order they are written."""
    text = _brief_text(config, project)
    found: list[Angle] = []
    inside = False
    for raw in text.splitlines():
        if raw.strip() == ANGLES_HEADING:
            inside = True
            continue
        if inside and _HEADING.match(raw):
            break
        match = _ANGLE.match(raw) if inside else None
        if match:
            found.append(
                Angle(
                    number=int(match.group("number")),
                    title=match.group("title").strip(),
                    promise=(match.group("promise") or "").strip(),
                )
            )
    return found


def confirm_project(
    config: Config,
    project: ContentProject,
    *,
    angle: int | None = None,
    title: str | None = None,
    promise: str | None = None,
) -> ContentProject:
    """Choose what this candidate becomes and move it to ``making``.

    The folder keeps the name it was created with even when the title changes,
    because a path that moves breaks every link already written to it.
    """
    if project.status != "candidate":
        raise ProjectError(
            f"{project.id} is {project.status!r}; only a candidate can be confirmed"
        )
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")

    chosen_title, chosen_promise = title, promise
    if angle is not None:
        offered = angles(config, project)
        picked = next((entry for entry in offered if entry.number == angle), None)
        if picked is None:
            known = ", ".join(str(entry.number) for entry in offered) or "none"
            raise ProjectError(
                f"{project.id} has no angle {angle} in its brief; it offers {known}"
            )
        chosen_title = title or picked.title
        chosen_promise = promise or picked.promise or None
    if not (chosen_title or "").strip():
        raise ProjectError(
            "confirming needs --angle N or --title; the title is the piece's name"
        )

    confirmed = replace(
        project,
        title=chosen_title.strip(),
        promise=(chosen_promise or project.promise) or None,
        status="making",
    )
    atomic_write(
        find_artifact(config.project, project.directory, PROJECT_FILE),
        confirmed.to_markdown(),
    )
    return confirmed
