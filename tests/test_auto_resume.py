"""Interrupted jobs resume automatically without duplicate concurrent work."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from my_backups import app


class AutomaticResumeTest(unittest.TestCase):
    def application(self):
        return SimpleNamespace(
            cfg={"setup_complete": True,
                 "services": {"daily": "daily.service",
                              "weekly": "weekly.service",
                              "monthly": "monthly.service"}},
            _resume_attempts={}, _resume_after={},
            _automatic_resume_notice=lambda *_args: False)

    def test_interrupted_backup_starts_automatically(self):
        application = self.application()
        with patch.object(app.B, "service_running", return_value=False), \
             patch.object(app.B, "backup_incomplete",
                          side_effect=lambda _cfg, key, running=False: key == "daily"), \
             patch.object(app.B, "start_backup") as start, \
             patch.object(app.time, "monotonic", return_value=100):
            app.BackupApplication._resume_interrupted_backups(application)
        start.assert_called_once()
        self.assertEqual(start.call_args.args[1], "daily")
        self.assertEqual(application._resume_after["daily"], 160)

    def test_active_job_prevents_duplicate_resume(self):
        application = self.application()
        with patch.object(app.B, "service_running", return_value=True), \
             patch.object(app.B, "start_backup") as start:
            app.BackupApplication._resume_interrupted_backups(application)
        start.assert_not_called()

    def test_retry_waits_then_tries_again(self):
        application = self.application()
        application._resume_attempts["daily"] = 1
        application._resume_after["daily"] = 200
        incomplete = lambda _cfg, key, running=False: key == "daily"
        with patch.object(app.B, "service_running", return_value=False), \
             patch.object(app.B, "backup_incomplete", side_effect=incomplete), \
             patch.object(app.B, "start_backup") as start, \
             patch.object(app.time, "monotonic", return_value=150):
            app.BackupApplication._resume_interrupted_backups(application)
            start.assert_not_called()
        with patch.object(app.B, "service_running", return_value=False), \
             patch.object(app.B, "backup_incomplete", side_effect=incomplete), \
             patch.object(app.B, "start_backup") as start, \
             patch.object(app.time, "monotonic", return_value=201):
            app.BackupApplication._resume_interrupted_backups(application)
            start.assert_called_once()
        self.assertEqual(application._resume_attempts["daily"], 2)
        self.assertEqual(application._resume_after["daily"], 501)

    def test_existing_setup_is_required(self):
        application = self.application()
        application.cfg["setup_complete"] = False
        with patch.object(app.B, "start_backup") as start:
            app.BackupApplication._resume_interrupted_backups(application)
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
