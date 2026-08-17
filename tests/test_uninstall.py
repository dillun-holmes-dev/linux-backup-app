"""Uninstall removes integration but preserves recovery-critical data."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from my_backups import backend
from my_backups.metadata import APP_ID


class UninstallTest(unittest.TestCase):
    def test_uninstall_preserves_config_keys_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            data = home / ".local" / "share" / "my-backups"
            units = home / ".config" / "systemd" / "user"
            install = home / ".local" / "lib" / "my-backups"
            stable_install = home / ".local" / "lib" / "vaultleaf-backup"
            menu = home / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
            for path in (data, units, install, stable_install, menu.parent):
                path.mkdir(parents=True, exist_ok=True)
            (data / "restic-passphrase.txt").write_text("secret")
            (data / "run-backup.sh").write_text("generated")
            (install / "MyBackups.AppImage").write_text("app")
            (stable_install / "VaultLeafBackup.AppImage").write_text("app")
            menu.write_text("desktop")
            config = home / ".config" / "my-backups" / "config.json"
            config.parent.mkdir(parents=True)
            config.write_text("{}")

            with patch.object(backend.Path, "home", return_value=home), \
                 patch.object(backend, "DATA_DIR", data), \
                 patch.object(backend, "USER_UNIT_DIR", units), \
                 patch.object(backend, "user_systemd_available", return_value=False):
                backend.uninstall_application()

            self.assertFalse(install.exists())
            self.assertFalse(stable_install.exists())
            self.assertFalse(menu.exists())
            self.assertFalse((data / "run-backup.sh").exists())
            self.assertTrue((data / "restic-passphrase.txt").exists())
            self.assertTrue(config.exists())


if __name__ == "__main__":
    unittest.main()
