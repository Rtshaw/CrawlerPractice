$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $PSScriptRoot
$supervisorPath = Join-Path $projectPath "scripts\run_fee_host.ps1"
# 可用環境變數指定直譯器（需有 tzdata），否則取 PATH 上的 python
$pythonPath = if ($env:RUTEN_TEST_PYTHON) { $env:RUTEN_TEST_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("ruten-host-supervisor-" + [guid]::NewGuid().ToString("N"))

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "Assertion failed: $Message"
    }
}

function Invoke-HostSupervisor {
    param(
        [string[]]$Arguments,
        [string]$SupervisorProjectPath = $projectPath,
        [string]$SupervisorRuntimePath = $testRoot,
        [string]$SupervisorPythonPath = $pythonPath,
        [string[]]$ExtraArguments = @()
    )
    # 空字串代表「不傳 -PythonPath」，用來測試從排程讀取直譯器的分支
    $pythonArgs = if ($SupervisorPythonPath) { @("-PythonPath", $SupervisorPythonPath) } else { @() }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & powershell.exe `
            -NoProfile `
            -NonInteractive `
            -ExecutionPolicy Bypass `
            -File $supervisorPath `
            -ProjectPath $SupervisorProjectPath `
            @pythonArgs `
            -RuntimePath $SupervisorRuntimePath `
            @ExtraArguments `
            @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $output | ForEach-Object { Write-Host $_ }
    return $exitCode
}

try {
    New-Item -ItemType Directory -Force -Path $testRoot | Out-Null

    $dryRunExit = Invoke-HostSupervisor @("-DryRun")
    Assert-True ($dryRunExit -eq 0) "host dry-run exits zero"
    $workerLog = Get-ChildItem -LiteralPath (Join-Path $testRoot "logs") -Filter "*.log" -Recurse |
        Where-Object { $_.Directory.Name -ne "host-supervisor" } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    Assert-True ($null -ne $workerLog) "host dry-run writes a worker log"
    Assert-True ((Get-Content -LiteralPath $workerLog.FullName -Raw) -match "DRY_RUN_OK") `
        "host dry-run never runs payment code"

    $browserExit = Invoke-HostSupervisor @("-BrowserSmoke", "-BrowserSmokeSeconds", "1")
    Assert-True ($browserExit -eq 0) "visible host browser smoke exits zero"
    $supervisorLog = Get-ChildItem -LiteralPath (Join-Path $testRoot "logs\host-supervisor") `
        -Filter "*.log" -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    Assert-True ($null -ne $supervisorLog) "browser smoke writes a supervisor log"
    Assert-True ((Get-Content -LiteralPath $supervisorLog.FullName -Raw) -match "HOST_BROWSER_SMOKE_OK") `
        "browser smoke records its harmless marker"

    $fakeProject = Join-Path $testRoot "fake-project"
    $fakeRuntime = Join-Path $testRoot "fake-runtime"
    New-Item -ItemType Directory -Force -Path $fakeProject | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectPath "scheduled_run.py") `
        -Destination (Join-Path $fakeProject "scheduled_run.py")
    Set-Content -LiteralPath (Join-Path $fakeProject "fee.py") -Encoding UTF8 -Value @'
def run():
    print("FAKE_PAYMENT_RUN_OK")
    print("PAYMENT_OUTCOME=no_fee")
    return 0
'@
    Set-Content -LiteralPath (Join-Path $fakeProject ".env") -Encoding UTF8 -Value @'
OTP_SERVER_URL=https://example.invalid
OTP_CONSUMER_TOKEN=test-only-token
'@

    $immediateExit = Invoke-HostSupervisor `
        -Arguments @("-ImmediatePayment") `
        -SupervisorProjectPath $fakeProject `
        -SupervisorRuntimePath $fakeRuntime
    Assert-True ($immediateExit -eq 0) "immediate payment mode exits with the scheduled runner"
    $immediateLog = Get-ChildItem -LiteralPath (Join-Path $fakeRuntime "logs\host-supervisor") `
        -Filter "*.log" -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    $immediateContent = Get-Content -LiteralPath $immediateLog.FullName -Raw
    Assert-True ($immediateContent -match "host_worker_started mode=immediate_payment") `
        "immediate mode is identified in the supervisor log"
    Assert-True ($immediateContent -match "host_worker_finished mode=immediate_payment exit_code=0") `
        "immediate mode returns the scheduled runner exit code"
    $immediateWorkerLog = Get-ChildItem -LiteralPath (Join-Path $fakeRuntime "logs") `
        -Filter "*.log" -Recurse -File |
        Where-Object { $_.Directory.Name -ne "host-supervisor" } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    Assert-True ($null -ne $immediateWorkerLog) `
        "immediate mode writes its worker log beneath the requested runtime path"
    Assert-True ((Get-Content -LiteralPath $immediateWorkerLog.FullName -Raw) -match "FAKE_PAYMENT_RUN_OK") `
        "immediate mode executes the payment runner through scheduled_run"
    Assert-True (Test-Path -LiteralPath (Join-Path $fakeRuntime "state\payment.lock")) `
        "immediate mode uses the same payment lock as the scheduled task"

    $invalidExit = Invoke-HostSupervisor `
        -Arguments @("-ImmediatePayment", "-DryRun") `
        -SupervisorProjectPath $fakeProject `
        -SupervisorRuntimePath $fakeRuntime
    Assert-True ($invalidExit -ne 0) "immediate payment and dry-run are mutually exclusive"

    $manualExit = Invoke-HostSupervisor `
        -Arguments @("-Manual") `
        -SupervisorProjectPath $fakeProject `
        -SupervisorRuntimePath $fakeRuntime
    Assert-True ($manualExit -eq 10) "manual mode maps no_fee to exit code 10"
    $manualLog = Get-ChildItem -LiteralPath (Join-Path $fakeRuntime "logs\host-supervisor") -Filter "*.log" -File |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    $manualContent = Get-Content -LiteralPath $manualLog.FullName -Raw
    Assert-True ($manualContent -match "mode=manual") "manual mode is identified in the supervisor log"
    Assert-True ($manualContent -match "RUTEN_OUTCOME status=no_fee") "manual mode records the payment outcome line"
    Assert-True ($manualContent -notmatch "test-only-token") "token never reaches the log"
    $manualInvalid = Invoke-HostSupervisor -Arguments @("-Manual", "-ImmediatePayment") `
        -SupervisorProjectPath $fakeProject -SupervisorRuntimePath $fakeRuntime
    Assert-True ($manualInvalid -ne 0) "manual and immediate payment are mutually exclusive"

    # 未給 PythonPath 且找不到 Worker 排程時必須 throw，不得退回 PATH 上的 python
    $noTaskExit = Invoke-HostSupervisor -Arguments @("-DryRun") `
        -SupervisorPythonPath "" `
        -ExtraArguments @("-WorkerTaskName", "RutenNoSuchTask-" + [guid]::NewGuid().ToString("N"))
    Assert-True ($noTaskExit -ne 0) "missing worker task and PythonPath throws"

    # 直譯器缺 tzdata（假直譯器一律失敗）時，非 BrowserSmoke 模式要 exit 1 並寫入 supervisor log
    $fakePython = Join-Path $testRoot "fake-python-no-tz.cmd"
    Set-Content -LiteralPath $fakePython -Encoding ASCII -Value "@echo off`r`nexit /b 1"
    foreach ($modeArgs in @(@("-DryRun"), @("-Manual"), @("-ImmediatePayment"), @())) {
        $tzRuntime = Join-Path $testRoot ("tz-" + [guid]::NewGuid().ToString("N"))
        $tzExit = Invoke-HostSupervisor -Arguments $modeArgs `
            -SupervisorProjectPath $fakeProject -SupervisorRuntimePath $tzRuntime `
            -SupervisorPythonPath $fakePython
        Assert-True ($tzExit -eq 1) "tz self-check failure exits 1 for mode [$modeArgs]"
        $tzLog = Get-ChildItem -LiteralPath (Join-Path $tzRuntime "logs\host-supervisor") -Filter "*.log" -File |
            Select-Object -First 1
        Assert-True ((Get-Content -LiteralPath $tzLog.FullName -Raw) -match "tz_self_check_failed") `
            "tz self-check failure is written to the supervisor log"
    }

    Write-Host "HOST_SUPERVISOR_TESTS_OK"
} finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
