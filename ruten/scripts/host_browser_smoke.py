"""Open a visible local Chrome window without loading payment code or websites."""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import undetected_chromedriver as uc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chrome_window import ensure_live_window  # noqa: E402


def detect_chrome_major() -> Optional[int]:
    chrome_path = uc.find_chrome_executable()
    if not chrome_path:
        return None
    if platform.system() == "Windows":
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"(Get-Item -LiteralPath '{chrome_path}').VersionInfo.ProductVersion",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    else:
        result = subprocess.run(
            [chrome_path, "--version"], capture_output=True, text=True, check=True
        )
    match = re.search(r"(\d+)\.\d+\.\d+\.\d+", result.stdout)
    return int(match.group(1)) if match else None


def run_once(major: Optional[int], duration: int) -> None:
    """以與正式 fee.py 相同的啟動參數開一次 Chrome，載入 data: URL 後關閉。"""
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--start-minimized")
    driver = uc.Chrome(options=options, version_main=major) if major else uc.Chrome(options=options)
    try:
        ensure_live_window(driver)
        driver.minimize_window()
        driver.set_window_size(1200, 600)
        driver.get(
            "data:text/html,<title>Ruten host browser smoke</title>"
            "<h1>Ruten host browser smoke: no payment</h1>"
        )
        if driver.title != "Ruten host browser smoke":
            raise RuntimeError("browser smoke title mismatch")
        time.sleep(duration)
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible, harmless host browser smoke")
    parser.add_argument("--duration-seconds", type=int, default=10)
    # 重複啟動才抓得到啟動競態（單次約 1/3 失敗率）
    parser.add_argument("--iterations", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.duration_seconds <= 60:
        parser.error("duration must be between 1 and 60 seconds")
    if not 1 <= args.iterations <= 30:
        parser.error("iterations must be between 1 and 30")

    major = detect_chrome_major()
    for i in range(1, args.iterations + 1):
        run_once(major, args.duration_seconds)
        print(f"HOST_BROWSER_SMOKE_ITERATION_OK {i}/{args.iterations}")
    print("HOST_BROWSER_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
