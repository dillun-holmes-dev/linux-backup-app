"""Tray pixels and desktop identity integration tests."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from my_backups import backend
from my_backups.metadata import APP_ID
from my_backups.tray import load_icon_pixmaps


class IconTest(unittest.TestCase):
    def test_tray_contains_real_argb_pixels(self):
        pixmaps = load_icon_pixmaps(sizes=(16, 32))
        self.assertEqual([item[:2] for item in pixmaps], [(16, 16), (32, 32)])
        for width, height, pixels in pixmaps:
            self.assertEqual(len(pixels), width * height * 4)
            self.assertTrue(any(pixels))

    def test_desktop_identity_uses_leaf_icon_and_application_id(self):
        with tempfile.TemporaryDirectory() as directory:
            appimage = Path(directory) / "VaultLeaf Backup.AppImage"
            appimage.touch()
            with patch.dict(os.environ, {"HOME": directory,
                                         "APPIMAGE": str(appimage)}), \
                 patch.object(backend.shutil, "which", return_value=None):
                self.assertTrue(backend.ensure_desktop_identity())
            desktop = (Path(directory) / ".local" / "share" /
                       "applications" / f"{APP_ID}.desktop")
            content = desktop.read_text()
            self.assertIn(f"StartupWMClass={APP_ID}", content)
            self.assertIn(f"{APP_ID}.png", content)
            self.assertIn(str(appimage), content)


if __name__ == "__main__":
    unittest.main()
