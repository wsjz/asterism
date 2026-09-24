import contextlib
from datetime import date, datetime
import io
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from asterism.cli import _apply, _propose, main
from asterism.projects import create_project
from asterism.config import CONFIG_NAME, ConfigError, initialize_vault, load_config
from asterism.digest import DigestBuilder
from asterism.gates import build_sheet, coverage, latest_sheet, read_sheet, sheets
from asterism.models import SourceItem
from asterism.pipeline import Pipeline
from asterism.projects import load_projects
from asterism.sources.base import Source
from asterism.state import FileStateBackend


SH = ZoneInfo("Asia/Shanghai")
TODAY = date(2026, 9, 26)
CONFIG = (
    "state:\n  backend: file\n"
    "digest:\n  timezone: Asia/Shanghai\n  week: { run_on: 3 }\n"
    "content:\n  pillars: [{ key: desk-setup, tags: [desk] }]\n"
    "picks:\n"
    "  every: 3\n"
    "  rules:\n"
    "    - { source: flomo, parent: Chores, default: dropped, auto: true }\n"
    "    - { source: flomo, default: reference }\n"
)


class FakeSource(Source):
    name = "flomo"
    output_name = "flomo"

    def __init__(self, items):
        self.items = items

    def collect(self):
        return self.items


def _vault(temporary: str, config_text: str = CONFIG) -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text(config_text, encoding="utf-8")
    return load_config(vault).vault


ITEMS = [
    SourceItem("flomo", "m1", "Desk lighting", "Body one", created_at=datetime(2026, 9, 14, 9, 20, tzinfo=SH), tags=("desk",)),
    SourceItem("flomo", "m2", "A loose thought", "Body two", created_at=datetime(2026, 9, 15, 12, 40, tzinfo=SH)),
    SourceItem("flomo", "m3", "Buy milk", "Body three", created_at=datetime(2026, 9, 16, 8, 0, tzinfo=SH), parent="Chores"),
    SourceItem("flomo", "m4", "After the week", "Body four", created_at=datetime(2026, 9, 24, 8, 0, tzinfo=SH)),
]


def _seed(vault: Path, *, now: datetime) -> None:
    config = load_config(vault)
    with FileStateBackend(config.state_dir / "manifest.json") as state:
        Pipeline(FakeSource(ITEMS), state, vault).sync()
        DigestBuilder(config, state, now=now).run()


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _call(function, *args) -> tuple[int, str]:
    """Run a command handler on a fixed date, which the command line cannot set."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = function(*args)
    return code, out.getvalue()


def _move(path: Path, title: str, section: str) -> None:
    """Move a line into another section, the way a person would in an editor."""
    lines = path.read_text(encoding="utf-8").splitlines()
    moved = next(line for line in lines if f"|{title}]]" in line)
    lines.remove(moved)
    index = next(i for i, line in enumerate(lines) if line.startswith("## ") and line.endswith(f" {section}"))
    lines.insert(index + 4, moved.lstrip())  # past the heading, its blank line, and the hint
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _group_under(path: Path, topic: str, titles: tuple[str, ...]) -> None:
    """Move several lines under one topic heading in the used section."""
    lines = path.read_text(encoding="utf-8").splitlines()
    moved = [next(line for line in lines if f"|{title}]]" in line) for title in titles]
    for line in moved:
        lines.remove(line)
    index = next(i for i, line in enumerate(lines) if line.startswith("## ") and line.endswith(" used"))
    block = [f"### {topic}", ""] + [line.lstrip() for line in moved] + [""]
    lines[index + 4 : index + 4] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class CoverageTest(unittest.TestCase):
    def test_takes_the_coarsest_closed_period_then_the_loose_days(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                covered = coverage(config, state, today=date(2026, 9, 26))
            labels = [period.label for period in covered["flomo"]]
            # the week ending Wednesday covers three days; 09-24 is a loose day after it
            self.assertEqual(["2026-W38", "2026-09-24"], labels)
            self.assertEqual(["week", "day"], [period.level for period in covered["flomo"]])

    def test_a_period_still_accumulating_is_never_offered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 16, 9, 0, tzinfo=SH))
            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                covered = coverage(config, state, today=date(2026, 9, 16))
            self.assertEqual(["2026-09-14", "2026-09-15"], [p.label for p in covered["flomo"]])


class SheetTest(unittest.TestCase):
    def test_rules_place_lines_and_auto_rules_never_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            code, out = _call(_propose, load_config(vault), None, TODAY)
            self.assertEqual(0, code)
            self.assertIn("Applied by rule: 1", out)
            self.assertIn("read flomo: 2026-W38, 2026-09-24", out)

            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            text = sheet.read_text(encoding="utf-8")
            self.assertIn("## IV. reference", text)
            self.assertIn("[[notes/flomo/origin/Desk lighting|Desk lighting]] (desk-setup)", text)
            self.assertNotIn("Buy milk", text)  # the auto rule took it without asking
            fields, lines = read_sheet(text)
            self.assertEqual("open", fields["state"])
            self.assertRegex(str(fields["round"]), r"^2026-09-26 \d{2}:\d{2}:\d{2}$")
            self.assertIn(f"# Picks {fields["round"]}", text)
            self.assertEqual(3, len(lines))
            self.assertEqual({"reference"}, {line.decision for line in lines})

            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                self.assertEqual("dropped", state.get_assignment("flomo", "m3").decision)

    def test_rebuilding_the_same_day_keeps_where_lines_were_moved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            _move(sheet, "Desk lighting", "used")
            _call(_propose, load_config(vault), None, TODAY)
            _, lines = read_sheet(sheet.read_text(encoding="utf-8"))
            self.assertEqual("used", next(l.decision for l in lines if "Desk lighting" in l.relative_path))

    def test_since_skips_the_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), "2026-09-20", TODAY)
            _, lines = read_sheet(next(iter(sorted((vault / "picks").glob("*.md")))).read_text(encoding="utf-8"))
            self.assertEqual(["notes/flomo/origin/After the week.md"], [line.relative_path for line in lines])


class ApplyTest(unittest.TestCase):
    def test_outcomes_are_recorded_and_used_becomes_a_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            _move(sheet, "Desk lighting", "used")
            _move(sheet, "A loose thought", "later")

            code, out = _call(_apply, load_config(vault), None, TODAY)
            self.assertEqual(0, code)
            self.assertIn("1 later", out)
            self.assertIn("1 reference", out)
            self.assertIn("1 used", out)

            config = load_config(vault)
            projects = load_projects(config).projects
            self.assertEqual(1, len(projects))
            self.assertEqual(("candidate", "desk-setup"), (projects[0].status, projects[0].pillar))
            self.assertEqual(("notes/flomo/origin/Desk lighting.md",), projects[0].sources)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                self.assertEqual("used", state.get_assignment("flomo", "m1").decision)
                self.assertEqual(projects[0].id, state.get_assignment("flomo", "m1").project_id)
                self.assertEqual("later", state.get_assignment("flomo", "m2").decision)
            self.assertIn('state: "applied"', sheet.read_text(encoding="utf-8"))

    def test_applying_twice_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            _move(next(iter(sorted((vault / "picks").glob("*.md")))), "Desk lighting", "used")
            _call(_apply, load_config(vault), None, TODAY)
            code, out = _call(_apply, load_config(vault), None, TODAY)
            self.assertEqual(0, code)
            self.assertIn("nothing left to apply", out)
            self.assertEqual(1, len(load_projects(load_config(vault)).projects))

    def test_later_items_come_back_and_decided_ones_do_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            _move(next(iter(sorted((vault / "picks").glob("*.md")))), "A loose thought", "later")
            _call(_apply, load_config(vault), None, TODAY)

            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                sheet = build_sheet(config, state, today=date(2026, 9, 27))
            ids = [line.source_id for line in sheet.lines]
            self.assertIn("m2", ids)  # put off, so it is offered again
            self.assertNotIn("m1", ids)  # settled as reference
            self.assertEqual("later", next(l.decision for l in sheet.lines if l.source_id == "m2"))

    def test_an_applied_sheet_is_never_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            first = next((vault / "picks").glob("*.md"))
            _move(first, "Desk lighting", "used")
            _call(_apply, load_config(vault), None, TODAY)
            recorded = first.read_text(encoding="utf-8")

            # a second round the same day opens its own sheet and leaves the record alone
            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                Pipeline(FakeSource([SourceItem(
                    "flomo", "m9", "Something new", "Body",
                    created_at=datetime(2026, 9, 16, 9, 0, tzinfo=SH),
                )]), state, config.vault).sync()
            _call(_propose, load_config(vault), None, TODAY)

            self.assertEqual(recorded, first.read_text(encoding="utf-8"))
            self.assertIn('state: "applied"', recorded)
            self.assertIn("Desk lighting", recorded)
            both = sorted((vault / "picks").glob("*.md"))
            self.assertEqual(2, len(both))
            self.assertRegex(both[1].stem, r"^2026-09-26-\d{6}")  # the name carries the time
            self.assertNotIn("Desk lighting", both[1].read_text(encoding="utf-8"))

    def test_apply_without_a_sheet_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            code, _, err = _run("apply", "--vault", str(vault))
            self.assertEqual(1, code)
            self.assertIn("nothing to apply", err)


class MaterialTest(unittest.TestCase):
    def test_lists_what_was_decided_and_counts_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            _move(sheet, "Desk lighting", "used")
            _move(sheet, "A loose thought", "dropped")
            _call(_apply, load_config(vault), None, TODAY)

            code, out, _ = _run("material", "--vault", str(vault))
            self.assertEqual(0, code)
            self.assertIn("2 dropped", out)  # the rule dropped one, I dropped another
            self.assertIn("1 used", out)

            _, listed, _ = _run("material", "--vault", str(vault), "--status", "dropped")
            self.assertIn("notes/flomo/origin/A loose thought.md", listed)
            self.assertIn("2 item(s)", listed)

            _, used, _ = _run("material", "--vault", str(vault), "--status", "used")
            self.assertIn("-> 2026-001", used)


class TopicTest(unittest.TestCase):
    def test_a_topic_becomes_one_project_holding_all_of_its_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            _group_under(sheet, "September report", ("Desk lighting", "A loose thought"))

            code, out = _call(_apply, load_config(vault), None, TODAY)
            self.assertEqual(0, code)
            self.assertIn("2 used", out)

            projects = load_projects(load_config(vault)).projects
            self.assertEqual(1, len(projects))  # one topic, one project, not one per line
            self.assertEqual("September report", projects[0].title)
            self.assertEqual(2, len(projects[0].sources))

            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                for source_id in ("m1", "m2"):
                    assignment = state.get_assignment("flomo", source_id)
                    self.assertEqual("used", assignment.decision)
                    self.assertEqual(projects[0].id, assignment.project_id)

            brief = (projects[0].directory / "02-brief.md").read_text(encoding="utf-8")
            self.assertIn("Body one", brief)  # the material travels into the brief
            self.assertIn("Body two", brief)

    def test_a_line_on_its_own_still_becomes_its_own_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            _group_under(sheet, "September report", ("Desk lighting",))
            _move(sheet, "A loose thought", "used")

            _call(_apply, load_config(vault), None, TODAY)
            titles = sorted(project.title for project in load_projects(load_config(vault)).projects)
            self.assertEqual(["A loose thought", "September report"], titles)

    def test_a_topic_survives_rebuilding_the_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            _group_under(sheet, "September report", ("Desk lighting", "A loose thought"))

            _call(_propose, load_config(vault), None, TODAY)  # the same open sheet, rebuilt
            _, lines = read_sheet(sheet.read_text(encoding="utf-8"))
            grouped = {line.group for line in lines if line.decision == "used"}
            self.assertEqual({"September report"}, grouped)

    def test_a_numbered_source_heading_is_not_a_topic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            text = sheet.read_text(encoding="utf-8")
            self.assertIn("### 1. flomo", text)
            _, lines = read_sheet(text)
            self.assertEqual({""}, {line.group for line in lines})


THREAD_ITEMS = [
    SourceItem("flomo", "t1", "Day one", "**SQL API**\n\n- CTE design",
               created_at=datetime(2026, 9, 14, 9, 0, tzinfo=SH)),
    SourceItem("flomo", "t2", "Day two", "**SQL API (P0)**\n\n- predicate pushdown",
               created_at=datetime(2026, 9, 15, 9, 0, tzinfo=SH)),
    SourceItem("flomo", "t3", "Day three", "**SQL API (P1)**\n\n- final review",
               created_at=datetime(2026, 9, 16, 9, 0, tzinfo=SH)),
    SourceItem("flomo", "t4", "Unrelated", "**Desk lighting**\n\n- a lamp",
               created_at=datetime(2026, 9, 17, 9, 0, tzinfo=SH)),
]


class ThreadTest(unittest.TestCase):
    """A heading the person wrote again and again is a thread worth reading whole."""

    def _sheet(self, vault: Path) -> str:
        config = load_config(vault)
        with FileStateBackend(config.state_dir / "manifest.json") as state:
            Pipeline(FakeSource(THREAD_ITEMS), state, config.vault).sync()
            DigestBuilder(config, state, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH)).run()
            sheet = build_sheet(config, state, today=TODAY)
        return sheet.path.read_text(encoding="utf-8")

    def test_a_repeated_heading_becomes_a_group_with_its_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            text = self._sheet(_vault(temporary))
            self.assertIn("### SQL API", text)
            self.assertIn("_3 note(s) repeat this heading._", text)

    def test_an_annotation_does_not_split_a_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            text = self._sheet(_vault(temporary))
            # "SQL API", "SQL API (P0)" and "SQL API (P1)" are one thread
            self.assertNotIn("### SQL API (P0)", text)

    def test_a_thread_already_written_says_so(self) -> None:
        """The first question about a recurring thread is whether it is already a piece."""
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            create_project(config, title="SQL API", status="making", today=TODAY)
            text = self._sheet(vault)
            self.assertIn("_3 note(s) repeat this heading. Already in 2026-001 (making)._", text)

    def test_a_thread_written_about_in_a_draft_is_found_too(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            project = create_project(config, title="Another name", status="making", today=TODAY)
            (project.directory / "03-draft.md").write_text("# Another name\n\nThe SQL API story.\n", encoding="utf-8")
            text = self._sheet(vault)
            self.assertIn("Already in 2026-001 (making)", text)

    def test_a_heading_below_the_threshold_stays_in_the_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            text = self._sheet(_vault(temporary))
            self.assertNotIn("### Desk lighting", text)
            self.assertIn("Unrelated", text)

    def test_a_thread_can_be_applied_as_one_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            self._sheet(vault)
            sheet = next(iter(sorted((vault / "picks").glob("*.md"))))
            # move the whole thread, heading and all, into used
            lines = sheet.read_text(encoding="utf-8").splitlines()
            start = lines.index("### SQL API")
            end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### "))
            block = [line for line in lines[start:end] if line.strip()]
            del lines[start:end]
            index = next(i for i, line in enumerate(lines) if line.endswith(" used"))
            lines[index + 4 : index + 4] = block + [""]
            sheet.write_text("\n".join(lines) + "\n", encoding="utf-8")

            _call(_apply, load_config(vault), None, TODAY)
            projects = load_projects(load_config(vault)).projects
            self.assertEqual(["SQL API"], [project.title for project in projects])
            self.assertEqual(3, len(projects[0].sources))


class WaitingTest(unittest.TestCase):
    def test_an_empty_sheet_says_whether_anything_is_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            today = datetime.now().astimezone()
            fresh = [SourceItem("flomo", "n1", "Just written", "Body", created_at=today)]
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                Pipeline(FakeSource(fresh), state, config.vault).sync()
                DigestBuilder(config, state, now=today).run()
                sheet = build_sheet(config, state, today=today.date())
            self.assertEqual(0, sheet.listed)
            self.assertEqual(1, sheet.waiting)  # its period has not closed

            code, out = _call(_propose, load_config(vault), None, today.date())
            self.assertEqual(0, code)
            self.assertIn("waiting in periods that have not closed", out)
            self.assertIn("propose --now", out)  # the way out, named

    def test_now_offers_what_was_written_today(self) -> None:
        """The first day with the tool should end with a sheet, not with 'come back tomorrow'."""
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            today = datetime.now().astimezone()
            fresh = [SourceItem("flomo", "n1", "Just written", "Body", created_at=today)]
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                Pipeline(FakeSource(fresh), state, config.vault).sync()
                DigestBuilder(config, state, now=today).run()
                sheet = build_sheet(config, state, today=today.date(), include_open=True)
            self.assertEqual(["Just written"], [line.title for line in sheet.lines])
            self.assertEqual(0, sheet.waiting)
            self.assertTrue(sheet.path.is_file())

            code, out, _err = _run("propose", "--vault", str(vault), "--now")
            self.assertEqual(0, code)
            self.assertIn("1 item(s) to sort", out)


    def test_a_round_with_nothing_to_decide_leaves_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            config = load_config(vault)
            with FileStateBackend(config.state_dir / "manifest.json") as state:
                build_sheet(config, state, today=TODAY)
            self.assertEqual([], sorted((vault / "picks").glob("*.md")))


class SheetDiscoveryTest(unittest.TestCase):
    def test_only_files_that_say_they_are_sorting_sheets_are_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _seed(vault, now=datetime(2026, 9, 26, 9, 0, tzinfo=SH))
            _call(_propose, load_config(vault), None, TODAY)
            sorting = next(iter(sorted((vault / "picks").glob("*.md"))))

            # a name of the same shape, which a project id can produce
            intruder = vault / "picks" / "2026-ai-001-draft.md"
            intruder.write_text(
                '---\nschema: 1\nkind: "check"\nstate: "open"\n---\n\n- [ ] ok\n',
                encoding="utf-8",
            )
            found = [path.name for path in sheets(load_config(vault))]
            self.assertEqual([sorting.name], found)
            self.assertEqual(sorting, latest_sheet(load_config(vault)))


class RuleConfigTest(unittest.TestCase):
    def test_a_rule_cannot_create_projects_on_its_own(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ConfigError) as raised:
                _vault(temporary, "state:\n  backend: file\npicks:\n  rules: [{ source: flomo, default: used, auto: true }]\n")
            self.assertIn("making a project is a decision", str(raised.exception))

    def test_rejects_an_unknown_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ConfigError):
                _vault(temporary, "state:\n  backend: file\npicks:\n  rules: [{ source: flomo, default: maybe }]\n")


if __name__ == "__main__":
    unittest.main()
