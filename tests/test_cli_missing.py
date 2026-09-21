import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from asterism.cli import main
from asterism.config import initialize_vault
from asterism.models import ItemState
from asterism.state import FileStateBackend


class MissingCommandTest(unittest.TestCase):
    def test_lists_items_not_seen_in_latest_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "file")
            with FileStateBackend(vault / "state" / "manifest.json") as state:
                state.save(ItemState("flomo", "old", "notes/flomo/old.md", "sha256:a", None,
                                     "2026-09-01T00:00:00+00:00", first_seen_at="2026-09-01T00:00:00+00:00"))
                state.save(ItemState("flomo", "new", "notes/flomo/new.md", "sha256:b", None,
                                     "2026-09-21T00:00:00+00:00", first_seen_at="2026-09-21T00:00:00+00:00"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["missing", "--vault", str(vault)])
            self.assertEqual(0, code)
            self.assertIn("flomo\t2026-09-01T00:00:00+00:00\tnotes/flomo/old.md", out.getvalue())
            self.assertNotIn("notes/flomo/new.md", out.getvalue())
            self.assertIn("1 missing item(s)", out.getvalue())

    def test_reports_nothing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "sqlite")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["missing", "--vault", str(vault)])
            self.assertEqual(0, code)
            self.assertIn("No missing items.", out.getvalue())


if __name__ == "__main__":
    unittest.main()
