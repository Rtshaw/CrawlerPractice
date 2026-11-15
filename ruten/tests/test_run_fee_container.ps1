$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $PSScriptRoot
$supervisorPath = Join-Path $projectPath "scripts\run_fee_container.ps1"
$containerName = "ruten-fee-worker-run"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "Assertion failed: $Message"
    }
}

function Test-ContainerExists {
    $names = @(docker ps --all --filter "name=^/$containerName$" --format "{{.Names}}")
    return $names -contains $containerName
}

function Get-LatestSupervisorLog {
    $logRoot = Join-Path $projectPath "runtime\logs\supervisor"
    return Get-ChildItem -LiteralPath $logRoot -Filter "*.log" -Recurse |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
}

function Invoke-Supervisor {
    param(
        [int]$TimeoutSeconds = 30,
        [int]$DryRunDelaySeconds = 0
    )
    $output = & powershell.exe `
        -NoProfile `
        -NonInteractive `
        -ExecutionPolicy Bypass `
        -File $supervisorPath `
        -ProjectPath $projectPath `
        -DryRun `
        -TimeoutSeconds $TimeoutSeconds `
        -PollSeconds 1 `
        -DryRunDelaySeconds $DryRunDelaySeconds 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    return $exitCode
}

try {
    if (Test-ContainerExists) {
        docker rm -f $containerName | Out-Null
    }

    $normalExit = Invoke-Supervisor
    Assert-True ($normalExit -eq 0) "normal dry-run exits zero"
    Assert-True (-not (Test-ContainerExists)) "normal dry-run removes exact worker container"
    $normalLog = Get-LatestSupervisorLog
    Assert-True ($null -ne $normalLog) "normal dry-run writes a supervisor log"
    Assert-True ((Get-Content -LiteralPath $normalLog.FullName -Raw) -match "DRY_RUN_OK") `
        "normal dry-run log records its harmless marker"

    docker run --detach --name $containerName --entrypoint sh ruten-fee-worker:1.0.0 `
        -c "sleep 60" *> $null
    Assert-True ($LASTEXITCODE -eq 0) "overlap fixture starts"
    $overlapExit = Invoke-Supervisor -TimeoutSeconds 900
    Assert-True ($overlapExit -eq 0) "live overlap is a successful skip"
    Assert-True (Test-ContainerExists) "live overlap is not removed before its timeout"
    $overlapLog = Get-LatestSupervisorLog
    Assert-True ((Get-Content -LiteralPath $overlapLog.FullName -Raw) -match "skipped_overlap") `
        "live overlap is recorded"
    docker rm -f $containerName | Out-Null

    $timeoutExit = Invoke-Supervisor -TimeoutSeconds 1 -DryRunDelaySeconds 5
    Assert-True ($timeoutExit -eq 124) "timeout returns 124"
    Assert-True (-not (Test-ContainerExists)) "timed-out worker is force removed"
    $timeoutLog = Get-LatestSupervisorLog
    Assert-True ((Get-Content -LiteralPath $timeoutLog.FullName -Raw) -match "timed_out") `
        "timeout is recorded"

    Write-Host "SUPERVISOR_TESTS_OK"
} finally {
    if (Test-ContainerExists) {
        docker rm -f $containerName | Out-Null
    }
}
