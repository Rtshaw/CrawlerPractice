param(
    [string]$TaskName = "RutenFeeHostManual",
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "",
    [string]$WorkerTaskName = "RutenFeeHostWorker"
)

# Default to the interpreter the daily worker task already uses (not whichever python is first on PATH).
if (-not $PythonPath) {
    $workerAction = (Get-ScheduledTask -TaskName $WorkerTaskName -ErrorAction SilentlyContinue).Actions | Select-Object -First 1
    if ($workerAction -and $workerAction.Arguments -match '-PythonPath "([^"]+)"') {
        $PythonPath = $Matches[1]
    } else {
        $PythonPath = (Get-Command python -ErrorAction Stop).Source
    }
}

# Idempotent (-Force replaces the same-named task). The daily RutenFeeHostWorker task is untouched.
# No trigger: start it from Task Scheduler (right-click > Run). Exit codes: see MANUAL_EXIT_CODES in scheduled_run.py.
$ErrorActionPreference = "Stop"
$project = (Resolve-Path -LiteralPath $ProjectPath).Path
$python = (Resolve-Path -LiteralPath $PythonPath).Path
$supervisor = Join-Path $project "scripts\run_fee_host.ps1"
if (-not (Test-Path -LiteralPath $supervisor -PathType Leaf)) { throw "Missing: $supervisor" }

$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$supervisor`" -ProjectPath `"$project`" -PythonPath `"$python`" -Manual"

$action = New-ScheduledTaskAction -Execute $ps -Argument $arguments -WorkingDirectory $project
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Settings $settings -Principal $principal `
    -Description "Ruten manual fee run: no trigger, runs any time, real payment" -Force | Out-Null
Write-Host "Installed manual task: $TaskName"
