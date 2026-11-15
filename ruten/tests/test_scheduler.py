import contextlib
import io
import os
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from scheduled_run import ProcessLock, claim_slot, run_guarded, run_scheduled, select_due_slot


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.taipei = ZoneInfo("Asia/Taipei")

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

    def test_scheduled_runner_can_keep_lock_in_state_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            lock_path = project / "state" / "payment.lock"

            result = run_scheduled(
                lambda: 0,
                project_dir=project,
                lock_path=lock_path,
                now=dt.datetime(2026, 8, 30, 2, 3, 4),
            )

            self.assertEqual(result, 0)
            self.assertTrue(lock_path.exists())
            self.assertFalse((project / ".fee.lock").exists())

    def test_scheduled_runner_returns_nonzero_for_runtime_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)

            def failing_runner():
                raise RuntimeError("sensitive payment detail")

            result = run_scheduled(
                failing_runner,
                project_dir=project,
                now=dt.datetime(2026, 8, 30, 2, 3, 4),
            )

            self.assertEqual(result, 1)
            content = (project / "logs" / "20260830" / "020304.log").read_text(
                encoding="utf-8"
            )
            self.assertIn("scheduled payment failed: RuntimeError", content)
            self.assertNotIn("sensitive payment detail", content)

    def test_process_lock_rejects_overlapping_run(self):
        with tempfile.TemporaryDirectory() as temp:
            lock_path = Path(temp) / ".fee.lock"
            with ProcessLock(lock_path):
                with self.assertRaises(RuntimeError):
                    with ProcessLock(lock_path):
                        pass

    def test_select_due_slot_accepts_exact_slot(self):
        now = dt.datetime(2026, 8, 31, 2, 14, tzinfo=self.taipei)

        result = select_due_slot(now, ("01:35", "02:00", "02:14", "02:31", "02:40"))

        self.assertEqual(result, now)

    def test_select_due_slot_includes_five_minute_boundary(self):
        now = dt.datetime(2026, 8, 31, 2, 19, tzinfo=self.taipei)

        result = select_due_slot(now, ("02:14",))

        self.assertEqual(result, dt.datetime(2026, 8, 31, 2, 14, tzinfo=self.taipei))

    def test_select_due_slot_rejects_one_second_past_grace(self):
        now = dt.datetime(2026, 8, 31, 2, 19, 1, tzinfo=self.taipei)

        result = select_due_slot(now, ("02:14",))

        self.assertIsNone(result)

    def test_select_due_slot_can_use_previous_day_across_midnight(self):
        now = dt.datetime(2026, 9, 1, 0, 2, tzinfo=self.taipei)

        result = select_due_slot(now, ("23:58",))

        self.assertEqual(result, dt.datetime(2026, 8, 31, 23, 58, tzinfo=self.taipei))

    def test_claim_slot_is_atomic_and_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            slot = dt.datetime(2026, 8, 31, 2, 14, tzinfo=self.taipei)

            self.assertTrue(claim_slot(Path(temp), slot))
            self.assertFalse(claim_slot(Path(temp), slot))

    def test_claiming_failed_slot_does_not_block_later_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp)
            first = dt.datetime(2026, 8, 31, 2, 14, tzinfo=self.taipei)
            later = dt.datetime(2026, 8, 31, 2, 31, tzinfo=self.taipei)

            self.assertTrue(claim_slot(state_dir, first))
            self.assertTrue(claim_slot(state_dir, later))

    def test_guarded_dry_run_never_calls_payment_runner(self):
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / "state"
            now = dt.datetime(2026, 8, 31, 2, 14, tzinfo=self.taipei)

            result = run_guarded(
                state_dir=state_dir,
                now=now,
                slots=("02:14",),
                dry_run=True,
                runner=lambda: self.fail("payment runner must not be called in dry-run"),
            )

            self.assertEqual(result, 0)
            logs = list((state_dir.parent / "logs" / "20260831").glob("*.log"))
            self.assertEqual(len(logs), 1)
            self.assertIn("DRY_RUN_OK", logs[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class ManualModeTests(unittest.TestCase):
    taipei = ZoneInfo("Asia/Taipei")

    def _run(self, temp, argv_runner=None, **kw):
        state = Path(temp) / "state"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = run_scheduled(
                argv_runner, project_dir=state.parent, lock_path=state / "payment.lock", mode="manual", **kw
            )
        return code, buf.getvalue()

    def test_manual_runs_outside_any_slot_but_auto_gate_still_skips(self):
        with tempfile.TemporaryDirectory() as temp:
            noon = dt.datetime(2026, 8, 31, 12, 0, tzinfo=self.taipei)
            called = []
            run_guarded(state_dir=Path(temp) / "g", now=noon, runner=lambda: called.append(1) or 0)
            self.assertEqual(called, [])
            code, out = self._run(temp, lambda: called.append(1) or 0)
            self.assertEqual((code, called), (21, [1]))
            self.assertIn("RUTEN_OUTCOME status=completed_unverified", out)

    def test_auto_runs_in_slot_and_second_claim_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            at = dt.datetime(2026, 8, 31, 2, 0, 30, tzinfo=self.taipei)
            called = []
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_guarded(state_dir=Path(temp) / "s", now=at, runner=lambda: called.append(1) or 0)
                run_guarded(state_dir=Path(temp) / "s", now=at, runner=lambda: called.append(1) or 0)
            self.assertEqual(called, [1])
            logs = "".join(p.read_text() for p in (Path(temp) / "logs" / "20260831").glob("*.log"))
            self.assertIn("skipped_already_claimed", logs)

    def test_exit_zero_is_not_payment_success(self):
        with tempfile.TemporaryDirectory() as temp:
            code, out = self._run(temp, lambda: print("PAYMENT_OUTCOME=no_fee") or 0)
            self.assertEqual(code, 10)
            self.assertIn("status=no_fee", out)
            self.assertNotIn("status=paid", out)

    def test_paid_and_failure_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            code, out = self._run(temp, lambda: print("PAYMENT_OUTCOME=paid") or 0)
            self.assertEqual(code, 0)
            self.assertIn("status=paid", out)
            code, out = self._run(temp, lambda: print("PAYMENT_OUTCOME=paid_unconfirmed") or 0)
            self.assertEqual(code, 20)
            self.assertIn("status=paid_unconfirmed", out)
            code, out = self._run(temp, lambda: 1)
            self.assertEqual(code, 1)
            self.assertIn("status=failed", out)
            code, out = self._run(temp, lambda: (_ for _ in ()).throw(ValueError("boom")))
            self.assertEqual(code, 1)
            self.assertIn("status=failed", out)

    def test_manual_blocked_while_payment_lock_held(self):
        with tempfile.TemporaryDirectory() as temp:
            with ProcessLock(Path(temp) / "state" / "payment.lock"):
                code, out = self._run(temp, lambda: self.fail("must not run"))
            self.assertEqual(code, 11)
            self.assertIn("status=skipped_overlap", out)

    def test_worker_output_secret_is_not_copied_to_outcome_line(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ["OTP_CONSUMER_TOKEN"] = "s3cret-token"
            try:
                _, out = self._run(temp, lambda: print("PAYMENT_OUTCOME=paid") or 0)
            finally:
                del os.environ["OTP_CONSUMER_TOKEN"]
            self.assertNotIn("s3cret-token", out)
