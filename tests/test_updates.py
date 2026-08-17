"""Architecture selection and verified atomic updater tests."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from my_backups import updates


class UpdateTest(unittest.TestCase):
    def test_supported_architectures(self):
        self.assertEqual(updates.normalized_arch("AMD64"), "x86_64")
        self.assertEqual(updates.normalized_arch("arm64"), "aarch64")

    def test_semantic_version_comparison(self):
        self.assertTrue(updates.is_newer("v1.1.0", "1.0.9"))
        self.assertFalse(updates.is_newer("1.0.0", "1.0.0"))

    def test_release_selects_matching_asset(self):
        payload = {
            "tag_name": "v1.2.0",
            "html_url": "https://example.invalid/release",
            "assets": [
                {"name": "VaultLeafBackup-aarch64.AppImage",
                 "browser_download_url": "https://example.invalid/app"},
                {"name": "SHA256SUMS-aarch64",
                 "browser_download_url": "https://example.invalid/sums"},
                {"name": "SHA256SUMS-aarch64.minisig",
                 "browser_download_url": "https://example.invalid/signature"},
            ],
        }
        with patch.object(updates, "_request_json", return_value=payload), \
             patch.object(updates, "normalized_arch", return_value="aarch64"):
            release = updates.check_latest_release()
        self.assertEqual(release.appimage_name, "VaultLeafBackup-aarch64.AppImage")

    def test_verified_update_atomically_replaces_single_installed_copy(self):
        new_content = b"new-appimage"
        digest = hashlib.sha256(new_content).hexdigest()
        release = updates.ReleaseInfo(
            version="1.1.0", page_url="", appimage_name="VaultLeafBackup-x86_64.AppImage",
            appimage_url="app", checksum_url="sums",
            checksum_signature_url="signature")

        def fake_download(url, target):
            if url == "app":
                Path(target).write_bytes(new_content)
            elif url == "sums":
                Path(target).write_text(f"{digest}  {release.appimage_name}\n")
            else:
                Path(target).write_text("signed manifest")

        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "VaultLeaf.AppImage"
            current.write_bytes(b"old-appimage")
            with patch.dict(os.environ, {"APPIMAGE": str(current)}), \
                 patch.object(updates, "_download", side_effect=fake_download), \
                 patch.object(updates, "_verify_release_signature") as verify:
                installed = updates.install_release(release)
            verify.assert_called_once()
            self.assertEqual(installed.read_bytes(), new_content)
            self.assertFalse(Path(str(current) + ".previous").exists())

    def test_invalid_publisher_signature_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            verifier = Path(directory) / "minisign"
            verifier.write_text("placeholder")
            checksum = Path(directory) / "SHA256SUMS"
            signature = Path(directory) / "SHA256SUMS.minisig"
            checksum.touch()
            signature.touch()
            with patch.dict(os.environ, {"VAULTLEAF_BUNDLED_BIN": directory}), \
                 patch.object(updates.subprocess, "run",
                              return_value=type("Result", (), {"returncode": 1})()):
                with self.assertRaisesRegex(RuntimeError, "signature is invalid"):
                    updates._verify_release_signature(checksum, signature)


if __name__ == "__main__":
    unittest.main()
