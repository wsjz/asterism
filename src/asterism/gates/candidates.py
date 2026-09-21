"""Gate 1: choosing which collected fragments become content projects.

The list lives in the week's digest, so the weekly session is one file: read
what arrived, tick what is worth making. Everything from the ``## Candidates``
heading to the end of that file belongs to the person, and the digest builder
preserves it when it rebuilds the document.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
import re

from ..config import Config
from ..digest.periods import Period
from ..enrich import classify_item
from ..links import link_to
from ..models import Assignment, ItemState
from ..projects import PROJECT_FILE, artifact_path, create_project
from ..state.base import StateBackend
from ..vault import atomic_write, validated_target


CANDIDATES_HEADING = "## Candidates"
UNCLASSIFIED = "Unclassified"

_LINE = re.compile(
    r"^- \[(?P<tick>[ xX])\]\s*(?P<label>.*?)\s*<!--\s*asterism:(?P<source>[A-Za-z0-9_-]+):(?P<id>.*?)\s*-->\s*$"
)
_APPLIED = re.compile(r"\s*->\s*(?P<link>.+?)\s*$")


@dataclass(frozen=True, slots=True)
class Candidate:
    source: str
    source_id: str
    title: str
    relative_path: str
    day: date | None
    pillar: str | None
    ticked: bool = False
    applied: str | None = None  # the project link written back after apply

    @property
    def marker(self) -> str:
        return f"<!-- asterism:{self.source}:{self.source_id} -->"


def preserved_tail(text: str) -> str | None:
    """The human-owned part of a digest: the candidates section and anything after it."""
    index = text.find("\n" + CANDIDATES_HEADING)
    if index == -1:
        return text[len(CANDIDATES_HEADING) :] and None if not text.startswith(CANDIDATES_HEADING) else text
    return text[index + 1 :]


def read_section(text: str) -> list[Candidate]:
    """Parse the candidate lines of a digest, keeping ticks and applied links."""
    tail = preserved_tail(text)
    if tail is None:
        return []
    candidates: list[Candidate] = []
    pillar: str | None = None
    for line in tail.splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()
            pillar = None if heading == UNCLASSIFIED else heading
            continue
        match = _LINE.match(line)
        if match is None:
            continue
        label = match.group("label")
        applied = None
        applied_match = _APPLIED.search(label)
        if applied_match:
            applied = applied_match.group("link")
            label = label[: applied_match.start()].rstrip()
        day, title = _split_label(label)
        candidates.append(
            Candidate(
                source=match.group("source"),
                source_id=match.group("id"),
                title=title,
                relative_path="",
                day=day,
                pillar=pillar,
                ticked=match.group("tick") in ("x", "X"),
                applied=applied,
            )
        )
    return candidates


def _split_label(label: str) -> tuple[date | None, str]:
    head, _, rest = label.partition(" ")
    try:
        return date.fromisoformat(head), rest.strip()
    except ValueError:
        return None, label.strip()


def collect_candidates(config: Config, state: StateBackend, period: Period) -> list[Candidate]:
    """Undecided items of the period, classified and ordered by pillar then date."""
    items = state.items_between(period.start.isoformat(), _exclusive_end(period))
    order = {pillar.key: index for index, pillar in enumerate(config.content.pillars)}
    candidates: list[Candidate] = []
    for item in items:
        if state.get_assignment(item.source, item.source_id) is not None:
            continue
        candidates.append(
            Candidate(
                source=item.source,
                source_id=item.source_id,
                title=item.title or item.source_id,
                relative_path=item.relative_path,
                day=_day(item),
                pillar=classify_item(config, item),
            )
        )
    candidates.sort(
        key=lambda item: (
            order.get(item.pillar, len(order)) if item.pillar else len(order) + 1,
            item.day or date.min,
            item.title,
        )
    )
    return candidates


def render_section(config: Config, candidates: list[Candidate], period: Period, digest_file: Path) -> str:
    """The candidates section as Markdown, grouped by pillar with unclassified last."""
    lines = [
        CANDIDATES_HEADING,
        "",
        f"Tick what is worth making, then run `asterism apply --week {period.label}`.",
        "Unticked lines stay here; nothing is decided for you.",
        "",
    ]
    if not candidates:
        lines.append("Nothing new to decide.")
        return "\n".join(lines).rstrip() + "\n"
    current = object()
    for candidate in candidates:
        if candidate.pillar != current:
            current = candidate.pillar
            lines.append(f"### {candidate.pillar or UNCLASSIFIED}")
            lines.append("")
        lines.append(_render_line(config, candidate, digest_file))
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_line(config: Config, candidate: Candidate, digest_file: Path) -> str:
    tick = "x" if candidate.ticked else " "
    day = candidate.day.isoformat() if candidate.day else ""
    label = (
        link_to(config.links, config.vault, candidate.relative_path, candidate.title, from_file=digest_file)
        if candidate.relative_path
        else candidate.title
    )
    parts = [part for part in (day, label) if part]
    if candidate.applied:
        parts.append(f"-> {candidate.applied}")
    return f"- [{tick}] " + " ".join(parts) + f" {candidate.marker}"


def propose_candidates(config: Config, state: StateBackend, period: Period) -> tuple[int, Path]:
    """Write or refresh the candidates section of a week's digest, keeping ticks."""
    digest_file = validated_target(config.vault, period.relative_path)
    if not digest_file.is_file():
        raise FileNotFoundError(
            f"{period.relative_path} does not exist yet; run `asterism digest` first"
        )
    existing = digest_file.read_text(encoding="utf-8")
    decided = {(item.source, item.source_id): item for item in read_section(existing)}
    fresh = [
        replace(
            candidate,
            ticked=decided[(candidate.source, candidate.source_id)].ticked
            if (candidate.source, candidate.source_id) in decided
            else False,
            applied=decided[(candidate.source, candidate.source_id)].applied
            if (candidate.source, candidate.source_id) in decided
            else None,
        )
        for candidate in collect_candidates(config, state, period)
    ]
    kept = _already_applied(config, existing, decided, fresh)
    section = render_section(config, kept + fresh, period, digest_file)
    body = existing[: existing.find("\n" + CANDIDATES_HEADING)] if "\n" + CANDIDATES_HEADING in existing else existing
    atomic_write(digest_file, body.rstrip() + "\n\n" + section)
    return len(fresh), digest_file


def _already_applied(
    config: Config, existing: str, decided: dict[tuple[str, str], Candidate], fresh: list[Candidate]
) -> list[Candidate]:
    """Lines whose item is no longer undecided, kept so the record of the week stays."""
    current = {(candidate.source, candidate.source_id) for candidate in fresh}
    return [candidate for key, candidate in decided.items() if key not in current and candidate.applied]


def apply_candidates(
    config: Config, state: StateBackend, period: Period, *, today: date | None = None
) -> list[tuple[Candidate, str]]:
    """Turn every ticked, not yet applied candidate into a content project."""
    digest_file = validated_target(config.vault, period.relative_path)
    if not digest_file.is_file():
        raise FileNotFoundError(f"{period.relative_path} does not exist yet")
    text = digest_file.read_text(encoding="utf-8")
    created: list[tuple[Candidate, str]] = []
    lines = text.splitlines()
    now = datetime.now().astimezone().isoformat()

    for index, line in enumerate(lines):
        match = _LINE.match(line)
        if match is None or match.group("tick") not in ("x", "X"):
            continue
        if _APPLIED.search(match.group("label")):
            continue  # already turned into a project
        source, source_id = match.group("source"), match.group("id")
        item = state.get(source, source_id)
        if item is None:
            continue
        candidate = Candidate(
            source=source,
            source_id=source_id,
            title=item.title or source_id,
            relative_path=item.relative_path,
            day=_day(item),
            pillar=classify_item(config, item),
            ticked=True,
        )
        project = create_project(
            config,
            title=candidate.title,
            pillar=candidate.pillar,
            sources=(candidate.relative_path,),
            status="approved",
            today=today,
        )
        card = project.directory / artifact_path(config.project, PROJECT_FILE)
        link = link_to(
            config.links, config.vault, card.relative_to(config.vault).as_posix(), project.id, from_file=digest_file
        )
        lines[index] = _render_line(config, replace(candidate, applied=link), digest_file)
        state.save_assignment(
            Assignment(source=source, source_id=source_id, decision="promoted", decided_at=now, project_id=project.id)
        )
        created.append((candidate, project.id))

    if created:
        atomic_write(digest_file, "\n".join(lines).rstrip() + "\n")
    return created


def pending_count(text: str) -> int:
    return sum(1 for candidate in read_section(text) if not candidate.applied)


def _day(item: ItemState) -> date | None:
    moment = item.digest_time
    if not moment:
        return None
    try:
        return date.fromisoformat(moment[:10])
    except ValueError:
        return None


def _exclusive_end(period: Period) -> str:
    from datetime import timedelta

    return (period.end + timedelta(days=1)).isoformat()
