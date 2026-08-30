"""Cross-platform scheduled entry point with a non-overlapping process lock."""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Callable, Optional, TextIO

PROJECT_DIR = Path(__file__).resolve().parent


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


def run_scheduled(
    runner: Optional[Callable[[], int]] = None,
    *,
    project_dir: Path = PROJECT_DIR,
    now: Optional[dt.datetime] = None,
) -> int:
    timestamp = now or dt.datetime.now()
    log_dir = project_dir / "logs" / timestamp.strftime("%Y%m%d")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{timestamp.strftime('%H%M%S')}.log"
    try:
        with ProcessLock(project_dir / ".fee.lock"):
            with log_path.open("a", encoding="utf-8", buffering=1) as log_file:
                with contextlib.redirect_stdout(log_file), contextlib.redirect_stderr(log_file):
                    print(f"[{timestamp.isoformat()}] scheduled payment started")
                    if runner is None:
                        from fee import run

                        runner = run
                    result = int(runner())
                    print(f"[{dt.datetime.now().isoformat()}] scheduled payment exited: {result}")
                    return result
    except RuntimeError as exc:
        with log_path.open("a", encoding="utf-8") as log_file:
            print(f"[{dt.datetime.now().isoformat()}] skipped: {exc}", file=log_file)
        return 0


if __name__ == "__main__":
    raise SystemExit(run_scheduled())
