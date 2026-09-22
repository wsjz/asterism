"""Sorting collected material: the periodic session where every item gets an outcome.

A sheet at ``review/<date>.md`` lists what has no outcome yet, each line placed
under the outcome a rule suggests. Moving a line to another section changes what
happens to it; `apply` records the outcomes and turns the `used` ones into
content projects. Under `used` a `### heading` is a topic: every line beneath
it becomes one project, because a piece is usually made of several fragments.
See docs/state-model.md for the vocabularies.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace as replace_fields
from datetime import date, datetime, timedelta
import json
from pathlib import Path, PurePosixPath
import re

from ..config import MATERIAL_DECISIONS, Config
from ..digest.builder import source_directory
from ..digest.periods import Period, digest_relative_path, period_containing
from ..enrich import classify_item
from ..links import link_to
from ..models import Assignment, ItemState
from ..projects import PROJECT_FILE, artifact_path, create_project
from ..rendering import SCHEMA_VERSION, parse_front_matter
from ..state.base import StateBackend
from ..vault import atomic_write, validated_target


SHEET_DIR = "review"
UNDECIDED = "undecided"
# Undecided comes first: it is where everything starts and where the reading
# happens. The outcomes follow, so a line only ever moves downwards.
SECTIONS: tuple[str, ...] = (UNDECIDED, "used", "later", "reference", "dropped")
SECTION_HELP = {
    "used": "becomes a content project; group lines under a `### topic` to make one project of them",
    "later": "worth making, but not now",
    "reference": "keep as material, not a piece of its own",
    "dropped": "seen, not keeping",
    UNDECIDED: "decide, or leave it for the next round",
}

_LINE = re.compile(r"^\s*- (?P<day>\d{4}-\d{2}-\d{2})?\s*(?P<rest>.+?)\s*$")
_TARGET = re.compile(r"\[\[(?P<wiki>[^|\]]+)(?:\|[^\]]*)?\]\]|\]\((?P<md>[^)]+)\)")
MAX_LABEL_CHARS = 60
ROMAN: tuple[str, ...] = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")
_SECTION = re.compile(r"^##\s+(?:[IVX]+\.\s*)?(?P<name>[a-z]+)\b")
_HEADING = re.compile(r"^###\s+(?P<name>.+?)\s*$")
# the renderer numbers its source headings, so "### 1. flomo" is a source and
# anything else a person or an enricher wrote is a topic
_SOURCE_HEADING = re.compile(r"^###\s+\d+\.\s")


@dataclass(frozen=True, slots=True)
class Line:
    source: str
    source_id: str
    title: str
    relative_path: str
    day: date | None
    pillar: str | None
    decision: str
    source_dir: str = ""
    parent: str = ""
    group: str = ""  # the topic heading this line sits under, in the used section



@dataclass(frozen=True, slots=True)
class Sheet:
    path: Path
    day: date
    covers: dict[str, list[str]] = field(default_factory=dict)
    auto: dict[str, int] = field(default_factory=dict)
    lines: tuple[Line, ...] = ()

    @property
    def listed(self) -> int:
        return len(self.lines)

    @property
    def stamp(self) -> str:
        """When this round was opened, read back from the file name."""
        stem = self.path.stem
        if len(stem) == 17 and stem[10] == "-" and stem[11:].isdigit():
            clock = stem[11:]
            return f"{stem[:10]} {clock[:2]}:{clock[2:4]}:{clock[4:]}"
        return self.day.isoformat()


# --- coverage -----------------------------------------------------------------


def coverage(config: Config, state: StateBackend, *, today: date, since: date | None = None) -> dict[str, list[Period]]:
    """The fewest digest documents that cover what has no outcome yet, per source.

    Walking forward from the earliest undecided day, the coarsest closed period
    that still holds undecided items wins, because reading one week is reading
    its seven days. Periods still accumulating are never offered.
    """
    result: dict[str, list[Period]] = {}
    for source in sorted(state.sources()):
        undecided = [item for item in state.items(source) if _is_undecided(state, item)]
        days = sorted({day for day in (_day(item) for item in undecided) if day is not None})
        if since is not None:
            days = [day for day in days if day >= since]
        if not days:
            continue
        ranges = {
            (digest.level, digest.period_start): digest
            for digest in state.digests(source)
            if digest.state != "open"
        }
        periods: list[Period] = []
        cursor = days[0]
        while cursor <= today:
            best: Period | None = None
            for level in ("year", "month", "week", "day"):
                if not config.digest.level(level).enabled:
                    continue
                period = period_containing(level, cursor, config.digest)
                if period.end >= today or (level, period.start.isoformat()) not in ranges:
                    continue
                if not _has_undecided(undecided, period):
                    continue
                if best is None or period.end > best.end:
                    best = period
            if best is None:
                cursor = _next_day(cursor, days)
                if cursor is None:
                    break
                continue
            periods.append(best)
            cursor = best.end + timedelta(days=1)
        if periods:
            result[source] = periods
    return result


def _next_day(cursor: date, days: list[date]) -> date | None:
    return next((day for day in days if day > cursor), None)


def _has_undecided(items: list[ItemState], period: Period) -> bool:
    return any(
        (day := _day(item)) is not None and period.start <= day <= period.end for item in items
    )


def _is_undecided(state: StateBackend, item: ItemState) -> bool:
    return state.get_assignment(item.source, item.source_id) is None


def _day(item: ItemState) -> date | None:
    moment = item.digest_time
    if not moment:
        return None
    try:
        return date.fromisoformat(moment[:10])
    except ValueError:
        return None


# --- building -----------------------------------------------------------------


def build_sheet(
    config: Config, state: StateBackend, *, today: date | None = None, since: date | None = None
) -> Sheet:
    """Write or refresh today's sheet, keeping the placements already made."""
    day = today or date.today()
    covered = coverage(config, state, today=day, since=since)
    dirs = {source: source_directory(state, source) for source in sorted(state.sources())}

    lines: list[Line] = []
    auto: dict[str, int] = {}
    now = datetime.now().astimezone().isoformat()
    for source, periods in covered.items():
        for item in state.items(source):
            if not _is_undecided(state, item):
                continue
            item_day = _day(item)
            if item_day is None or not any(p.start <= item_day <= p.end for p in periods):
                continue
            parent = _parent_of(config, item)
            rule = config.review.rule_for(dirs[source], source, parent)
            if rule is not None and rule.auto:
                state.save_assignment(
                    Assignment(
                        source=item.source,
                        source_id=item.source_id,
                        decision=rule.default,
                        decided_at=now,
                    )
                )
                key = f"{rule.source}/{rule.parent or '*'} -> {rule.default}"
                auto[key] = auto.get(key, 0) + 1
                continue
            lines.append(
                _line_for(config, state, item, item_day, rule.default if rule else UNDECIDED, dirs[source], parent)
            )

    # items put off earlier stay visible, already in place
    for assignment in state.assignments("later"):
        item = state.get(assignment.source, assignment.source_id)
        if item is not None:
            lines.append(
                _line_for(config, state, item, _day(item), "later", dirs.get(item.source, item.source))
            )

    path = _sheet_path(config, day)
    lines = _keep_placements(path, lines)
    sheet = Sheet(
        path=path,
        day=day,
        covers={dirs[source]: [p.label for p in periods] for source, periods in covered.items()},
        auto=auto,
        lines=tuple(lines),
    )
    atomic_write(path, render_sheet(config, sheet, state))
    return sheet


def _sheet_path(config: Config, day: date) -> Path:
    """The open sheet if there is one, otherwise a new one stamped with the time.

    An applied sheet is the record of what was decided in that round, so it is
    never rewritten. Several rounds in one day are ordinary, so the name carries
    the time as well: ``2026-09-22-150524.md``.
    """
    for existing in reversed(sheets(config)):
        if not _is_applied(existing):
            return existing
    # Every name keeps the same shape so sorting by name is sorting by time; two
    # rounds inside one second take the next free second.
    stamp = datetime.now().replace(microsecond=0)
    for offset in range(120):
        moment = (stamp + timedelta(seconds=offset)).strftime("%H%M%S")
        candidate = validated_target(config.vault, f"{SHEET_DIR}/{day.isoformat()}-{moment}.md")
        if not candidate.exists():
            return candidate
    raise ValueError(f"too many review sheets on {day.isoformat()}")


def _is_applied(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        fields, _ = parse_front_matter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return fields.get("state") == "applied"


def _parent_of(config: Config, item: ItemState) -> str:
    try:
        fields, _ = parse_front_matter((config.vault / item.relative_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return ""
    parent = fields.get("parent")
    return parent if isinstance(parent, str) else ""


def _line_for(
    config: Config,
    state: StateBackend,
    item: ItemState,
    day: date | None,
    decision: str,
    source_dir: str = "",
    parent: str | None = None,
) -> Line:
    return Line(
        source=item.source,
        source_id=item.source_id,
        title=item.title or item.source_id,
        relative_path=item.relative_path,
        day=day,
        pillar=classify_item(config, item),
        decision=decision,
        source_dir=source_dir or item.source,
        parent=parent if parent is not None else _parent_of(config, item),
    )


def _keep_placements(path: Path, lines: list[Line]) -> list[Line]:
    """Respect where a line already sits when the same day's sheet is rebuilt.

    Both the section and the topic it was grouped under are kept, so a round of
    sorting is never undone by running `review` again before `apply`.
    """
    if not path.is_file():
        return lines
    try:
        _, existing = read_sheet(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return lines
    placed = {line.relative_path: (line.decision, line.group) for line in existing}
    kept: list[Line] = []
    for line in lines:
        decision, group = placed.get(line.relative_path, (line.decision, line.group))
        kept.append(replace_fields(line, decision=decision, group=group))
    return kept


def render_sheet(config: Config, sheet: Sheet, state: StateBackend) -> str:
    front = [
        ("schema", SCHEMA_VERSION),
        ("review", sheet.stamp),
        ("state", "open"),
        ("covers", sheet.covers),
        ("items", sheet.listed),
        ("auto", sheet.auto),
    ]
    out = ["---", *(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in front), "---", ""]
    out.append(f"# Review {sheet.stamp}")
    out.append("")
    if sheet.covers:
        out.append("Read these digests, then move each line into the section that says what")
        out.append("happens to it and run `asterism apply`.")
        out.append("")
        for source, labels in sheet.covers.items():
            out.append(f"- {source}: {', '.join(labels)}")
        out.append("")
    if sheet.auto:
        for key, count in sorted(sheet.auto.items()):
            out.append(f"Applied by rule without listing: {count} ({key})")
        out.append("")
    if not sheet.lines:
        out.append("Nothing to decide.")
        return "\n".join(out).rstrip() + "\n"
    # every section lists every source, so a line can be moved under the right
    # heading without anyone having to type one
    order = sorted(
        {line.source_dir for line in sheet.lines},
        key=lambda name: (_newest([l for l in sheet.lines if l.source_dir == name]), name),
        reverse=True,
    )
    for number, section in enumerate(SECTIONS):
        out.append(f"## {ROMAN[number]}. {section}")
        out.append("")
        out.append(f"_{SECTION_HELP[section]}_")
        out.append("")
        chosen = [l for l in sheet.lines if l.decision == section]
        if section == "used":
            out.extend(_render_used(config, chosen, sheet.path))
        else:
            out.extend(_render_group(config, chosen, sheet.path, order))
    return "\n".join(out).rstrip() + "\n"


def _render_used(config: Config, lines: list[Line], sheet_path: Path) -> list[str]:
    """What has been chosen, organized by topic instead of by source.

    Where an item comes from stops mattering once it is going to be made, so
    this section carries no source headings and a `###` here means a topic.
    Lines inside a topic run oldest first, because they are the material of one
    piece and it reads in the order it happened; loose lines keep the sheet's
    newest-first order.
    """
    grouped: dict[str, list[Line]] = {}
    loose: list[Line] = []
    for line in lines:
        if line.group:
            grouped.setdefault(line.group, []).append(line)
        else:
            loose.append(line)
    out: list[str] = []
    for name, members in grouped.items():
        out.append(f"### {name}")
        out.append("")
        members.sort(key=lambda line: (line.day or date.min, line.title))
        out.extend(_render_line(config, line, sheet_path) for line in members)
        out.append("")
    loose.sort(key=lambda line: (line.day or date.min, line.title), reverse=True)
    out.extend(_render_line(config, line, sheet_path) for line in loose)
    if loose:
        out.append("")
    return out


def _newest(lines: list[Line]) -> date:
    return max((line.day for line in lines if line.day), default=date.min)


def _render_group(config: Config, lines: list[Line], sheet_path: Path, order: list[str]) -> list[str]:
    """Group by source, then by the folder the item sits in, newest first throughout.

    Sources keep the same number in every section so the destinations are
    learnable, and appear even when they hold nothing here.
    """
    by_source: dict[str, list[Line]] = {}
    for line in lines:
        by_source.setdefault(line.source_dir, []).append(line)
    out: list[str] = []
    for number, source in enumerate(order, 1):
        out.append(f"### {number}. {source}")
        out.append("")
        if source in by_source:
            out.extend(_render_folder(config, by_source[source], sheet_path, "", 0))
            out.append("")
    return out


def _render_folder(config: Config, lines: list[Line], sheet_path: Path, prefix: str, depth: int) -> list[str]:
    """One folder of a source, as a tree: subfolders nest, items sit under theirs.

    Folders and items are interleaved by recency, so whatever was touched last
    is at the top whatever depth it lives at.
    """
    indent = "  " * depth
    direct = [line for line in lines if line.parent == prefix]
    children: dict[str, list[Line]] = {}
    for line in lines:
        if line.parent == prefix:
            continue
        rest = line.parent[len(prefix) :].lstrip("/") if prefix else line.parent
        children.setdefault(rest.split("/", 1)[0], []).append(line)

    entries: list[tuple[date, str, str, object]] = [
        (line.day or date.min, line.title, "item", line) for line in direct
    ]
    entries += [(_newest(group), name, "folder", (name, group)) for name, group in children.items()]
    entries.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)

    out: list[str] = []
    for _day, _name, kind, payload in entries:
        if kind == "item":
            out.append(indent + _render_line(config, payload, sheet_path))
        else:
            name, group = payload
            out.append(f"{indent}- **{name}**")
            out.extend(
                _render_folder(config, group, sheet_path, f"{prefix}/{name}" if prefix else name, depth + 1)
            )
    return out


def _render_line(config: Config, line: Line, sheet_path: Path) -> str:
    """One item: its date, a link to it, and the pillar when a rule matched one.

    The link is the identity, so the line stays short enough to read and there
    is no machine marker to look at.
    """
    title = line.title if len(line.title) <= MAX_LABEL_CHARS else line.title[:MAX_LABEL_CHARS].rstrip() + "..."
    label = link_to(config.links, config.vault, line.relative_path, title, from_file=sheet_path)
    parts = [part for part in (line.day.isoformat() if line.day else "", label) if part]
    if line.pillar:
        parts.append(f"({line.pillar})")
    return "- " + " ".join(parts)


# --- reading and applying ------------------------------------------------------


def read_sheet(text: str, paths: dict[str, ItemState] | None = None) -> tuple[dict[str, object], list[Line]]:
    """Read a sheet back. Each line is identified by the note it links to.

    A ``###`` heading that the renderer did not number is a topic, and every
    line under it belongs to it until the next heading.
    """
    fields, body = parse_front_matter(text)
    lines: list[Line] = []
    section = UNDECIDED
    group = ""
    for raw in body.splitlines():
        heading = _SECTION.match(raw)
        if heading:
            name = heading.group("name")
            section = name if name in SECTIONS else UNDECIDED
            group = ""
            continue
        topic = _HEADING.match(raw)
        if topic:
            group = "" if _SOURCE_HEADING.match(raw) else topic.group("name")
            continue
        match = _LINE.match(raw)
        if match is None or raw.lstrip().startswith("- **"):
            continue  # folder headings carry no item
        target = _target_of(match.group("rest"))
        if target is None:
            continue
        day = None
        if match.group("day"):
            try:
                day = date.fromisoformat(match.group("day"))
            except ValueError:
                day = None
        item = (paths or {}).get(target)
        lines.append(
            Line(
                source=item.source if item else "",
                source_id=item.source_id if item else "",
                title=item.title or target if item else target,
                relative_path=target,
                day=day,
                pillar=None,
                decision=section,
                group=group,
            )
        )
    return fields, lines


def _target_of(rest: str) -> str | None:
    """The vault-relative note a line points at, from either link style."""
    match = _TARGET.search(rest)
    if match is None:
        return None
    target = (match.group("wiki") or match.group("md") or "").strip()
    if not target:
        return None
    if target.startswith("../"):  # a markdown link is relative to review/
        target = str(PurePosixPath("review").joinpath(target))
        target = str(PurePosixPath(target).resolve()) if False else _normalize(target)
    return target if target.endswith(".md") else f"{target}.md"


def _normalize(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    return "/".join(parts)


def path_index(state: StateBackend) -> dict[str, ItemState]:
    return {
        item.relative_path: item
        for source in state.sources()
        for item in state.items(source)
    }


def sheets(config: Config, prefix: str = "") -> list[Path]:
    """Every review sheet, oldest first; ``prefix`` selects a date or an exact name."""
    root = config.vault / SHEET_DIR
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("????-??-??*.md") if path.stem.startswith(prefix))


def latest_sheet(config: Config, prefix: str = "") -> Path | None:
    """The newest sheet that still has decisions to record, else the newest at all."""
    found = sheets(config, prefix)
    open_sheets = [path for path in found if not _is_applied(path)]
    return (open_sheets or found)[-1] if found else None


def apply_sheet(
    config: Config, state: StateBackend, path: Path, *, today: date | None = None
) -> tuple[dict[str, int], list[tuple[Line, str]]]:
    """Record every placement and turn the ``used`` ones into content projects.

    A topic under ``used`` becomes one project holding all of its material; a
    line on its own still becomes a project of its own.
    """
    text = path.read_text(encoding="utf-8")
    fields, lines = read_sheet(text, path_index(state))
    if fields.get("state") == "applied":
        return {}, []
    recorded: dict[str, int] = {}
    created: list[tuple[Line, str]] = []
    now = datetime.now().astimezone().isoformat()

    def record(line: Line, project_id: str | None) -> None:
        state.save_assignment(
            Assignment(
                source=line.source,
                source_id=line.source_id,
                decision=line.decision,
                decided_at=now,
                project_id=project_id,
            )
        )
        recorded[line.decision] = recorded.get(line.decision, 0) + 1

    for topic, members in _topics(state, lines).items():
        pillars = [classify_item(config, item) for _line, item in members]
        project = create_project(
            config,
            title=topic,
            pillar=next((pillar for pillar in pillars if pillar), None),
            sources=tuple(item.relative_path for _line, item in members),
            status="making",
            today=today,
        )
        created.append((members[0][0], project.id))
        for line, _item in members:
            record(line, project.id)

    for line in lines:
        if line.decision == UNDECIDED or (line.decision == "used" and line.group):
            continue  # a grouped line was already taken by its topic
        item = state.get(line.source, line.source_id) if line.source else None
        if item is None:
            continue  # the line points at a note this vault no longer has
        project_id = None
        if line.decision == "used":
            project = create_project(
                config,
                title=item.title or line.source_id,
                pillar=line.pillar or classify_item(config, item),
                sources=(item.relative_path,),
                status="making",
                today=today,
            )
            project_id = project.id
            created.append((line, project.id))
        record(line, project_id)

    atomic_write(path, text.replace('state: "open"', 'state: "applied"', 1))
    return recorded, created


def _topics(state: StateBackend, lines: list[Line]) -> dict[str, list[tuple[Line, ItemState]]]:
    """The topics under ``used``, each with the material it gathered, in sheet order.

    A line whose note the vault no longer holds is left out, so a topic that
    lost all of its material creates nothing.
    """
    topics: dict[str, list[tuple[Line, ItemState]]] = {}
    for line in lines:
        if line.decision != "used" or not line.group:
            continue
        item = state.get(line.source, line.source_id) if line.source else None
        if item is not None:
            topics.setdefault(line.group, []).append((line, item))
    return topics


def days_since_last(config: Config, *, today: date | None = None) -> int | None:
    sheet = latest_sheet(config)
    if sheet is None:
        return None
    try:
        return ((today or date.today()) - date.fromisoformat(sheet.stem[:10])).days
    except ValueError:
        return None
