"""A vault's snapshot has to include the writing, not only the notes mirror."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from asterism.cli import main
from asterism.config import CONFIG_NAME, initialize_vault, load_config


CONFIG = "state:\n  backend: file\n"


def _git(vault: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(vault), *arguments], capture_output=True, text=True, check=True
    )
    return completed.stdout


def _vault(temporary: str) -> Path:
    vault = Path(temporary) / "vault"
    initialize_vault(vault, "file")  # which starts the repository
    (vault / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    config = load_config(vault)
    _git(config.vault, "config", "user.email", "test@example.invalid")
    _git(config.vault, "config", "user.name", "Test")
    return config.vault


def _run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, out.getvalue()


class SnapshotTest(unittest.TestCase):
    def test_a_snapshot_keeps_the_writing_as_well_as_the_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            (vault / "notes" / "a.md").write_text("collected\n", encoding="utf-8")
            draft = vault / "content" / "2026" / "A piece" / "03-draft.md"
            draft.parent.mkdir(parents=True)
            draft.write_text("# A piece\n\nreal prose\n", encoding="utf-8")

            code, out = _run("snapshot", "--vault", str(vault), "-m", "before a rewrite")
            self.assertEqual(0, code)
            self.assertIn("Committed: before a rewrite", out)

            tracked = _git(vault, "ls-files").splitlines()
            self.assertIn("content/2026/A piece/03-draft.md", tracked)
            self.assertIn("notes/a.md", tracked)
            self.assertNotIn("state/manifest.json", tracked)  # the vault's .gitignore holds

    def test_a_draft_can_be_recovered_from_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            draft = vault / "content" / "2026" / "A piece" / "03-draft.md"
            draft.parent.mkdir(parents=True)
            draft.write_text("# A piece\n\nreal prose\n", encoding="utf-8")
            _run("snapshot", "--vault", str(vault), "-m", "save point")

            draft.write_text("", encoding="utf-8")  # the accident
            _git(vault, "checkout", "--", "content")
            self.assertIn("real prose", draft.read_text(encoding="utf-8"))

    def test_nothing_to_commit_is_said_plainly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = _vault(temporary)
            _run("snapshot", "--vault", str(vault))
            _code, out = _run("snapshot", "--vault", str(vault))
            self.assertIn("nothing changed", out)

    def test_a_vault_outside_git_is_reported_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "plain"
            initialize_vault(vault, "file")
            (vault / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
            shutil.rmtree(vault / ".git")  # a vault someone chose not to version
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = main(["snapshot", "--vault", str(load_config(vault).vault), "--json"])
            payload = json.loads(out.getvalue())
            self.assertEqual(0, code)
            self.assertFalse(payload["ok"])
            self.assertIn("not a Git repository", payload["result"])


if __name__ == "__main__":
    unittest.main()
