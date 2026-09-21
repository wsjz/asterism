"""Build digest documents from item state and the notes mirror."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import DIGEST_LEVELS, Config
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
        entries = [entry for entry in self._items() if period.start <= entry.day <= period.end]
        updated = [
            entry for entry in self._items()
            if entry.updated_day is not None
            and period.start <= entry.updated_day <= period.end
            and not (period.start <= entry.day <= period.end)
        ]
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

        if period.level == "day":
            lines.extend(self._day_body(entries, updated, target))
        else:
            lines.extend(self._rollup_body(period, entries, target))

        rendered = "\n".join(lines).rstrip() + "\n"
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

    def _day_body(self, entries: list[_Placed], updated: list[_Placed], target: Path) -> list[str]:
        lines: list[str] = []
        if entries:
            lines.append("## New")
            lines.append("")
            by_source: dict[str, list[_Placed]] = defaultdict(list)
            for entry in entries:
                by_source[entry.item.source].append(entry)
            for source in sorted(by_source):
                lines.append(f"### {source}")
                lines.append("")
                for entry in sorted(by_source[source], key=lambda placed: (placed.moment, placed.item.source_id)):
                    lines.extend(self._entry_lines(entry, target))
                lines.append("")
        if updated:
            lines.append("## Updated")
            lines.append("")
            for entry in sorted(updated, key=lambda placed: (placed.item.source, placed.item.source_id)):
                lines.append(f"- {self._link(entry.item, target)}")
            lines.append("")
        return lines

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
        return body[:limit].rstrip() + " …"

    def _rollup_body(self, period: Period, entries: list[_Placed], target: Path) -> list[str]:
        lines: list[str] = []
        counts = Counter(entry.item.source for entry in entries)
        if counts:
            lines.append("| source | items |")
            lines.append("|---|---|")
            for source, count in sorted(counts.items()):
                lines.append(f"| {source} | {count} |")
            lines.append("")

        level_config = self.config.digest.level(period.level)
        if not level_config.include_lower:
            return lines
        lower = self._lower_level(period.level)
        if lower is None:
            return lines
        merge = self._will_move_lower(period.level)
        section: list[str] = []
        for child in self._children(period, lower):
            child_target = validated_target(self.vault, child.relative_path)
            if child_target.is_file():
                section.extend(self._merged(child, child_target) if merge else [self._embed(child, target)])
            elif merge and self._archived_copy(child).is_file():
                section.extend(self._merged(child, self._archived_copy(child)))
            # periods without a document are simply absent
        if section:
            lines.append(f"## {lower.capitalize()} digests")
            lines.append("")
            lines.extend(section)
            lines.append("")
        return lines

    def _will_move_lower(self, level: str) -> bool:
        return (
            self.config.archive.enabled
            and self.config.archive.mode == "move"
            and self.config.digest.level(level).archive_lower
        )

    def _archived_copy(self, child: Period) -> Path:
        return self.config.archive_root / child.relative_path

    def _merged(self, child: Period, path: Path) -> list[str]:
        try:
            _, body = parse_front_matter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return [f"- {child.label}: unreadable digest"]
        merged = [f"### {child.label}", ""]
        for line in body.strip().splitlines():
            merged.append(f"#{line}" if line.startswith("#") else line)
        merged.append("")
        return merged

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
        title = item.title or item.source_id
        if self.config.links == "wikilink":
            return f"[[{item.relative_path.removesuffix('.md')}|{_escape_link_text(title)}]]"
        relative = _relative_href(self.vault / item.relative_path, target)
        return f"[{_escape_link_text(title)}]({relative})"

    def _embed(self, child: Period, target: Path) -> str:
        if self.config.links == "wikilink":
            return f"![[{child.relative_path.removesuffix('.md')}]]"
        relative = _relative_href(self.vault / child.relative_path, target)
        return f"- [{child.label}]({relative})"


def _same_except_timestamp(existing: str, rendered: str) -> bool:
    strip = lambda text: "\n".join(line for line in text.splitlines() if not line.startswith("generated_at: "))
    return strip(existing) == strip(rendered)


def _escape_link_text(text: str) -> str:
    return " ".join(text.replace("]", "").replace("[", "").replace("|", "-").split())


def _relative_href(path: Path, from_file: Path) -> str:
    import os

    return os.path.relpath(path, start=from_file.parent).replace(os.sep, "/")


def _local_zone() -> tzinfo:
    zone = datetime.now().astimezone().tzinfo
    assert zone is not None
    return zone
