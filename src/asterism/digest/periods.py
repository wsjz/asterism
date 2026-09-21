"""Pure period arithmetic for digests. No I/O, no Asterism state."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
import re

from ..config import DIGEST_LEVELS, MONTH_RUN_ON_LAST, DigestConfig


_LEVEL_DIRS = {"day": "daily", "week": "weekly", "month": "monthly", "year": "yearly"}
_LABELS = {
    "day": re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"),
    "week": re.compile(r"^(\d{4})-W(\d{2})$"),
    "month": re.compile(r"^(\d{4})-(\d{2})$"),
    "year": re.compile(r"^(\d{4})$"),
}


@dataclass(frozen=True, slots=True)
class Period:
    level: str
    start: date  # inclusive
    end: date  # inclusive

    @property
    def label(self) -> str:
        if self.level == "day":
            return self.end.isoformat()
        if self.level == "week":
            iso_year, iso_week, _ = self.end.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"
        if self.level == "month":
            return f"{self.end.year}-{self.end.month:02d}"
        return f"{self.end.year}"

    @property
    def relative_path(self) -> str:
        directory = _LEVEL_DIRS[self.level]
        if self.level == "year":
            return f"digest/{directory}/{self.label}.md"
        return f"digest/{directory}/{self.end.year}/{self.label}.md"

    @property
    def title(self) -> str:
        if self.level == "day":
            return self.label
        return f"{self.label} ({self.start.isoformat()} to {self.end.isoformat()})"

    def is_closed(self, today: date) -> bool:
        return self.end < today

    def days(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range((self.end - self.start).days + 1)]


def _month_end_day(year: int, month: int, run_on: int | tuple[str, ...] | str | None) -> int:
    last = calendar.monthrange(year, month)[1]
    if run_on == MONTH_RUN_ON_LAST or run_on is None:
        return last
    if isinstance(run_on, int):
        return min(7 * run_on, last)
    return min(int(run_on[month - 1].split("-")[1]), last)


def _month_period_end(year: int, month: int, run_on: int | tuple[str, ...] | str | None) -> date:
    return date(year, month, _month_end_day(year, month, run_on))


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def period_containing(level: str, day: date, config: DigestConfig) -> Period:
    """The period of ``level`` that contains ``day``."""
    if level not in DIGEST_LEVELS:
        raise ValueError(f"unknown digest level: {level}")
    run_on = config.level(level).run_on

    if level == "day":
        return Period("day", day, day)

    if level == "week":
        weekday = run_on if isinstance(run_on, int) else 7
        end = day + timedelta(days=(weekday - day.isoweekday()) % 7)
        return Period("week", end - timedelta(days=6), end)

    if level == "month":
        end = _month_period_end(day.year, day.month, run_on)
        if day > end:
            year, month = _shift_month(day.year, day.month, 1)
            end = _month_period_end(year, month, run_on)
            previous_end = _month_period_end(day.year, day.month, run_on)
        else:
            year, month = _shift_month(day.year, day.month, -1)
            previous_end = _month_period_end(year, month, run_on)
        return Period("month", previous_end + timedelta(days=1), end)

    month = run_on if isinstance(run_on, int) else 12
    end = date(day.year, month, calendar.monthrange(day.year, month)[1])
    if day > end:
        end = date(day.year + 1, month, calendar.monthrange(day.year + 1, month)[1])
    previous_end = date(end.year - 1, month, calendar.monthrange(end.year - 1, month)[1])
    return Period("year", previous_end + timedelta(days=1), end)


def next_period(period: Period, config: DigestConfig) -> Period:
    return period_containing(period.level, period.end + timedelta(days=1), config)


def pending_periods(level: str, since: date, today: date, config: DigestConfig, generated: set[str]) -> list[Period]:
    """Closed periods from ``since`` up to ``today`` whose start date is not in ``generated``."""
    result: list[Period] = []
    period = period_containing(level, since, config)
    while period.is_closed(today):
        if period.start.isoformat() not in generated:
            result.append(period)
        period = next_period(period, config)
    return result


def parse_label(label: str, config: DigestConfig) -> Period:
    """Turn a label such as ``2026-09-21``, ``2026-W39``, ``2026-09``, or ``2026`` into its period."""
    for level, pattern in _LABELS.items():
        match = pattern.match(label.strip())
        if not match:
            continue
        if level == "day":
            return Period("day", *(date(*map(int, match.groups())),) * 2)
        if level == "week":
            anchor = date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
            return period_containing("week", anchor, config)
        if level == "month":
            year, month = int(match.group(1)), int(match.group(2))
            return period_containing("month", _month_period_end(year, month, config.month.run_on), config)
        year = int(match.group(1))
        month = config.year.run_on if isinstance(config.year.run_on, int) else 12
        return period_containing("year", date(year, month, 1), config)
    raise ValueError(f"unrecognized digest label: {label!r}")
