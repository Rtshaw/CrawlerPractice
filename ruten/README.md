# Ruten fee payment automation

本專案執行 `fee.py` 進入露天計費中心並填寫信用卡資料；銀行要求 3-D Secure（3DS）時，由 [pppscn/SmsForwarder](https://github.com/pppscn/SmsForwarder) 把手機 SMS 轉送至 relay，Selenium 取得一次性 OTP 後填碼並確認付款結果。`scheduled_run.py` 提供不重疊執行與每日日誌。

> 這會進行真實信用卡交易。第一次請在有人監看時執行，確認露天及發卡銀行頁面仍相符，再啟用排程。不要用正式卡號進行測試交易。

## 架構

1. 排程啟動 `scheduled_run.py` → `fee.py`。
2. `fee.py` 在點擊付款前向 relay 取得伺服器時間作為 `not_before`；relay 不可用時不會送出付款。
3. 手機收到銀行 SMS，SmsForwarder 規則把它送至 `/api/v1/smsforwarder`。
4. relay 依 SmsForwarder 官方規格驗證 `timestamp + "\n" + secret` 的 HMAC-SHA256/Base64 `sign`、時間窗與 sender，再擷取 4–8 位 OTP。
5. `fee.py` 用獨立 consumer token 長輪詢 `/api/v1/otp/next`；OTP 只可讀取一次且會逾時刪除。
6. Selenium 跨新視窗及巢狀 iframe 找到 3DS 欄位，填碼送出並辨識成功、失敗或導回付款網站。

relay 使用記憶體佇列；服務重啟會清除尚未使用的 OTP，這是刻意的安全設計。

## 1. Python 與付款設定

建議 Python 3.9+：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.ini config.ini  # 僅在尚無 config.ini 時
```

在 `config.ini` 填入帳務與卡片欄位。relay URL/token 建議只放環境變數：

```powershell
$env:OTP_SERVER_URL = "https://opt.yurishop.xyz"
$env:OTP_CONSUMER_TOKEN = "<consumer-token>"
```

`cookies.json` 必須是有效的露天登入 cookies。`config.ini` 與 `cookies.json` 含完整身分/付款資訊，禁止提交、分享或寫入日誌；若曾外洩請輪替卡片與登入狀態。

## 2. 在日本 VPS 部署 OTP relay（Docker + 既有 Traefik）

日本 VPS **只執行 relay**，不放 `fee.py`、`config.ini`、`cookies.json` 或任何卡片資料。露天 Selenium 仍在台灣 IP 的電腦執行，因此露天不會看到日本 IP。

部署前確認：

1. `opt.yurishop.xyz` 的 DNS A/AAAA 已指向 VPS。
2. VPS 防火牆允許 Traefik 使用的 `80/tcp`、`443/tcp`。
3. Traefik 已有 Docker provider、HTTP/HTTPS entrypoint 與 ACME resolver。
4. 找出 Traefik external network 與 resolver 名稱：`docker network ls` 及 Traefik static config。

在 VPS 的 `ruten/docker` 目錄執行（上層需保留 `main.py`）：

```sh
cd /path/to/ruten/docker
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32)); print(secrets.token_urlsafe(32))"
chmod 600 .env
# 編輯 .env：填入兩個不同 secrets、實際銀行 sender regex，並核對 Traefik 名稱

docker network inspect traefik       # 若名稱不同，修改 TRAEFIK_NETWORK
docker compose config                # 部署前檢查展開後設定
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 relay
```

`compose.yml` 不發布 host port；relay 只透過 external Traefik network 的內部 `8000` 提供服務。容器使用 UID 10001、唯讀 root filesystem、移除全部 capabilities，且 image build context 不包含付款相關檔案。

驗證 HTTP 強制轉址與 HTTPS 健康檢查：

```sh
curl -I http://opt.yurishop.xyz/health
curl -fsS https://opt.yurishop.xyz/health
```

第一個請求應 redirect 至 HTTPS；第二個應回傳 `status: ok`，且 `smsforwarder_configured`、`consumer_configured` 都是 `true`。若既有 Traefik network、entrypoint 或 certificate resolver 不是預設的 `traefik`、`web`、`websecure`、`letsencrypt`，請修改 `.env` 中對應的 `TRAEFIK_*` 值。

更新服務：

```sh
docker compose build --pull
docker compose up -d
docker image prune -f
```

官方 SmsForwarder `sign` 只簽 timestamp，並未涵蓋 SMS 內容，因此 HTTPS、300 秒時間窗及嚴格 sender regex 都不可省略。`.env` 含 secrets，不可提交或傳送給第三方。

## 3. 設定 pppscn/SmsForwarder

依官方 [Releases](https://github.com/pppscn/SmsForwarder/releases) 安裝，授予 SMS 權限並依官方保活說明允許背景執行。

### 3.1 Webhook 發送通道

在「發送通道」新增 Webhook：

- **WebServer**：`https://opt.yurishop.xyz/api/v1/smsforwarder`
- **請求方式**：`POST`
- **Secret**：與伺服器 `SMSFORWARDER_SECRET` 完全相同
- **webParams**（建議）：

```json
{"from":"[from]","org_content":"[org_content]","timestamp":"[timestamp]","sign":"[sign]"}
```

此 JSON 使用官方附錄1提供的 `[from]`、`[org_content]`、`[timestamp]`、`[sign]`，讓 relay 收到原始 SMS，而不是被訊息模板加工後的內容。若將 webParams 留空，官方預設會用 `application/x-www-form-urlencoded` 傳送 `from/content/timestamp/sign`，relay 也相容；此時請確保自訂訊息模板保留完整 `{{SMS}}`。

### 3.2 SMS 轉發規則

建立「短信轉發」規則並指定上述 Webhook 通道：

- 優先依實際銀行 sender/短碼限制來源；也可再要求內容包含「驗證碼」、「動態密碼」或 `OTP`。
- relay 的 `OTP_ALLOWED_SENDER_PATTERN` 應使用同樣限制。先從 SmsForwarder 轉發日誌確認實際 `from`，再設定 regex。
- 不要建立「轉發所有 SMS」的規則，以免把私人簡訊送到伺服器。

Webhook 測試若使用不含 OTP 的官方測試內容，relay 會刻意回 `422 No unambiguous ... OTP`；這代表簽章/連線可能已成功，但內容不會進入 OTP 佇列。請以 `python -m unittest discover -s tests -v` 驗證完整官方 payload，不要為了讓測試按鈕成功而關閉簽章或 sender 檢查。

官方格式參考：

- [附錄1：Webhook POST/GET/PUT/PATCH 與 sign 規則](https://github.com/pppscn/SmsForwarder/wiki/%E9%99%84%E5%BD%951%EF%BC%9A%E5%90%91webhook%E5%8F%91%E9%80%81post-get-put-patch%E8%AF%B7%E6%B1%82)
- [附錄3：自訂模板變數](https://github.com/pppscn/SmsForwarder/wiki/%E9%99%84%E5%BD%953%EF%BC%9A%E8%87%AA%E5%AE%9A%E4%B9%89%E6%A8%A1%E6%9D%BF%E5%8F%AF%E7%94%A8%E5%8F%98%E9%87%8F)

## 4. 執行與排程

第一次先在有人監看時執行：

```powershell
python fee.py
```

Windows 每天 02:00（只在使用者登入時執行，適合可見 Chrome）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_schedule.ps1 -DailyAt "02:00"
Get-ScheduledTask -TaskName RutenFeePayment
Start-ScheduledTask -TaskName RutenFeePayment
```

Linux cron：

```sh
sh scripts/install_schedule.sh "0 2 * * *"
crontab -l
```

日誌位於 `logs/YYYYMMDD/HHMMSS.log`，不包含 OTP 或完整 cookies/card number；`.fee.lock` 防止兩次付款重疊。移除 Windows 工作：`Unregister-ScheduledTask -TaskName RutenFeePayment`。

## 5. 測試

測試不連線露天，也不會進行真實扣款：

```powershell
python -m unittest discover -s tests -v
python -m py_compile fee.py main.py otp_client.py scheduled_run.py sms.py
```

真實交易屬不可逆外部動作，不包含在自動化測試。銀行改版 challenge DOM 時，仍需以受控的小額/應繳款流程人工確認 selectors。

## 故障排除

- `/api/v1/smsforwarder` 回 `401 Invalid signature`：SmsForwarder Secret 不一致，或 sign/template 被改動。
- 回 `401 Webhook timestamp expired`：同步手機與伺服器時間；預設只接受 300 秒內請求。
- 回 `422 Sender is not allowed`：`OTP_ALLOWED_SENDER_PATTERN` 與實際 `from` 不符。
- 回 `422 No unambiguous...`：內容沒有唯一 4–8 位 OTP，或模板沒有保留原始 SMS。
- `fee.py` 回 consumer `401`：`OTP_CONSUMER_TOKEN` 不一致；它與 SmsForwarder Secret 必須不同。
- 找不到 3DS 欄位：銀行可能改版；可暫設 `keep_browser_on_error=true` 人工檢查，排程環境建議保持 false。
- cookies 失效：重新匯出 `cookies.json`，不要在程式內保存露天帳號密碼。
