from pathlib import Path
import tempfile
import unittest

from asterism.config import CONFIG_NAME, Pillar, initialize_vault, load_config
from asterism.enrich import classify, classify_item, classify_text, item_facets
from asterism.models import ItemState, SourceItem
from asterism.rendering import render_markdown
from asterism.vault import atomic_write


PILLARS = (
    Pillar(key="vibe-coding", name="Vibe Coding", tags=("vibe-coding", "coding")),
    Pillar(key="desk-setup", name="Desk Setup", tags=("desk-setup", "desk")),
)


class ClassifyTest(unittest.TestCase):
    def test_matches_a_tag_segment_or_a_folder_segment(self) -> None:
        self.assertEqual("vibe-coding", classify(PILLARS, ("topic/Coding", "draft"), None))
        self.assertEqual("desk-setup", classify(PILLARS, (), "Notes/Desk/2026"))
        self.assertEqual("vibe-coding", classify(PILLARS, ("vibe-coding",), "Notes/Desk"))
        self.assertIsNone(classify(PILLARS, ("cooking",), "Notes/Recipes"))
        self.assertIsNone(classify((), ("coding",), None))

    def test_reads_facets_from_a_collected_note(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(_vault(temporary))
            item = SourceItem("flomo", "m1", "Idea", "Body", tags=("area/desk", "draft"), parent="Ideas")
            relative = "notes/flomo/origin/Idea.md"
            atomic_write(config.vault / relative, render_markdown(item))

            self.assertEqual((("area/desk", "draft"), "Ideas"), item_facets(config.vault, relative))
            state = ItemState("flomo", "m1", relative, "sha256:x", None, "2026-09-22T00:00:00+08:00")
            self.assertEqual("desk-setup", classify_item(config, state))

    def test_a_missing_or_unreadable_note_classifies_as_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(_vault(temporary))
            self.assertEqual(((), None), item_facets(config.vault, "notes/flomo/origin/gone.md"))
            state = ItemState("flomo", "m1", "notes/flomo/origin/gone.md", "sha256:x", None, "2026-09-22T00:00:00+08:00")
            self.assertIsNone(classify_item(config, state))


def _vault(temporary: str) -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text(
        "state:\n  backend: file\n"
        "content:\n"
        "  pillars:\n"
        "    - { key: vibe-coding, tags: [coding] }\n"
        "    - { key: desk-setup, tags: [desk] }\n",
        encoding="utf-8",
    )
    return vault


class ClassifyTextTest(unittest.TestCase):
    """A topic heading carries a pillar even when none of its material was tagged."""

    PILLARS = (
        Pillar(key="tooling", name="工具设计", tags=("cli", "tooling")),
        Pillar(key="writing", name="写作", tags=("写作", "writing")),
    )

    def test_an_ascii_alias_matches_a_whole_word(self) -> None:
        self.assertEqual("tooling", classify_text(self.PILLARS, "CLI 设计的四条判断"))

    def test_an_ascii_alias_does_not_match_inside_another_word(self) -> None:
        self.assertIsNone(classify_text(self.PILLARS, "client 端的重试策略"))

    def test_an_alias_in_another_script_matches_anywhere(self) -> None:
        self.assertEqual("writing", classify_text(self.PILLARS, "写作流程里最贵的一步"))

    def test_nothing_matching_stays_unclassified(self) -> None:
        self.assertIsNone(classify_text(self.PILLARS, "关于渐进式重构"))
        self.assertIsNone(classify_text(self.PILLARS, "   "))


if __name__ == "__main__":
    unittest.main()
