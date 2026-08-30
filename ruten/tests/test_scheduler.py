import datetime as dt
import tempfile
import unittest
from pathlib import Path

from scheduled_run import ProcessLock, run_scheduled


class SchedulerTests(unittest.TestCase):
    def test_scheduled_runner_writes_dated_log_and_exit_code(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)

            def runner():
                print("simulated payment")
                return 0

            result = run_scheduled(
                runner,
                project_dir=project,
                now=dt.datetime(2026, 8, 30, 2, 3, 4),
            )
            self.assertEqual(result, 0)
            log = project / "logs" / "20260830" / "020304.log"
            self.assertTrue(log.exists())
            content = log.read_text(encoding="utf-8")
            self.assertIn("simulated payment", content)
            self.assertIn("scheduled payment exited: 0", content)

    def test_process_lock_rejects_overlapping_run(self):
        with tempfile.TemporaryDirectory() as temp:
            lock_path = Path(temp) / ".fee.lock"
            with ProcessLock(lock_path):
                with self.assertRaises(RuntimeError):
                    with ProcessLock(lock_path):
                        pass


if __name__ == "__main__":
    unittest.main()
