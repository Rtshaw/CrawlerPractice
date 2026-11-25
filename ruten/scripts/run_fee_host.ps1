param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "",
    # 未指定 PythonPath 時，從此排程讀取直譯器（可注入以利測試）
    [string]$WorkerTaskName = "RutenFeeHostWorker",
    [string]$EnvFile = "",
    [string]$RuntimePath = "",
    [switch]$DryRun,
    [switch]$BrowserSmoke,
    [switch]$ImmediatePayment,
    [switch]$Manual,
    [ValidateRange(1, 60)]
    [int]$BrowserSmokeSeconds = 10
)

$ErrorActionPreference = "Stop"
$expectedOffset = [TimeSpan]::FromHours(8)
if ([DateTimeOffset]::Now.Offset -ne $expectedOffset) {
    throw "Windows time zone must currently use UTC+8."
}
if (@($DryRun, $BrowserSmoke, $ImmediatePayment, $Manual).Where({ $_ }).Count -gt 1) {
    throw "DryRun, BrowserSmoke, ImmediatePayment, and Manual are mutually exclusive."
}

# 手動執行未帶 -PythonPath 時，必須與排程使用同一個直譯器，不可退回 PATH 上的 python
if (-not $PythonPath) {
    $workerTask = Get-ScheduledTask -TaskName $WorkerTaskName -ErrorAction SilentlyContinue
    $taskArguments = if ($workerTask) { [string]$workerTask.Actions[0].Arguments } else { "" }
    if ($taskArguments -notmatch '-PythonPath\s+"([^"]+)"') {
        throw "Cannot determine PythonPath: pass -PythonPath or install scheduled task '$WorkerTaskName'."
    }
    $PythonPath = $Matches[1]
}

$resolvedProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
$resolvedPythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$scheduledRunner = Join-Path $resolvedProjectPath "scheduled_run.py"
$browserSmokeScript = Join-Path $resolvedProjectPath "scripts\host_browser_smoke.py"
$resolvedRuntimePath = if ($RuntimePath) {
    [IO.Path]::GetFullPath($RuntimePath)
} else {
    Join-Path $resolvedProjectPath "runtime"
}
$statePath = Join-Path $resolvedRuntimePath "state"
$logRoot = Join-Path $resolvedRuntimePath "logs\host-supervisor"

foreach ($requiredPath in @($resolvedPythonPath, $scheduledRunner)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required host worker file was not found: $requiredPath"
    }
}
if ($BrowserSmoke -and -not (Test-Path -LiteralPath $browserSmokeScript -PathType Leaf)) {
    throw "Browser smoke script was not found: $browserSmokeScript"
}

New-Item -ItemType Directory -Force -Path $statePath, $logRoot | Out-Null
$logPath = Join-Path $logRoot ((Get-Date).ToString("yyyyMMdd-HHmmss-fff") + "-$PID.log")

function Write-Status {
    param([string]$Status)
    $line = "[{0}] {1}" -f ([DateTimeOffset]::Now.ToString("o")), $Status
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

$mode = if ($BrowserSmoke) {
    "browser_smoke"
} elseif ($DryRun) {
    "dry_run"
} elseif ($Manual) {
    "manual"
} elseif ($ImmediatePayment) {
    "immediate_payment"
} else {
    "payment"
}
$pythonArguments = @()
if ($BrowserSmoke) {
    $pythonArguments = @($browserSmokeScript, "--duration-seconds", $BrowserSmokeSeconds)
} else {
    $pythonArguments = @($scheduledRunner, "--state-dir", $statePath)
    if ($Manual) {
        $pythonArguments += "--manual"
    }
    if ($DryRun) {
        $pythonArguments += "--dry-run"
    } elseif (-not $ImmediatePayment -and -not $Manual) {
        $pythonArguments += "--guarded"
    }
    if (-not $DryRun) {
        $resolvedEnvFile = if ($EnvFile) {
            (Resolve-Path -LiteralPath $EnvFile).Path
        } else {
            Join-Path $resolvedProjectPath ".env"
        }
        if (-not (Test-Path -LiteralPath $resolvedEnvFile -PathType Leaf)) {
            throw "Host worker environment file was not found: $resolvedEnvFile"
        }
        $allowedNames = @("OTP_SERVER_URL", "OTP_CONSUMER_TOKEN")
        foreach ($line in Get-Content -LiteralPath $resolvedEnvFile) {
            if ($line -notmatch '^\s*([^#][^=]*)=(.*)$') {
                continue
            }
            $name = $Matches[1].Trim()
            if ($allowedNames -notcontains $name) {
                continue
            }
            $value = $Matches[2].Trim()
            if (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            ) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
        foreach ($name in $allowedNames) {
            if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
                throw "Required host worker environment value is missing: $name"
            }
        }
    }
}

# 非 BrowserSmoke 模式需要 ZoneInfo('Asia/Taipei')；缺 tzdata 時提前明確失敗，避免跑到付款流程才炸
if (-not $BrowserSmoke) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $tzOutput = @(& $resolvedPythonPath -c "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Taipei')" 2>&1 | ForEach-Object { $_.ToString() })
        $tzExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($tzExit -ne 0) {
        Write-Status "tz_self_check_failed python=$resolvedPythonPath exit_code=$tzExit (interpreter lacks tzdata for Asia/Taipei)"
        foreach ($line in $tzOutput) {
            Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
        }
        exit 1
    }
}

$exitCode = 1
Write-Status "host_worker_started mode=$mode"
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $output = @(& $resolvedPythonPath @pythonArguments 2>&1 | ForEach-Object { $_.ToString() })
    $exitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousPreference
}
foreach ($line in $output) {
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $line
}
# 輸出含多行（逐次 ITERATION 訊息），須判斷「沒有任何一行」符合標記
if ($BrowserSmoke -and -not ($output -match "HOST_BROWSER_SMOKE_OK")) {
    $exitCode = 1
}
Write-Status "host_worker_finished mode=$mode exit_code=$exitCode"
exit $exitCode
