import contextlib
from datetime import date
import io
from pathlib import Path
import tempfile
import unittest

from asterism.cli import main
from asterism.config import CONFIG_NAME, initialize_vault, load_config
from asterism.projects import (
    Project,
    ProjectError,
    create_project,
    find_artifact,
    load_projects,
    next_id,
)


PILLARS = (
    "content:\n"
    "  pillars:\n"
    "    - { key: vibe-coding, name: Vibe Coding }\n"
    "    - { key: desk-setup, name: Desk Setup }\n"
)


def _vault(temporary: str, extra: str = PILLARS) -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text("state:\n  backend: file\n" + extra, encoding="utf-8")
    return load_config(vault).vault


class CreateProjectTest(unittest.TestCase):
    def test_creates_folder_card_brief_and_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(_vault(temporary))
            project = create_project(
                config, title="Desktop Status Screen", pillar="vibe-coding", type_="tutorial",
                platforms=("blog", "zhihu"), sources=("notes/flomo/origin/Idea.md",), today=date(2026, 9, 22),
            )
            self.assertEqual("2026-001", project.id)
            self.assertEqual("2026/2026-09-22-Desktop Status Screen", project.directory.relative_to(config.projects_root).as_posix())
            card = Project.load(project.directory)
            self.assertEqual(("vibe-coding", "tutorial", "blog"), (card.pillar, card.type, card.primary))
            self.assertEqual(("notes/flomo/origin/Idea.md",), card.sources)
            self.assertIn("# Desktop Status Screen", card.body)
            brief = (project.directory / "02-brief.md").read_text(encoding="utf-8")
            self.assertIn("## Core question", brief)
            self.assertIn("### [[notes/flomo/origin/Idea|Idea]]", brief)
            self.assertIn("> the note could not be read", brief)  # the note itself was never collected here
            self.assertTrue((config.templates_root / "project.md").is_file())
            # a pillar gets its own editable copy, seeded from the packaged default
            self.assertTrue((config.templates_root / "brief-tutorial.md").is_file())  # the shape, not the subject

    def test_ids_and_folders_never_collide(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(_vault(temporary))
            first = create_project(config, title="Same Title", today=date(2026, 9, 22))
            second = create_project(config, title="Same Title", today=date(2026, 9, 22))
            self.assertEqual(["2026-001", "2026-002"], [first.id, second.id])
            self.assertEqual("2026-09-22-Same Title (2)", second.directory.name)
            self.assertEqual("2026-003", next_id(config, today=date(2026, 9, 22)))
            self.assertEqual("2027-001", next_id(config, today=date(2027, 1, 2)))

    def test_an_edited_pillar_template_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(_vault(temporary))
            config.templates_root.mkdir(parents=True, exist_ok=True)
            (config.templates_root / "brief-desk-setup.md").write_text(
                "# {{title}}\n\n## Problem with the current desk\n", encoding="utf-8"
            )
            project = create_project(config, title="Lighting", pillar="desk-setup", today=date(2026, 9, 22))
            self.assertIn("## Problem with the current desk", (project.directory / "02-brief.md").read_text(encoding="utf-8"))

    def test_rejects_unknown_pillar_type_and_platform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(_vault(temporary))
            for kwargs, needle in (
                ({"pillar": "cooking"}, "unknown pillar"),
                ({"type_": "essay"}, "unknown type"),
                ({"platforms": ("mastodon",)}, "unknown platforms"),
                ({"title": "   "}, "needs a title"),
            ):
                arguments = {"title": "T", "today": date(2026, 9, 22), **kwargs}
                with self.assertRaises(ProjectError, msg=str(kwargs)) as raised:
                    create_project(config, **arguments)
                self.assertIn(needle, str(raised.exception))

    def test_pillar_in_the_path_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary, PILLARS + "project:\n  path: '{pillar}/{date}-{title}'\n")
            config = load_config(vault)
            project = create_project(config, title="Lighting", pillar="desk-setup", today=date(2026, 9, 22))
            self.assertEqual("desk-setup/2026-09-22-Lighting", project.directory.relative_to(config.projects_root).as_posix())
            loose = create_project(config, title="Stray", today=date(2026, 9, 22))
            self.assertEqual("unsorted", loose.directory.parent.name)


class NumberingTest(unittest.TestCase):
    def test_a_project_folder_reads_as_the_order_it_is_made_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = create_project(load_config(vault), title="Desk Lighting", today=date(2026, 9, 22))
            self.assertEqual(
                ["01-project.md", "02-brief.md"],
                sorted(path.name for path in project.directory.iterdir()),
            )

    def test_a_project_made_before_the_numbers_keeps_its_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            project = create_project(load_config(vault), title="Desk Lighting", today=date(2026, 9, 22))
            for name, plain in (("01-project.md", "project.md"), ("02-brief.md", "brief.md")):
                (project.directory / name).rename(project.directory / plain)

            config = load_config(vault)
            registry = load_projects(config)
            self.assertEqual(["2026-001"], [item.id for item in registry.projects])

            # a second project still gets the next id, not a colliding one
            second = create_project(config, title="Cable routing", today=date(2026, 9, 22))
            self.assertEqual("2026-002", second.id)

            # and writing to the old project keeps writing to the old names
            found = registry.projects[0]
            self.assertEqual(
                project.directory / "project.md",
                find_artifact(config.project, found.directory, "project.md"),
            )


class NewCommandTest(unittest.TestCase):
    def test_creates_a_project_from_the_command_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main([
                    "new", "Desk Lighting", "--vault", str(vault), "--pillar", "desk-setup",
                    "--type", "tutorial", "--platform", "blog", "--status", "making",
                ])
            self.assertEqual(0, code)
            self.assertIn("Created 2026-", out.getvalue())
            cards = list((vault / "projects").rglob("01-project.md"))
            self.assertEqual(1, len(cards))
            self.assertEqual("making", Project.load(cards[0].parent).status)

    def test_reports_an_unknown_pillar_without_creating_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main(["new", "T", "--vault", str(vault), "--pillar", "nope"])
            self.assertEqual(1, code)
            self.assertIn("unknown pillar", err.getvalue())
            self.assertFalse((vault / "projects").exists())


if __name__ == "__main__":
    unittest.main()
