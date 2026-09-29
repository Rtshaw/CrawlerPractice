# Ruten SMS Content Allowlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a startup-validated SMS body allowlist for the Ruten OTP relay while preserving optional sender filtering and all existing OTP security controls.

**Architecture:** Compile both allowlist regexes once in `create_app()`, expose a small pure `validate_sms_allowlist()` helper, and apply it only to the SmsForwarder webhook. Preserve the current `app = create_app()` and `uvicorn main:app` startup model; test modules seed a sender-only environment value before importing `main`.

**Tech Stack:** Docker Python 3.11.10, FastAPI 0.115.4, Pydantic 2.9.2, Uvicorn 0.32.0, `unittest`, real local Uvicorn integration tests, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-29-ruten-sms-content-allowlist-design.md`

## Global Constraints

- `OTP_ALLOWED_MESSAGE_PATTERN` matches the original SMS body selected as `org_content`, then `content`, then `msg`.
- `OTP_ALLOWED_MESSAGE_PATTERN` and `OTP_ALLOWED_SENDER_PATTERN` use AND semantics when both are configured.
- At least one SMS allowlist must be configured; otherwise `create_app()` raises `ValueError` with the exact required message.
- Invalid message or sender regexes fail at app initialization; never silently accept all messages.
- SmsForwarder validation order is required fields, HMAC, timestamp freshness, allowlist, then OTP parse/store.
- Preserve HMAC verification, timestamp freshness, OTP parsing, TTL, replay/deduplication, consumer authentication, long polling, and consume-once behavior.
- Never write OTP, full SMS body, full sender, secrets, tokens, signatures, amount, or identifier to audit logs.
- `smsforwarder_configured` is true only when `SMSFORWARDER_SECRET` and at least one allowlist are configured.
- Compose must allow either allowlist variable to be empty and must not make either one individually required.
- The new message allowlist applies only to `/api/v1/smsforwarder`; `/api/v1/otp` remains governed by its existing `OTP_UPLOAD_TOKEN`, sender, and parser behavior.
- Keep `app = create_app()` and `uvicorn main:app`; do not change the production startup model.
- Do not modify `otp_client.py`, payment automation, or the Taiwan-side OTP polling protocol.

## Review Focus

- Original-body precedence: `org_content` must be matched and parsed instead of a disallowed templated `content`; pin in the existing custom JSON integration test owned by Task 2.
- Allowlist precedence: invalid HMAC or stale timestamp must return 401 before a body rejection; pin in Task 2's webhook integration tests.
- Configuration boundaries: message-only, sender-only, both, neither, and invalid regexes must have distinct startup/HTTP behavior; pin in Task 1 and Task 2.
- Audit privacy: message rejection may expose only lengths/fingerprints and must redact OTP/body/sender/signature; pin in Task 3's audit integration test.
- Global app startup behavior: production still imports `main:app` and fails on invalid configuration; test modules set a sender-only environment value before importing `main`; pin in Task 1's test setup and configuration tests.

### Task 1: Add pure allowlist validation and startup configuration checks

**Files:**
- Modify: `ruten/main.py`
- Test: `ruten/tests/test_otp_server.py`

**Interfaces:**
- Produces `validate_sms_allowlist(message: str, sender: str, message_regex: Optional[Pattern[str]], sender_regex: Optional[Pattern[str]]) -> Optional[str]`, returning `None` when allowed, `"message_not_allowed"` when the message pattern fails, and `"sender_not_allowed"` when the sender pattern fails.
- Produces one-time compiled `message_regex` and `sender_regex` inside `create_app()`.
- Produces `ServerSettings.allowed_message_pattern` loaded from `OTP_ALLOWED_MESSAGE_PATTERN`.

- [ ] **Step 1: Write failing unit tests for allowlist outcomes**

  Before importing `main` in `test_otp_server.py` and `test_audit_integration.py`, set `os.environ.setdefault("OTP_ALLOWED_SENDER_PATTERN", "^BANK$")` so the retained global `app = create_app()` can initialize during test collection. Add tests that assert message-only accepts a matching body from any sender, sender-only accepts a matching sender, both filters require both matches, message failure returns `message_not_allowed`, and sender failure returns `sender_not_allowed`.

- [ ] **Step 2: Run the focused tests and verify the expected RED failure**

  Run from `ruten/`: `C:\Users\casey\.pyenv\pyenv-win\versions\3.11.9\python.exe -m unittest tests.test_otp_server.OTPAllowlistTests -v`.

  Expected: test discovery/import fails because `validate_sms_allowlist` and `OTPAllowlistTests` do not yet exist; fix only test setup errors until the failure is specifically about the missing production behavior.

- [ ] **Step 3: Implement the minimal pure helper**

  Add the exact `validate_sms_allowlist()` signature. Evaluate message first when `message_regex` is present, then sender when `sender_regex` is present, using `.search()` and returning the exact rejection reason strings.

- [ ] **Step 4: Run the focused tests and verify GREEN**

  Run the same focused command. Expected: all `OTPAllowlistTests` pass.

- [ ] **Step 5: Write failing startup-validation tests**

  Add tests for `create_app(ServerSettings(... allowed_message_pattern="", allowed_sender_pattern=""))` raising the exact missing-allowlist `ValueError`, invalid message regex raising `ValueError` naming `OTP_ALLOWED_MESSAGE_PATTERN`, and invalid sender regex raising `ValueError` naming `OTP_ALLOWED_SENDER_PATTERN`.

- [ ] **Step 6: Run the startup tests and verify RED**

  Run from `ruten/`: `C:\Users\casey\.pyenv\pyenv-win\versions\3.11.9\python.exe -m unittest tests.test_otp_server.OTPConfigurationTests -v`.

  Expected: the new tests fail because the new setting is not loaded and startup validation is not implemented.

- [ ] **Step 7: Implement settings loading and initialization validation**

  Add `allowed_message_pattern` to `ServerSettings.from_env()`. In `create_app()`, compile non-empty patterns once with `re.IGNORECASE`, wrap `re.error` as `ValueError` with the corresponding environment variable name, and reject the both-empty case using the exact spec message. Keep the compiled regexes local to the app closure and use them for the SmsForwarder webhook path.

- [ ] **Step 8: Run the focused configuration tests and verify GREEN**

  Run the same `OTPConfigurationTests` command. Expected: all configuration tests pass, with no request-time regex compilation involved.

- [ ] **Step 9: Commit the completed task**

  ```text
  git add ruten/main.py ruten/tests/test_otp_server.py
  git commit -m "feat: add SMS allowlist configuration validation"
  ```

### Task 2: Enforce message/sender allowlists in the SmsForwarder webhook

**Files:**
- Modify: `ruten/main.py`
- Test: `ruten/tests/test_otp_server.py`

**Interfaces:**
- Consumes Task 1's compiled regexes and `validate_sms_allowlist()` result strings.
- Produces HTTP 422 `SMS content is not allowed` with rejection reason `message_not_allowed`.
- Preserves HTTP 422 `Sender is not allowed` with rejection reason `sender_not_allowed`.
- Leaves `/api/v1/otp` unchanged; it continues using only its existing upload auth, sender, and parser behavior.

- [ ] **Step 1: Write failing integration tests for message-only and original-body matching**

  Add a real-Uvicorn integration server configured with the ESUN message pattern and no sender pattern. Test that two different senders with the valid ESUN body return 202 and consume as `338228`, identifier `WDCT`, amount `137`; test JSON with disallowed `content` but matching `org_content` is accepted and returns the OTP from `org_content`.

- [ ] **Step 2: Run the new integration tests and verify RED**

  Run from `ruten/`: `C:\Users\casey\.pyenv\pyenv-win\versions\3.11.9\python.exe -m unittest tests.test_otp_server.MessageAllowlistApiIntegrationTests -v`.

  Expected: the configured message-only server currently accepts unrelated bodies or the new test class cannot find the expected rejection behavior; the failure must be attributable to missing allowlist enforcement.

- [ ] **Step 3: Write failing integration tests for rejections and ordering**

  Add tests for unrelated SMS and generic `OTP 246810` returning 422 with exact detail `SMS content is not allowed`; invalid signature and expired timestamp returning 401 even when the message matches; and both message plus `^BANK$` sender patterns rejecting sender `OTHER` with exact detail `Sender is not allowed`.

- [ ] **Step 4: Run the rejection tests and verify RED**

  Run the same focused integration test command. Expected: message-invalid cases are currently accepted or reach the parser instead of returning the new 422 response.

- [ ] **Step 5: Implement allowlist enforcement at the correct point**

  After required fields, HMAC verification, and timestamp freshness in `/api/v1/smsforwarder`, call `validate_sms_allowlist()` before constructing/storing the OTP payload. Map its result to the specified HTTP detail and rejection reason. Do not call the helper from `/api/v1/otp`; preserve that endpoint's existing behavior.

- [ ] **Step 6: Run the focused integration tests and verify GREEN**

  Run the same `MessageAllowlistApiIntegrationTests` command. Expected: all message-only, original-body, rejection-ordering, and AND-semantics tests pass.

- [ ] **Step 7: Run the existing OTP server suite**

  Run from `ruten/`: `C:\Users\casey\.pyenv\pyenv-win\versions\3.11.9\python.exe -m unittest tests.test_otp_server -v`.

  Expected: all legacy sender-only, HMAC, timestamp, parser, replay, TTL, consume-once, correlation, and long-poll tests pass.

- [ ] **Step 8: Commit the completed task**

  ```text
  git add ruten/main.py ruten/tests/test_otp_server.py
  git commit -m "feat: enforce SMS message allowlist"
  ```

### Task 3: Add health flags and sanitized message-rejection audit coverage

**Files:**
- Modify: `ruten/main.py`
- Modify: `ruten/audit_log.py`
- Modify: `ruten/tests/test_audit_integration.py`

**Interfaces:**
- `GET /health` adds boolean `message_filter_configured` and `sender_filter_configured` fields.
- `smsforwarder_configured` is true only for a configured secret plus at least one allowlist.
- Audit `smsforwarder.rejected` for message mismatch includes `reason="message_not_allowed"`, `status_code=422`, `message_length`, and sender fingerprint/length without sensitive values.

- [ ] **Step 1: Write failing health and audit tests**

  Add health assertions for message-only, sender-only, and both-filter configurations. Add an audit integration case posting a validly signed SMS with a non-matching body and assert the rejection reason/status, `message_length`, sender fingerprint presence, and absence of the body, OTP, full sender, signature, secret, and token.

- [ ] **Step 2: Run the focused audit tests and verify RED**

  Run from `ruten/`: `C:\Users\casey\.pyenv\pyenv-win\versions\3.11.9\python.exe -m unittest tests.test_audit_integration -v`.

  Expected: the new health fields, message rejection reason, or sanitized message length are missing.

- [ ] **Step 3: Implement health and audit changes**

  Add the two health booleans and update `smsforwarder_configured`. Emit the message rejection audit event with `_sender_audit_fields(sender)`, `message_length=len(message)`, processing time, status 422, and no message content. Add `message_length` to `audit_log.py`'s allowed non-sensitive field set.

- [ ] **Step 4: Run the focused audit tests and verify GREEN**

  Run the same audit test command. Expected: all audit integration tests pass and the generated JSONL contains no sensitive values.

- [ ] **Step 5: Commit the completed task**

  ```text
  git add ruten/main.py ruten/audit_log.py ruten/tests/test_audit_integration.py
  git commit -m "feat: audit SMS allowlist rejections"
  ```

### Task 4: Update Compose, examples, and deployment documentation

**Files:**
- Modify: `ruten/docker/compose.yml`
- Modify: `ruten/.env.example`
- Modify: `ruten/docker/.env.example`
- Modify: `ruten/README.md`
- Modify: `ruten/docker/README.md`
- Modify: `ruten/SESSION_HANDOFF.md`
**Interfaces:**
- Compose passes `OTP_ALLOWED_MESSAGE_PATTERN` and `OTP_ALLOWED_SENDER_PATTERN` with `:-` empty defaults, leaving OR validation to app startup.
- Documentation names message filter as primary, sender filter as optional secondary, includes the ESUN regex and migration/recreate steps, and retains `uvicorn main:app`.

- [ ] **Step 1: Write failing Compose/documentation verification checks**

  Add shell-level checks that the Compose file no longer contains `:?OTP_ALLOWED_*_PATTERN` for either allowlist, that both example env files contain the ESUN message pattern plus an optional empty sender pattern, and that all deployment docs retain `uvicorn main:app` while documenting message-primary/sender-optional behavior.

- [ ] **Step 2: Run the checks and verify RED**

  Run: `rg -n "OTP_ALLOWED_(MESSAGE|SENDER)_PATTERN:\?" ruten/docker/compose.yml ruten/.env.example ruten/docker/.env.example` plus `rg -n "main:app|OTP_ALLOWED_MESSAGE_PATTERN|OTP_ALLOWED_SENDER_PATTERN" ruten/README.md ruten/docker/README.md ruten/SESSION_HANDOFF.md`.

  Expected: the old Compose requirement and example/documentation content cause the new checks to fail; `main:app` remains present and is not removed.

- [ ] **Step 3: Implement the deployment configuration changes**

  Make both Compose allowlist variables optional with `:-`. Add the exact ESUN regex and migration instructions to both env examples and all three deployment documents, including the unchanged `uvicorn main:app` startup model, `docker compose config`, and container recreate/restart guidance. Do not modify Dockerfile or production startup commands.

- [ ] **Step 4: Run configuration and syntax verification**

  Run:

  ```text
  C:\Users\casey\.pyenv\pyenv-win\versions\3.11.9\python.exe -m py_compile ruten/fee.py ruten/main.py ruten/otp_client.py ruten/scheduled_run.py ruten/sms.py
  docker compose --env-file .env.example config
  ```

  Expected: Python compilation succeeds; Compose renders with either allowlist empty without interpolation errors. If Docker is unavailable, record that limitation and still inspect the rendered-variable syntax.

- [ ] **Step 5: Commit the completed task**

  ```text
  git add ruten/docker/compose.yml ruten/.env.example ruten/docker/.env.example ruten/README.md ruten/docker/README.md ruten/SESSION_HANDOFF.md
  git commit -m "docs: document SMS content based relay deployment"
  ```

### Task 5: Run the complete verification suite and prepare migration handoff

**Files:**
- Verify: `ruten/tests/`
- Review: all files changed by Tasks 1–4

**Interfaces:**
- No new production interface; this task verifies the complete spec and records deployment actions.

- [ ] **Step 1: Run the complete test suite**

  Run from `ruten/`:

  ```text
  C:\Users\casey\.pyenv\pyenv-win\versions\3.11.9\python.exe -m unittest discover -s tests -v
  ```

  Expected: all tests pass with zero failures/errors.

- [ ] **Step 2: Run full syntax verification**

  Run from `ruten/`:

  ```text
  C:\Users\casey\.pyenv\pyenv-win\versions\3.11.9\python.exe -m py_compile fee.py main.py otp_client.py scheduled_run.py sms.py
  ```

  Expected: exit code 0 and no syntax errors.

- [ ] **Step 3: Review the final diff against the spec**

  Run: `git diff master --check` and inspect `git diff master -- ruten docs/superpowers/plans/2026-09-29-ruten-sms-content-allowlist-design.md`.

  Confirm every acceptance criterion is represented, no secret/body/OTP logging was introduced, and no unrelated payment/client behavior changed.

- [ ] **Step 4: Record the VPS migration handoff**

  Report the exact environment transition from sender-only to message-primary configuration, whether `OTP_ALLOWED_SENDER_PATTERN` is retained, the required `docker compose config` check, and `docker compose up -d --build`/recreate needed to load the new image and `.env`.

- [ ] **Step 5: Perform final verification before claiming completion**

  Re-run the complete test suite after any final edits and report the actual command, exit status, test count, syntax result, changed files, backward compatibility behavior, and any Docker limitation with evidence.
