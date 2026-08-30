# OTP relay Docker deployment

此目錄可直接部署 FastAPI OTP relay；日本 VPS 只執行此 relay，不要上傳 `config.ini`、`cookies.json` 或在 VPS 執行 `fee.py`。Compose 會以上層 `../main.py` 建置服務，因此 VPS 上需保留以下結構：

```text
ruten/
├─ main.py
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
