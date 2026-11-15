"""Exercise the production undetected-chromedriver path inside the worker container."""

import re
import subprocess
import time

import undetected_chromedriver as uc


xvfb = subprocess.Popen(
    ["Xvfb", ":99", "-screen", "0", "1200x800x24", "-listen", "tcp", "-nolisten", "unix"]
)
driver = None
try:
    time.sleep(0.5)
    options = uc.ChromeOptions()
    options.binary_location = "/usr/bin/chromium"
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    chromium_version = subprocess.check_output(["chromium", "--version"], text=True)
    version_match = re.search(r"(\d+)\.", chromium_version)
    assert version_match is not None
    driver = uc.Chrome(options=options, version_main=int(version_match.group(1)))
    driver.get("data:text/html,<title>Ruten UC worker smoke</title><p>offline</p>")
    assert driver.title == "Ruten UC worker smoke"
    print("UC_BROWSER_SMOKE_OK")
finally:
    if driver is not None:
        driver.quit()
    xvfb.terminate()
    xvfb.wait(timeout=5)
