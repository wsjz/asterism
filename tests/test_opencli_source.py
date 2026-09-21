import json
from pathlib import Path
import tempfile
import unittest

from asterism.config import CONFIG_NAME, ConfigError, OpencliCollection, OpencliMap, initialize_vault, load_config
from asterism.sources.base import SourceError
from asterism.sources.opencli import OpencliSource
from asterism.sources.opencli.manifest import load_manifest, validate_collection
from asterism.sources.registry import build_source, configured_sources


FIXTURES = Path(__file__).parent / "fixtures" / "opencli"


def fake_runner(outputs: dict[str, tuple[int, str, str]]):
    calls: list[list[str]] = []

    def runner(arguments: list[str], timeout: int) -> tuple[int, str, str]:
        calls.append(arguments)
        key = " ".join(arguments)
        for prefix, result in outputs.items():
            if key.startswith(prefix):
                return result
        raise AssertionError(f"unexpected opencli call: {key}")

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


HN = OpencliCollection(
    "hn-top", ("hackernews", "top"), (("limit", 3),),
    OpencliMap(id="id", url="url", title="title", author="author", exclude=("rank",)),
)
DEVTO = OpencliCollection(
    "devto", ("devto", "read"), (("id", "2000000"),),
    OpencliMap(id="id", url="url", title="title", content=("body",), created_at="published_at", author="author", tags="tags"),
)


class OpencliSourceTest(unittest.TestCase):
    def test_collects_and_maps_rows_from_real_output(self) -> None:
        runner = fake_runner({
            "--version": (0, "1.8.7\n", ""),
            "hackernews top --limit 3 --format json": (0, (FIXTURES / "hackernews-top.json").read_text(), ""),
        })
        source = OpencliSource(HN, runner=runner)
        items = source.collect()
        self.assertEqual("opencli-hn-top", source.name)
        self.assertEqual(3, len(items))
        first = items[0]
        self.assertEqual("49783495", first.source_id)
        self.assertEqual("Grim Fandango Puzzle Document (1996) [pdf]", first.title)
        self.assertEqual("kelseyfrog", first.author)
        self.assertEqual("http://gameshelf.jmac.org/2008/11/13/GrimPuzzleDoc_small.pdf", first.url)
        self.assertEqual("", first.content_text)
        self.assertEqual("hackernews/top", first.source_meta["opencli_command"])
        self.assertIn("score", first.source_meta)
        self.assertNotIn("rank", first.source_meta)
        self.assertEqual({"adapter": "opencli", "producer": "hackernews/top", "producer_version": "1.8.7"}, first.origin.as_dict())
        self.assertEqual(["--version"], runner.calls[0])

    def test_content_tags_and_dates_from_devto(self) -> None:
        runner = fake_runner({
            "--version": (1, "", "boom"),
            "devto read --id 2000000 --format json": (0, (FIXTURES / "devto-read.json").read_text(), ""),
        })
        item = OpencliSource(DEVTO, runner=runner).collect()[0]
        self.assertEqual("2000000", item.source_id)
        self.assertTrue(item.content_text.startswith("A table in our Aurora MySQL"))
        self.assertEqual(("aws", "database", "mysql", "beginners"), item.tags)
        self.assertEqual(2024, item.created_at.year)
        self.assertIsNone(item.origin.producer_version)

    def test_exit_codes(self) -> None:
        for code, needle in ((69, "Browser Bridge"), (77, "log in"), (2, "arguments"), (1, "failed")):
            runner = fake_runner({"--version": (0, "1.8.7", ""), "hackernews": (code, "", "ok: false")})
            with self.assertRaises(SourceError, msg=str(code)) as raised:
                OpencliSource(HN, runner=runner).collect()
            self.assertIn(needle, str(raised.exception))
            self.assertIn(str(code), str(raised.exception))
        empty = fake_runner({"--version": (0, "1.8.7", ""), "hackernews": (66, "", "")})
        self.assertEqual([], OpencliSource(HN, runner=empty).collect())
        empty_array = fake_runner({"--version": (0, "1.8.7", ""), "hackernews": (0, "[]\n", "")})
        self.assertEqual([], OpencliSource(HN, runner=empty_array).collect())

    def test_rejects_non_array_output_and_rows_without_identity(self) -> None:
        help_object = fake_runner({"--version": (0, "1.8.7", ""), "hackernews": (0, '{"name": "opencli"}', "")})
        with self.assertRaises(SourceError):
            OpencliSource(HN, runner=help_object).collect()
        no_id = fake_runner({"--version": (0, "1.8.7", ""), "hackernews": (0, '[{"title": "x"}]', "")})
        with self.assertRaises(SourceError) as raised:
            OpencliSource(HN, runner=no_id).collect()
        self.assertIn("id or url", str(raised.exception))
        duplicate = fake_runner({"--version": (0, "1.8.7", ""), "hackernews": (0, '[{"id": 1}, {"id": 1}]', "")})
        with self.assertRaises(SourceError):
            OpencliSource(HN, runner=duplicate).collect()

    def test_url_identity_and_tolerant_dates(self) -> None:
        collection = OpencliCollection(
            "posts", ("v2ex", "topic"), (), OpencliMap(url="url", title="title", content=("content",), created_at="created", parent="node"),
        )
        runner = fake_runner({"--version": (0, "1.8.7", ""), "v2ex": (0, (FIXTURES / "v2ex-topic.json").read_text(), "")})
        item = OpencliSource(collection, runner=runner).collect()[0]
        self.assertEqual("https://www.v2ex.com/t/1", item.source_id)
        self.assertEqual("Project Babel", item.parent)
        self.assertEqual(2010, item.created_at.year)  # unix seconds
        bad_date = fake_runner({"--version": (0, "1.8.7", ""), "v2ex": (0, '[{"url": "https://a.b/c?utm_source=x#f", "created": "yesterday"}]', "")})
        item = OpencliSource(collection, runner=bad_date).collect()[0]
        self.assertEqual("https://a.b/c", item.source_id)
        self.assertIsNone(item.created_at)


class OpencliManifestTest(unittest.TestCase):
    def test_validation_against_real_manifest_excerpt(self) -> None:
        runner = fake_runner({"list --format json": (0, (FIXTURES / "list.json").read_text(), "")})
        manifest = load_manifest(runner)
        self.assertEqual([], [p for p in validate_collection(HN, manifest) if not p.endswith("informational")])
        bookmarks = OpencliCollection("tw", ("twitter", "bookmarks"), (("limit", 50),), OpencliMap(id="id", url="url", content=("text",), created_at="created_at"))
        problems = validate_collection(bookmarks, manifest)
        self.assertTrue(any("browser" in p for p in problems))
        self.assertEqual([], [p for p in problems if not p.endswith("informational")])
        publish = OpencliCollection("xhs", ("xiaohongshu", "publish"), (), OpencliMap(id="id"))
        self.assertTrue(any("only read commands" in p for p in validate_collection(publish, manifest)))
        wrong_field = OpencliCollection("hn2", ("hackernews", "top"), (("page", 2),), OpencliMap(id="id", content=("body",)))
        problems = validate_collection(wrong_field, manifest)
        self.assertTrue(any("'body'" in p for p in problems))
        self.assertTrue(any("--page" in p for p in problems))
        unknown = OpencliCollection("x", ("nosuchsite", "cmd"), (), OpencliMap(id="id"))
        self.assertIn("not found", validate_collection(unknown, manifest)[0])


class OpencliConfigTest(unittest.TestCase):
    def _load(self, text: str):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "file")
            (vault / CONFIG_NAME).write_text("state:\n  backend: file\n" + text, encoding="utf-8")
            return load_config(vault)

    def test_parses_collections_and_registers_sources(self) -> None:
        config = self._load(
            "sources:\n  opencli:\n    collections:\n"
            "      - name: twitter-bookmarks\n        command: [twitter, bookmarks]\n        args: { limit: 200, all: true }\n"
            "        map: { id: id, url: url, content: [text], created_at: created_at, author: author, exclude: [rank] }\n"
        )
        collection = config.opencli.collection("twitter-bookmarks")
        self.assertEqual(("twitter", "bookmarks"), collection.command)
        self.assertEqual((("limit", 200), ("all", True)), collection.args)
        self.assertEqual(("text",), collection.map.content)
        self.assertIn("opencli:twitter-bookmarks", configured_sources(config))
        source = build_source(config, "opencli:twitter-bookmarks")
        self.assertEqual("opencli-twitter-bookmarks", source.output_name)
        self.assertEqual(["twitter", "bookmarks", "--limit", "200", "--all", "--format", "json"], source.command_line())
        with self.assertRaises(ValueError):
            build_source(config, "opencli:nope")

    def test_rejects_bad_collections(self) -> None:
        bad = [
            ("      - name: Bad Name\n        command: [a, b]\n        map: { id: id }\n", "slug"),
            ("      - name: ok\n        command: [a]\n        map: { id: id }\n", "command"),
            ("      - name: ok\n        command: [a, b]\n        map: { content: [text] }\n", "identity"),
            ("      - name: ok\n        command: [a, b]\n        args: { 'Bad Key': 1 }\n        map: { id: id }\n", "keys"),
            ("      - name: ok\n        command: [a, b]\n        map: { id: id, content_format: pdf }\n", "content_format"),
            ("      - name: ok\n        command: [a, b]\n        map: { id: id }\n      - name: ok\n        command: [c, d]\n        map: { id: id }\n", "duplicates"),
        ]
        for text, needle in bad:
            with self.assertRaises(ConfigError, msg=text) as raised:
                self._load("sources:\n  opencli:\n    collections:\n" + text)
            self.assertIn(needle, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
