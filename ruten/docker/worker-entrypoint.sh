#!/bin/sh
set -eu

state_dir=/runtime/state

if [ "${RUTEN_DRY_RUN:-0}" = "1" ]; then
    dry_run_delay="${RUTEN_DRY_RUN_DELAY_SECONDS:-0}"
    case "$dry_run_delay" in
        ''|*[!0-9]*) echo "Invalid dry-run delay" >&2; exit 2 ;;
    esac
    if [ "$dry_run_delay" -gt 0 ]; then
        sleep "$dry_run_delay"
    fi
    exec python /app/scheduled_run.py --dry-run --state-dir "$state_dir"
fi

Xvfb :99 -screen 0 1200x800x24 -listen tcp -nolisten unix &
xvfb_pid=$!
trap 'kill "$xvfb_pid" 2>/dev/null || true' EXIT INT TERM

if [ "${RUTEN_BROWSER_SMOKE:-0}" = "1" ]; then
    chromium_major="$(chromium --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')"
    driver_major="$(chromedriver --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')"
    if [ "$chromium_major" != "$driver_major" ]; then
        echo "Browser/driver major mismatch" >&2
        exit 1
    fi
    python - <<'PY'
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

options = Options()
options.binary_location = "/usr/bin/chromium"
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=options)
try:
    driver.get("data:text/html,<title>Ruten worker smoke</title><p>offline</p>")
    assert driver.title == "Ruten worker smoke"
    print("BROWSER_SMOKE_OK")
finally:
    driver.quit()
PY
    exit 0
fi

exec python /app/scheduled_run.py --guarded --state-dir "$state_dir"
