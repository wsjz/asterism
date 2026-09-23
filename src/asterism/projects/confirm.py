"""Gate 1: deciding which piece a candidate becomes.

A candidate already holds the material gathered for it and, in its brief, the
angles that material could support. Confirming one writes it into the card's
``title`` and ``promise`` and moves the status to ``making``.

This is the only place the machine advances that status. An agent may fill the
brief with angles; answering the gate's question is the person's move.
"""
from __future__ import annotations

from dataclasses import dataclass, replace, replace as replace_fields
from datetime import date
import re

from ..config import Config
from ..vault import atomic_write
from .model import BRIEF_FILE, PROJECT_FILE, Project, ProjectError
from .stages import find_artifact


ANGLES_HEADING = "## Candidate angles"
# "1. **A title** — the promise it keeps", the promise optional
_ANGLE = re.compile(r"^\s*(?P<number>\d+)\.\s+\*\*(?P<title>.+?)\*\*\s*(?:[—:-]\s*(?P<promise>.*))?$")
_HEADING = re.compile(r"^##\s+")
_REASON = re.compile(r"^\s+_(?P<text>.+?)_\s*$")


@dataclass(frozen=True, slots=True)
class Angle:
    number: int
    title: str
    promise: str
    reason: str = ""  # why this material belongs together, for the person to audit


def _brief_text(config: Config, project: Project) -> str:
    if project.directory is None:
        return ""
    brief = find_artifact(config.project, project.directory, BRIEF_FILE)
    try:
        return brief.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def offers_angles(config: Config, project: Project) -> bool:
    """Whether the brief has the section at all, empty or not.

    A vault seeds its templates once and the machine never rewrites them, so a
    vault older than this section keeps a brief without it. That is a different
    problem from a brief that offers no angle yet, and the person needs to be
    told which one they have.
    """
    return any(line.strip() == ANGLES_HEADING for line in _brief_text(config, project).splitlines())


def angles(config: Config, project: Project) -> list[Angle]:
    """The angles the project's brief offers, in the order they are written."""
    text = _brief_text(config, project)
    found: list[Angle] = []
    reasons: list[list[str]] = []
    inside = False
    for raw in text.splitlines():
        if raw.strip() == ANGLES_HEADING:
            inside = True
            continue
        if inside and _HEADING.match(raw):
            break
        if not inside:
            continue
        match = _ANGLE.match(raw)
        if match:
            found.append(
                Angle(
                    number=int(match.group("number")),
                    title=match.group("title").strip(),
                    promise=(match.group("promise") or "").strip(),
                )
            )
            reasons.append([])
            continue
        # an indented italic line under an angle says why its material belongs
        # together; that reasoning is what makes the angle auditable
        note = _REASON.match(raw)
        if note and reasons:
            reasons[-1].append(note.group("text").strip())
    return [
        replace_fields(angle, reason=" ".join(reason).strip())
        for angle, reason in zip(found, reasons)
    ]


def confirm_project(
    config: Config,
    project: Project,
    *,
    angle: int | None = None,
    title: str | None = None,
    promise: str | None = None,
) -> Project:
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


def set_fields(
    config: Config,
    project: Project,
    *,
    pillar: str | None = None,
    type_: str | None = None,
    platforms: tuple[str, ...] | None = None,
    promise: str | None = None,
    scheduled: date | None = None,
) -> Project:
    """Change the card's editable fields; anything not given is left alone.

    These are the fields Obsidian's Properties panel offers, which is where a
    person edits them. A command exists for the same reason `--json` does: what
    a person can do in the vault, whatever drives the vault must be able to do
    through the CLI.
    """
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    known = tuple(entry.key for entry in config.content.pillars)
    if pillar is not None and known and pillar not in known:
        raise ProjectError(f"unknown pillar {pillar!r}; configured pillars are {', '.join(known)}")
    if type_ is not None and type_ not in config.content.types:
        raise ProjectError(
            f"unknown type {type_!r}; configured types are {', '.join(config.content.types)}"
        )
    unknown = [name for name in (platforms or ()) if name not in config.content.platforms]
    if unknown:
        raise ProjectError(
            f"unknown platforms: {', '.join(unknown)}; "
            f"configured platforms are {', '.join(config.content.platforms)}"
        )

    updated = replace(
        project,
        pillar=pillar if pillar is not None else project.pillar,
        type=type_ if type_ is not None else project.type,
        platforms=platforms if platforms is not None else project.platforms,
        primary=(platforms[0] if platforms else project.primary),
        promise=promise if promise is not None else project.promise,
        scheduled=scheduled if scheduled is not None else project.scheduled,
    )
    atomic_write(
        find_artifact(config.project, project.directory, PROJECT_FILE), updated.to_markdown()
    )
    return updated
