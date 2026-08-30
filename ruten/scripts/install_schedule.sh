#!/bin/sh
set -eu

CRON_EXPRESSION="${1:-0 2 * * *}"
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
TAG="# ruten-fee-payment"
COMMAND="cd '$PROJECT_DIR' && '$PYTHON_BIN' '$PROJECT_DIR/scheduled_run.py'"
NEW_LINE="$CRON_EXPRESSION $COMMAND $TAG"

EXISTING=$(crontab -l 2>/dev/null || true)
{
    printf '%s\n' "$EXISTING" | grep -vF "$TAG" || true
    printf '%s\n' "$NEW_LINE"
} | sed '/^[[:space:]]*$/d' | crontab -

printf "Installed cron entry: %s\n" "$NEW_LINE"
printf "Remove with: crontab -l | grep -vF '%s' | crontab -\n" "$TAG"
