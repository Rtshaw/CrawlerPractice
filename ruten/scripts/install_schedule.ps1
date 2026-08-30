param(
    [string]$TaskName = "RutenFeePayment",
    [string]$DailyAt = "02:00",
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = (Get-Command python -ErrorAction Stop).Source
)

$ErrorActionPreference = "Stop"
$entryPoint = Join-Path $ProjectPath "scheduled_run.py"
if (-not (Test-Path $entryPoint)) {
    throw "scheduled_run.py not found: $entryPoint"
}
try {
    $at = [datetime]::ParseExact($DailyAt, "HH:mm", $null)
} catch {
    throw "DailyAt must use HH:mm (for example 02:00)"
}

$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument ('"{0}"' -f $entryPoint) `
    -WorkingDirectory $ProjectPath
$trigger = New-ScheduledTaskTrigger -Daily -At $at
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Ruten fee payment with SMS OTP relay" `
    -Force | Out-Null

Write-Host "Installed task '$TaskName' (daily at $DailyAt)."
Write-Host "Test: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove: Unregister-ScheduledTask -TaskName '$TaskName'"
