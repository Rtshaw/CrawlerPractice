# Ruten 自動付款專案 — Session Handoff

更新時間：2026-08-30 14:54 +08:00  
專案位置：`D:\Project\SideProject\CrawlerPractice\ruten`

## 1. 目標與目前結論

目標是排程執行 `fee.py` 進入露天計費中心、填寫信用卡付款資料；銀行發送 3-D Secure SMS OTP 後，由 Android 的 `pppscn/SmsForwarder` 傳送至 FastAPI relay，`fee.py` 取回一次性 OTP、自動填碼並判斷付款結果。

已知露天封鎖海外 IP，而 VPS 位於日本，因此採分離架構：

```text
Android SmsForwarder
        │ HTTPS
        ▼
日本 VPS：Docker + Traefik + FastAPI OTP relay
        ▲
        │ HTTPS server-time / OTP long polling
台灣 IP 電腦：fee.py + Chrome + Windows Task Scheduler
        │
        ▼
露天（只看到台灣出口 IP）
```

**不可在日本 VPS 執行 `fee.py`**，除非另有經授權的台灣出口。VPS 不放 `config.ini`、`cookies.json` 或信用卡資料。

公開網域：`https://opt.yurishop.xyz`

## 2. 已完成程式

### `fee.py`

- 以 `cookies.json` 還原露天 session。
- 進入露天計費中心並依 `config.ini` 的 `card_type` 填表，不再強制固定 MASTER。
- 點擊不可逆付款按鈕前，先使用 consumer token 呼叫 relay `/api/v1/time` 取得伺服器時間；relay 不可用時不送出付款。
- 跨新視窗及最多四層 iframe 尋找常見 OTP 欄位。
- 長輪詢 fresh OTP、自動填碼、送出，判斷成功、失敗或導回露天。
- OTP 不寫入日誌；錯誤回傳非零；正常情況關閉瀏覽器。

### `main.py`（FastAPI OTP relay）

主要 API：

- `GET /health`：健康與 secrets 是否設定。
- `POST /api/v1/smsforwarder`：SmsForwarder 官方 webhook。
- `GET /api/v1/time`：consumer token 保護的 relay 時鐘。
- `GET /api/v1/otp/next`：consumer token 保護的長輪詢、consume-once OTP。
- `POST /api/v1/otp`：保留的手動 JSON upload 相容端點，使用 `OTP_UPLOAD_TOKEN`；SmsForwarder 不使用。

SmsForwarder endpoint 支援：

- 官方 form：`from/content/timestamp/sign`。
- 自訂 JSON：建議 `from/org_content/timestamp/sign`。
- 官方簽章：`Base64(HMAC-SHA256(key=secret, message=timestamp + "\n" + secret))`，相容 URL-encoded sign。
- 預設 300 秒 timestamp 時間窗。
- `OTP_ALLOWED_SENDER_PATTERN` sender regex。
- OTP 4–8 位解析、TTL、防 request replay、重送冪等回應。
- OTP freshness 以 relay `created_at` 判斷，避免手機、台灣電腦與 VPS 時鐘偏差。
- SmsForwarder secret、consumer token 權限分離。

### `otp_client.py`

- 受 token 保護地取得 relay server time。
- 長輪詢 `/api/v1/otp/next`。
- 驗證回應的 OTP 必須為 4–8 位數字。
- 401/403/503 立即報錯；204 繼續等待。

### 排程

- `scheduled_run.py`：Windows 使用 `msvcrt`、POSIX 使用 `fcntl` 的非重疊 process lock。
- 日誌：`logs/YYYYMMDD/HHMMSS.log`。
- `scripts/install_schedule.ps1`：Windows 每日工作排程。
- `scripts/install_schedule.sh`：Linux cron。
- `script.sh` 已改用 `scheduled_run.py`。

## 3. SmsForwarder 設定

使用現成專案：<https://github.com/pppscn/SmsForwarder>

Webhook 發送通道：

```text
WebServer: https://opt.yurishop.xyz/api/v1/smsforwarder
Method: POST
Secret: 與 VPS SMSFORWARDER_SECRET 相同
```

建議 `webParams`：

```json
{"from":"[from]","org_content":"[org_content]","timestamp":"[timestamp]","sign":"[sign]"}
```

轉發規則必須限制實際銀行 sender/短碼，最好再要求內容包含「驗證碼」、「動態密碼」或 `OTP`。不要轉發所有私人 SMS。relay 的 `OTP_ALLOWED_SENDER_PATTERN` 必須對應 SmsForwarder 日誌中的實際 `from`。

## 4. Docker / Traefik

所有部署檔已集中至 `ruten/docker/`：

```text
ruten/
├─ main.py
└─ docker/
   ├─ .env.example
   ├─ Dockerfile
   ├─ Dockerfile.dockerignore
   ├─ README.md
   ├─ compose.yml
   └─ requirements-server.txt
```

Compose 特性：

- 從 `ruten/docker` 可直接執行。
- build context 為上層 `ruten/`，但 `Dockerfile.dockerignore` 採 deny-all allowlist，只納入 `main.py`、Dockerfile、server requirements。
- Image：`python:3.11.10-slim-bookworm`，server-only 固定版本 dependencies。
- UID/GID 10001 非 root、唯讀 root filesystem、`cap_drop: ALL`、`no-new-privileges`、`pids_limit: 100`。
- 無 host port，只 `expose: 8000` 並連接既有 external Traefik network。
- HTTP router 永久 redirect HTTPS。
- HTTPS router 使用 `opt.yurishop.xyz`、websecure、TLS 與可設定 certificate resolver。
- Docker JSON log rotation。

VPS 部署：

```sh
cd /path/to/ruten/docker
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(32)); print(secrets.token_urlsafe(32))"
# 編輯 .env，填入兩個不同 secrets、sender regex、Traefik 實際名稱

docker network inspect traefik
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 relay
```

`.env` 關鍵值：

```dotenv
SMSFORWARDER_SECRET=<random secret A>
OTP_CONSUMER_TOKEN=<different random secret B>
OTP_ALLOWED_SENDER_PATTERN=^實際銀行sender$
SMSFORWARDER_MAX_SKEW_SECONDS=300
OTP_TTL_SECONDS=300
OTP_MAX_LONG_POLL_SECONDS=30
OTP_DOMAIN=opt.yurishop.xyz
TRAEFIK_NETWORK=traefik
TRAEFIK_HTTP_ENTRYPOINT=web
TRAEFIK_HTTPS_ENTRYPOINT=websecure
TRAEFIK_CERTRESOLVER=letsencrypt
```

若既有 Traefik 名稱不同，修改 `.env` 中對應值。

驗證：

```sh
curl -I http://opt.yurishop.xyz/health
curl -fsS https://opt.yurishop.xyz/health
```

HTTP 應轉 HTTPS；HTTPS 應回 `status: ok`，並且 `smsforwarder_configured`、`consumer_configured` 為 `true`。

## 5. 台灣端 fee.py

台灣電腦設定：

```powershell
$env:OTP_SERVER_URL = "https://opt.yurishop.xyz"
$env:OTP_CONSUMER_TOKEN = "<與VPS相同的consumer-token>"
python fee.py
```

或在不含 secrets 的 `config.example.ini` 參考 `[OTP]` 欄位。正式 `config.ini` 與 `cookies.json` 已被 `.gitignore` 排除。

第一次 live run 必須有人監看。此 session **沒有執行真實信用卡扣款**；測試使用模擬付款頁與本機 API。

Windows 排程：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_schedule.ps1 -DailyAt "02:00"
Get-ScheduledTask -TaskName RutenFeePayment
Start-ScheduledTask -TaskName RutenFeePayment
```

## 6. 已完成驗證

最近一次驗證結果：

- `python -m unittest discover -s tests -v`：**19/19 passed**。
- 覆蓋付款表單、跨視窗/雙層 iframe 3DS、relay server-time、clock skew、OTP consume-once、long polling。
- 覆蓋 SmsForwarder 官方 HMAC 公式、URL-encoded sign、form、JSON + `org_content`、錯誤簽章、過期 timestamp、sender 拒絕與 replay idempotency。
- `python -m py_compile`：通過。
- PowerShell AST parser 及 `sh -n`：通過。
- 從 `ruten/docker` 執行 `docker compose --env-file .env.example config`：通過。
- 從 `ruten/docker` 執行 Compose build：成功。
- Container UID：10001；Docker health：`healthy`。
- Image `/app` 僅有 `main.py`、`requirements-server.txt`。
- 容器內 SmsForwarder HMAC POST → consumer 取碼 round-trip：通過，第二次取碼為 204。
- 先前獨立程式及 Docker review 結果：`APPROVED`。

## 7. 安全注意事項

- `config.ini`、`cookies.json` 含真實感個資、卡號/CVV/session cookies；目前 Git 檢查顯示未追蹤，但應視為敏感資料並考慮輪替。
- `.env`、`docker/.env` 已被 `.gitignore` 排除。
- SmsForwarder 官方 sign 只簽 timestamp，不涵蓋 SMS body，因此 HTTPS、短時間窗和 sender regex 都不可取消。
- 日本 VPS 只放 relay；付款及露天 cookies 留在台灣電腦。
- relay 是記憶體佇列，容器重新啟動會清除未取用 OTP，屬預期安全行為。
- 不要公開 Uvicorn 8000 host port；只透過 Traefik 443。

## 8. 下一個 Chat 建議先做

1. 讀取本文件與 `docker/README.md`。
2. 確認 `opt.yurishop.xyz` DNS 已指向日本 VPS。
3. 確認 VPS 現有 Traefik network、entrypoint、ACME resolver 實際名稱。
4. 建立 `docker/.env` 並部署 relay。
5. 用 HTTPS `/health` 驗證。
6. 在 SmsForwarder 設定 Webhook、Secret、webParams 與銀行 sender 規則。
7. 在台灣電腦設定 consumer token，先做有人監看的受控執行，再安裝排程。

## 9. 主要文件

- `README.md`：完整架構、SmsForwarder、付款與排程文件。
- `docker/README.md`：VPS Docker 快速部署。
- `.env.example`：一般 relay/client 環境範本。
- `docker/.env.example`：Docker/Traefik 環境範本。
- `config.example.ini`：不含正式資料的付款設定範本。
- `tests/`：19 項測試。

請勿在新 chat 的輸出中顯示 `config.ini`、`cookies.json` 或任何實際 secrets/卡片內容。
