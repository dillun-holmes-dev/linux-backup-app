"""Interrupted backup state is surfaced without mistaking active work."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from my_backups import backend


class BackupStateTest(unittest.TestCase):
    def config(self, output):
        return {"daily_json": str(output),
                "services": {"daily": "my-backups-daily.service"}}

    def test_interrupted_marker_offers_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "daily.json"
            Path(str(output) + ".run").write_text(
                json.dumps({"state": "interrupted"}))
            with patch.object(backend, "service_running", return_value=False):
                self.assertTrue(backend.backup_incomplete(self.config(output), "daily"))

    def test_active_backup_is_not_called_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "daily.json"
            Path(str(output) + ".run").write_text(json.dumps({"state": "running"}))
            with patch.object(backend, "service_running", return_value=True):
                self.assertFalse(backend.backup_incomplete(self.config(output), "daily"))

    def test_old_partial_json_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "daily.json"
            output.write_text(json.dumps({"message_type": "status",
                                          "percent_done": 0.5}) + "\n")
            with patch.object(backend, "service_running", return_value=False):
                self.assertTrue(backend.backup_incomplete(self.config(output), "daily"))

    def test_completed_marker_clears_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "daily.json"
            Path(str(output) + ".run").write_text(json.dumps({"state": "complete"}))
            with patch.object(backend, "service_running", return_value=False):
                self.assertFalse(backend.backup_incomplete(self.config(output), "daily"))

    def test_new_summary_completes_an_old_manual_start_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "daily.json"
            marker = Path(str(output) + ".run")
            marker.write_text(json.dumps({"state": "running"}))
            output.write_text(json.dumps({"message_type": "summary"}) + "\n")
            with patch.object(backend, "service_running", return_value=False):
                self.assertFalse(backend.backup_incomplete(self.config(output), "daily"))


if __name__ == "__main__":
    unittest.main()
