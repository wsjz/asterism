from datetime import date
from pathlib import Path
import tempfile
import unittest

from asterism.config import CONFIG_NAME, ConfigError, initialize_vault, load_config
from asterism.projects import ContentProject, ProjectError, artifact_path, stage_directory


CARD = """---
id: 2026-042
title: Desktop Status Screen
pillar: vibe-coding
type: tutorial
status: making
promise: Finish a status screen without front-end experience
primary: blog
platforms:
  - blog
  - zhihu
scheduled: 2026-10-12
created: 2026-09-22
sources:
  - notes/flomo/origin/Idea.md
published:
  blog: {at: 2026-10-05, url: 'https://example.com/a'}
notion: https://www.notion.so/row
---

Notes to myself.
"""


class ProjectCardTest(unittest.TestCase):
    def test_reads_a_hand_written_card(self) -> None:
        project = ContentProject.from_markdown(CARD)
        self.assertEqual(("2026-042", "making", "vibe-coding"), (project.id, project.status, project.pillar))
        self.assertEqual(date(2026, 10, 12), project.scheduled)
        self.assertEqual(("blog", "zhihu"), project.platforms)
        self.assertEqual("Notes to myself.\n", project.body)
        self.assertTrue(project.published_on("blog"))
        self.assertFalse(project.published_on("zhihu"))
        self.assertTrue(project.is_published is False)

    def test_round_trip_keeps_every_key_and_the_body(self) -> None:
        project = ContentProject.from_markdown(CARD)
        again = ContentProject.from_markdown(project.to_markdown())
        self.assertEqual(project.front_matter(), again.front_matter())
        self.assertEqual(project.body.strip(), again.body.strip())

    def test_empty_values_stay_visible_for_obsidian_properties(self) -> None:
        text = ContentProject(id="2026-001", title="T").to_markdown()
        for key in ("pillar", "type", "promise", "primary", "scheduled", "notion"):
            self.assertIn(f"{key}: null", text)
        self.assertIn("platforms: []", text)

    def test_rejects_unusable_cards(self) -> None:
        cases = {
            "no front matter\n": "front matter",
            "---\nid: 1\ntitle: T\n": "terminated",
            "---\nid: 1\ntitle: T\nstatus: cooking\n---\n": "status",
            "---\nid: 1\ntitle: T\nweird: x\n---\n": "unknown front matter keys",
            "---\nid: 1\ntitle: T\nscheduled: someday\n---\n": "date",
            "---\ntitle: T\n---\n": "id is required",
            "---\nid: 1\n---\n": "title is required",
            "---\n- a\n- b\n---\n": "mapping",
        }
        for text, needle in cases.items():
            with self.assertRaises(ProjectError, msg=text) as raised:
                ContentProject.from_markdown(text)
            self.assertIn(needle, str(raised.exception))

    def test_load_reports_a_missing_card(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ProjectError):
                ContentProject.load(Path(temporary))


class ProjectConfigTest(unittest.TestCase):
    def _load(self, text: str):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "file")
            (vault / CONFIG_NAME).write_text("state:\n  backend: file\n" + text, encoding="utf-8")
            return load_config(vault)

    def test_defaults_and_pillars(self) -> None:
        config = self._load(
            "content:\n"
            "  pillars:\n"
            "    - { key: vibe-coding, name: Vibe Coding, tags: [coding] }\n"
            "    - { key: desk-setup }\n"
            "  types: [tutorial, opinion]\n"
        )
        self.assertEqual(("vibe-coding", "desk-setup"), tuple(p.key for p in config.content.pillars))
        self.assertEqual("Vibe Coding", config.content.pillars[0].name)
        self.assertEqual(("vibe-coding", "coding"), config.content.pillars[0].tags)
        self.assertEqual("desk-setup", config.content.pillars[1].name)
        self.assertEqual(("tutorial", "opinion"), config.content.types)
        self.assertIn("blog", config.content.platforms)
        self.assertEqual("{year}/{date}-{title}", config.project.path)
        self.assertEqual("01-brief", stage_directory(config.project, config.project.stages[0]))
        # flat keeps the files together and numbers them in production order
        self.assertEqual("01-project.md", artifact_path(config.project, "project.md"))
        self.assertEqual("03-draft.md", artifact_path(config.project, "draft.md"))
        self.assertEqual("05-exports/blog.md", artifact_path(config.project, "exports/blog.md"))

    def test_staged_layout_and_unnumbered_stages(self) -> None:
        config = self._load(
            "project:\n"
            "  layout: staged\n"
            "  numbered: false\n"
            "  path: '{pillar}/{date}-{title}'\n"
            "  stages:\n"
            "    - { key: brief, artifacts: [project.md, brief.md] }\n"
            "    - { key: media, media: [photo], dir: Media }\n"
            "    - { key: export, media_per_platform: true }\n"
            "  bindings: { platform_exports: export, unassigned_media: media }\n"
        )
        self.assertEqual("brief/project.md", artifact_path(config.project, "project.md"))
        self.assertEqual("Media", stage_directory(config.project, config.project.stages[1]))
        self.assertEqual("media", config.project.bound_stage("unassigned_media").key)

    def test_rejects_bad_content_and_project_settings(self) -> None:
        cases = [
            ("content:\n  pillars: [{ key: Bad Key }]\n", "slug"),
            ("content:\n  pillars: [{ key: a }, { key: a }]\n", "duplicates"),
            ("content:\n  types: [Tutorial]\n", "lowercase"),
            ("project:\n  path: '/{title}'\n", "relative"),
            ("project:\n  path: '{year}/{month}-{title}'\n", "unknown placeholders"),
            ("project:\n  path: '{year}/{date}'\n", "{title} or {id}"),
            ("project:\n  id_format: '{year}'\n", "{seq}"),
            ("project:\n  layout: nested\n", "layout"),
            ("project:\n  stages: [{ key: a }]\n  bindings: { covers: b }\n", "configured stages"),
            ("project:\n  stages: [{ key: a }]\n  bindings: { platform_exports: a }\n", "media_per_platform"),
            ("project:\n  stages: [{ key: a, artifacts: ['../x.md'] }]\n", "relative path"),
        ]
        for text, needle in cases:
            with self.assertRaises(ConfigError, msg=text) as raised:
                self._load(text)
            self.assertIn(needle, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
