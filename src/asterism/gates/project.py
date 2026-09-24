"""Gates 2 and 3: the two questions a person answers about a finished piece.

Each is a Markdown file the machine writes, the person edits, and a command
reads back. What the machine can verify it lists; what only a person can judge
it asks, as a short checklist. Nothing moves until every box is ticked, so
passing a gate is something the person did, not something a command inferred.

The sheets live in the project's own folder, named after the command that
writes them, because they belong to that piece: dropping a project takes its
gates with it. ``picks/`` holds the rounds of choosing and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
import re

from ..compose import Checked, check_draft, draft_path, export_path
from ..config import Config
from ..links import link_to
from ..projects import PROJECT_FILE, Project, ProjectError, find_artifact
from ..rendering import SCHEMA_VERSION, parse_front_matter
from ..vault import atomic_write


CHECK_FILE = "check.md"  # gate 2, written by `asterism check`
RELEASE_FILE = "release.md"  # gate 3, written by `asterism release`
GATE_FILES = {"check": CHECK_FILE, "release": RELEASE_FILE}
_TICKED = re.compile(r"^\s*-\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+?)\s*$")

CHECK_QUESTIONS = (
    "the draft keeps the promise on the card",
    "every claim that needs a source has one",
    "it is worth publishing",
)
RELEASE_QUESTIONS = (
    "every export has been read as it will appear",
    "links, images and code resolve",
    "publish it now",
)
NO_PLATFORM_QUESTIONS = (
    "the piece is finished",
    "it has reached whoever it was written for",
)


@dataclass(frozen=True, slots=True)
class Answer:
    path: Path
    open: bool
    unticked: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.unticked


def sheet_path(config: Config, project: Project, gate: str) -> Path:
    """Where a gate's sheet lives inside its project."""
    if project.directory is None:
        raise ProjectError(f"project {project.id} was not loaded from a directory")
    return find_artifact(config.project, project.directory, GATE_FILES[gate])


def write_draft_gate(config: Config, project: Project) -> tuple[Path, Checked]:
    """Gate 2: what the checks found, and the three questions only a person answers."""
    _require(project, "making", "check")
    checked = check_draft(config, project)
    target = sheet_path(config, project, "check")
    body = [
        f"Read {_link(config, draft_path(config, project), target)} and answer below,",
        f"then run `asterism accept {project.id}`.",
        "",
        f"Material: {checked.material}. Leaving most of it unused is normal.",
        "",
        "## What the checks found",
        "",
    ]
    if checked.findings:
        body += [f"- {finding.kind}: {finding.detail}" for finding in checked.findings]
    else:
        body.append("Nothing. Every section has prose, and the card is complete.")
    body += ["", "## Your answer", ""]
    body += [f"- [ ] {question}" for question in CHECK_QUESTIONS]
    body += ["", "Notes:", ""]
    _write(target, project, gate=2, body=body)
    return target, checked


def write_publish_gate(config: Config, project: Project) -> tuple[Path, list[str]]:
    """Gate 3: the exports that would go out, and the last three questions."""
    _require(project, "ready", "release")
    target = sheet_path(config, project, "release")
    missing: list[str] = []
    body = [
        f"These go out when you run `asterism publish {project.id}`.",
        "",
        "## Exports",
        "",
    ]
    if not project.platforms:
        # Not everything written is posted somewhere. A report goes to one
        # person, a note goes into a wiki; the piece is still finished, and a
        # gate that insisted on a platform left it stuck at `ready` forever.
        body.append("None: the card names no platform, so this piece is not being posted.")
        body.append("Publishing records that it is done and when.")
    for platform in project.platforms:
        path = export_path(config, project, platform)
        if path.is_file():
            body.append(f"- {platform}: {_link(config, path, target)}")
        else:
            missing.append(platform)
            body.append(f"- {platform}: **missing**, run `asterism adapt {project.id}`")
    body += ["", "## Your answer", ""]
    questions = RELEASE_QUESTIONS if project.platforms else NO_PLATFORM_QUESTIONS
    body += [f"- [ ] {question}" for question in questions]
    body += ["", "Notes:", ""]
    _write(target, project, gate=3, body=body)
    return target, missing


def read_answer(config: Config, project: Project, gate: str) -> Answer:
    """What the person ticked, and whether the sheet is still open."""
    target = sheet_path(config, project, gate)
    if not target.is_file():
        raise ProjectError(
            f"{project.id} has no {GATE_FILES[gate]}; run `asterism {gate} {project.id}` first"
        )
    text = target.read_text(encoding="utf-8")
    fields, body = parse_front_matter(text)
    unticked = tuple(
        match.group("text")
        for line in body.splitlines()
        if (match := _TICKED.match(line)) and match.group("mark") == " "
    )
    return Answer(path=target, open=fields.get("state") == "open", unticked=unticked)


def pass_gate(
    config: Config, project: Project, *, gate: str, status: str, **card: object
) -> Project:
    """Move the project on, once the sheet says the person answered every question."""
    answer = read_answer(config, project, gate)
    if not answer.open:
        raise ProjectError(f"{answer.path.name} was already answered; {project.id} is {project.status}")
    if not answer.passed:
        unanswered = "; ".join(answer.unticked)
        raise ProjectError(
            f"{answer.path.name} still has unticked boxes: {unanswered}"
        )
    moved = replace(project, status=status, **card)
    atomic_write(
        find_artifact(config.project, project.directory, PROJECT_FILE), moved.to_markdown()
    )
    atomic_write(
        answer.path, answer.path.read_text(encoding="utf-8").replace('state: "open"', 'state: "applied"', 1)
    )
    return moved


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


def _link(config: Config, target: Path, from_file: Path) -> str:
    relative = target.relative_to(config.vault).as_posix()
    return link_to(config.links, config.vault, relative, Path(relative).stem, from_file=from_file)


def _write(target: Path, project: Project, *, gate: int, body: list[str]) -> None:
    head = [
        "---",
        f"schema: {SCHEMA_VERSION}",
        f'kind: "{ "check" if gate == 2 else "release" }"',
        f'project: "{project.id}"',
        f"gate: {gate}",
        'state: "open"',
        "---",
        "",
        f"# Gate {gate} - {project.id} {project.title}",
        "",
    ]
    atomic_write(target, "\n".join(head + body).rstrip() + "\n")
