"""The bundled runtime must not leak into commands supplied by the host."""

import os
import unittest
from unittest.mock import patch

from my_backups.backend import _child_process_env


class RuntimeIsolationTest(unittest.TestCase):
    def test_bundle_paths_are_removed_for_child_processes(self):
        source = {
            "PATH": "/app/usr/bin:/usr/bin",
            "LD_LIBRARY_PATH": "/app/usr/lib",
            "PYTHONHOME": "/app/usr",
            "PYTHONPATH": "/app/usr/lib/python",
            "GTK_PATH": "/app/usr/lib/gtk-4.0",
            "VAULTLEAF_SYSTEM_LD_LIBRARY_PATH": "/host/lib",
            "VAULTLEAF_SYSTEM_XDG_DATA_DIRS": "/usr/share",
        }
        cleaned = _child_process_env(source)
        self.assertEqual(cleaned["LD_LIBRARY_PATH"], "/host/lib")
        self.assertEqual(cleaned["XDG_DATA_DIRS"], "/usr/share")
        self.assertNotIn("PYTHONHOME", cleaned)
        self.assertNotIn("PYTHONPATH", cleaned)
        self.assertNotIn("GTK_PATH", cleaned)

    def test_empty_original_paths_are_not_reintroduced(self):
        with patch.dict(os.environ, {
            "LD_LIBRARY_PATH": "/app/usr/lib",
            "VAULTLEAF_SYSTEM_LD_LIBRARY_PATH": "",
        }, clear=True):
            cleaned = _child_process_env()
        self.assertNotIn("LD_LIBRARY_PATH", cleaned)


if __name__ == "__main__":
    unittest.main()
