# Win11 建立 Ruten 五時段 Docker 工作排程教學

更新日期：2026-08-31
目標讀者：接手實作的另一個 AI，或負責部署的維運者

## 1. 目標

在一台保持 Windows 使用者登入、Docker Desktop 常駐的 Windows 11 主機上，
每天於 UTC+8 的下列時間觸發 Ruten fee Docker worker：

- `01:35`
- `02:00`
- `02:14`
- `02:31`
- `02:40`

本文件只說明 Windows 工作排程的建立、驗證與移除方式，不實作
`fee.py`、Docker worker 或 PowerShell supervisor，也不進行真實付款。

完整部署架構請先閱讀：

- `docs/superpowers/specs/2026-08-31-ruten-win10-docker-scheduler-design.md`
- 設計 commit：`7200365`

## 2. 目前程式庫狀態

已存在：

- `ruten/fee.py`
- `ruten/scheduled_run.py`
- `ruten/scripts/install_schedule.ps1`
- OTP relay 專用的 `ruten/docker/compose.yml`

尚未存在：

- fee worker Dockerfile／Compose service
- `ruten/scripts/run_fee_container.ps1` supervisor
- 支援五個 trigger 的 Docker 排程安裝腳本
- 5 分鐘補跑與 slot dedupe 實作

目前的 `ruten/scripts/install_schedule.ps1` 只接受一個 `DailyAt`，而且使用
固定 TaskName 搭配 `Register-ScheduledTask -Force`。不可用相同 TaskName
執行五次；後一次會覆蓋前一次，而不是累積五個時間。

## 3. 一個 Task、五個 Trigger

推薦建立一個名為 `RutenFeeDockerWorker` 的工作，並在同一個工作內加入
五個每日 trigger。Windows Task Scheduler 官方允許單一工作包含多個 trigger；
任一 trigger 到期都會啟動同一個 action，單一工作最多可包含 48 個 trigger。

不要建立五個名稱不同、內容相同的工作，原因如下：

- 只能在同一處設定 `IgnoreNew`，較容易避免重疊。
- 更新 supervisor 路徑時只需更新一個工作。
- 檢查、匯出、停用及移除都比較簡單。
- 五個時間共用同一份 slot journal 與容器清理規則。

官方參考：

- [Task Triggers](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-triggers)
- [New-ScheduledTaskTrigger](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasktrigger)
- [Register-ScheduledTask](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask)

## 4. 部署前準備

### 4.1 Windows 與 Docker

1. Windows 使用者必須保持已登入；畫面可以鎖定。
2. Docker Desktop 必須切換成 Linux containers。
3. Docker Desktop 必須設定為使用者登入後自動啟動。
4. 排程帳號必須能在一般權限 PowerShell 中執行 `docker version`。
5. Windows 當地時區必須是 UTC+8。

檢查：

```powershell
Get-TimeZone
[DateTimeOffset]::Now.Offset
docker version
docker compose version
```

預期 offset 為：

```text
08:00:00
```

如果不是 `+08:00`，installer 與 supervisor 必須拒絕建立或執行付款排程，
不可自行換算後繼續。

### 4.2 預期檔案

本教學假設另一個 AI 將建立：

```text
D:\Services\CrawlerPractice\ruten\
├─ scripts\
│  ├─ run_fee_container.ps1
│  └─ install_docker_schedule.ps1
├─ docker\
│  └─ compose.worker.yml
└─ runtime\
   ├─ config.ini
   ├─ cookies.json
   ├─ worker.env
   ├─ logs\
   └─ state\
```

實際路徑可以不同，但所有 Task Scheduler action 都必須使用絕對路徑。
不得把卡號、cookies、OTP token 或任何 secret 放進 Task Scheduler 的
Arguments、Description 或工作名稱。

## 5. PowerShell 建立方式

以下範例是另一個 AI 應實作進
`ruten/scripts/install_docker_schedule.ps1` 的核心結構。

```powershell
param(
    [string]$TaskName = "RutenFeeDockerWorker",
    [string]$ProjectPath = "D:\Services\CrawlerPractice\ruten"
)

$ErrorActionPreference = "Stop"

$expectedOffset = [TimeSpan]::FromHours(8)
if ([DateTimeOffset]::Now.Offset -ne $expectedOffset) {
    throw "Windows time zone must currently use UTC+8."
}

$supervisorPath = Join-Path $ProjectPath "scripts\run_fee_container.ps1"
if (-not (Test-Path -LiteralPath $supervisorPath -PathType Leaf)) {
    throw "Supervisor not found: $supervisorPath"
}

docker version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not available for the current user."
}

$dailyTimes = @("01:35", "02:00", "02:14", "02:31", "02:40")
$culture = [Globalization.CultureInfo]::InvariantCulture
$triggers = @(
    foreach ($dailyTime in $dailyTimes) {
        $at = [DateTime]::ParseExact($dailyTime, "HH:mm", $culture)
        New-ScheduledTaskTrigger -Daily -At $at
    }
)

$windowsPowerShell = Join-Path `
    $env:SystemRoot `
    "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = @(
    "-NoProfile"
    "-NonInteractive"
    "-ExecutionPolicy Bypass"
    "-File `"$supervisorPath`""
) -join " "

$action = New-ScheduledTaskAction `
    -Execute $windowsPowerShell `
    -Argument $arguments `
    -WorkingDirectory $ProjectPath

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -RunOnlyIfNetworkAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Ruten one-shot Docker fee worker; no in-slot retry" `
    -Force | Out-Null

Write-Host "Installed task: $TaskName"
```

### 設定理由

| 設定 | 用意 |
|---|---|
| 一個 Task、五個 Trigger | 集中管理並共用防重疊規則 |
| `LogonType Interactive` | Docker Desktop 由登入中的使用者持有 |
| `RunLevel Limited` | supervisor 不需要系統管理員權限 |
| `MultipleInstances IgnoreNew` | 前一個 action 尚未結束時忽略新的 action |
| `ExecutionTimeLimit 20 分鐘` | 給 15 分鐘 worker hard timeout 留下清理時間 |
| `RunOnlyIfNetworkAvailable` | 沒有網路時不啟動付款 worker |
| `StartWhenAvailable` | Windows 錯過時間時可以嘗試稍後啟動 |
| `AllowStartIfOnBatteries` | 筆電使用電池時仍可在排程時間啟動 |
| `DontStopIfGoingOnBatteries` | 執行中拔除 AC 電源時不會中止 worker |

## 6. 5 分鐘補跑的重要限制

`StartWhenAvailable` 不能單獨保證「錯過後五分鐘內立即補跑」。Microsoft
文件指出，錯過時間後排入 Task Scheduler 佇列的工作可能有預設延遲。
因此另一個 AI 必須在 supervisor 或 schedule gate 中自行判斷：

```text
0 秒 <= 現在時間 - 最近 slot 時間 <= 300 秒：允許
其他情況：記錄 skipped_late 並返回，不啟動 fee worker
```

官方參考：

- [TaskSettings.StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable)

如果需求是「主機在 slot 後第 1 至第 5 分鐘恢復時，必須在五分鐘內補跑」，
則五個每日 trigger 還必須各自加入每分鐘一次、持續五分鐘的 repetition
pattern；supervisor 的 slot claim 保證同一 slot 只有第一次能真正啟動 worker。
Microsoft 的 repetition pattern 支援 interval 與 duration，且日曆 trigger
可包含 repetition：

- [Repeating a Task](https://learn.microsoft.com/en-us/windows/win32/taskschd/repeating-a-task)
- [RepetitionPattern](https://learn.microsoft.com/en-us/windows/win32/taskschd/repetitionpattern)

PowerShell `New-ScheduledTaskTrigger -Daily` 沒有直接公開 repetition 參數。
要嚴格實現時，另一個 AI 應使用 Task Scheduler COM API 或產生／註冊 XML，
在每個 `CalendarTrigger` 中加入：

```xml
<Repetition>
  <Interval>PT1M</Interval>
  <Duration>PT5M</Duration>
  <StopAtDurationEnd>false</StopAtDurationEnd>
</Repetition>
```

`PT1M`／`PT5M` 會讓 trigger 在原時間及後續每分鐘再次呼叫 action。
這些額外呼叫不得直接重跑付款；schedule gate 必須先以
`YYYY-MM-DD/HH:mm` claim 去重。

## 7. 安裝排程

以目標 Windows 使用者登入後開啟一般 PowerShell：

```powershell
Set-Location D:\Services\CrawlerPractice\ruten
powershell -ExecutionPolicy Bypass `
    -File .\scripts\install_docker_schedule.ps1 `
    -ProjectPath "D:\Services\CrawlerPractice\ruten"
```

若 `Register-ScheduledTask` 因本機原則要求提升權限，才改用「以系統管理員
身分執行」開啟 PowerShell；排程的 principal 仍應是實際登入並執行 Docker
Desktop 的使用者，不要改成 `SYSTEM`。

## 8. PowerShell 驗證

### 8.1 確認只有一個 Task

```powershell
Get-ScheduledTask -TaskName RutenFeeDockerWorker |
    Select-Object TaskName, State, Author, Description
```

### 8.2 確認五個主要時間

```powershell
$task = Get-ScheduledTask -TaskName RutenFeeDockerWorker
$task.Triggers |
    Select-Object Enabled, StartBoundary |
    Format-Table -AutoSize
```

主要 StartBoundary 的當地時間必須是：

```text
01:35
02:00
02:14
02:31
02:40
```

如果使用 repetition，還要檢查每個 trigger 的 repetition interval／duration
分別為 `PT1M` 與 `PT5M`。

### 8.3 確認 action 沒有 secret

```powershell
$task.Actions | Format-List Execute, Arguments, WorkingDirectory
```

Arguments 只能包含 supervisor `.ps1` 路徑，不得出現：

- OTP token
- `config.ini` 的內容
- cookies
- 卡號或安全碼
- SMS／OTP

### 8.4 確認設定

```powershell
$task.Settings |
    Format-List StartWhenAvailable, MultipleInstances, ExecutionTimeLimit,
        RunOnlyIfNetworkAvailable, DisallowStartIfOnBatteries,
        StopIfGoingOnBatteries
```

預期：

```text
StartWhenAvailable      : True
MultipleInstances       : IgnoreNew
ExecutionTimeLimit      : PT20M
RunOnlyIfNetworkAvailable : True
DisallowStartIfOnBatteries : False
StopIfGoingOnBatteries    : False
```

### 8.5 查看最近執行結果

```powershell
Get-ScheduledTaskInfo -TaskName RutenFeeDockerWorker |
    Format-List LastRunTime, LastTaskResult, NextRunTime,
        NumberOfMissedRuns
```

`LastTaskResult = 0` 只代表 supervisor 正常結束，不等於信用卡付款已確認成功；
仍需查看 sanitised worker log 的明確狀態。

## 9. GUI 核對方式

1. 按 `Win + R`。
2. 輸入 `taskschd.msc`。
3. 開啟「工作排程器程式庫」。
4. 找到 `RutenFeeDockerWorker`。
5. 在「觸發程序」頁籤確認五個每日時間。
6. 在「動作」頁籤確認只執行 Windows PowerShell 與 supervisor 路徑。
7. 在「設定」頁籤確認工作已執行時不啟動新執行個體。
8. 確認執行時間上限為 20 分鐘。

不要在 GUI 中加入 secret，也不要把執行帳號改成 `SYSTEM`。

## 10. 安全測試方式

### 不要直接測試真實付款

另一個 AI 應先讓 supervisor 支援安全的 `-DryRun` 或替代 Compose command，
只啟動一個無害的測試容器並驗證：

- Task Scheduler 能呼叫 supervisor。
- Docker Desktop 對排程使用者可用。
- 正常結束後測試容器被刪除。
- 模擬逾時後容器被 `docker rm -f` 清除。
- Task action 重複觸發時沒有重疊容器。
- 超過 slot 五分鐘時不啟動 fee worker。

手動執行 Task：

```powershell
Start-ScheduledTask -TaskName RutenFeeDockerWorker
```

注意：若 supervisor 已實作 slot gate，在非排程時間手動啟動時，正確結果應是
`skipped_not_due`，而不是啟動付款。測試 Docker 清理必須使用 supervisor 的
`-DryRun`，不能繞過 gate 執行 `fee.py`。

## 11. 匯出與備份 Task 定義

```powershell
Export-ScheduledTask -TaskName RutenFeeDockerWorker |
    Set-Content -LiteralPath .\runtime\RutenFeeDockerWorker.xml `
        -Encoding Unicode
```

XML 可能包含本機使用者名稱與絕對路徑，不應直接提交 Git。它不應包含
卡號、cookies 或 OTP token；若發現這些內容，代表 action 設計錯誤。

## 12. 停用、啟用與移除

停用：

```powershell
Disable-ScheduledTask -TaskName RutenFeeDockerWorker
```

啟用：

```powershell
Enable-ScheduledTask -TaskName RutenFeeDockerWorker
```

停止目前 action：

```powershell
Stop-ScheduledTask -TaskName RutenFeeDockerWorker
```

停止 Task 不保證 Docker worker 一定隨之停止。應再由 supervisor 只針對固定的
worker container name 執行清理；不要使用會刪除其他容器的廣泛指令。

移除：

```powershell
Unregister-ScheduledTask `
    -TaskName RutenFeeDockerWorker `
    -Confirm:$false
```

移除後確認：

```powershell
Get-ScheduledTask -TaskName RutenFeeDockerWorker `
    -ErrorAction SilentlyContinue
```

應無輸出。

## 13. 交給另一個 AI 的實作清單

另一個 AI 應依序完成：

1. 先讀取本文件與完整 Docker scheduler design spec。
2. 保留現有 OTP relay Docker 資產，不覆蓋 `ruten/docker/compose.yml`。
3. 建立 `run_fee_container.ps1`，包含 UTC+8、slot age、dedupe、鎖、15 分鐘
   hard timeout 及 exact-container cleanup。
4. 建立 fee worker Dockerfile 與 worker Compose file。
5. 新增 `install_docker_schedule.ps1`，建立一個 Task 與五個每日 trigger。
6. 若要求嚴格五分鐘補跑，使用 COM/XML 為五個 trigger 加入每分鐘 repetition，
   不要假設 `StartWhenAvailable` 會在五分鐘內啟動。
7. 新增安全 dry-run，不可在測試中開啟露天付款流程。
8. 新增 slot 邊界、重複觸發、後續 slot、重疊、正常清理與逾時清理測試。
9. 執行既有 26 個 Python regression tests、PowerShell/task definition 檢查、
   `docker compose config`、image build 與無付款 browser smoke test。
10. 建立新的 `docs/handoff`，記錄已完成、未完成、下一步、風險與實際驗證。

## 14. 完成標準

- `Get-ScheduledTask` 只看到一個 `RutenFeeDockerWorker`。
- 該 Task 具有五個主要 UTC+8 daily trigger。
- action 只呼叫 supervisor，沒有任何 secret。
- 同時只能存在一個 fee worker。
- 同一 slot 的重複 action 不會重複付款。
- slot 後超過五分鐘必須跳過。
- worker 正常、失敗或逾時後都沒有殘留容器或瀏覽器程序。
- 前一個 slot 失敗不會停用後續 slot。
- 所有自動化驗證都不執行真實付款。

## 15. 已知風險與誠實狀態

- 本文件沒有建立或修改 Windows 工作排程。
- fee worker、supervisor 與五-trigger installer 目前仍未實作。
- `StartWhenAvailable` 不保證五分鐘內補跑；嚴格補跑需要 repetition 或其他
  每分鐘喚醒機制，再由 schedule gate 去重。
- Windows Task 的成功碼不是付款成功證據。
- 真實排程付款仍需要第一次有人監看的部署驗證。

## 16. 2026-09-01 實作與本機部署結果

本節取代第 2 節與第 15 節中「尚未實作」的狀態描述。實際部署路徑為：

```text
C:\Users\<USER>\project\CrawlerPractice\ruten
```

已新增並驗證：

- `docker/Dockerfile.worker` 與 `docker/Dockerfile.worker.dockerignore`
- `docker/compose.worker.yml` 與 `docker/worker-entrypoint.sh`
- `scripts/run_fee_container.ps1`
- `scripts/install_docker_schedule.ps1`
- `scheduled_run.py` 的 UTC+8 slot gate、五分鐘 grace、atomic claim 與 state lock
- 不會 import 或呼叫 `fee.py` 的 `-DryRun` 路徑

### 一次性排程測試

`RutenFeeDockerWorker-Test` 排定於 `2026-09-01 00:46:23 +08:00`，實際
`LastRunTime` 為 `00:46:23`，`LastTaskResult` 為 `0`。Supervisor log 同時包含：

```text
DRY_RUN_OK
cleanup_complete
```

測試後確認固定名稱 `ruten-fee-worker-run` 的容器數為 `0`，並已刪除
`RutenFeeDockerWorker-Test`；`Get-ScheduledTask` 不再找到它。

### 正式排程

已建立一個 `RutenFeeDockerWorker`，內含五個每日 trigger：

```text
01:35
02:00
02:14
02:31
02:40
```

已核對 `StartWhenAvailable=True`、`DisallowStartIfOnBatteries=False`、
`StopIfGoingOnBatteries=False`、`MultipleInstances=IgnoreNew`、
`ExecutionTimeLimit=PT20M`、`RunOnlyIfNetworkAvailable=True`、
`LogonType=Interactive`、`RunLevel=Limited`。Action 只包含 Windows PowerShell、
supervisor 絕對路徑及專案絕對路徑，沒有 `-DryRun` 或 secret。建立時顯示的
下一次執行時間為 `2026-09-01 01:35:00 +08:00`。

### 驗證範圍與剩餘風險

- Python scheduler 與既有 regression tests 已通過。
- Compose 設定、worker image build、Chromium/chromedriver major alignment、
  Xvfb/Chromium 離線 smoke test 已通過；smoke marker 為 `BROWSER_SMOKE_OK`。
- Supervisor 的正常 dry-run、live overlap 與 forced timeout cleanup 已通過。
- 自動化及一次性 Task 測試都未開啟露天，也未執行真實付款。
- 五個 trigger 沒有加入每分鐘 repetition；`StartWhenAvailable` 仍不保證主機
  恢復後一定在五分鐘內喚醒。Supervisor/Python gate 會拒絕超過五分鐘的執行。
- 第一筆真實排程付款仍須人工監看 log，確認網站、cookies 與銀行 3DS 流程。

### 2026-09-01 電池供電事件與修正

五個排程未付款的原因已由系統事件與 worker log 證實：筆電於
`2026-09-01 01:08:51 +08:00` 進入電池供電，直到 `08:15:25` 才恢復 AC；
舊 Task 設定為 `DisallowStartIfOnBatteries=True`，因此 01:35 至 02:40 的五個
trigger 都沒有準時啟動。恢復 AC 後 Task 才於 08:15 啟動，但 schedule gate
正確判定已超過五分鐘並記錄 `skipped_not_due`，所以未進入付款流程。

修正後 installer 明確使用 `-AllowStartIfOnBatteries` 與
`-DontStopIfGoingOnBatteries`，並已重新註冊正式 Task。實機核對結果為
`DisallowStartIfOnBatteries=False`、`StopIfGoingOnBatteries=False`；五個每日
trigger 維持 01:35、02:00、02:14、02:31、02:40，下一次執行時間為
`2026-09-02 01:35:00 +08:00`。

### 2026-09-01 手動付款驗證與 OTP 阻擋

手動驗證先發現 `/home/app` tmpfs 帶有 `noexec`，使
`undetected-chromedriver` 在瀏覽器啟動前收到 `EACCES`。Compose 已只為
`/home/app` 加入 `exec`；根檔案系統仍為唯讀、`/tmp` 仍為 `noexec`，UC
離線 browser smoke 與完整 regression tests 均已通過。

之後確認費用頁確有待繳款，且信用卡付款表單可以開啟。另修正 `payfee()`：
只有付款按鈕不存在時才回傳 `no_fee`；若按鈕存在但點擊逾時，必須回傳失敗，
不可把執行錯誤誤報為沒有欠費。

真實付款在取得 OTP relay server time 時收到 HTTP 401，程式在最終付款送出前
中止並記錄 `payment was not submitted`，因此本次沒有扣款。Docker `.env` 與
`config.ini` 的 consumer token 都已設定但彼此不同，relay 對兩者均回 401；
下一次付款前必須先將台灣 worker 的 `OTP_CONSUMER_TOKEN` 與日本 VPS relay
目前的 token 同步，並確認 `/api/v1/time` 回傳 HTTP 200。

token 同步後已確認 `/api/v1/time` 回傳 HTTP 200，且付款送出前探針可完整完成
信用卡表單、地址選單與 server-time 檢查。經使用者再次明確授權後執行一次真實
付款，Chrome 於流程中回報 `tab crashed`；worker exit code 為 1，沒有記錄付款
成功頁或完成的 3DS 結果。隨後的唯讀費用頁檢查仍找到信用卡付款按鈕，確認
待繳狀態仍在，本次付款沒有完成。依單次授權未再次重試；下一次真實付款前應先
處理 production Chrome 的分頁穩定性並完成不送出交易的回歸驗證。

## 17. 2026-09-01 改用 Windows 主機 Python 排程

Docker/Xvfb 內的 Chrome 不會顯示在 Windows 桌面上，而且真實付款驗證曾在
容器內發生 `tab crashed`。由於相同環境以主機執行 `python fee.py` 能正常開啟
瀏覽器，正式排程已改為直接使用 Windows 主機 Python；不需要把 `fee.py` 打包
成 `.exe`。

新增的主機排程元件如下：

- `scripts/run_fee_host.ps1`：保留 UTC+8 檢查、獨立 supervisor log、正確的
  exit code，以及正式執行時的 `scheduled_run.py --guarded` gate/lock。
- `scripts/install_host_schedule.ps1`：建立互動登入、Limited 權限及五個每日
  trigger 的 Windows Task。
- `scripts/host_browser_smoke.py`：只開啟本機 `data:` 測試頁，不讀取付款設定、
  cookies 或 OTP，也不會進入露天或送出付款。

一次性可見瀏覽器測試 `RutenFeeHostWorker-Test` 排定於
`2026-09-01 19:58:08 +08:00`，實際準時啟動並於約 36 秒後結束；結果為：

```text
LastTaskResult = 0
HOST_BROWSER_SMOKE_OK
host_worker_finished mode=browser_smoke exit_code=0
```

確認成功後已刪除 `RutenFeeHostWorker-Test`。

正式 Task 現為 `RutenFeeHostWorker`，五個每日 trigger 維持：

```text
01:35
02:00
02:14
02:31
02:40
```

Action 使用以下固定 Python：

```text
C:\Users\<USER>\AppData\Local\Programs\Python\Python39\python.exe
```

已核對 Task 為 `Ready`、`LogonType=Interactive`、`RunLevel=Limited`、允許電池
供電、需要網路、錯過時儘快啟動、重疊時忽略新執行；下一次執行時間為
`2026-09-02 01:35:00 +08:00`。正式 action 沒有 Docker、`-DryRun`、
`-BrowserSmoke`、OTP URL 或 token。Supervisor 只在正式子程序的環境變數中載入
`.env` 的 OTP 設定，不將 secret 寫入 Task action 或 supervisor log。

新 Task 完整驗證後，舊的 `RutenFeeDockerWorker` 已移除，避免兩套排程重複付款。
因為使用 `LogonType=Interactive` 讓 Chrome 能顯示於桌面，五個時段執行時 Windows
使用者必須保持登入，且電腦不能處於睡眠或關機狀態。首次真實自動付款仍應人工
監看 `runtime/logs/host-supervisor` 與每日 worker log；本次可見瀏覽器 smoke test
本身沒有執行付款。

### 2026-09-01 Windows 主機一次性付款成功

為了在正式五個時段以外執行經使用者明確授權的單次付款，主機 supervisor 與
installer 新增 `-ImmediatePayment`。此模式只略過每日 slot gate，仍使用
`scheduled_run.py`、`runtime/state/payment.lock`、worker log、OTP 環境變數及互動
Windows Task；`-ImmediatePayment` 與 `-DryRun`、`-BrowserSmoke` 互斥。正式
`RutenFeeHostWorker` 不含此旗標，仍維持 guarded 模式。

首次執行發現非 guarded 路徑忽略 `--state-dir`，導致 log 與 lock 落在專案根目錄。
已以整合測試重現後修正，Immediate 模式現在和正式排程共用 `runtime` 下的 log 與
付款鎖。付款前另發現 `card_type=JCB` 但只有 `[MASTER]` 區塊；該次在 Chrome 啟動
前即安全失敗，沒有送出付款。使用者修正卡別設定後才再次執行。

`RutenFeeHostWorker-Manual` 於 `2026-09-01 20:28:00 +08:00` 啟動。實際 worker
log 為 `runtime/logs/20260901/202801.log`，確認流程依序完成：

```text
已驗證玉山 3DS 來源、金額與網頁識別碼候選值
OTP relay 已收到包含交易關聯資料的簡訊轉發
已送出一次與交易相符的 OTP
已確認信用卡授權與繳費成功
繳費流程結束: paid
scheduled payment exited: 0
```

Supervisor 同時記錄 `host_worker_finished mode=immediate_payment exit_code=0`，Windows
Task 的 `LastTaskResult` 為 `0`。成功後已刪除一次性
`RutenFeeHostWorker-Manual`；正式 `RutenFeeHostWorker` 仍為 `Ready`，五個時間維持
01:35、02:00、02:14、02:31、02:40，下一次執行為
`2026-09-02 01:35:00 +08:00`。
