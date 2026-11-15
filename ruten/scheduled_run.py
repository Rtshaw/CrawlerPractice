"""Cross-platform scheduled entry point with a non-overlapping process lock."""

from __future__ import annotations

import contextlib
import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional, TextIO, Tuple
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_SLOTS: Tuple[str, ...] = ("01:35", "02:00", "02:14", "02:31", "02:40")


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file: Optional[TextIO] = None

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write("0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.file.close()
            self.file = None
            raise RuntimeError("another fee payment process is already running") from exc
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.file is None:
            return
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None


def _taipei_datetime(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIPEI)
    return value.astimezone(TAIPEI)


def select_due_slot(
    now: dt.datetime,
    slots: Iterable[str] = DEFAULT_SLOTS,
    *,
    grace_seconds: int = 300,
) -> Optional[dt.datetime]:
    """Return the most recent Taipei slot if it is no more than five minutes old."""
    local_now = _taipei_datetime(now)
    candidates = []
    for slot_text in slots:
        parsed = dt.datetime.strptime(slot_text, "%H:%M").time()
        for day_offset in (0, -1):
            slot_date = local_now.date() + dt.timedelta(days=day_offset)
            candidate = dt.datetime.combine(slot_date, parsed, tzinfo=TAIPEI)
            if candidate <= local_now:
                candidates.append(candidate)
    if not candidates:
        return None
    latest = max(candidates)
    age_seconds = (local_now - latest).total_seconds()
    return latest if 0 <= age_seconds <= grace_seconds else None


def claim_slot(state_dir: Path, slot: dt.datetime) -> bool:
    """Atomically claim one local slot; a claim remains after every outcome."""
    local_slot = _taipei_datetime(slot)
    claim_dir = state_dir / "claims" / local_slot.strftime("%Y-%m-%d")
    claim_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claim_dir / f"{local_slot.strftime('%H%M')}.claim"
    try:
        with claim_path.open("x", encoding="utf-8") as claim_file:
            claim_file.write(local_slot.isoformat())
    except FileExistsError:
        return False
    return True


def _report(status: str, log_path: Path) -> None:
    """One machine-readable line: process exit 0 alone never proves a payment happened."""
    print(f"RUTEN_OUTCOME status={status} log={log_path}", flush=True)


def _write_guard_status(state_dir: Path, now: dt.datetime, status: str) -> None:
    log_dir = state_dir.parent / "logs" / now.strftime("%Y%m%d")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{now.strftime('%H%M%S')}.log"
    with log_path.open("a", encoding="utf-8") as log_file:
        print(f"[{now.isoformat()}] {status}", file=log_file)
    _report(status.split()[0], log_path)


def _dry_run() -> int:
    print("DRY_RUN_OK: payment runner was not imported or executed")
    return 0


def run_guarded(
    *,
    state_dir: Path,
    now: Optional[dt.datetime] = None,
    slots: Iterable[str] = DEFAULT_SLOTS,
    dry_run: bool = False,
    runner: Optional[Callable[[], int]] = None,
) -> int:
    timestamp = _taipei_datetime(now or dt.datetime.now(tz=TAIPEI))
    slot = select_due_slot(timestamp, slots)
    if slot is None:
        _write_guard_status(state_dir, timestamp, "skipped_not_due")
        return 0
    try:
        with ProcessLock(state_dir / "worker.lock"):
            if not claim_slot(state_dir, slot):
                _write_guard_status(state_dir, timestamp, f"skipped_already_claimed slot={slot:%Y-%m-%d/%H:%M}")
                return 0
            selected_runner = _dry_run if dry_run else runner
            return run_scheduled(
                selected_runner,
                project_dir=state_dir.parent,
                lock_path=state_dir / "payment.lock",
                now=timestamp,
            )
    except RuntimeError:
        _write_guard_status(state_dir, timestamp, f"skipped_overlap slot={slot:%Y-%m-%d/%H:%M}")
        return 0
def run_scheduled(
    runner: Optional[Callable[[], int]] = None,
    *,
    project_dir: Path = PROJECT_DIR,
    lock_path: Optional[Path] = None,
    now: Optional[dt.datetime] = None,
    mode: str = "scheduled",
) -> int:
    timestamp = now or dt.datetime.now()
    log_dir = project_dir / "logs" / timestamp.strftime("%Y%m%d")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{timestamp.strftime('%H%M%S')}.log"
    lock_path = lock_path or (project_dir / ".fee.lock")
    process_lock = ProcessLock(lock_path)
    try:
        process_lock.__enter__()
    except RuntimeError as exc:
        with log_path.open("a", encoding="utf-8") as log_file:
            print(f"[{dt.datetime.now().isoformat()}] skipped: {exc}", file=log_file)
        _report("skipped_overlap", log_path)
        return MANUAL_EXIT_CODES["skipped_overlap"] if mode == "manual" else 0

    result = 1
    try:
        with log_path.open("a", encoding="utf-8", buffering=1) as log_file:
            with contextlib.redirect_stdout(log_file), contextlib.redirect_stderr(log_file):
                print(f"[{timestamp.isoformat()}] {mode} payment started")
                try:
                    if runner is None:
                        from fee import run

                        runner = run
                    result = int(runner())
                    print(f"[{dt.datetime.now().isoformat()}] {mode} payment exited: {result}")
                except Exception as exc:
                    print(
                        f"[{dt.datetime.now().isoformat()}] {mode} payment failed: "
                        f"{exc.__class__.__name__}"
                    )
                    result = 1
    finally:
        process_lock.__exit__(None, None, None)
    status = _outcome(log_path, result)
    _report(status, log_path)
    return MANUAL_EXIT_CODES.get(status, 1) if mode == "manual" else result


# Manual-only exit codes so Task Scheduler "Last Run Result" shows the outcome.
MANUAL_EXIT_CODES = {
    "paid": 0, "no_fee": 10, "skipped_overlap": 11,
    "completed_unverified": 21, "paid_unconfirmed": 20, "failed": 1,
}


def _outcome(log_path: Path, result: int) -> str:
    if result != 0:
        return "failed"
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if "DRY_RUN_OK" in text:
        return "dry_run"
    found = re.findall(r"^PAYMENT_OUTCOME=(\w+)$", text, re.M)
    return found[-1] if found else "completed_unverified"


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Ruten fee worker safely")
    parser.add_argument("--guarded", action="store_true", help="enforce the production slot gate")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="run now, skipping the slot gate; keeps the payment lock and fee.py protections",
    )
    parser.add_argument("--dry-run", action="store_true", help="never import or execute the payment runner")
    parser.add_argument("--state-dir", type=Path, default=PROJECT_DIR / "runtime" / "state")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.manual:
        result = run_scheduled(
            _dry_run if args.dry_run else None,
            project_dir=args.state_dir.parent,
            lock_path=args.state_dir / "payment.lock",
            mode="manual",
        )
    elif args.guarded:
        result = run_guarded(state_dir=args.state_dir, dry_run=args.dry_run)
    elif args.dry_run:
        result = run_scheduled(
            _dry_run,
            project_dir=args.state_dir.parent,
            lock_path=args.state_dir / "payment.lock",
        )
    else:
        result = run_scheduled(
            project_dir=args.state_dir.parent,
            lock_path=args.state_dir / "payment.lock",
        )
    if args.dry_run and result == 0:
        print("DRY_RUN_OK")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
