"""The draft skeleton, and the material list it keeps up to date.

The machine does not write prose. What it can do is spare the person the blank
page: it lays out the sections the brief's outline names and lists every piece
of gathered material under ``## Material``, each with a link back to the note.

Once the file exists it belongs to the writer. Composing again only refreshes
the material list; headings, prose and structure are never touched, because
restructuring is the first thing writing does and an earlier version of this
module deleted a finished draft for exactly that reason.
"""
from __future__ import annotations

from pathlib import Path
import re

from ..config import Config
from ..links import link_to
from ..projects import BRIEF_FILE, Project, ProjectError, find_artifact
from ..rendering import parse_front_matter
from ..vault import atomic_write


DRAFT_FILE = "draft.md"
MATERIAL_HEADING = "## Material"
OUTLINE_HEADING = "## Outline"
_HEADING = re.compile(r"^##\s+(?P<name>.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(?P<name>.+?)\s*$")


def draft_path(config: Config, project: Project) -> Path:
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    return find_artifact(config.project, project.directory, DRAFT_FILE)


def brief_headings(config: Config, project: Project) -> list[str]:
    """The sections the brief's outline asks for, in order.

    Only the outline is copied. The brief's other headings are prompts for
    planning — "Audience", "Evidence or demo" — and a finished piece has no
    section by those names.
    """
    brief = find_artifact(config.project, project.directory, BRIEF_FILE)
    try:
        text = brief.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found: list[str] = []
    inside = False
    for raw in text.splitlines():
        if raw.strip() == OUTLINE_HEADING:
            inside = True
            continue
        if inside and _HEADING.match(raw):
            break
        bullet = _BULLET.match(raw) if inside else None
        if bullet and not bullet.group("name").startswith("_"):
            found.append(bullet.group("name"))
    return found


def compose_draft(config: Config, project: Project) -> tuple[Path, list[str], bool]:
    """Write the skeleton, or refresh an existing draft's material list.

    Returns the path, the sections the draft has, and whether it was created.
    """
    if project.status not in ("making", "ready"):
        raise ProjectError(
            f"{project.id} is {project.status!r}; confirm it first with `asterism confirm {project.id}`"
        )
    target = draft_path(config, project)
    if target.is_file():
        headings = _refresh_material(config, project, target)
        return target, headings, False

    out: list[str] = [f"# {project.title}", ""]
    if project.promise:
        out += [f"_{project.promise}_", ""]
    headings = brief_headings(config, project)
    for heading in headings:
        out += [f"## {heading}", ""]
    out += [MATERIAL_HEADING, ""]
    out += _material(config, project, target)
    atomic_write(target, "\n".join(out).rstrip() + "\n")
    return target, headings, True


def _refresh_material(config: Config, project: Project, target: Path) -> list[str]:
    """Replace the material list and nothing else; report the draft's own sections."""
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = [
        match.group("name")
        for line in lines
        if (match := _HEADING.match(line)) and line.strip() != MATERIAL_HEADING
    ]
    material = _material(config, project, target)
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == MATERIAL_HEADING)
    except StopIteration:
        atomic_write(target, text.rstrip() + "\n\n" + "\n".join([MATERIAL_HEADING, "", *material]) + "\n")
        return headings
    end = next((i for i in range(start + 1, len(lines)) if _HEADING.match(lines[i])), len(lines))
    replaced = lines[:start] + [MATERIAL_HEADING, "", *material, ""] + lines[end:]
    atomic_write(target, "\n".join(replaced).rstrip() + "\n")
    return headings


def _material(config: Config, project: Project, draft: Path) -> list[str]:
    """Every gathered note as one line, oldest first, each linking back.

    The quotes themselves stay in the brief; repeating them here would make the
    draft a second copy of the archive instead of a place to write.
    """
    if not project.sources:
        return ["_Nothing gathered yet; run `asterism gather`._"]
    lines = []
    for relative in project.sources:
        label = Path(relative).stem
        day = _day_of(config, relative)
        link = link_to(config.links, config.vault, relative, label, from_file=draft)
        lines.append(f"- {day} {link}" if day else f"- {link}")
    return lines


def _day_of(config: Config, relative: str) -> str:
    try:
        fields, _body = parse_front_matter((config.vault / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return ""
    return str(fields.get("created_at") or "")[:10]
