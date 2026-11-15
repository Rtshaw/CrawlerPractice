[CmdletBinding(DefaultParameterSetName = "Daily")]
param(
    [string]$TaskName = "RutenFeeDockerWorker",
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true, ParameterSetName = "OneTime")]
    [datetime]$OneTimeAt,
    [Parameter(ParameterSetName = "OneTime")]
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$expectedOffset = [TimeSpan]::FromHours(8)
if ([DateTimeOffset]::Now.Offset -ne $expectedOffset) {
    throw "Windows time zone must currently use UTC+8."
}
if ($PSCmdlet.ParameterSetName -eq "OneTime" -and $OneTimeAt -le (Get-Date)) {
    throw "OneTimeAt must be in the future."
}

$resolvedProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
$supervisorPath = Join-Path $resolvedProjectPath "scripts\run_fee_container.ps1"
if (-not (Test-Path -LiteralPath $supervisorPath -PathType Leaf)) {
    throw "Supervisor not found: $supervisorPath"
}

$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    docker version --format "{{.Server.Version}}" *> $null
    $dockerExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousPreference
}
if ($dockerExitCode -ne 0) {
    throw "Docker Desktop is not available for the current user."
}

if ($PSCmdlet.ParameterSetName -eq "OneTime") {
    $triggers = @(New-ScheduledTaskTrigger -Once -At $OneTimeAt)
} else {
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $dailyTimes = @("01:35", "02:00", "02:14", "02:31", "02:40")
    $triggers = @(
        foreach ($dailyTime in $dailyTimes) {
            $at = [datetime]::ParseExact($dailyTime, "HH:mm", $culture)
            New-ScheduledTaskTrigger -Daily -At $at
        }
    )
}

$windowsPowerShell = Join-Path `
    $env:SystemRoot `
    "System32\WindowsPowerShell\v1.0\powershell.exe"
$actionArguments = @(
    "-NoProfile"
    "-NonInteractive"
    "-ExecutionPolicy Bypass"
    "-File `"$supervisorPath`""
    "-ProjectPath `"$resolvedProjectPath`""
)
if ($DryRun) {
    $actionArguments += "-DryRun"
}
$action = New-ScheduledTaskAction `
    -Execute $windowsPowerShell `
    -Argument ($actionArguments -join " ") `
    -WorkingDirectory $resolvedProjectPath

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

$description = if ($DryRun) {
    "Ruten harmless Docker scheduler validation; no payment code"
} else {
    "Ruten one-shot Docker fee worker; no in-slot retry"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description $description `
    -Force | Out-Null

Write-Host "Installed task: $TaskName"
if ($PSCmdlet.ParameterSetName -eq "OneTime") {
    Write-Host "One-time trigger: $($OneTimeAt.ToString('o'))"
} else {
    Write-Host "Daily triggers: 01:35, 02:00, 02:14, 02:31, 02:40"
}
