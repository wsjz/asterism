import contextlib
from datetime import date
import io
from pathlib import Path
import tempfile
import unittest

from asterism.cli import main
from asterism.config import CONFIG_NAME, initialize_vault, load_config
from asterism.projects import ContentProject, create_project, load_projects, write_views
from asterism.projects.index import BASE_FILE, INDEX_FILE


def _config(temporary: str):
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text(
        "state:\n  backend: file\n"
        "content:\n  pillars: [{ key: vibe-coding }, { key: desk-setup }]\n",
        encoding="utf-8",
    )
    return load_config(vault)


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class RegistryTest(unittest.TestCase):
    def test_reads_cards_newest_first_and_reports_broken_ones(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            create_project(config, title="Older", pillar="desk-setup", today=date(2026, 9, 10))
            newer = create_project(config, title="Newer", pillar="vibe-coding", today=date(2026, 9, 22))
            broken = config.content_root / "2026" / "broken"
            broken.mkdir(parents=True)
            (broken / "project.md").write_text("not a card\n", encoding="utf-8")

            registry = load_projects(config)

            self.assertEqual(["Newer", "Older"], [p.title for p in registry.projects])
            self.assertEqual(1, len(registry.problems))
            self.assertIn("broken/project.md", registry.problems[0])
            self.assertEqual((newer,), registry.filtered(pillar="vibe-coding").projects[:1])
            self.assertEqual(2, len(registry.in_flight()))

    def test_no_content_directory_yields_an_empty_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            self.assertEqual((), load_projects(config).projects)


class ViewsTest(unittest.TestCase):
    def test_index_lists_projects_and_the_base_is_seeded_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            project = create_project(
                config, title="Desk Lighting", pillar="desk-setup", type_="tutorial",
                platforms=("blog", "zhihu"), today=date(2026, 9, 22),
            )
            card = ContentProject.load(project.directory)
            published = card.to_markdown().replace("published: {}", "published:\n  blog: {at: 2026-09-23, url: 'https://x.y/a'}")
            (project.directory / "project.md").write_text(published, encoding="utf-8")

            changed = write_views(config, load_projects(config))
            self.assertEqual([INDEX_FILE, BASE_FILE], changed)
            index = (config.content_root / INDEX_FILE).read_text(encoding="utf-8")
            self.assertIn("| 2026-09-22 |", index)
            self.assertIn("desk-setup", index)
            self.assertIn("blog +, zhihu -", index)
            self.assertIn("[[content/2026/2026-09-22-Desk Lighting/project|Desk Lighting]]", index)

            base = config.content_root / BASE_FILE
            base.write_text("views: []\n", encoding="utf-8")
            self.assertEqual([], write_views(config, load_projects(config)))
            self.assertEqual("views: []\n", base.read_text(encoding="utf-8"))  # an edited view is kept

    def test_nothing_is_written_when_there_are_no_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            self.assertEqual([], write_views(config, load_projects(config)))
            self.assertFalse(config.content_root.exists())


class StatusAndWeekTest(unittest.TestCase):
    def test_status_groups_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            create_project(config, title="Desk Lighting", pillar="desk-setup", status="making", today=date(2026, 9, 20))
            create_project(config, title="Status Screen", pillar="vibe-coding", status="candidate", today=date(2026, 9, 22))

            code, out, _ = _run("status", "--vault", str(config.vault))
            self.assertEqual(0, code)
            self.assertIn("2 project(s): 1 candidate, 1 making", out)
            self.assertLess(out.index("candidate"), out.index("making"))

            _, filtered, _ = _run("status", "--vault", str(config.vault), "--pillar", "desk-setup")
            self.assertIn("Desk Lighting", filtered)
            self.assertNotIn("Status Screen", filtered)
            _, none, _ = _run("status", "--vault", str(config.vault), "--status", "published")
            self.assertIn("No projects match.", none)

    def test_status_reports_a_broken_card_without_hiding_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            create_project(config, title="Fine", today=date(2026, 9, 22))
            broken = config.content_root / "2026" / "broken"
            broken.mkdir(parents=True)
            (broken / "project.md").write_text("---\nid: 1\ntitle: T\nstatus: cooking\n---\n", encoding="utf-8")
            code, out, err = _run("status", "--vault", str(config.vault))
            self.assertEqual(1, code)
            self.assertIn("Fine", out)
            self.assertIn("unreadable", err)

    def test_drop_and_restore_move_the_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            project = create_project(config, title="Abandoned Idea", status="making", today=date(2026, 9, 22))
            relative = project.directory.relative_to(config.content_root).as_posix()

            code, out, err = _run("drop", project.id, "--vault", str(config.vault))
            self.assertEqual(0, code, err)
            self.assertIn("trash/", out)
            self.assertFalse(project.directory.exists())
            moved = config.trash_root / relative
            self.assertTrue((moved / "brief.md").is_file())
            self.assertEqual("dropped", ContentProject.load(moved).status)
            self.assertFalse((config.content_root / "2026").exists())  # the empty year folder is pruned

            self.assertEqual((), load_projects(config).projects)
            self.assertEqual(1, len(load_projects(config, include_dropped=True).projects))
            _, listed, _ = _run("status", "--vault", str(config.vault), "--include-dropped")
            self.assertIn("dropped", listed)

            code, out, err = _run("restore", project.id, "--vault", str(config.vault))
            self.assertEqual(0, code, err)
            back = config.content_root / relative
            self.assertTrue((back / "brief.md").is_file())
            self.assertEqual("candidate", ContentProject.load(back).status)
            self.assertFalse(config.trash_root.joinpath(relative).exists())

    def test_dropping_an_unknown_project_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            code, _, err = _run("drop", "2026-999", "--vault", str(config.vault))
            self.assertEqual(1, code)
            self.assertIn("no live project", err)

    def test_week_shows_what_is_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(temporary)
            code, out, _ = _run("week", "--vault", str(config.vault))
            self.assertEqual(0, code)
            self.assertIn("Nothing in flight", out)
            create_project(config, title="Status Screen", status="making", today=date(2026, 9, 22))
            _, out, _ = _run("week", "--vault", str(config.vault))
            self.assertIn("In flight (1)", out)
            self.assertIn("waiting: gather the material and write the draft", out)


if __name__ == "__main__":
    unittest.main()
