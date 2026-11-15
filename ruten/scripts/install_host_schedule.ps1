[CmdletBinding(DefaultParameterSetName = "Daily")]
param(
    [string]$TaskName = "RutenFeeHostWorker",
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = (Get-Command python -ErrorAction Stop).Source,
    [Parameter(Mandatory = $true, ParameterSetName = "OneTime")]
    [datetime]$OneTimeAt,
    [Parameter(ParameterSetName = "OneTime")]
    [switch]$DryRun,
    [Parameter(ParameterSetName = "OneTime")]
    [switch]$BrowserSmoke,
    [Parameter(ParameterSetName = "OneTime")]
    [switch]$ImmediatePayment,
    [Parameter(ParameterSetName = "OneTime")]
    [ValidateRange(1, 60)]
    [int]$BrowserSmokeSeconds = 10
)

$ErrorActionPreference = "Stop"
$expectedOffset = [TimeSpan]::FromHours(8)
if ([DateTimeOffset]::Now.Offset -ne $expectedOffset) {
    throw "Windows time zone must currently use UTC+8."
}
if ($PSCmdlet.ParameterSetName -eq "OneTime" -and $OneTimeAt -le (Get-Date)) {
    throw "OneTimeAt must be in the future."
}
if (@($DryRun, $BrowserSmoke, $ImmediatePayment).Where({ $_ }).Count -gt 1) {
    throw "DryRun, BrowserSmoke, and ImmediatePayment are mutually exclusive."
}

$resolvedProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
$resolvedPythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$supervisorPath = Join-Path $resolvedProjectPath "scripts\run_fee_host.ps1"
foreach ($requiredPath in @($resolvedPythonPath, $supervisorPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required host scheduler file was not found: $requiredPath"
    }
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
    "-PythonPath `"$resolvedPythonPath`""
)
if ($DryRun) {
    $actionArguments += "-DryRun"
}
if ($BrowserSmoke) {
    $actionArguments += @("-BrowserSmoke", "-BrowserSmokeSeconds $BrowserSmokeSeconds")
}
if ($ImmediatePayment) {
    $actionArguments += "-ImmediatePayment"
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

$description = if ($BrowserSmoke) {
    "Ruten visible host browser validation; data URL only; no payment"
} elseif ($DryRun) {
    "Ruten harmless host scheduler validation; no payment code"
} elseif ($ImmediatePayment) {
    "Ruten authorized one-time immediate host payment"
} else {
    "Ruten one-shot Windows host Python fee worker; no in-slot retry"
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
