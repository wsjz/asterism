"""Gate 1: a candidate becomes a piece only when a person confirms the angle."""
import contextlib
from datetime import date
import io
from pathlib import Path
import tempfile
import unittest

from asterism.cli import main
from asterism.config import CONFIG_NAME, initialize_vault, load_config
from asterism.projects import (
    BRIEF_FILE,
    ProjectError,
    angles,
    confirm_project,
    create_project,
    load_projects,
    offers_angles,
)


CONFIG = "state:\n  backend: file\ncontent:\n  pillars: [{ key: desk-setup, tags: [desk] }]\n"
TODAY = date(2026, 9, 26)


def _vault(temporary: str) -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    return load_config(vault).vault


def _candidate(vault: Path, title: str = "Desk lighting"):
    config = load_config(vault)
    create_project(config, title=title, pillar="desk-setup", status="candidate", today=TODAY)
    return load_projects(load_config(vault)).projects[0]


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class AngleTest(unittest.TestCase):
    def test_the_brief_offers_the_title_as_the_first_angle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _candidate(vault)
            offered = angles(load_config(vault), project)
            self.assertEqual([(1, "Desk lighting")], [(a.number, a.title) for a in offered])

    def test_angles_written_by_hand_are_read_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _candidate(vault)
            brief = project.directory / "02-brief.md"
            text = brief.read_text(encoding="utf-8").replace(
                "1. **Desk lighting** —",
                "1. **Desk lighting** — pick a lamp that does not glare\n"
                "2. **Cable routing** — hide every cable in one afternoon",
            )
            brief.write_text(text, encoding="utf-8")
            offered = angles(load_config(vault), project)
            self.assertEqual(["Desk lighting", "Cable routing"], [a.title for a in offered])
            self.assertEqual("hide every cable in one afternoon", offered[1].promise)


    def test_a_brief_from_an_older_vault_is_told_apart_from_an_empty_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _candidate(vault)
            config = load_config(vault)
            self.assertTrue(offers_angles(config, project))

            brief = project.directory / "02-brief.md"
            text = brief.read_text(encoding="utf-8")
            start = text.index("## Candidate angles")
            brief.write_text(text[:start] + text[text.index("## Core question"):], encoding="utf-8")
            reloaded = load_projects(load_config(vault)).projects[0]
            self.assertFalse(offers_angles(config, reloaded))

            code, _out, err = _run("confirm", reloaded.id, "--vault", str(vault))
            self.assertEqual(1, code)
            self.assertIn("predates it", err)


class ConfirmTest(unittest.TestCase):
    def test_confirming_an_angle_names_the_piece_and_starts_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _candidate(vault)
            brief = project.directory / "02-brief.md"
            brief.write_text(
                brief.read_text(encoding="utf-8").replace(
                    "1. **Desk lighting** —",
                    "1. **Desk lighting** — pick a lamp that does not glare",
                ),
                encoding="utf-8",
            )
            confirmed = confirm_project(load_config(vault), project, angle=1)
            self.assertEqual("making", confirmed.status)
            self.assertEqual("pick a lamp that does not glare", confirmed.promise)

            reloaded = load_projects(load_config(vault)).projects[0]
            self.assertEqual("making", reloaded.status)
            self.assertEqual(project.directory, reloaded.directory)  # the folder never moves

    def test_a_title_may_be_given_instead_of_an_angle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            confirmed = confirm_project(
                load_config(vault), _candidate(vault), title="Lamps", promise="see clearly"
            )
            self.assertEqual(("Lamps", "see clearly", "making"),
                             (confirmed.title, confirmed.promise, confirmed.status))

    def test_only_a_candidate_can_be_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _candidate(vault)
            confirm_project(load_config(vault), project, angle=1)
            started = load_projects(load_config(vault)).projects[0]
            with self.assertRaises(ProjectError) as raised:
                confirm_project(load_config(vault), started, angle=1)
            self.assertIn("only a candidate", str(raised.exception))

    def test_an_unknown_angle_says_which_ones_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            with self.assertRaises(ProjectError) as raised:
                confirm_project(load_config(vault), _candidate(vault), angle=7)
            self.assertIn("offers 1", str(raised.exception))


class ConfirmCommandTest(unittest.TestCase):
    def test_without_a_choice_it_lists_the_angles_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _candidate(vault)
            code, out, _ = _run("confirm", project.id, "--vault", str(vault))
            self.assertEqual(1, code)  # the gate was not passed
            self.assertIn("1. Desk lighting", out)
            self.assertEqual("candidate", load_projects(load_config(vault)).projects[0].status)

    def test_confirming_through_the_command_moves_the_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = _candidate(vault)
            code, out, _ = _run(
                "confirm", project.id, "--vault", str(vault), "--angle", "1",
                "--promise", "see clearly",
            )
            self.assertEqual(0, code)
            self.assertIn("Confirmed", out)
            self.assertIn("gather the material", out)
            self.assertEqual("making", load_projects(load_config(vault)).projects[0].status)


if __name__ == "__main__":
    unittest.main()
