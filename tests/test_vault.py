from pathlib import Path
import tempfile
import unittest

from asterism.vault import VaultPathError, mount_table, network_filesystem, require_mounted, validated_target


MOUNT_OUTPUT = """/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
devfs on /dev (devfs, local, nobrowse)
//zj@nas.local/Content on /Volumes/Content (smbfs, nodev, nosuid, mounted by zj)
/dev/disk4s1 on /Volumes/Backup (apfs, local, nodev, nosuid, journaled, noowners)
"""


class VaultTest(unittest.TestCase):
    def test_validated_target_rejects_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual((root / "notes" / "a.md").resolve(), validated_target(root, "notes/a.md"))
            for bad in ("../x.md", "/etc/passwd", "notes/../../x"):
                with self.assertRaises(VaultPathError, msg=bad):
                    validated_target(root, bad)
            with self.assertRaises(VaultPathError):
                validated_target(root, "other/a.md", within=root / "notes")

    def test_mount_table_and_network_detection(self) -> None:
        table = mount_table(MOUNT_OUTPUT)
        self.assertIn((Path("/Volumes/Content"), "smbfs"), table)
        self.assertEqual("smbfs", network_filesystem(Path("/Volumes/Content/2026/x"), table))
        self.assertIsNone(network_filesystem(Path("/Volumes/Backup/vault"), table))
        self.assertIsNone(network_filesystem(Path("/Users/someone/vault"), table))

    def test_require_mounted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(Path(temporary).resolve(), require_mounted(Path(temporary), "archive.root"))
            with self.assertRaises(VaultPathError):
                require_mounted(Path(temporary) / "absent", "archive.root")


if __name__ == "__main__":
    unittest.main()
