# Ruten Docker Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely run the Ruten fee worker in a disposable Docker container at five UTC+8 daily slots, with a harmless one-time Task Scheduler validation before the permanent task is installed.

**Architecture:** One Windows scheduled task owns five daily triggers and calls a PowerShell supervisor. The supervisor enforces the UTC+8/time-window/overlap rules, starts one fixed-name Compose worker, waits at most 15 minutes, captures sanitized status, and removes that exact container; Python owns slot selection and atomic slot claims. A separate one-time task passes `-DryRun`, bypasses all payment code, and is deleted only after Task Scheduler, Docker execution, and cleanup are verified.

**Tech Stack:** Python 3.11/unittest, PowerShell ScheduledTasks, Docker Desktop/Linux containers, Docker Compose v2, Debian Chromium/chromedriver/Xvfb.

**Spec:** `docs/superpowers/specs/2026-08-31-ruten-win10-docker-scheduler-design.md`

## Global Constraints

- Host current UTC offset must equal `+08:00`; otherwise installation and execution fail closed.
- Production slots are exactly `01:35`, `02:00`, `02:14`, `02:31`, and `02:40` in `Asia/Taipei`.
- A slot is eligible from 0 through 300 seconds after its scheduled time, with no in-slot retry.
- One fixed worker name is used; only that exact container may be removed.
- Worker hard timeout is 15 minutes; Task Scheduler limit is 20 minutes.
- Payment credentials, cookies, OTPs, SMS content, and tokens never enter images, task definitions, labels, or logs.
- Automated verification and the one-time task use dry-run only and never call `fee.py`.

---

### Task 1: Guarded Python scheduler

**Files:**
- Modify: `ruten/scheduled_run.py`
- Modify: `ruten/tests/test_scheduler.py`

**Interfaces:**
- Produces: `select_due_slot(now, slots, grace_seconds=300) -> datetime | None`
- Produces: `claim_slot(state_dir, slot) -> bool`
- Produces: CLI options `--guarded`, `--state-dir`, and `--dry-run`

- [ ] Add failing tests for exact-slot selection, 300-second inclusion, 301-second rejection, prior-day rejection, duplicate atomic claim, later-slot eligibility after an earlier claim, and guarded dry-run avoiding the payment runner.
- [ ] Run `python -m unittest tests.test_scheduler -v` and confirm each new behavior fails because its API is absent.
- [ ] Add minimal timezone-aware slot selection, atomic claim creation, persistent lock use, sanitized status logging, and a dry-run branch that does not import `fee`.
- [ ] Re-run scheduler tests and then the complete Python suite.

### Task 2: Disposable Linux fee worker

**Files:**
- Create: `ruten/docker/Dockerfile.worker`
- Create: `ruten/docker/compose.worker.yml`
- Create: `ruten/docker/worker-entrypoint.sh`
- Create: `ruten/docker/worker.env.example`
- Modify: `ruten/.gitignore`

**Interfaces:**
- Consumes: `python scheduled_run.py --guarded --state-dir /runtime/state`
- Produces: Compose service `fee-worker` and environment switch `RUTEN_DRY_RUN=1`

- [ ] Add a failing static/Compose verification that requires a separate image, non-root UID 10001, read-only root filesystem, dropped capabilities, no restart, read-only secret mounts, and writable logs/state.
- [ ] Build the smallest worker image with pinned Python dependencies, Debian Chromium/chromedriver, Xvfb, and a non-root entrypoint.
- [ ] Make dry-run print a fixed harmless marker and exit before config/cookies/payment imports.
- [ ] Run `docker compose -f docker/compose.worker.yml config`, build the image, compare browser/driver major versions, and run a local non-payment browser smoke test.

### Task 3: PowerShell supervisor

**Files:**
- Create: `ruten/scripts/run_fee_container.ps1`
- Create: `ruten/tests/test_run_fee_container.ps1`

**Interfaces:**
- Consumes: Compose service `fee-worker`
- Produces: `-DryRun`, `-ProjectPath`, `-TimeoutSeconds`, and deterministic exit codes/status log

- [ ] Write failing PowerShell assertions using a fake Docker executable for UTC offset rejection, live-worker overlap rejection, stale-worker exact cleanup, successful dry-run cleanup, nonzero worker exit propagation, and timeout forced cleanup.
- [ ] Run the PowerShell test script and confirm expected failures.
- [ ] Implement the supervisor with exact-name inspection/removal, detached Compose execution, bounded polling, sanitized logs, and `finally` cleanup.
- [ ] Re-run fake-Docker tests, then run a real dry-run container and confirm no fixed-name worker remains.

### Task 4: Five-trigger installer and one-time validation installer

**Files:**
- Create: `ruten/scripts/install_docker_schedule.ps1`
- Create: `ruten/tests/test_install_docker_schedule.ps1`

**Interfaces:**
- Produces: permanent task `RutenFeeDockerWorker` with five daily triggers
- Produces: optional one-time task name/time with action argument `-DryRun`

- [ ] Write failing PowerShell assertions for five trigger boundaries, principal/settings/action safety, and a one-time dry-run trigger exactly at the requested timestamp.
- [ ] Implement idempotent registration using absolute paths, the interactive limited principal, `IgnoreNew`, `StartWhenAvailable`, network requirement, and a 20-minute task limit.
- [ ] Verify exported task XML contains no known secret material and exactly the requested trigger definitions.

### Task 5: Host validation and installation

**Files:**
- Modify: `docs/handoff/2026-08-31-ruten-win11-task-scheduler-guide.md`

**Interfaces:**
- Consumes: completed worker, supervisor, and installer
- Produces: verified Windows Task Scheduler state

- [ ] Run all Python, PowerShell, Compose, image, browser, and supervisor dry-run checks with fresh output.
- [ ] Register `RutenFeeDockerWorker-Test` for ten minutes in the future with `-DryRun`; inspect its action and trigger before waiting.
- [ ] After triggering, require `LastTaskResult = 0`, the dry-run marker in the sanitized supervisor log, and no worker container.
- [ ] Delete the test task and confirm `Get-ScheduledTask` returns no object.
- [ ] Register `RutenFeeDockerWorker`; verify exactly five daily triggers, action contains only the supervisor path, settings match the spec, and no secret appears in exported XML.
- [ ] Update the handoff with the exact installed path, verification evidence, operational commands, and remaining real-payment validation risk.

