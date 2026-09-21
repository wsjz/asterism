from datetime import date
import unittest

from asterism.config import DigestConfig, DigestLevelConfig
from asterism.digest.periods import Period, parse_label, pending_periods, period_containing


def cfg(week=7, month="last", year=12, week_on=True, month_on=True):
    return DigestConfig(
        week=DigestLevelConfig(enabled=week_on, run_on=week),
        month=DigestLevelConfig(enabled=month_on, run_on=month),
        year=DigestLevelConfig(enabled=True, run_on=year),
    )


class PeriodTest(unittest.TestCase):
    def test_week_ends_on_run_on_weekday(self) -> None:
        # 2026-09-21 is a Monday; with run_on=3 (Wednesday) the period is Thu 17 .. Wed 23
        period = period_containing("week", date(2026, 9, 21), cfg(week=3))
        self.assertEqual((date(2026, 9, 17), date(2026, 9, 23)), (period.start, period.end))
        self.assertEqual("2026-W39", period.label)
        self.assertEqual("digest/weekly/2026/2026-W39.md", period.relative_path)
        # the day after a period end starts the next one
        following = period_containing("week", date(2026, 9, 24), cfg(week=3))
        self.assertEqual(date(2026, 9, 24), following.start)

    def test_month_variants(self) -> None:
        last = period_containing("month", date(2026, 2, 10), cfg(month="last"))
        self.assertEqual((date(2026, 2, 1), date(2026, 2, 28)), (last.start, last.end))
        fourth = period_containing("month", date(2026, 9, 29), cfg(month=4))
        # after the 4th block (ends 28th) the 29th belongs to the period ending Oct 28
        self.assertEqual((date(2026, 9, 29), date(2026, 10, 28)), (fourth.start, fourth.end))
        self.assertEqual("2026-10", fourth.label)
        listed = tuple(f"{m:02d}-{d:02d}" for m, d in [(1,31),(2,28),(3,31),(4,30),(5,15),(6,30),(7,31),(8,31),(9,30),(10,31),(11,30),(12,31)])
        may = period_containing("month", date(2026, 5, 20), cfg(month=listed))
        self.assertEqual((date(2026, 5, 16), date(2026, 6, 30)), (may.start, may.end))
        clamped = period_containing("month", date(2026, 2, 5), cfg(month=5))
        self.assertEqual(date(2026, 2, 28), clamped.end)

    def test_year_ends_on_run_on_month(self) -> None:
        period = period_containing("year", date(2026, 9, 21), cfg(year=6))
        self.assertEqual((date(2026, 7, 1), date(2027, 6, 30)), (period.start, period.end))
        self.assertEqual("2027", period.label)
        self.assertEqual("digest/yearly/2027.md", period.relative_path)

    def test_pending_periods_catch_up_and_skip_generated(self) -> None:
        pending = pending_periods("week", date(2026, 9, 1), date(2026, 9, 24), cfg(week=3), {"2026-09-03"})
        starts = [period.start.isoformat() for period in pending]
        self.assertEqual(["2026-08-27", "2026-09-10", "2026-09-17"], starts)
        self.assertTrue(all(period.end < date(2026, 9, 24) for period in pending))
        self.assertEqual([], pending_periods("day", date(2026, 9, 24), date(2026, 9, 24), cfg(), set()))

    def test_parse_label(self) -> None:
        config = cfg(week=3)
        self.assertEqual(Period("day", date(2026, 9, 21), date(2026, 9, 21)), parse_label("2026-09-21", config))
        self.assertEqual("2026-W39", parse_label("2026-W39", config).label)
        self.assertEqual("2026-09", parse_label("2026-09", config).label)
        self.assertEqual("2026", parse_label("2026", config).label)
        with self.assertRaises(ValueError):
            parse_label("last-week", config)


if __name__ == "__main__":
    unittest.main()
