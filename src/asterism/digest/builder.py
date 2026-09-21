"""Build digest documents from item state and the notes mirror."""
from __future__ import annotations

from collections import Counter, defaultdict
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
from .periods import Period, next_period, pending_periods, period_containing


@dataclass(frozen=True, slots=True)
class _Placed:
    item: ItemState
    moment: datetime
    day: date
    updated_day: date | None


class DigestBuilder:
    def __init__(self, config: Config, state: StateBackend, *, now: datetime | None = None) -> None:
        self.config = config
        self.state = state
        self.vault = config.vault
        self.zone: tzinfo = ZoneInfo(config.digest.timezone) if config.digest.timezone else _local_zone()
        self.now = (now or datetime.now(self.zone)).astimezone(self.zone)
        self.today = self.now.date()
        self._placed: list[_Placed] | None = None
        self.notes: list[str] = []

    # --- public ---------------------------------------------------------------

    def run(self) -> list[str]:
        """Generate every pending closed period and rebuild the open one for each enabled level."""
        messages: list[str] = []
        placed = self._items()
        if not placed:
            return ["no items collected yet"]
        since = min(entry.day for entry in placed)
        for level in DIGEST_LEVELS:
            if not self.config.digest.level(level).enabled:
                continue
            generated = {digest.period_start for digest in self.state.digests(level) if digest.state != "open"}
            for period in pending_periods(level, since, self.today, self.config.digest, generated):
                if not self._has_items(period):
                    continue  # closed periods without items get no document
                self._build(period, closed=True)
                messages.append(f"{level} {period.label} generated")
            current = period_containing(level, self.today, self.config.digest)
            if current.start <= self.today and self._has_items(current):
                changed = self._build(current, closed=False)
                messages.append(f"{level} {current.label} {'rebuilt' if changed else 'unchanged'}")
        messages.extend(self.notes)
        self.notes = []
        return messages

    def regenerate(self, period: Period) -> str:
        if not self.config.digest.level(period.level).enabled:
            raise ValueError(f"digest level {period.level} is disabled")
        self._build(period, closed=period.is_closed(self.today))
        return f"{period.level} {period.label} regenerated"

    # --- items ----------------------------------------------------------------

    def _items(self) -> list[_Placed]:
        if self._placed is not None:
            return self._placed
        placed: list[_Placed] = []
        for source in sorted(self.state.sources()):
            for item in self.state.items(source):
                moment = self._moment(item.digest_time)
                if moment is None:
                    continue
                updated = self._moment(item.source_updated_at)
                placed.append(_Placed(item, moment, moment.date(), updated.date() if updated else None))
        self._placed = placed
        return placed

    def _has_items(self, period: Period) -> bool:
        return any(period.start <= entry.day <= period.end for entry in self._items())

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

    def _build(self, period: Period, *, closed: bool) -> bool:
        """Write the period's document; returns False when the existing file already matched."""
        target = validated_target(self.vault, period.relative_path)
        existing_status = self._existing_review_status(target)
        state_name = "closed" if closed else "open"
        entries = self._entries_in(period)
        counts = Counter(entry.item.source for entry in entries)

        front = [
            ("schema", SCHEMA_VERSION),
            ("digest", period.level),
            ("period_start", period.start.isoformat()),
            ("period_end", period.end.isoformat()),
            ("state", state_name),
            ("review_status", existing_status or self.config.digest.review_status_default),
            ("items", len(entries)),
            ("sources", dict(sorted(counts.items()))),
            ("generated_at", self.now.isoformat()),
        ]
        lines = ["---", *(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in front), "---", ""]
        lines.append(f"# {period.title}")
        lines.append("")

        lines.extend(self._content(period, 2, target))

        rendered = "\n".join(lines).rstrip() + "\n"
        rendered = _with_preserved_tail(rendered, target)
        changed = not (target.is_file() and _same_except_timestamp(target.read_text(encoding="utf-8"), rendered))
        if changed:
            atomic_write(target, rendered)
        self.state.save_digest(
            DigestState(
                level=period.level,
                period_start=period.start.isoformat(),
                period_end=period.end.isoformat(),
                relative_path=period.relative_path,
                state=state_name,
                generated_at=self.now.isoformat(),
            )
        )
        if closed:
            rolled = self._mark_lower_rolled(period)
            if rolled and self.config.digest.level(period.level).archive_lower:
                self.notes.extend(archive_children(self.config, self.state, rolled))
        return changed

    def _existing_review_status(self, target: Path) -> str | None:
        if not target.is_file():
            return None
        try:
            fields, _ = parse_front_matter(target.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        value = fields.get("review_status")
        return value if isinstance(value, str) and value in self.config.digest.review_status_values else None

    # --- content ----------------------------------------------------------------

    def _content(self, period: Period, depth: int, target: Path) -> list[str]:
        """The period's whole content, rendered from state.

        Every level holds its own text rather than pointing at the level below,
        so a week still shows the whole week after its days have been archived
        away, and a month still shows the whole month.
        """
        if period.level == "day":
            return self._items_body(period, depth, target)

        lines = self._summary_table(self._entries_in(period))
        level_config = self.config.digest.level(period.level)
        if not level_config.include_lower:
            return lines
        lower = self._lower_level(period.level)
        if lower is None:
            lines.extend(self._items_body(period, depth, target))
            return lines
        for child in self._children(period, lower):
            if not self._entries_in(child) and not self._updated_in(child):
                continue  # periods with nothing in them are simply absent
            lines.append(f"{_heading(depth)} {child.label}")
            lines.append("")
            lines.extend(self._content(child, depth + 1, target))
        return lines

    def _summary_table(self, entries: list[_Placed]) -> list[str]:
        counts = Counter(entry.item.source for entry in entries)
        if not counts:
            return []
        lines = ["| source | items |", "|---|---|"]
        lines.extend(f"| {source} | {count} |" for source, count in sorted(counts.items()))
        lines.append("")
        return lines

    def _items_body(self, period: Period, depth: int, target: Path) -> list[str]:
        entries = self._entries_in(period)
        updated = self._updated_in(period)
        lines: list[str] = []
        if entries:
            lines.append(f"{_heading(depth)} New")
            lines.append("")
            by_source: dict[str, list[_Placed]] = defaultdict(list)
            for entry in entries:
                by_source[entry.item.source].append(entry)
            for source in sorted(by_source):
                lines.append(f"{_heading(depth + 1)} {source}")
                lines.append("")
                for entry in sorted(by_source[source], key=lambda placed: (placed.moment, placed.item.source_id)):
                    lines.extend(self._entry_lines(entry, target))
                lines.append("")
        if updated:
            lines.append(f"{_heading(depth)} Updated")
            lines.append("")
            for entry in sorted(updated, key=lambda placed: (placed.item.source, placed.item.source_id)):
                lines.append(f"- {self._link(entry.item, target)}")
            lines.append("")
        return lines

    def _entries_in(self, period: Period) -> list[_Placed]:
        return [entry for entry in self._items() if period.start <= entry.day <= period.end]

    def _updated_in(self, period: Period) -> list[_Placed]:
        return [
            entry
            for entry in self._items()
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
        body = body.strip()
        limit = self.config.digest.excerpt_chars
        if len(body) <= limit:
            return body
        return body[:limit].rstrip() + " ..."

    def _lower_level(self, level: str) -> str | None:
        """The nearest enabled level below ``level``; months fall back to days when weeks are off."""
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

    def _mark_lower_rolled(self, period: Period) -> list[DigestState]:
        lower = self._lower_level(period.level)
        if lower is None:
            return []
        rolled: list[DigestState] = []
        for child in self._children(period, lower):
            recorded = self.state.get_digest(lower, child.start.isoformat())
            if recorded is not None and recorded.state in {"closed", "rolled"}:
                updated = DigestState(
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

    # --- links ------------------------------------------------------------------

    def _link(self, item: ItemState, target: Path) -> str:
        label = item.title or item.source_id
        return link_to(self.config.links, self.vault, item.relative_path, label, from_file=target)

def _heading(depth: int) -> str:
    """Markdown allows six levels; deeper nesting keeps the last one."""
    return "#" * min(depth, 6)


def _with_preserved_tail(rendered: str, target: Path) -> str:
    """Keep the person's candidates section when a digest is rebuilt."""
    from ..gates.candidates import preserved_tail

    if not target.is_file():
        return rendered
    try:
        tail = preserved_tail(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return rendered
    return rendered if tail is None else rendered.rstrip() + "\n\n" + tail.lstrip("\n")


def _same_except_timestamp(existing: str, rendered: str) -> bool:
    strip = lambda text: "\n".join(line for line in text.splitlines() if not line.startswith("generated_at: "))
    return strip(existing) == strip(rendered)


def _local_zone() -> tzinfo:
    zone = datetime.now().astimezone().tzinfo
    assert zone is not None
    return zone
