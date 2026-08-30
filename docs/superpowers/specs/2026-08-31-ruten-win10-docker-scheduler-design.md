# Ruten Win10 one-shot Docker scheduler design

Date: 2026-08-31

## 1. Objective

Run `ruten/fee.py` on a separate Windows 10 host in an isolated Linux
container at five UTC+8 slots every day. A run missed because the host or
Docker Desktop was temporarily unavailable may start only within five minutes
after its slot. Every slot remains independently eligible even when an earlier
slot failed or ended with an unknown payment result.

The primary safety goal is lifecycle isolation: a failed or hung run must not
leave Chrome, chromedriver, Xvfb, Python, or a worker container running, and it
must not overlap another run.

## 2. Confirmed operating assumptions

- The Windows 10 user remains signed in, although the desktop may be locked.
- Docker Desktop uses Linux containers and remains running for that user.
- The host local time zone is UTC+8. The installer and supervisor fail closed
  if the current UTC offset is not `+08:00`.
- Scheduled local times are `01:35`, `02:00`, `02:14`, `02:31`, and `02:40`.
- A late start is allowed from zero through five minutes after the slot;
  anything later is skipped.
- An earlier failed or unknown run does not suppress later slots.
- No automatic retry occurs inside a slot.
- The existing external OTP relay remains the source of fresh correlated OTP
  events. The worker does not host the relay.

## 3. Architecture

Windows Task Scheduler owns time-based triggering and recovery after a short
host interruption. It invokes a PowerShell supervisor. The supervisor starts a
named, detached, one-shot Docker Compose worker, monitors it for at most 15
minutes, records its exit status, and removes the exact container in a
`finally` path. A persistent state directory supplies cross-invocation locking,
slot deduplication, and logs.

```text
Windows Task Scheduler (five daily triggers, StartWhenAvailable)
    -> PowerShell supervisor
       -> validate UTC+8 and Docker availability
       -> reject overlap or clean an expired stale worker
       -> docker compose run one named worker
          -> schedule gate (0..5 minute grace and slot dedupe)
          -> Xvfb + Chromium + chromedriver
          -> scheduled_run.py -> fee.py
       -> monitor <= 15 minutes
       -> collect sanitized status
       -> always remove the exact worker container
```

This split keeps the payment runtime reproducible in Docker while using the
Windows host facility that best understands sign-in, resume, and missed task
starts. It avoids mounting the Docker Engine socket into a scheduler container.

## 4. Components and repository changes

### Worker image

Add a fee-specific Dockerfile without changing the existing OTP relay image.
The image contains Python 3.11, Chromium, matching distro chromedriver, Xvfb,
the fee runtime, and pinned Python dependencies. It runs as a non-root user,
drops Linux capabilities, uses a read-only root filesystem, and receives
writable tmpfs/runtime mounts only where Chrome and undetected-chromedriver
need them.

The entrypoint starts Xvfb, copies the image chromedriver into an ephemeral
writable location when required by undetected-chromedriver, and then executes
the schedule gate. The container does not contain payment credentials at image
build time.

### Worker Compose file

Add a worker-specific Compose file beside the current relay Compose file. It
defines the one-shot fee service, `TZ=Asia/Taipei`, security restrictions,
read-only mounts for `config.ini` and `cookies.json`, a local secret environment
file for the OTP relay URL/token, and writable mounts for `logs` and `state`.
It has no restart policy because each invocation is intentionally disposable.

### Schedule gate and run journal

Extend the scheduled runner with testable functions that:

1. Convert the current instant to `Asia/Taipei`.
2. Select the most recent configured slot whose age is between zero and five
   minutes inclusive.
3. Claim `YYYY-MM-DD/HH:MM` atomically in the persistent state directory.
4. Skip when no slot is due, the slot was already claimed, or another run owns
   the lock.
5. Preserve the claim regardless of payment outcome so the same slot cannot be
   triggered twice. A later slot has a different claim and remains eligible.

The existing direct/manual scheduled runner remains available for tests and
manual operations; the Docker entrypoint uses the guarded scheduled mode.

### Windows supervisor

Add a PowerShell script that uses a constant, narrowly scoped worker container
name. It validates the UTC offset and Docker availability, refuses to overlap a
live worker, and removes only an expired stale worker older than the 15-minute
execution limit. It starts the worker detached, polls its Docker state, and
always removes that exact container after completion, failure, or timeout.

The supervisor never retries a payment. A timeout is an unknown result and is
reported as failure, but it does not disable later scheduled slots.

### Task Scheduler installer

Add an idempotent PowerShell installer that creates one task with the five
daily triggers. The task uses `StartWhenAvailable`, ignores concurrent task
instances, runs only as the signed-in Windows user with limited privileges,
and invokes the supervisor from the deployed project directory. An uninstall
command and inspection commands are documented.

## 5. Runtime data and secrets

The Win10 deployment keeps the following outside Git and outside the image:

```text
ruten/runtime/config.ini       # identity and card fields, read-only mount
ruten/runtime/cookies.json     # Ruten session cookies, read-only mount
ruten/runtime/worker.env       # OTP URL and consumer token
ruten/runtime/logs/            # sanitized per-run logs
ruten/runtime/state/           # slot claims and lock files
```

The implementation adds ignore rules for the runtime directory while keeping a
sanitized example environment file. Neither OTP values, full SMS bodies, card
numbers, cookies, nor tokens may appear in logs or container labels.

## 6. Failure and cleanup semantics

- `fee.py` keeps `keep_browser_on_error=false` in deployment configuration and
  calls `driver.quit()` from its existing `finally` block.
- Normal completion or Python failure exits the worker; the supervisor removes
  its container.
- A hung worker is force-removed after 15 minutes, which terminates every
  process in its PID namespace, including Chrome, chromedriver, and Xvfb.
- A live worker blocks a simultaneous trigger. A worker older than the hard
  limit is considered stale and is removed before evaluating the new trigger.
- A missing/invalid config, expired cookies, unavailable OTP relay, invalid
  ACS state, or unknown payment result returns nonzero and does not cause an
  in-slot retry.
- Per the approved policy, later slots remain eligible even after an unknown
  result. Logs must make this risk visible rather than silently treating the
  earlier run as successful.

## 7. Observability

Each invocation writes a timestamped UTF-8 log under the mounted logs directory
and a short supervisor status containing slot, start/end time, container exit
code, and cleanup outcome. Output is sanitized and does not include the OTP,
SMS body, cookie values, card fields, or consumer token.

Operational commands documented for the target host include task inspection,
manual task start, recent worker logs, current worker inspection, image build,
and task removal.

## 8. Verification

Implementation is complete only after all of the following pass without making
a real payment:

1. Unit tests for exact-slot, five-minute-inclusive catch-up, over-five-minute
   rejection, duplicate-slot rejection, later-slot eligibility after failure,
   and non-overlapping lock behavior.
2. Existing fee, OTP client, OTP relay, and scheduler regression tests.
3. Python compilation checks.
4. `docker compose config` with sanitized test settings.
5. Worker image build and checks that Chromium/chromedriver versions align.
6. Xvfb/Chromium browser smoke test that does not open the Ruten payment flow.
7. Supervisor dry run proving normal cleanup and forced timeout cleanup against
   a harmless test command.
8. Task installer inspection showing exactly five UTC+8 triggers and the
   intended task settings.

The first real scheduled payment remains a monitored deployment validation. It
is not part of automated tests and must not be triggered by the implementation
or verification process.

## 9. Non-goals

- Moving the OTP relay onto the Win10 worker host.
- Embedding secrets, cookies, or card information into the image.
- Mounting the Docker Engine socket into a container.
- Automatically retrying a slot or suppressing later slots after a failure.
- Running Docker Desktop before Windows user sign-in.
- Adding VNC or remote interactive browser access in the initial deployment.
- Performing a real payment during build or automated verification.

## 10. Acceptance criteria

- The target host installs one task with the five approved daily triggers.
- A trigger within the five-minute grace window starts at most one worker.
- A trigger outside the grace window performs no payment work.
- Every worker exits or is forcibly removed within 15 minutes.
- Failed workers leave no worker container or browser process behind.
- A later scheduled slot can run after an earlier failed/unknown slot.
- Runtime secrets never enter Git or the image.
- All offline tests and browser/container smoke checks pass.
