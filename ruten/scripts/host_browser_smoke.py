"""Open a visible local Chrome window without loading payment code or websites."""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import time
from typing import Optional

import undetected_chromedriver as uc


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Visible, harmless host browser smoke")
    parser.add_argument("--duration-seconds", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.duration_seconds <= 60:
        parser.error("duration must be between 1 and 60 seconds")

    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    major = detect_chrome_major()
    driver = uc.Chrome(options=options, version_main=major) if major else uc.Chrome(options=options)
    try:
        driver.get(
            "data:text/html,<title>Ruten host browser smoke</title>"
            "<h1>Ruten host browser smoke: no payment</h1>"
        )
        if driver.title != "Ruten host browser smoke":
            raise RuntimeError("browser smoke title mismatch")
        print("HOST_BROWSER_SMOKE_OK")
        time.sleep(args.duration_seconds)
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
