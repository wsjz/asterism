"""What a draft still lacks, checked without reading the prose for meaning.

Every check is something a machine can be sure about: a heading with nothing
under it, a gathered note the draft never links to, a project with no platform
chosen. Judging whether the writing is any good is gate 2, and that is the
person's answer, not a check's.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from ..config import Config
from ..projects import ContentProject
from .skeleton import MATERIAL_HEADING, draft_path


_HEADING = re.compile(r"^##\s+(?P<name>.+?)\s*$")
# a citation is a link, in either style; mentioning a note's name is not one
_LINK = re.compile(r"\[\[(?P<wiki>[^|\]]+)(?:\|[^\]]*)?\]\]|\]\((?P<md>[^)]+)\)")


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str  # empty-section | uncited | no-platform | no-promise | no-draft
    detail: str


def check_draft(config: Config, project: ContentProject) -> list[Finding]:
    """Everything verifiable that stands between this draft and a publication."""
    findings: list[Finding] = []
    target = draft_path(config, project)
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [Finding("no-draft", f"there is no draft yet; run `asterism draft {project.id}`")]

    for name, body in _sections(text).items():
        if name == MATERIAL_HEADING.removeprefix("## "):
            continue
        if not body.strip():
            findings.append(Finding("empty-section", name))

    cited = _cited(_prose(text))
    for relative in project.sources:
        if relative not in cited and Path(relative).stem not in cited:
            findings.append(Finding("uncited", relative))

    if not project.promise:
        findings.append(Finding("no-promise", "the card has no promise"))
    if not project.platforms:
        findings.append(Finding("no-platform", "no platform is chosen on the card"))
    return findings


def _sections(text: str) -> dict[str, str]:
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
    return {name: "\n".join(lines) for name, lines in sections.items()}


def _cited(prose: str) -> set[str]:
    """Every note the prose links to, by path and by name.

    Only a link counts. A draft named after the note it grew from would
    otherwise look like it cites it, which is how this check first went wrong.
    """
    found: set[str] = set()
    for match in _LINK.finditer(prose):
        target = (match.group("wiki") or match.group("md") or "").strip()
        if target:
            found.add(target)
            found.add(Path(target).stem)
    return found


def _prose(text: str) -> str:
    """The draft without its material list, which links everything by definition."""
    marker = text.find(MATERIAL_HEADING)
    return text if marker == -1 else text[:marker]
