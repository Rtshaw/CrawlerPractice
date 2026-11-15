param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [switch]$DryRun,
    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 900,
    [ValidateRange(1, 60)]
    [int]$PollSeconds = 2,
    [ValidateRange(0, 3600)]
    [int]$DryRunDelaySeconds = 0
)

$ErrorActionPreference = "Stop"
$containerName = "ruten-fee-worker-run"
$expectedOffset = [TimeSpan]::FromHours(8)
$exitCode = 1
$timedOut = $false
$ownsWorker = $false

function Invoke-DockerChecked {
    param([string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& docker @Arguments 2>&1 | ForEach-Object { $_.ToString() })
        $dockerExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($dockerExitCode -ne 0) {
        throw "Docker command failed with exit code $dockerExitCode."
    }
    return $output
}

function Test-ExactContainerExists {
    $names = @(Invoke-DockerChecked @(
        "ps", "--all", "--filter", "name=^/$containerName$", "--format", "{{.Names}}"
    ))
    return $names -contains $containerName
}

function Get-ExactContainerState {
    $json = (Invoke-DockerChecked @("inspect", "--format", "{{json .State}}", $containerName)) -join ""
    return $json | ConvertFrom-Json
}

if ([DateTimeOffset]::Now.Offset -ne $expectedOffset) {
    throw "Windows time zone must currently use UTC+8."
}
if ($DryRunDelaySeconds -gt 0 -and -not $DryRun) {
    throw "DryRunDelaySeconds is allowed only with DryRun."
}

$resolvedProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
$composePath = Join-Path $resolvedProjectPath "docker\compose.worker.yml"
$runtimePath = Join-Path $resolvedProjectPath "runtime"
$logRoot = Join-Path $runtimePath "logs\supervisor"
$statePath = Join-Path $runtimePath "state"
$envFile = if ($DryRun) {
    Join-Path $resolvedProjectPath "docker\worker.env.example"
} else {
    Join-Path $resolvedProjectPath ".env"
}

foreach ($requiredPath in @($composePath, $envFile)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required worker file was not found: $requiredPath"
    }
}
New-Item -ItemType Directory -Force -Path $logRoot, $statePath | Out-Null
$logPath = Join-Path $logRoot ((Get-Date).ToString("yyyyMMdd-HHmmss-fff") + "-$PID.log")

function Write-Status {
    param([string]$Status)
    $line = "[{0}] {1}" -f ([DateTimeOffset]::Now.ToString("o")), $Status
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

try {
    Invoke-DockerChecked @("version", "--format", "{{.Server.Version}}") | Out-Null

    if (Test-ExactContainerExists) {
        $existingState = Get-ExactContainerState
        if ([bool]$existingState.Running) {
            $startedAt = [DateTimeOffset]::Parse(
                [string]$existingState.StartedAt,
                [Globalization.CultureInfo]::InvariantCulture
            )
            $ageSeconds = ([DateTimeOffset]::UtcNow - $startedAt.ToUniversalTime()).TotalSeconds
            if ($ageSeconds -lt $TimeoutSeconds) {
                Write-Status "skipped_overlap container=$containerName"
                exit 0
            }
            Invoke-DockerChecked @("rm", "--force", $containerName) | Out-Null
            Write-Status "stale_worker_removed container=$containerName"
        } else {
            Invoke-DockerChecked @("rm", "--force", $containerName) | Out-Null
            Write-Status "stopped_worker_removed container=$containerName"
        }
    }

    $composeArguments = @(
        "compose", "--env-file", $envFile, "-f", $composePath,
        "run", "--no-deps", "--detach", "--name", $containerName
    )
    if ($DryRun) {
        $composeArguments += @(
            "-e", "RUTEN_DRY_RUN=1",
            "-e", "RUTEN_DRY_RUN_DELAY_SECONDS=$DryRunDelaySeconds"
        )
    }
    $composeArguments += "fee-worker"
    $ownsWorker = $true
    Invoke-DockerChecked $composeArguments | Out-Null
    Write-Status "worker_started container=$containerName dry_run=$($DryRun.IsPresent)"

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        $state = Get-ExactContainerState
        if (-not [bool]$state.Running) {
            $exitCode = [int]$state.ExitCode
            break
        }
        if ($stopwatch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
            $timedOut = $true
            $exitCode = 124
            Write-Status "timed_out container=$containerName timeout_seconds=$TimeoutSeconds"
            break
        }
        Start-Sleep -Seconds $PollSeconds
    }

    if (-not $timedOut -and $DryRun) {
        $workerLogs = (Invoke-DockerChecked @("logs", $containerName)) -join "`n"
        if ($workerLogs -notmatch "DRY_RUN_OK") {
            throw "Dry-run marker was not emitted."
        }
        Write-Status "DRY_RUN_OK container=$containerName"
    }
    if (-not $timedOut) {
        Write-Status "worker_finished container=$containerName exit_code=$exitCode"
    }
} catch {
    $exitCode = 1
    Write-Status "supervisor_failed type=$($_.Exception.GetType().Name)"
} finally {
    try {
        if ($ownsWorker -and (Test-ExactContainerExists)) {
            Invoke-DockerChecked @("rm", "--force", $containerName) | Out-Null
            Write-Status "cleanup_complete container=$containerName"
        }
    } catch {
        Write-Status "cleanup_failed container=$containerName"
        if ($exitCode -eq 0) {
            $exitCode = 1
        }
    }
}

exit $exitCode
