from pathlib import Path
import tempfile
import unittest

from asterism.config import initialize_vault, load_config
from asterism.sources.registry import SOURCE_NAMES, build_source, configured_sources


class RegistryTest(unittest.TestCase):
    def test_names_and_configured_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            initialize_vault(vault, "file")
            config = load_config(vault)
            self.assertEqual(("apple-notes", "flomo", "cubox", "markdown", "notion"), SOURCE_NAMES)
            self.assertEqual(["apple-notes", "cubox"], configured_sources(config))
            with self.assertRaises(ValueError):
                build_source(config, "flomo")
            with self.assertRaises(ValueError):
                build_source(config, "opencli:twitter-bookmarks")
            with self.assertRaises(ValueError):
                build_source(config, "nope")
            self.assertEqual("cubox", build_source(config, "cubox").name)


if __name__ == "__main__":
    unittest.main()
