"""Split a daily-log note into time-stamped fragments.

A daily log is one note per day to which the writer appends lines such as
``09:20 an idea`` throughout the day. The fragment, not the note, is the unit
of collection: editing one line changes one item and appending a line adds
one item.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo
import re

from ..normalize.punctuation import TIME_SEPARATORS


# "09:20 text", optionally "09:20:05" and an optional separator after the time
_TIME_LINE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*[" + re.escape(TIME_SEPARATORS) + r"]?\s*(.*)$")
_LEADING_DATE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")
PREAMBLE_ANCHOR = "preamble"


@dataclass(frozen=True, slots=True)
class Fragment:
    anchor: str
    created_at: datetime
    text: str


def note_date(title: str, fallback: datetime | None) -> date | None:
    """The day a daily-log note describes: a leading YYYY-MM-DD in the title, else the fallback."""
    match = _LEADING_DATE.match(title or "")
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return fallback.date() if fallback else None


def split_daily_log(
    content: str,
    *,
    title: str,
    day: date | None,
    note_created_at: datetime | None,
    zone: tzinfo,
) -> list[Fragment]:
    """Return the fragments of ``content`` in document order.

    Lines before the first timestamp form a ``preamble`` fragment dated at the
    note's creation time. A title line identical to ``title`` is skipped.
    Repeated times get ``-2``, ``-3`` … suffixes so anchors stay unique.
    """
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and title and lines[0].strip() == title.strip():
        lines = lines[1:]

    fragments: list[Fragment] = []
    seen: dict[str, int] = {}
    current_anchor: str | None = None
    current_time: datetime | None = None
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        buffer.clear()
        if not text:
            return
        if current_anchor is None:
            anchor = PREAMBLE_ANCHOR
            created = _localize(note_created_at, zone) or (
                datetime.combine(day, datetime.min.time(), tzinfo=zone) if day else None
            )
        else:
            anchor = current_anchor
            created = current_time
        if created is None:
            return
        count = seen.get(anchor, 0) + 1
        seen[anchor] = count
        unique = anchor if count == 1 else f"{anchor}-{count}"
        fragments.append(Fragment(unique, created, text))

    for line in lines:
        match = _TIME_LINE.match(line)
        stamped = None
        if match and day is not None:
            hour, minute = int(match.group(1)), int(match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                stamped = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        if stamped is not None:
            flush()
            current_anchor = f"{stamped:%H:%M}"
            current_time = stamped
            buffer.append(match.group(3))
        else:
            buffer.append(line)
    flush()
    return fragments


def _localize(value: datetime | None, zone: tzinfo) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=zone)
