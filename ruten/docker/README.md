# OTP relay Docker deployment

此目錄只部署 Linux SMS runtime 的 FastAPI OTP relay；日本 VPS 只執行此 relay，不要上傳 `config.ini`、`cookies.json` 或在 VPS 執行 `fee.py`。Win11 fee runtime 透過 HTTPS 呼叫此 relay，並在自己的 `ruten/logs/YYYYMMDD/*.log` 保存付款執行紀錄。Compose 會以上層 `../main.py` 建置服務，因此 Linux VPS 上需保留以下結構：

```text
ruten/
├─ main.py
├─ audit_log.py
└─ docker/
   ├─ Dockerfile
   ├─ Dockerfile.dockerignore
   ├─ compose.yml
   ├─ requirements-server.txt
   └─ .env.example
```

## Deploy

```sh
cd /path/to/ruten/docker
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(32)); print(secrets.token_urlsafe(32))"
```

編輯 `.env`：

- 將兩個不同亂數分別填入 `SMSFORWARDER_SECRET`、`OTP_CONSUMER_TOKEN`。
- 將 `OTP_ALLOWED_SENDER_PATTERN` 改為 SmsForwarder 日誌中的實際銀行 sender regex。
- 核對現有 Traefik 的 `TRAEFIK_NETWORK`、entrypoint 與 certificate resolver 名稱。

建立持久化 audit log 目錄。容器以 UID/GID `10001:10001` 執行，目錄必須可寫：

```sh
mkdir -p runtime/logs
chown 10001:10001 runtime/logs
chmod 750 runtime/logs
```

```sh
docker network inspect traefik
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 relay
```

## Verify

```sh
curl -I http://opt.yurishop.xyz/health
curl -fsS https://opt.yurishop.xyz/health
```

HTTP 應永久轉至 HTTPS；HTTPS JSON 的 `status` 應為 `ok`，且 `smsforwarder_configured`、`consumer_configured` 應為 `true`。

## Persistent audit log

Relay 會將 sanitized JSONL audit log 寫入：

```text
./runtime/logs/audit.jsonl
```

Compose 將此目錄掛載至容器 `/var/log/ruten-otp`。每個 audit 檔上限預設為
10 MiB，超過後輪替並保留 30 個輪替檔，總量約不超過 310 MiB；可用
`OTP_AUDIT_LOG_MAX_BYTES` 與 `OTP_AUDIT_LOG_BACKUP_COUNT` 調整。每行 timestamp
固定使用 `Asia/Taipei`，所以可直接依時間查詢。Docker stdout 的近期 log rotation
仍保留，但歷史查詢應以 `runtime/logs/audit.jsonl*` 為準。

Audit event 只包含事件名稱、HTTP 狀態、拒絕原因、時間差、雜湊指紋與布林欄位；
不包含 OTP、SMS 原文、Token、卡號、完整 sender、交易金額或網頁識別碼。

查詢 02:40（台灣時間）附近的事件：

```sh
grep -E '2026-09-08T02:4[0-3]|smsforwarder|otp.consume|relay.initialized' \
  runtime/logs/audit.jsonl*
```

判讀方式：

- 沒有 `smsforwarder.request`：手機沒有打到 relay，或查錯 relay/時間範圍。
- 有 `smsforwarder.rejected`：查看同一行的 `reason` 與 `status_code`。
- 有 `smsforwarder.accepted` 但 `otp.consume` 一直是 `outcome=empty`：檢查
  `not_before`、relay 是否重啟，以及 OTP 是否已被其他 consumer 取走。
- 有 `otp.consume` 的 `outcome=delivered`：Win11 端應能取得該次 OTP；後續問題在
  3DS/瀏覽器階段。

SmsForwarder WebServer：

```text
https://opt.yurishop.xyz/api/v1/smsforwarder
```

台灣端 `fee.py` 使用：

```text
OTP_SERVER_URL=https://opt.yurishop.xyz
OTP_CONSUMER_TOKEN=<與VPS相同的consumer token>
```

更新：

```sh
cd /path/to/ruten/docker
docker compose build --pull
docker compose up -d
docker compose logs --tail=100 relay
```
