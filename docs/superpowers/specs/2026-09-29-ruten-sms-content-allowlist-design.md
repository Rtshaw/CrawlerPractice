# Ruten OTP Relay：以簡訊內容識別玉山 OTP 設計規格

**日期：** 2026-09-29  
**範圍：** `ruten/` OTP relay、Docker deployment、測試與部署文件

## 目標

將 SmsForwarder webhook 的主要 allowlist 從固定 sender phone number 改為原始 SMS body 的 regex matching，以便銀行 sender/shortcode 變更時仍能識別玉山 OTP。`OTP_ALLOWED_SENDER_PATTERN` 保留為可選的額外限制，並維持既有 HMAC、timestamp、OTP parser、TTL、replay、consumer authentication 與一次性消費安全機制。

## 已確認的行為

- `OTP_ALLOWED_MESSAGE_PATTERN` 套用於原始 SMS body；Webhook 欄位選取順序維持 `org_content`、`content`、`msg`。
- message pattern 與 sender pattern 都存在時，兩者採 AND 語意。
- 只設定 message pattern 時，不檢查 sender。
- 只設定 sender pattern 時，維持現有 sender-only 行為。
- 兩者皆空時，`create_app()` fail-fast，錯誤訊息為：

  ```text
  At least one SMS allowlist must be configured: OTP_ALLOWED_MESSAGE_PATTERN or OTP_ALLOWED_SENDER_PATTERN
  ```

- 任一 regex 無效時，`create_app()` 立即失敗，不忽略設定、不接受所有 SMS。
- Webhook 驗證順序為：parse payload、required fields、timestamp freshness、HMAC、allowlist、OTP parse/store。
- message allowlist 不符合時回 HTTP 422，detail 為 `SMS content is not allowed`，audit reason 為 `message_not_allowed`。
- sender allowlist 不符合時維持 HTTP 422 與 detail `Sender is not allowed`，audit reason 為 `sender_not_allowed`。
- HMAC、timestamp、parser、TTL、replay 與 consumer authentication 的錯誤狀態與行為維持現況。
- audit log 可記錄 sender fingerprint、sender length、message length、processing time 與 rejection reason，但不得記錄 OTP、完整 SMS、完整 sender、secret、token、signature、amount 或 identifier。

## 架構決策

### 1. 在 app initialization 編譯 regex

`ServerSettings` 新增 `allowed_message_pattern: str = ""`。`create_app()` 會集中編譯 message 與 sender regex，避免每個 request 重複編譯。regex 編譯錯誤轉成帶有環境變數名稱的 `ValueError`，讓 deployment 在啟動時即暴露錯誤。

新增下列純驗證 helper，讓 message/sender 的 AND 語意可單獨測試：

```python
def validate_sms_allowlist(
    message: str,
    sender: str,
    message_regex: Optional[Pattern[str]],
    sender_regex: Optional[Pattern[str]],
) -> None:
```

helper 成功時不回傳值；失敗時 raise 可映射到 HTTP 422 與 audit reason 的明確例外或回傳明確 rejection reason。message 檢查先於 sender 檢查，兩者都配置時必須同時通過。

同一 allowlist helper 會套用到 SmsForwarder webhook 與既有手動 JSON upload ingress；sender-only 設定不會改變手動 upload 的既有結果。Webhook rejection 必須保留本 spec 指定的 audit event；手動 upload 維持既有 token/auth 與 response contract。

### 2. 使用 app factory 觸發 startup validation

移除 module import 時無條件建立的 global app，改由 `uvicorn main:create_app --factory` 建立應用程式。這使測試可匯入 parser、store 與 helper，而實際 Uvicorn startup 仍會在沒有 allowlist 或 regex 無效時 fail-fast。

Dockerfile command、`main.py` 執行說明、README 與 deployment handoff 會同步改為 app factory 方式。

### 3. Health semantics

`GET /health` 回傳：

```json
{
  "status": "ok",
  "upload_configured": true,
  "smsforwarder_configured": true,
  "consumer_configured": true,
  "message_filter_configured": true,
  "sender_filter_configured": false
}
```

其中 `smsforwarder_configured` 代表 `SMSFORWARDER_SECRET` 存在且至少一種 SMS allowlist 已配置；message/sender 欄位分別反映各自 regex 是否存在。

## 設定與部署

### Compose

`ruten/docker/compose.yml` 的兩個 allowlist 都改為可選：

```yaml
OTP_ALLOWED_MESSAGE_PATTERN: ${OTP_ALLOWED_MESSAGE_PATTERN:-}
OTP_ALLOWED_SENDER_PATTERN: ${OTP_ALLOWED_SENDER_PATTERN:-}
```

缺少兩者時由 application startup validation 拒絕啟動，而非由 Compose interpolation 拒絕展開。`docker compose config` 必須能在兩者任一為空時展開，但 container 啟動仍須由 `create_app()` 驗證。

### 範例 pattern

範例使用原始 SMS body 的玉山必要 marker 與六位交易驗證碼：

```regex
(?s)(?=.*?玉山卡網路消費)(?=.*網頁識別碼)(?=.*交易驗證碼\s*[:：]?\s*\d{6})
```

`ruten/.env.example` 與 `ruten/docker/.env.example` 都要說明 message filter 是 primary、sender filter 是 optional secondary，並提醒以實際 SmsForwarder webhook/log 的 `from` 與原始 SMS 確認 pattern。文件需說明 Docker Compose `.env`、反斜線與 regex quoting，並要求用 `docker compose config` 檢查展開結果。

## 測試策略

維持現有 `unittest` 與 real local Uvicorn integration pattern，新增或調整測試以覆蓋：

- valid 玉山內容由不同 sender 傳入仍回 202，且 OTP/identifier/amount 正確解析。
- unrelated SMS 與只含 generic OTP 的 SMS 回 422 `SMS content is not allowed`。
- invalid signature 與 expired timestamp 在 message allowlist 前仍回 401。
- message + sender 同時配置時，sender 不符合回 422 `Sender is not allowed`。
- sender-only legacy configuration 仍可接受符合 sender 的 SMS。
- message-only configuration 不依賴 sender。
- message/sender 都空、message regex 無效、sender regex 無效時 `create_app()` 失敗。
- health flags 正確反映 filter configuration。
- message rejection audit 包含 `message_not_allowed`、422、message length 與 sender fingerprint，且不包含敏感內容。
- 既有 HMAC、timestamp、replay、TTL、consume-once、long polling、原始內容優先順序與 ESUN correlation tests 維持通過。

完成前執行：

```text
python -m unittest discover -s tests -v
python -m py_compile fee.py main.py otp_client.py scheduled_run.py sms.py
```

若環境的 `python` shim 未選定版本，改用已安裝的 Python 3.11 executable 執行相同命令，並在報告中明確記錄實際命令與結果。

## 變更檔案

- Modify: `ruten/main.py`
- Modify: `ruten/audit_log.py`
- Modify: `ruten/docker/Dockerfile`
- Modify: `ruten/docker/compose.yml`
- Modify: `ruten/.env.example`
- Modify: `ruten/docker/.env.example`
- Modify: `ruten/README.md`
- Modify: `ruten/docker/README.md`
- Modify: `ruten/SESSION_HANDOFF.md`
- Modify: `ruten/tests/test_otp_server.py`
- Modify: `ruten/tests/test_audit_integration.py`

不修改 `otp_client.py`、付款流程或台灣端 OTP polling protocol。

## 安全與相容性限制

- 不可移除或弱化 HMAC signature verification、timestamp freshness、OTP TTL、one-time consumption、duplicate/replay handling 或 consumer auth。
- 不可接受所有 SMS，也不可因 SMS 任意包含六位數字就接受。
- `OTP_ALLOWED_SENDER_PATTERN` 空值代表不啟用 sender secondary filter，不代表允許在兩個 filter 都空時啟動。
- VPS `.env` 必須至少加入 message pattern；若保留 sender pattern，兩者會同時套用。修改環境後需重建或重啟 relay container，讓新設定與新程式載入。
