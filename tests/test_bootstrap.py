"""A downloaded AppImage promotes itself to one safe, stable executable."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from my_backups import bootstrap


class BootstrapTest(unittest.TestCase):
    def test_download_is_promoted_to_stable_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "Downloads" / "VaultLeafBackup-x86_64.AppImage"
            installed = root / ".local/lib/vaultleaf-backup/VaultLeafBackup.AppImage"
            source.parent.mkdir()
            source.write_bytes(b"appimage")
            with patch.object(bootstrap, "appimage_version", return_value=()):
                target, changed = bootstrap.promote_appimage(source, installed)
            self.assertTrue(changed)
            self.assertEqual(target, installed)
            self.assertEqual(installed.read_bytes(), b"appimage")
            self.assertTrue(installed.stat().st_mode & 0o111)

    def test_older_download_never_replaces_newer_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "old.AppImage"
            installed = root / "installed.AppImage"
            source.write_bytes(b"old")
            installed.write_bytes(b"new")
            with patch.object(bootstrap, "appimage_version", return_value=(99, 0, 0)):
                target, changed = bootstrap.promote_appimage(source, installed)
            self.assertFalse(changed)
            self.assertEqual(target.read_bytes(), b"new")

    def test_cleanup_only_removes_vaultleaf_appimages(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            downloads = home / "Downloads"
            downloads.mkdir()
            old = downloads / "VaultLeafBackup-x86_64.v1.1.2.previous.AppImage"
            current = downloads / "VaultLeafBackup-x86_64.AppImage"
            unrelated = downloads / "AnotherProgram.AppImage"
            archive = downloads / "VaultLeafBackup-x86_64.tar.gz"
            for path in (old, current, unrelated, archive):
                path.write_bytes(b"x")
            with patch.object(bootstrap.Path, "home", return_value=home):
                removed = bootstrap.remove_downloaded_copies(home / "installed.AppImage")
            self.assertEqual(set(removed), {old, current})
            self.assertTrue(unrelated.exists())
            self.assertTrue(archive.exists())

    def test_handoff_continues_current_runtime_using_stable_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "download.AppImage"
            target = root / "installed.AppImage"
            source.write_bytes(b"new")
            with patch.dict(bootstrap.os.environ, {"APPIMAGE": str(source)}), \
                 patch.object(bootstrap, "promote_appimage", return_value=(target, True)), \
                 patch.object(bootstrap, "_quit_existing_instance"), \
                 patch.object(bootstrap, "remove_downloaded_copies"):
                self.assertFalse(bootstrap.handoff_to_installed_appimage())
                self.assertEqual(bootstrap.os.environ["APPIMAGE"], str(target))


if __name__ == "__main__":
    unittest.main()
