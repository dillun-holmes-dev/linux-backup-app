"""Tests for the desktop identity used by Linux shells and task managers."""

import unittest

from my_backups.metadata import APP_ICON, APP_ID, EXECUTABLE_NAME


class DesktopIdentityTest(unittest.TestCase):
    def test_icon_and_application_id_match(self):
        self.assertEqual(APP_ICON, APP_ID)

    def test_application_id_is_reverse_domain_name(self):
        self.assertGreaterEqual(APP_ID.count("."), 3)

    def test_executable_name_is_shell_safe(self):
        self.assertEqual(EXECUTABLE_NAME, "vaultleaf-backup")


if __name__ == "__main__":
    unittest.main()
