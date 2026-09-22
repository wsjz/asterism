import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

from asterism.cli import main
from asterism.config import CONFIG_NAME, initialize_vault


FIXTURE = Path(__file__).parent / "fixtures" / "flomo-export.html"


def _vault(temporary: str, extra: str = "") -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")
    (vault / CONFIG_NAME).write_text(
        "state:\n  backend: file\n"
        f"sources:\n  flomo:\n    export_path: {FIXTURE}\n" + extra,
        encoding="utf-8",
    )
    return vault


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class SyncCommandTest(unittest.TestCase):
    def test_runs_named_source_and_writes_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            code, out, err = _run("sync", "--vault", str(vault), "--source", "flomo")
            self.assertEqual(0, code, err)
            self.assertIn("Sync [flomo]: 3 discovered, 3 new", out)
            self.assertIn("Digest: flomo day", out)
            self.assertTrue((vault / "notes" / "flomo" / "digest" / "daily").exists())
            code, out, _ = _run("sync", "--vault", str(vault), "--source", "flomo", "--no-digest")
            self.assertIn("3 unchanged", out)
            self.assertNotIn("Digest:", out)

    def test_one_failing_source_does_not_stop_the_others(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary, "  markdown:\n    roots: [/nonexistent/asterism-root]\n")
            code, out, err = _run("sync", "--vault", str(vault), "--source", "markdown", "--source", "flomo")
            self.assertEqual(1, code)
            self.assertIn("Sync [markdown]: skipped", err)
            self.assertIn("Sync [flomo]: 3 discovered", out)
            self.assertTrue(list((vault / "notes" / "flomo" / "origin").glob("*.md")))

    def test_unknown_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            code, _, err = _run("sync", "--vault", str(vault), "--source", "opencli:nope")
            self.assertEqual(1, code)
            self.assertIn("unknown source", err)

    def test_commit_creates_a_git_snapshot_only_when_something_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            subprocess.run(["git", "init", "-q", str(vault)], check=True)
            subprocess.run(["git", "-C", str(vault), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(vault), "config", "user.name", "Test"], check=True)
            code, out, err = _run("sync", "--vault", str(vault), "--source", "flomo", "--commit")
            self.assertEqual(0, code, err)
            self.assertIn("Committed: sync ", out)
            log = subprocess.run(["git", "-C", str(vault), "log", "--oneline"], capture_output=True, text=True, check=True).stdout
            self.assertEqual(1, len(log.strip().splitlines()))
            self.assertIn("(+3 ~0)", log)
            code, out, _ = _run("sync", "--vault", str(vault), "--source", "flomo", "--commit")
            self.assertIn("nothing changed", out)

    def test_commit_without_repository_is_reported_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            code, out, _ = _run("sync", "--vault", str(vault), "--source", "flomo", "--commit", "--no-digest")
            self.assertEqual(0, code)
            self.assertIn("not a Git repository", out)


if __name__ == "__main__":
    unittest.main()
