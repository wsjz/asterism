"""The draft skeleton: the brief's shape with the material placed under it.

The machine does not write prose. What it can do is spare the person the blank
page: it copies the brief's headings, leaves each empty, and puts every piece
of gathered material at the end with a link back to the note it came from. An
agent or a person then moves quotes up under the heading they belong to.

Composing again never overwrites what was written. The material section is
refreshed and the headings that are new since last time are added; a heading
holding prose is left exactly as it is.
"""
from __future__ import annotations

from pathlib import Path
import re

from ..config import Config
from ..links import link_to
from ..projects import BRIEF_FILE, ContentProject, ProjectError, find_artifact
from ..rendering import parse_front_matter
from ..vault import atomic_write


DRAFT_FILE = "draft.md"
MATERIAL_HEADING = "## Material"
# the brief's own scaffolding, which a draft does not repeat
SKIPPED_HEADINGS = ("Candidate angles", "Source fragments")
_HEADING = re.compile(r"^##\s+(?P<name>.+?)\s*$")


def draft_path(config: Config, project: ContentProject) -> Path:
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    return find_artifact(config.project, project.directory, DRAFT_FILE)


def brief_headings(config: Config, project: ContentProject) -> list[str]:
    """The brief's section names, minus the ones that belong to the brief alone."""
    brief = find_artifact(config.project, project.directory, BRIEF_FILE)
    try:
        text = brief.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found = []
    for raw in text.splitlines():
        match = _HEADING.match(raw)
        if match and match.group("name") not in SKIPPED_HEADINGS:
            found.append(match.group("name"))
    return found


def compose_draft(config: Config, project: ContentProject) -> tuple[Path, list[str]]:
    """Write or refresh ``draft.md``; return its path and the headings it now has."""
    if project.status not in ("making", "ready"):
        raise ProjectError(
            f"{project.id} is {project.status!r}; confirm it first with `asterism confirm {project.id}`"
        )
    target = draft_path(config, project)
    headings = brief_headings(config, project)
    existing = _existing_sections(target)

    out: list[str] = [f"# {project.title}", ""]
    if project.promise:
        out += [f"_{project.promise}_", ""]
    for heading in headings:
        out.append(f"## {heading}")
        out.append("")
        body = existing.get(heading, "").strip()
        if body:
            out.append(body)
            out.append("")
    out.append(MATERIAL_HEADING)
    out.append("")
    out.extend(_material(config, project, target))
    atomic_write(target, "\n".join(out).rstrip() + "\n")
    return target, headings


def _existing_sections(target: Path) -> dict[str, str]:
    """What the person has already written, by heading, so it is never lost."""
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        match = _HEADING.match(raw)
        if match:
            current = match.group("name")
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw)
    sections.pop(MATERIAL_HEADING.removeprefix("## "), None)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _material(config: Config, project: ContentProject, draft: Path) -> list[str]:
    """Every gathered note as one line, newest last, each linking back.

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
