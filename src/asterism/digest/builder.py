"""Build digest documents, one tree per collected source.

Each source keeps its own ``digest/<source>/<level>/`` tree, and every level
renders its whole period from state rather than pointing at the level below.
A week therefore holds the week, a month holds the month, and archiving the
lower level away loses nothing.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import DIGEST_LEVELS, Config
from ..links import link_to
from ..models import DigestState, ItemState
from ..normalize.datetimes import parse_datetime
from ..rendering import SCHEMA_VERSION, parse_front_matter
from ..state.base import StateBackend
from ..vault import atomic_write, validated_target
from .archive import archive_children
from .periods import Period, digest_relative_path, next_period, pending_periods, period_containing


@dataclass(frozen=True, slots=True)
class _Placed:
    item: ItemState
    moment: datetime
    day: date
    updated_day: date | None


def _without_repeated_title(body: str, title: str | None) -> str:
    """Drop a leading ``# Title`` that repeats the link above it.

    A digest entry already shows the item's title as the link, so the note's own
    first heading says it a second time and pushes the content down a line.
    """
    if not title:
        return body
    lines = body.splitlines()
    if lines and lines[0].lstrip("# ").strip() == title.strip() and lines[0].startswith("#"):
        return "\n".join(lines[1:]).lstrip("\n")
    return body


class DigestBuilder:
    def __init__(self, config: Config, state: StateBackend, *, now: datetime | None = None) -> None:
        self.config = config
        self.state = state
        self.vault = config.vault
        self.zone: tzinfo = ZoneInfo(config.digest.timezone) if config.digest.timezone else _local_zone()
        self.now = (now or datetime.now(self.zone)).astimezone(self.zone)
        self.today = self.now.date()
        self._placed: dict[str, list[_Placed]] = {}
        self._dirs: dict[str, str] = {}
        self.notes: list[str] = []

    # --- public ---------------------------------------------------------------

    def run(self) -> list[str]:
        """Generate every pending closed period and rebuild the open one, per source."""
        messages: list[str] = []
        sources = sorted(self.state.sources())
        if not sources:
            return ["no items collected yet"]
        for source in sources:
            placed = self._items(source)
            if not placed:
                continue
            since = min(entry.day for entry in placed)
            for level in DIGEST_LEVELS:
                if not self.config.digest.level(level).enabled:
                    continue
                generated = {
                    digest.period_start
                    for digest in self.state.digests(source, level)
                    if digest.state != "open"
                }
                for period in pending_periods(level, since, self.today, self.config.digest, generated):
                    if not self._has_items(source, period):
                        continue  # closed periods without items get no document
                    self._build(source, period, closed=True)
                    messages.append(f"{source} {level} {period.label} generated")
                current = period_containing(level, self.today, self.config.digest)
                if current.start <= self.today and self._has_items(source, current):
                    changed = self._build(source, current, closed=False)
                    messages.append(f"{source} {level} {current.label} {'rebuilt' if changed else 'unchanged'}")
        messages.extend(self.notes)
        self.notes = []
        return messages or ["nothing to aggregate yet"]

    def regenerate(self, period: Period, source: str | None = None) -> list[str]:
        if not self.config.digest.level(period.level).enabled:
            raise ValueError(f"digest level {period.level} is disabled")
        chosen = [source] if source else sorted(self.state.sources())
        messages: list[str] = []
        for name in chosen:
            if not self._has_items(name, period):
                continue
            self._build(name, period, closed=period.is_closed(self.today))
            messages.append(f"{name} {period.level} {period.label} regenerated")
        return messages or [f"nothing collected in {period.label}"]

    # --- items ----------------------------------------------------------------

    def _items(self, source: str) -> list[_Placed]:
        if source in self._placed:
            return self._placed[source]
        placed: list[_Placed] = []
        for item in self.state.items(source):
            moment = self._moment(item.digest_time)
            if moment is None:
                continue
            updated = self._moment(item.source_updated_at)
            placed.append(_Placed(item, moment, moment.date(), updated.date() if updated else None))
        self._placed[source] = placed
        return placed

    def source_dir(self, source: str) -> str:
        if source not in self._dirs:
            self._dirs[source] = source_directory(self.state, source)
        return self._dirs[source]

    def relative_path(self, source: str, period: Period) -> str:
        return digest_relative_path(self.source_dir(source), period)

    def _has_items(self, source: str, period: Period) -> bool:
        return bool(self._entries_in(source, period) or self._updated_in(source, period))

    def _moment(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parse_datetime(value)
        except ValueError:
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self.zone)
        return parsed.astimezone(self.zone)

    # --- documents --------------------------------------------------------------

    def _build(self, source: str, period: Period, *, closed: bool) -> bool:
        """Write the document; returns False when the existing file already matched."""
        relative = self.relative_path(source, period)
        target = validated_target(self.vault, relative)
        state_name = "closed" if closed else "open"
        entries = self._entries_in(source, period)

        front = [
            ("schema", SCHEMA_VERSION),
            ("digest", period.level),
            ("source", source),
            ("period_start", period.start.isoformat()),
            ("period_end", period.end.isoformat()),
            ("state", state_name),
            ("items", len(entries)),
            ("generated_at", self.now.isoformat()),
        ]
        lines = ["---", *(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in front), "---", ""]
        # the directory already says which source this is, so the title is the period
        lines.append(f"# {period.title}")
        lines.append("")
        lines.extend(self._content(source, period, 2, target))

        rendered = "\n".join(lines).rstrip() + "\n"
        changed = not (target.is_file() and _same_except_timestamp(target.read_text(encoding="utf-8"), rendered))
        if changed:
            atomic_write(target, rendered)
        self.state.save_digest(
            DigestState(
                source=source,
                level=period.level,
                period_start=period.start.isoformat(),
                period_end=period.end.isoformat(),
                relative_path=relative,
                state=state_name,
                generated_at=self.now.isoformat(),
            )
        )
        if closed:
            rolled = self._mark_lower_rolled(source, period)
            if rolled and self.config.digest.level(period.level).archive_lower:
                self.notes.extend(archive_children(self.config, self.state, rolled))
        return changed

    # --- content ----------------------------------------------------------------

    def _content(self, source: str, period: Period, depth: int, target: Path) -> list[str]:
        """The period's whole content for one source, rendered from state."""
        if period.level == "day":
            return self._items_body(source, period, depth, target)
        if not self.config.digest.level(period.level).include_lower:
            return []
        lower = self._lower_level(period.level)
        if lower is None:
            return self._items_body(source, period, depth, target)
        lines: list[str] = []
        for child in self._children(period, lower):
            if not self._has_items(source, child):
                continue  # periods with nothing in them are simply absent
            lines.append(f"{_heading(depth)} {child.label}")
            lines.append("")
            lines.extend(self._content(source, child, depth + 1, target))
        return lines

    def _items_body(self, source: str, period: Period, depth: int, target: Path) -> list[str]:
        entries = self._entries_in(source, period)
        updated = self._updated_in(source, period)
        lines: list[str] = []
        if entries:
            by_day: dict[date, list[_Placed]] = defaultdict(list)
            for entry in entries:
                by_day[entry.day].append(entry)
            single = period.level == "day" or len(by_day) == 1
            for day in sorted(by_day):
                if not single:
                    lines.append(f"{_heading(depth)} {day.isoformat()}")
                    lines.append("")
                for entry in sorted(by_day[day], key=lambda placed: (placed.moment, placed.item.source_id)):
                    lines.extend(self._entry_lines(entry, target))
                lines.append("")
        if updated:
            lines.append(f"{_heading(depth)} Updated")
            lines.append("")
            for entry in sorted(updated, key=lambda placed: (placed.item.source_id,)):
                lines.append(f"- {self._link(entry.item, target)}")
            lines.append("")
        return lines

    def _entries_in(self, source: str, period: Period) -> list[_Placed]:
        return [entry for entry in self._items(source) if period.start <= entry.day <= period.end]

    def _updated_in(self, source: str, period: Period) -> list[_Placed]:
        return [
            entry
            for entry in self._items(source)
            if entry.updated_day is not None
            and period.start <= entry.updated_day <= period.end
            and not (period.start <= entry.day <= period.end)
        ]

    def _entry_lines(self, entry: _Placed, target: Path) -> list[str]:
        stamp = entry.moment.strftime("%H:%M")
        head = f"- **{stamp}** {self._link(entry.item, target)}"
        excerpt = self._excerpt(entry.item)
        if not excerpt:
            return [head]
        return [head, *(f"  {line}" if line else "" for line in excerpt.splitlines())]

    def _excerpt(self, item: ItemState) -> str:
        try:
            path = validated_target(self.vault, item.relative_path)
            _, body = parse_front_matter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return ""
        body = _without_repeated_title(body.strip(), item.title)
        limit = self.config.digest.excerpt_chars
        if len(body) <= limit:
            return body
        return body[:limit].rstrip() + " ..."

    # --- levels -----------------------------------------------------------------

    def _lower_level(self, level: str) -> str | None:
        """The nearest enabled level below ``level``."""
        index = DIGEST_LEVELS.index(level)
        for lower in reversed(DIGEST_LEVELS[:index]):
            if self.config.digest.level(lower).enabled:
                return lower
        return None

    def _children(self, period: Period, lower: str) -> list[Period]:
        children: list[Period] = []
        child = period_containing(lower, period.start, self.config.digest)
        while child.start <= period.end:
            children.append(child)
            child = next_period(child, self.config.digest)
        return children

    def _mark_lower_rolled(self, source: str, period: Period) -> list[DigestState]:
        lower = self._lower_level(period.level)
        if lower is None:
            return []
        rolled: list[DigestState] = []
        for child in self._children(period, lower):
            recorded = self.state.get_digest(source, lower, child.start.isoformat())
            if recorded is not None and recorded.state in {"closed", "rolled"}:
                updated = DigestState(
                    source=recorded.source,
                    level=recorded.level,
                    period_start=recorded.period_start,
                    period_end=recorded.period_end,
                    relative_path=recorded.relative_path,
                    state="rolled",
                    generated_at=recorded.generated_at,
                )
                if recorded.state == "closed":
                    self.state.save_digest(updated)
                rolled.append(updated)
        return rolled

    # --- links --------------------------------------------------------------------

    def _link(self, item: ItemState, target: Path) -> str:
        label = item.title or item.source_id
        return link_to(self.config.links, self.vault, item.relative_path, label, from_file=target)


def source_directory(state: StateBackend, source: str) -> str:
    """The directory a source's digests live in, mirroring ``notes/<dir>/``."""
    for item in state.items(source):
        parts = item.relative_path.split("/")
        if len(parts) > 2 and parts[0] == "notes":
            return parts[1]
        break
    return source


def _heading(depth: int) -> str:
    """Markdown allows six levels; deeper nesting keeps the last one."""
    return "#" * min(depth, 6)


def _same_except_timestamp(existing: str, rendered: str) -> bool:
    strip = lambda text: "\n".join(line for line in text.splitlines() if not line.startswith("generated_at: "))
    return strip(existing) == strip(rendered)


def _local_zone() -> tzinfo:
    zone = datetime.now().astimezone().tzinfo
    assert zone is not None
    return zone
